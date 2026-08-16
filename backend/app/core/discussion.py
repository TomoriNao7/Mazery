#讨论引擎
"""轮次制讨论引擎：在提问/交流阶段让 NPC 与玩家按轮次轮流发言。

状态存于 game_log["discussion"]：
  stage / act / max_rounds / round / turn_index / order / asked / pending / done

- 每轮按 order 顺序（NPC…最后玩家）每人发言/提问一次，然后进入下一轮。
- NPC 轮次由 LLM 生成（提问或陈述）；问到 NPC 则连同其回应一起生成；
  问到玩家则置 pending，由玩家作答后才能继续。
- 所有发言/问答写入各 NPC 记忆（propagate_public_info）。
"""

import logging
from typing import Any, Dict, List, Optional

from backend.app.core.schemas import NpcDiscussionReply, NpcDiscussionTurn

logger = logging.getLogger(__name__)

# 各讨论阶段的提问轮数（exchange 的"公开线索"轮由既有 stage_speech 处理，不计入）
DISCUSSION_STAGES = {
    "intro_r2": {"max_rounds": 1},
    "exchange": {"max_rounds": 2},
    "public": {"max_rounds": 2},
}

# LLM 不可用时的兜底提问/陈述
_FALLBACK_QUESTIONS = [
    "关于刚才公开的那条线索，你有什么要补充的吗？",
    "你昨晚的行踪，方便再细说一些吗？",
    "你对这件事是怎么看的？",
]
_FALLBACK_STATEMENTS = [
    "我暂时没什么要公开的，先听听大家怎么说。",
    "这条线索我还在琢磨，等想清楚了再说。",
]
_FALLBACK_REPLIES = [
    "这件事说来话长，我暂时只能说到这儿。",
    "（斟酌片刻）该说的我方才已经说了，别的恕难奉告。",
    "你问到这个……我也在奇怪，不过眼下没有更多线索。",
]


def is_discussion_stage(stage: str) -> bool:
    return stage in DISCUSSION_STAGES


