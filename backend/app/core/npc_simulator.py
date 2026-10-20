#NPC多视角模拟系统（TRD 六）
"""NPC 多视角模拟：状态管理、信息传播、私聊批量生成、每幕状态更新。

关键约束（TRD 6.1）：不是分布式多 Agent。每轮/每幕最多 1 次 LLM 调用
批量处理所有 NPC；动机评估用规则引擎（无 LLM）。
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)

# 私聊动机优先级（TRD 6.3：每幕选 2-3 组，按优先级排序）
MOTIVE_PRIORITY = {
    "threaten": 6,   # 威胁（真凶/有秘密者 → 知情者）
    "frame": 5,      # 嫁祸栽赃（真凶 → 替罪羊）
    "trade": 4,      # 交易（信息持有者 → 需求者）
    "probe": 3,      # 试探（怀疑者 → 被怀疑对象）
    "ally": 2,       # 结盟（目标一致双方）
    "confide": 1,    # 倾诉（压力大 → 信任对象）
}

# 私聊回复失败时的兜底话术（按 npc_id+消息长度稳定取一条，避免每次重复同一句）
_PRIVATE_FALLBACKS = [
    "（他压低声音，往前凑了凑）既然你问到这个份上……我可以告诉你一些事，但你也得拿你知道的来换。",
    "（她咬了咬唇，犹豫片刻）……你猜得不算错。这事我本不想提，但你既然开了头，我们不妨聊聊。",
    "（他抬眼打量了你一下，语气平缓）我们之间，未必没有合作的空间。你先说你知道多少。",
    "（她轻轻摇头，却还是开口了）这事说来话长。你若真想听，我今晚可以慢慢讲——只要你别到处乱说。",
    "（他叹了口气，指尖敲了敲桌面）你既然问到这一层，说明你也不是外人。有些话，我只对你一个人说。",
    "（她指尖摩挲着杯沿，声音低了下来）你找对人了。不过丑话说在前头——我也有我想要的。",
    "（他低头摆弄着袖口，终于抬起头）你我各取所需，我不瞒你瞒到底。你想问哪一件，我拣能说的说。",
    "（她转过头，目光落回你身上，声音飘忽却认真）你倒是个明白人。那就告诉你吧——但要留到合适的时机。",
]


def _stable_hash(text: str) -> int:
    return sum((i + 1) * ord(ch) for i, ch in enumerate(text))


def _private_fallback(npc_id: str, message: str) -> str:
    idx = _stable_hash(f"{npc_id}:{message}") % len(_PRIVATE_FALLBACKS)
    return _PRIVATE_FALLBACKS[idx]


@dataclass
class NpcState:
    """单个 NPC 的动态状态（对应 NPCKnowledgeState 表）。"""

    npc_id: str
    public_identity: Dict[str, Any] = field(default_factory=dict)
    private_knowledge: List[str] = field(default_factory=list)   # 角色卡过滤后的私有知识
    alibi: Dict[str, Any] = field(default_factory=dict)          # 不在场证明
    knowledge_boundary: List[str] = field(default_factory=list)  # 允许知道的信息范围
    known_info: List[str] = field(default_factory=list)          # 动态已知信息
    suspicions: Dict[str, float] = field(default_factory=dict)   # {npc_id: 0-1}
    discoveries: List[str] = field(default_factory=list)         # 自己发现的线索 id
    emotional_state: Dict[str, float] = field(
        default_factory=lambda: {"stress": 0.0, "trust": 0.5}
    )
    strategy: str = "defensive"  # defensive/threaten/frame/confide/ally

    def context_card(self) -> Dict[str, Any]:
        """注入 LLM 的 NPC 状态卡（不含私有知识，私有知识由 truth_snippet 单独给 GM）。"""
        return {
            "npc_id": self.npc_id,
            "public_identity": self.public_identity,
            "knowledge_boundary": self.knowledge_boundary,
            "known_info": self.known_info,
            "suspicions": self.suspicions,
            "emotional_state": self.emotional_state,
            "strategy": self.strategy,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "npc_id": self.npc_id,
            "public_identity": self.public_identity,
            "private_knowledge": self.private_knowledge,
            "alibi": self.alibi,
            "knowledge_boundary": self.knowledge_boundary,
            "known_info": self.known_info,
            "suspicions": self.suspicions,
            "discoveries": self.discoveries,
            "emotional_state": self.emotional_state,
            "strategy": self.strategy,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NpcState":
        return cls(
            npc_id=data["npc_id"],
            public_identity=data.get("public_identity", {}),
            private_knowledge=data.get("private_knowledge", []),
            alibi=data.get("alibi", {}),
            knowledge_boundary=data.get("knowledge_boundary", []),
            known_info=data.get("known_info", []),
            suspicions=data.get("suspicions", {}),
            discoveries=data.get("discoveries", []),
            emotional_state=data.get("emotional_state", {"stress": 0.0, "trust": 0.5}),
            strategy=data.get("strategy", "defensive"),
        )


def npc_states_from_character_set(character_set: Dict[str, Any]) -> List[NpcState]:
    """从剧本角色集构建初始 NPC 状态（L1 公开 + 各自 L3/L4/L5 私有知识）。"""
    states: List[NpcState] = []
    for c in character_set.get("characters", []) if isinstance(character_set, dict) else []:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if not cid:
            continue
        private: List[str] = []
        if c.get("secrets"):
            private.append("secrets: " + json.dumps(c["secrets"], ensure_ascii=False))
        if c.get("motive"):
            private.append("motive: " + json.dumps(c["motive"], ensure_ascii=False))
        if c.get("truth"):
            private.append("truth: " + json.dumps(c["truth"], ensure_ascii=False))
        states.append(NpcState(
            npc_id=cid,
            public_identity=c.get("public") or {"name": c.get("name", cid)},
            private_knowledge=private,
            knowledge_boundary=list(c.get("knowledge_boundary") or []),
        ))
    return states


class NpcSimulator:
    """NPC 多视角模拟器：信息传播 + 私聊动机评估 + 批量生成 + 每幕更新。"""

    def __init__(self, states: List[NpcState]):
        self.states: Dict[str, NpcState] = {s.npc_id: s for s in states}

    # ---------- 查询 ----------

    def get(self, npc_id: str) -> Optional[NpcState]:
        return self.states.get(npc_id)

    def all_states(self) -> List[NpcState]:
        return list(self.states.values())

    def context_cards(self) -> Dict[str, Dict[str, Any]]:
        return {sid: s.context_card() for sid, s in self.states.items()}

    # ---------- 信息传播（TRD 6.3 公开信息层次） ----------

    def propagate_public_info(self, info: str, act: int,
                              source_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """公开信息 → 所有 NPC 的 known_info；轻微提升压力值。"""
        logs: List[Dict[str, Any]] = []
        for s in self.states.values():
            if info not in s.known_info:
                s.known_info.append(info)
                s.emotional_state["stress"] = min(
                    1.0, s.emotional_state.get("stress", 0.0) + 0.05
                )
            logs.append({
                "npc_id": s.npc_id,
                "info": info,
                "act": act,
                "source_id": source_id,
            })
        return logs

    # ---------- 私聊（TRD 6.3） ----------

    def evaluate_private_chat_candidates(self, max_groups: int = 3) -> List[Dict[str, Any]]:
        """规则引擎评估私聊动机，按优先级选最多 max_groups 组。"""
        candidates: List[Dict[str, Any]] = []
        ids = list(self.states)
        for a in ids:
            for b in ids:
                if a == b:
                    continue
                motive = self._evaluate_motive(a, b)
                if motive:
                    candidates.append({"initiator": a, "target": b, "motive": motive})

        candidates.sort(key=lambda c: MOTIVE_PRIORITY.get(c["motive"], 0), reverse=True)
        seen = set()
        selected = []
        for c in candidates:
            pair = frozenset((c["initiator"], c["target"]))
            if pair in seen:
                continue
            seen.add(pair)
            selected.append(c)
            if len(selected) >= max_groups:
                break
        return selected

    def _evaluate_motive(self, a: str, b: str) -> Optional[str]:
        sa, sb = self.states[a], self.states[b]
        if sa.strategy in ("threaten",) and sb.suspicions.get(a, 0) > 0.3:
            return "threaten"
        if sa.strategy == "frame":
            return "frame"
        if sb.suspicions.get(a, 0) > 0.4:
            return "probe"
        if sa.emotional_state.get("stress", 0) > 0.6 and sb.emotional_state.get("trust", 0) > 0.5:
            return "confide"
        return None

    async def generate_private_chats(self,
                                     candidates: List[Dict[str, Any]],
                                     truth: Any,
                                     game_state: Any,
                                     llm) -> Dict[str, Any]:
        """1 次 LLM 调用（character_actor）批量生成私聊；结果写入双方 known_info。"""
        from backend.app.core.schemas import PrivateChatBatch
        from backend.app.core.skill_manager import get_skill_manager

        sm = get_skill_manager()
        prompt = sm.build_system_prompt(
            ["character_actor"],
            npc_private_chats=candidates,
            truth=truth,
            game_state=game_state,
            npc_contexts=self.context_cards(),
        )
        result = await llm.call(prompt, schema=PrivateChatBatch, max_tokens=1500)

        chats = result.chats if hasattr(result, "chats") else []
        for chat in chats:
            summary = getattr(chat, "content_summary", "")
            for pid in (getattr(chat, "initiator_id", ""), getattr(chat, "target_id", "")):
                st = self.states.get(pid)
                if st and summary and summary not in st.known_info:
                    st.known_info.append(summary)
        return result

    # ---------- 每幕状态更新（TRD 6.5） ----------

    async def end_of_act_update(self,
                                act: int,
                                truth: Any,
                                llm) -> List[Dict[str, Any]]:
        """每幕结束：吸收信息 → 更新怀疑 → 情绪渐变 → LLM 批量生成下一幕策略。"""
        # 规则部分：怀疑表微调 + 情绪渐变（压力回落）
        updates: List[Dict[str, Any]] = []
        for s in self.states.values():
            s.emotional_state["stress"] = max(
                0.0, s.emotional_state.get("stress", 0.0) - 0.1
            )
            s.emotional_state["trust"] = min(
                1.0, s.emotional_state.get("trust", 0.5) + 0.05
            )
            updates.append({
                "npc_id": s.npc_id,
                "emotional_state": dict(s.emotional_state),
                "suspicions": dict(s.suspicions),
            })

        # LLM 部分：批量生成下一幕策略（1 次调用）
        from backend.app.core.schemas import NpcStrategyBatch
        from backend.app.core.skill_manager import get_skill_manager

        sm = get_skill_manager()
        prompt = sm.build_system_prompt(
            ["character_actor"],
            act_end_update=True,
            current_act=act,
            truth=truth,
            npc_contexts=self.context_cards(),
        )
        result = await llm.call(prompt, schema=NpcStrategyBatch, max_tokens=800)
        for item in getattr(result, "strategies", []):
            st = self.states.get(getattr(item, "npc_id", ""))
            if st:
                st.strategy = getattr(item, "strategy", st.strategy)
        return updates

    # ---------- 展示名 ----------

    def display_name(self, npc_id: str) -> str:
        st = self.states.get(npc_id)
        if not st:
            return npc_id
        pid = st.public_identity or {}
        return pid.get("name") or pid.get("姓名") or npc_id

    # ---------- 完整上下文（含私有知识，供单 NPC 生成使用） ----------

    def full_context(self, npc_id: str) -> Dict[str, Any]:
        """该 NPC 的完整上下文卡：公开层 + 自身私有知识 + 不在场证明 + 动态状态。

        只包含该 NPC 自己的信息，不泄露其他角色私有内容与剧本全量真相。
        """
        st = self.states.get(npc_id)
        if not st:
            return {}
        ctx = st.context_card()
        ctx["private_knowledge"] = list(st.private_knowledge)
        ctx["alibi"] = st.alibi
        return ctx

    # ---------- 抽卡搜证：为 NPC 分配各自线索（PRD v0.2.0） ----------

    def assign_draw_clues(self, pool_ids: List[str],
                          player_char_id: Optional[str] = None,
                          player_chosen: Optional[str] = None) -> Dict[str, str]:
        """为每个 NPC 分配本幕 1 条线索（写入 discoveries + known_info）。

        排除玩家已选中的线索；玩家扮演的角色不分配（由玩家自行抽卡）。
        返回 {npc_id: clue_id}。
        """
        import random
        available = [c for c in pool_ids if c != player_chosen]
        random.shuffle(available)
        assignments: Dict[str, str] = {}
        for s in self.states.values():
            if s.npc_id == player_char_id:
                continue
            if not available:
                break
            clue_id = available.pop()
            s.discoveries = [clue_id]  # 仅保留本幕分配的线索（供交换信息阶段使用）
            note = f"[线索] {clue_id}"
            if note not in s.known_info:
                s.known_info.append(note)
            assignments[s.npc_id] = clue_id
        return assignments

    # ---------- 私聊：单个 NPC 回复玩家（PRD v0.2.0 第三/五幕） ----------

    async def generate_npc_reply_stream(self, npc_id: str, message: str,
                                        llm, max_tokens: int = 300,
                                        player_char_id: Optional[str] = None,
                                        player_profile: Optional[Dict[str, Any]] = None,
                                        ) -> AsyncIterator[str]:
        """流式生成单个 NPC 对玩家私聊消息的回复（纯文本，逐段产出）。

        注入该 NPC 完整上下文（含自身私有知识/秘密/真相，但受 character_actor
        硬约束，绝不承认自己是凶手）。同时注入玩家角色的公开信息，让 NPC 能判断
        立场是否一致、决定交换真实信息还是给假信息（character_actor R12/R13）。
        要求直接输出回复文本（不输出 JSON），失败时产出兜底话术。
        """
        st = self.states.get(npc_id)
        if not st:
            yield "……"
            return
        try:
            from backend.app.core.skill_manager import get_skill_manager
            sm = get_skill_manager()
            prompt = sm.build_system_prompt(
                ["character_actor"],
                npc_id=npc_id,
                npc_context=self.full_context(npc_id),
                player_message=message,
                player_char_id=player_char_id,
                player_profile=player_profile,
                private_chat=True,
            )
            prompt += (
                "\n\n请直接输出该 NPC 的回复（自然中文，第一人称，约 2-4 句，不加引号；"
                "动作/表情用（）放在句后），"
                "不要输出 JSON、不要输出字段名、不要加代码块。"
            )
            text = ""
            async for chunk in llm.stream(prompt, max_tokens=max_tokens):
                text += chunk
                yield chunk
            if not text.strip():
                yield _private_fallback(npc_id, message)
        except Exception as e:
            logger.warning("NPC 私聊回复流式生成失败（已降级）: %s", e)
            yield _private_fallback(npc_id, message)

    # ---------- 投票：全角色投票（PRD v0.2.0 第五幕） ----------

    async def cast_npc_votes(self, llm,
                             player_char_id: Optional[str] = None) -> Dict[str, str]:
        """为每个 NPC 生成投票：优先 LLM 依据其怀疑与已知线索判断，失败降级为怀疑度最高者。"""
        import random
        votes: Dict[str, str] = {}
        npc_ids = [s.npc_id for s in self.states.values() if s.npc_id != player_char_id]

        try:
            from backend.app.core.schemas import NpcVoteBatch
            from backend.app.core.skill_manager import get_skill_manager
            sm = get_skill_manager()
            prompt = sm.build_system_prompt(
                ["character_actor"],
                vote_decision=True,
                current_act=5,
                npc_contexts=self.context_cards(),
            )
            result = await llm.call(prompt, schema=NpcVoteBatch, max_tokens=800)
            for item in getattr(result, "votes", []):
                votes[item.npc_id] = item.target_id
        except Exception:
            votes = {}

        all_ids = list(self.states)
        for npc_id in npc_ids:
            if npc_id in votes:
                continue
            st = self.states.get(npc_id)
            target = None
            if st and st.suspicions:
                target = max(st.suspicions, key=st.suspicions.get)
            if not target or target == npc_id:
                others = [c for c in all_ids if c != npc_id]
                target = random.choice(others) if others else None
            if target:
                votes[npc_id] = target
        return votes

    # ---------- NPC↔NPC 私聊：生成玩家可见表象（PRD v0.2.0） ----------

    async def surface_npc_private_chats(self, full: Any, llm) -> List[str]:
        """评估 NPC 私聊动机 → 批量生成 → 返回玩家可见的表象描述列表。"""
        candidates = self.evaluate_private_chat_candidates(max_groups=2)
        if not candidates:
            return []
        try:
            result = await self.generate_private_chats(
                candidates, full, {"current_act": self._current_act_hint}, llm
            )
            return [
                getattr(c, "player_visible_description", "")
                for c in getattr(result, "chats", [])
                if getattr(c, "player_visible_description", "")
            ]
        except Exception:
            surface = []
            for c in candidates[:2]:
                a, b = c["initiator"], c["target"]
                surface.append(
                    f"{self.display_name(a)} 和 {self.display_name(b)} 在角落里低声交谈了几句，"
                    f"{self.display_name(b)} 的脸色似乎变了。"
                )
            return surface

    _current_act_hint: int = 3

    # ---------- 交换信息：NPC 是否如实介绍自己的线索（PRD v0.2.0） ----------

    def _find_murderer(self, full: Any) -> Optional[str]:
        cc = (full or {}).get("case_core") or {}
        return cc.get("murderer_id")

    def npc_exchange_plans(self, full: Any) -> Dict[str, Optional[Dict[str, Any]]]:
        """每个 NPC 在交换信息阶段的发言计划（三态）。

        - truthful：如实公开真实线索（进公开列表/人物卡）；
        - partial：隐瞒一部分，只含糊提及（不进公开列表，但作为公开陈述被记住）；
        - fabricate：编造一条可信但不直接指认真凶的假线索（作为公开陈述被记住）。

        规则引擎（无 LLM）：真凶或 threaten/frame 策略的 NPC 绝不真实，
        随机走 partial/fabricate；其余多数如实，少数隐瞒/编造。
        返回 {npc_id: {clue_id, mode, truthful} | None}。
        """
        import random as _r
        murderer = self._find_murderer(full)
        plans: Dict[str, Optional[Dict[str, Any]]] = {}
        for s in self.states.values():
            clues = [c for c in s.discoveries if c]
            if not clues:
                plans[s.npc_id] = None
                continue
            deceptive = (s.npc_id == murderer) or s.strategy in ("threaten", "frame")
            if deceptive:
                mode = "fabricate" if _r.random() < 0.6 else "partial"
            else:
                r = _r.random()
                if r < 0.68:
                    mode = "truthful"
                elif r < 0.88:
                    mode = "partial"
                else:
                    mode = "fabricate"
            plans[s.npc_id] = {"clue_id": clues[0], "mode": mode,
                               "truthful": mode == "truthful"}
        return plans

    def npc_exchange_reveals(self, full: Any) -> Dict[str, Optional[Dict[str, Any]]]:
        """交换阶段「如实公开」的线索计划（供 reconcile 补公开 / 前端判断）。

        规则（规则引擎，无 LLM）：真凶或 strategy 为 threaten/frame 的 NPC
        会隐瞒/编造；其余如实。返回 {npc_id: {clue_id, truthful} | None}。
        """
        plans = self.npc_exchange_plans(full)
        return {
            k: ({"clue_id": v["clue_id"], "truthful": v["truthful"]} if v else None)
            for k, v in plans.items()
        }

    # ---------- 阶段自发言：LLM-first（character_actor），失败才用模板 ----------

    def _stage_speech_prompt(self, npc_id: str, task: str) -> str:
        from backend.app.core.skill_manager import get_skill_manager
        sm = get_skill_manager()
        prompt = sm.build_system_prompt(
            ["character_actor"],
            npc_id=npc_id,
            npc_context=self.full_context(npc_id),
            stage_speech=task,
        )
        prompt += (
            "\n\n请直接用该 NPC 的第一人称输出这段发言（自然中文，约 2-4 句、不超过 100 字）。"
            "不要输出 JSON、不要输出字段名、不要加代码块。"
            "发言内容不要加引号；如有动作/表情，用（）放在对应句子后面。"
        )
        return prompt

    async def _gen_intro_speech(self, c: Dict[str, Any], llm) -> str:
        task = ("请以该角色的公开身份做一段简短的自我介绍：姓名、身份、性格气质，让在场的人对你有个印象。"
                "只介绍自己公开知道、愿意说的内容，不要泄露任何秘密。")
        prompt = self._stage_speech_prompt(c.get("id"), task)
        return await _collect_text(llm, prompt, max_tokens=200)

    async def _gen_exchange_speech(self, c: Dict[str, Any], plan: Dict[str, Any],
                                   full: Any, llm) -> str:
        clue = _clue_by_id(full, plan.get("clue_id") or "")
        mode = plan.get("mode", "truthful")
        if mode == "truthful" and clue.get("name"):
            task = (f"你在搜证中发现了一条线索：《{clue.get('name')}》。你决定如实公开它。"
                    f"请用你的说话方式把这条线索讲给在场的人听——要自然、像随口提及，而不是念资料。"
                    f"线索内容：{clue.get('description', '')}")
        elif mode == "partial":
            task = ("你搜到了一条线索，但你并不打算全部公开。请用你的说话方式含糊提及这条线索"
                    "确实存在，保留最关键的部分、欲言又止，让在场的人知道你有保留但套不出全貌。"
                    "不要说出线索的真实内容。")
        else:  # fabricate
            task = ("你搜到了一条线索，但你并不打算如实公开。请编造一个听起来可信、与本案氛围相符"
                    "的假线索（地点、物品、目击都行）讲给大家听。规则：绝对不能直接说'某某就是凶手'"
                    "或给出任何一锤定音的指控，只能让人觉得你确实发现了些东西，之后你还能就这个说法"
                    "继续周旋。不要提及你真实拿到的线索。")
        prompt = self._stage_speech_prompt(c.get("id"), task)
        return await _collect_text(llm, prompt, max_tokens=260)

    async def generate_stage_speeches(self, stage: str, full: Any,
                                      player_char_id: Optional[str],
                                      llm, act: int = 1) -> List[Dict[str, Any]]:
        """LLM-first 生成某阶段的 NPC 自发言；单个生成失败时用确定性模板兜底。

        intro：各 NPC 自我介绍 + GM 提示；exchange：按 npc_exchange_plans 的
        三态决策生成发言——如实发言带 reveal_clue_id；隐瞒/编造发言标记
        public_statement，并把"某NPC声称…"传播进所有 NPC 记忆（后续可被追问）。
        """
        chars = (full or {}).get("characters") or {}
        ordered = [c for c in chars.get("characters", []) if isinstance(c, dict)]
        speeches: List[Dict[str, Any]] = []

        if stage in ("intro_r1", "intro_r2"):
            intro_chars = [c for c in ordered
                           if not (player_char_id and c.get("id") == player_char_id)]
            results = await asyncio.gather(
                *(self._gen_intro_speech(c, llm) for c in intro_chars)
            )
            for c, text in zip(intro_chars, results):
                if text:
                    speeches.append({
                        "role": f"character_{c.get('id')}",
                        "speaker_name": c.get("id"),
                        "content": text,
                        "action_type": "stage_speech",
                    })
                else:
                    speeches.append(_intro_template(c, player_char_id))
            gm = _gm_turn_prompt(ordered, player_char_id)
            if gm:
                speeches.append(gm)

        elif stage == "exchange":
            plans = self.npc_exchange_plans(full)
            targets: List[tuple] = []
            for c in ordered:
                cid = c.get("id")
                if not cid or (player_char_id and cid == player_char_id):
                    continue
                plan = plans.get(cid)
                if not plan or not plan.get("clue_id"):
                    continue
                targets.append((c, plan))
            results = await asyncio.gather(
                *(self._gen_exchange_speech(c, plan, full, llm) for c, plan in targets)
            )
            for (c, plan), text in zip(targets, results):
                cid = c.get("id")
                if text:
                    sp: Dict[str, Any] = {
                        "role": f"character_{cid}",
                        "speaker_name": cid,
                        "content": text,
                        "action_type": "stage_speech",
                    }
                    if plan.get("truthful"):
                        sp["reveal_clue_id"] = plan.get("clue_id")
                    else:
                        sp["public_statement"] = True
                        sp["statement_speaker"] = cid
                        self._remember_statement(cid, text, act)
                    speeches.append(sp)
                else:
                    tpl = _exchange_template(c, {"clue_id": plan.get("clue_id"),
                                                 "truthful": plan.get("truthful")}, full)
                    if not plan.get("truthful"):
                        tpl["public_statement"] = True
                        tpl["statement_speaker"] = cid
                        self._remember_statement(cid, tpl.get("content", ""), act)
                    speeches.append(tpl)
        return speeches

    def _remember_statement(self, speaker: str, content: str, act: int) -> None:
        """把某 NPC 说出的（编造/隐瞒）陈述写进所有 NPC 记忆，供后续被提问。"""
        info = f"[公开陈述] {self.display_name(speaker)}：{content}"
        self.propagate_public_info(info, act)


# 欺骗性 NPC 交换信息时的敷衍/误导话术
_DECEPTIVE_LINES = [
    "我那条线索不值一提，都是些无关紧要的旧事。",
    "我手里的线索指向很模糊，暂且不便多说。",
    "我搜到的东西跟本案应该没什么关系，你们别抱期待。",
    "我没什么好公开的，与其听我瞎说，不如去问别人。",
]

# 隐瞒一部分（partial）的兜底话术
_PARTIAL_LINES = [
    "我这条线索……确实有些发现，但关键的细节我暂时还不能说。",
    "我手里是有点东西，不过现在说全了反而不好，先卖个关子。",
    "我知道一点事，但牵扯太大，只能说到这儿。",
    "这条线索我还没完全看明白，等我想清楚了再告诉大家。",
]

# 编造（fabricate）的兜底话术：可信、不直接指认"XX是凶手"
_FABRICATED_LINES = [
    "我在现场附近发现了一些被人刻意抹掉的痕迹，顺着查下去应该能落到某个人身上。",
    "我打听到：案发前后，有人看见某个身影在包厢外徘徊，行色匆匆。",
    "我注意到有一件物品被人移动过，位置和当晚对不上，这里面有文章。",
    "我得到消息，最近有人私下打听过死者的行程，打听的人很怕被认出来。",
]


def _clue_by_id(full: Any, clue_id: str) -> Dict[str, Any]:
    clues = (full or {}).get("clues") or {}
    for group in ("key_clues", "misleading_clues", "neutral_clues"):
        for c in clues.get(group) or []:
            if isinstance(c, dict) and c.get("id") == clue_id:
                return c
    return {}


async def _collect_text(llm, prompt: str, max_tokens: int = 240) -> str:
    """非流式取一次完整 LLM 输出；失败返回空串（由调用方用模板兜底）。

    若模型按 skill 的 output_format 输出了 JSON，提取其中 content 字段。
    """
    try:
        text = await llm.call(prompt, max_tokens=max_tokens)
        text = (text or "").strip()
        if text.startswith("{"):
            try:
                obj = json.loads(text)
                inner = obj.get("content") or obj.get("response") or ""
                if isinstance(inner, str) and inner.strip():
                    text = inner.strip()
            except json.JSONDecodeError:
                pass
        return text
    except Exception as e:
        logger.warning("阶段自发言 LLM 生成失败（将用模板兜底）: %s", e)
        return ""


def _intro_template(c: Dict[str, Any], player_char_id: Optional[str] = None) -> Dict[str, Any]:
    pub = c.get("public") or {}
    name = c.get("name") or pub.get("name") or "某人"
    identity = (pub.get("identity") or pub.get("profession")
                or pub.get("身份") or pub.get("职业") or "一位来客")
    personality = pub.get("personality") or pub.get("性格") or ""
    line = f"我是{name}，{identity}。"
    if personality:
        line += f"{personality}。"
    return {
        "role": f"character_{c.get('id')}",
        "speaker_name": c.get("id"),
        "content": line,
        "action_type": "stage_speech",
    }


def _exchange_template(c: Dict[str, Any], plan: Dict[str, Any], full: Any) -> Dict[str, Any]:
    cid = c.get("id")
    mode = plan.get("mode") or ("truthful" if plan.get("truthful") else "partial")
    clue = _clue_by_id(full, plan.get("clue_id") or "")
    sp: Dict[str, Any] = {
        "role": f"character_{cid}",
        "speaker_name": cid,
        "action_type": "stage_speech",
    }
    if mode == "truthful" and clue.get("name"):
        sp["content"] = f"我这边有条线索可以公开——《{clue.get('name')}》：{clue.get('description', '')}"
        sp["reveal_clue_id"] = plan.get("clue_id")
    elif mode == "fabricate":
        idx = _stable_hash(f"{cid}:{plan.get('clue_id')}") % len(_FABRICATED_LINES)
        sp["content"] = _FABRICATED_LINES[idx]
    else:
        idx = _stable_hash(f"{cid}:{plan.get('clue_id')}") % len(_PARTIAL_LINES)
        sp["content"] = _PARTIAL_LINES[idx]
    return sp


def _gm_turn_prompt(ordered: List[Dict[str, Any]],
                    player_char_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not player_char_id:
        return None
    pchar = next((c for c in ordered if c.get("id") == player_char_id), None)
    pname = (pchar or {}).get("name") or "你"
    return {
        "role": "system",
        "speaker_name": "GM",
        "content": f"轮到你自我介绍了。请以「{pname}」的身份发言：介绍一下你的公开身份与在场状态。",
        "action_type": "stage_speech",
    }


def build_stage_speeches(stage: str, full: Any, sim: "NpcSimulator",
                         player_char_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """某阶段的 NPC 自发言（确定性模板，仅在 LLM 生成失败时兜底）。

    返回消息字典列表：{role, speaker_name, content, action_type, reveal_clue_id?}。
    - intro_r1/intro_r2：各 NPC 依次自我介绍，末尾 GM 提示轮到玩家；
    - exchange：各 NPC 决定是否如实公开自己拿到的线索（真凶/被威胁者隐瞒），
      如实发言带 reveal_clue_id（由前端在发言结束后调用公开接口）。
    """
    chars = (full or {}).get("characters") or {}
    ordered = [c for c in chars.get("characters", []) if isinstance(c, dict)]
    speeches: List[Dict[str, Any]] = []

    if stage in ("intro_r1", "intro_r2"):
        for c in ordered:
            if player_char_id and c.get("id") == player_char_id:
                continue
            speeches.append(_intro_template(c, player_char_id))
        gm = _gm_turn_prompt(ordered, player_char_id)
        if gm:
            speeches.append(gm)

    elif stage == "exchange":
        plans = sim.npc_exchange_plans(full) if sim is not None else {}
        for c in ordered:
            cid = c.get("id")
            if not cid or (player_char_id and cid == player_char_id):
                continue
            plan = plans.get(cid)
            if not plan or not plan.get("clue_id"):
                continue
            speeches.append(_exchange_template(c, plan, full))
    return speeches
