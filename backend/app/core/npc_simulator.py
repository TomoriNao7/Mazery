#NPC多视角模拟系统（TRD 六）
"""NPC 多视角模拟：状态管理、信息传播、私聊批量生成、每幕状态更新。

关键约束（TRD 6.1）：不是分布式多 Agent。每轮/每幕最多 1 次 LLM 调用
批量处理所有 NPC；动机评估用规则引擎（无 LLM）。
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 私聊动机优先级（TRD 6.3：每幕选 2-3 组，按优先级排序）
MOTIVE_PRIORITY = {
    "threaten": 6,   # 威胁（真凶/有秘密者 → 知情者）
    "frame": 5,      # 嫁祸栽赃（真凶 → 替罪羊）
    "trade": 4,      # 交易（信息持有者 → 需求者）
    "probe": 3,      # 试探（怀疑者 → 被怀疑对象）
    "ally": 2,       # 结盟（目标一致双方）
    "confide": 1,    # 倾诉（压力大 → 信任对象）
}


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
        result = await llm.call(prompt, schema=PrivateChatBatch)

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
        result = await llm.call(prompt, schema=NpcStrategyBatch)
        for item in getattr(result, "strategies", []):
            st = self.states.get(getattr(item, "npc_id", ""))
            if st:
                st.strategy = getattr(item, "strategy", st.strategy)
        return updates