def init_discussion(stage: str, act: int, full: Any, player_char_id: Optional[str],
                    existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """初始化（或复用已有）讨论状态；order = 各 NPC + 玩家（玩家最后）。"""
    if existing and existing.get("stage") == stage and existing.get("act") == act:
        return existing
    chars = (full or {}).get("characters") or {}
    order = [c.get("id") for c in chars.get("characters", []) if isinstance(c, dict)]
    if player_char_id and player_char_id in order:
        order.remove(player_char_id)
    if player_char_id:
        order.append(player_char_id)
    return {
        "stage": stage,
        "act": act,
        "max_rounds": DISCUSSION_STAGES[stage]["max_rounds"],
        "round": 1,
        "turn_index": 0,
        "order": order,
        "asked": [],
        "pending": None,
        "done": False,
        "started": False,  # 首次调用 /discussion/next 后置 True（此前 exchange 允许玩家先介绍线索）
    }


class DiscussionEngine:
    """讨论引擎：读取/推进 game_log["discussion"]，生成 NPC 轮次。"""

    def __init__(self, sim, full: Dict[str, Any], player_char_id: Optional[str],
                 game_log: Dict[str, Any]):
        self.sim = sim
        self.full = full
        self.player_char_id = player_char_id
        self.game_log = game_log
        self.state = game_log.setdefault("discussion", {})

    # ---------- 状态 ----------

    def display(self, pid: Optional[str]) -> str:
        if not pid:
            return ""
        if pid == self.player_char_id:
            return self.sim.display_name(pid) or "你"
        return self.sim.display_name(pid)

    def current_participant(self) -> Optional[str]:
        d = self.state
        if not d or d.get("done") or not d.get("order"):
            return None
        return d["order"][d.get("turn_index", 0)]

    def is_done(self) -> bool:
        d = self.state
        return bool(d.get("done")) or d.get("round", 1) > d.get("max_rounds", 1)

    def advance_turn(self) -> None:
        d = self.state
        if not d.get("order"):
            return
        d["turn_index"] = (d.get("turn_index", 0) + 1) % len(d["order"])
        if d["turn_index"] == 0:
            d["round"] = d.get("round", 1) + 1

    def record_asked(self, asker: str, target: str, question: str) -> None:
        d = self.state
        d.setdefault("asked", []).append({
            "round": d.get("round", 1), "asker": asker, "target": target,
            "question": question,
        })

    # ---------- 提示词与生成 ----------

    def _participants_brief(self) -> List[Dict[str, Any]]:
        d = self.state
        out = []
        for pid in d.get("order", []):
            out.append({"id": pid, "name": self.display(pid),
                        "is_player": pid == self.player_char_id})
        return out

    def _public_brief(self) -> List[Dict[str, Any]]:
        stmts = self.game_log.get("public_statements") or []
        return [{"id": s.get("id"), "name": s.get("name")} for s in stmts]

    def _build_turn_prompt(self, npc_id: str, llm) -> str:
        from backend.app.core.skill_manager import get_skill_manager
        sm = get_skill_manager()
        d = self.state
        return sm.build_system_prompt(
            ["character_actor"],
            npc_id=npc_id,
            npc_context=self.sim.full_context(npc_id),
            discussion={
                "round": d.get("round"), "max_rounds": d.get("max_rounds"),
                "participants": self._participants_brief(),
                "asked": d.get("asked"),
                "public_clues": self._public_brief(),
                "pending_player_answer": d.get("pending"),
            },
        )

    def _turn_task(self) -> str:
        return (
            "请输出该 NPC 本轮在讨论中的一次发言（结构化 JSON，字段：kind/target/content）：\n"
            "- kind: question（提问）或 statement（陈述/公开线索）\n"
            "- target: 提问对象 participant id（statement 时留空）\n"
            "- content: 发言内容（第一人称，2-4 句）\n"
            "规则：\n"
            "1. 优先根据场上已公开线索提问——线索指向谁就问谁；也可凭自己的推理问自己想知道的事。\n"
            "2. 绝不能用自己撒谎/编造过的内容去问别人。\n"
            "3. 提问不能暴露自己的隐私秘密；若你是凶手，绝不能通过提问暴露自己是凶手。\n"
            "4. 避免与别人重复问同一人、同一问题；可以就某人上一轮的回答做追加追问。\n"
            "5. 每个角色每轮只发言一次。"
        )

    async def gen_npc_turn(self, npc_id: str, llm) -> NpcDiscussionTurn:
        prompt = self._build_turn_prompt(npc_id, llm)
        prompt += "\n\n" + self._turn_task()
        try:
            result = await llm.call(prompt, schema=NpcDiscussionTurn, max_tokens=220)
            if isinstance(result, str):
                return NpcDiscussionTurn(kind="statement", target=None,
                                         content=(result or "……")[:120])
            if not result.content or not result.content.strip():
                raise ValueError("empty turn")
            return result
        except Exception as e:
            logger.warning("NPC 讨论轮次生成失败（使用兜底）: %s", e)
            return self._fallback_turn(npc_id)

    async def gen_npc_reply(self, npc_id: str, asker: str, question: str,
                            llm) -> NpcDiscussionReply:
        from backend.app.core.skill_manager import get_skill_manager
        sm = get_skill_manager()
        prompt = sm.build_system_prompt(
            ["character_actor"],
            npc_id=npc_id,
            npc_context=self.sim.full_context(npc_id),
            discussion_reply={"asker": self.display(asker), "question": question},
        )
        prompt += (
            "\n\n请输出该 NPC 对被问问题的回应（第一人称，2-4 句，结构化 JSON：content/is_lying）。\n"
            "可按其目的如实回答或撒谎；但绝不能说出自己不该知道的秘密；凶手绝不承认自己是凶手。"
        )
        try:
            result = await llm.call(prompt, schema=NpcDiscussionReply, max_tokens=200)
            if isinstance(result, str):
                return NpcDiscussionReply(content=(result or "……")[:120], is_lying=False)
            if not result.content or not result.content.strip():
                raise ValueError("empty reply")
            return result
        except Exception as e:
            logger.warning("NPC 讨论回应生成失败（使用兜底）: %s", e)
            return self._fallback_reply(npc_id, question)

    # ---------- 兜底 ----------

    def _fallback_turn(self, npc_id: str) -> NpcDiscussionTurn:
        import random
        d = self.state
        order = [p for p in d.get("order", []) if p != npc_id]
        asked_targets = [a.get("target") for a in d.get("asked", [])]
        stmts = self.game_log.get("public_statements") or []
        if stmts:
            st = random.choice(stmts)
            target = st.get("speaker_id") or (order[0] if order else None)
            if target and target not in asked_targets:
                q = f"关于你刚才说的「{st.get('name', '那件事')}」，能再讲讲吗？"
                return NpcDiscussionTurn(kind="question", target=target, content=q)
        fresh = [p for p in order if p not in asked_targets]
        target = fresh[0] if fresh else (order[0] if order else None)
        if target:
            q = random.choice(_FALLBACK_QUESTIONS)
            return NpcDiscussionTurn(kind="question", target=target, content=q)
        return NpcDiscussionTurn(kind="statement", target=None,
                                 content=random.choice(_FALLBACK_STATEMENTS))

    def _fallback_reply(self, npc_id: str, question: str) -> NpcDiscussionReply:
        import random
        text = random.choice(_FALLBACK_REPLIES)
        if self._is_murderer(npc_id) and any(k in question for k in ("你杀的", "凶手", "杀人")):
            text = f"（{self.display(npc_id)}神色不变）这样的话可不能乱说，我清者自清。"
        return NpcDiscussionReply(content=text, is_lying=False)

    def _is_murderer(self, npc_id: str) -> bool:
        cc = (self.full or {}).get("case_core") or {}
        return cc.get("murderer_id") == npc_id

    # ---------- 生成单个 NPC 轮次 ----------

    async def process_npc_turn(self, npc_id: str, act: int, llm) -> List[Dict[str, Any]]:
        """生成一个 NPC 的轮次：提问或陈述；问到 NPC 则连同回应一起生成。

        返回消息列表（role/speaker_name/content/action_type）。同时写入各 NPC 记忆。
        """
        d = self.state
        turn = await self.gen_npc_turn(npc_id, llm)
        msgs: List[Dict[str, Any]] = []
        speaker = self.display(npc_id)
        if turn.kind == "question" and turn.target and turn.target != npc_id:
            target = turn.target
            self.record_asked(npc_id, target, turn.content)
            msgs.append(self._msg(npc_id, turn.content))
            self.sim.propagate_public_info(
                f"[讨论] {speaker}问{self.display(target)}：{turn.content}", act)
            if target == self.player_char_id:
                d["pending"] = {"asker": npc_id, "question": turn.content}
            else:
                reply = await self.gen_npc_reply(target, npc_id, turn.content, llm)
                msgs.append(self._msg(target, reply.content))
                self.sim.propagate_public_info(
                    f"[回答] {self.display(target)}：{reply.content}", act)
        else:
            msgs.append(self._msg(npc_id, turn.content))
            self.sim.propagate_public_info(f"[发言] {speaker}：{turn.content}", act)
        self.advance_turn()
        return msgs

    def _msg(self, npc_id: str, content: str) -> Dict[str, Any]:
        return {
            "role": f"character_{npc_id}" if npc_id != self.player_char_id else "player",
            "speaker_name": npc_id,
            "content": content,
            "action_type": "stage_speech",
        }
