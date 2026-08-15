#GM分幕状态机（PRD v0.2.0 第九章 / TRD 第五章）
"""GM 分幕状态机：抽卡搜证 + 交换信息 + 私聊 + 全角色投票。

五幕结构（PRD v0.2.0）：
    第一幕 介绍：自我介绍 1 轮 → 互相提问 1 轮
    第二幕 线索搜证：抽卡（5 选 1）
    第三幕 交换信息与私聊：交换信息 4 轮 → 私聊（每人发起一次，每对 32 条）
    第四幕 线索搜查：同第二幕（抽卡）
    第五幕 收束：交换信息 4 轮 → 私聊 → 公聊 2 轮 → 投票（全角色）

GM 自身动作（narration / system / advance / notification）不受约束。
私聊计数：8 轮 × 每轮双方各发言 2 次 = 32 条消息，达到上限强制结束。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple


class ActionType(str, Enum):
    NARRATION = "narration"               # GM 旁白
    SYSTEM = "system"                     # 系统消息
    ADVANCE = "advance_act"               # 幕/阶段推进
    NOTIFICATION = "notification"         # 幕间新隐私/目标通知
    INTRODUCE = "introduce"               # 自我介绍（第一幕第一轮）
    QUESTION = "question"                 # 互问 / 追问 / 质疑
    INTRODUCE_CLUE = "introduce_clue"     # 介绍自己拿到的线索（交换信息第一轮）
    TALK = "talk"                         # 公聊发言
    ACCUSE = "accuse"                     # 公开指控/对质
    DRAW = "draw"                         # 抽卡搜证（第二/四幕）
    PRIVATE_CHAT_SEND = "private_chat_send"  # 私聊发送
    VOTE = "vote"                         # 投票指认（第五幕）
    OBSERVE = "observe"                   # 观察


GM_ACTIONS = frozenset({
    ActionType.NARRATION, ActionType.SYSTEM,
    ActionType.ADVANCE, ActionType.NOTIFICATION,
})

# 私聊上限：8 轮 × 每轮双方各发言 2 次 = 32 条消息
PRIVATE_CHAT_MAX_MESSAGES = 32


@dataclass(frozen=True)
class StageConfig:
    """一幕内的一个阶段。kind: rounds=普通轮次 / private=私聊 / vote=投票。"""
    name: str
    label: str
    allowed_actions: FrozenSet[ActionType]
    kind: str = "rounds"
    max_rounds: int = 1  # 仅 kind=rounds 使用（玩家在本阶段的可行动轮数）


@dataclass(frozen=True)
class ActConfig:
    act: int
    name: str
    stages: tuple


def _build_acts() -> Dict[int, ActConfig]:
    return {
        1: ActConfig(1, "介绍", (
            StageConfig("intro_r1", "自我介绍",
                        frozenset({ActionType.INTRODUCE, ActionType.TALK, ActionType.OBSERVE})),
            StageConfig("intro_r2", "互相提问",
                        frozenset({ActionType.QUESTION, ActionType.TALK, ActionType.OBSERVE})),
        )),
        2: ActConfig(2, "线索搜证", (
            StageConfig("draw", "抽卡搜证",
                        frozenset({ActionType.DRAW, ActionType.OBSERVE})),
        )),
        3: ActConfig(3, "交换信息与私聊", (
            StageConfig("exchange", "交换信息",
                        frozenset({ActionType.INTRODUCE_CLUE, ActionType.QUESTION,
                                   ActionType.TALK, ActionType.ACCUSE, ActionType.OBSERVE}),
                        max_rounds=4),
            StageConfig("private", "私聊",
                        frozenset({ActionType.PRIVATE_CHAT_SEND}),
                        kind="private"),
        )),
        4: ActConfig(4, "线索搜查", (
            StageConfig("draw", "抽卡搜证",
                        frozenset({ActionType.DRAW, ActionType.OBSERVE})),
        )),
        5: ActConfig(5, "收束", (
            StageConfig("exchange", "交换信息",
                        frozenset({ActionType.INTRODUCE_CLUE, ActionType.QUESTION,
                                   ActionType.TALK, ActionType.ACCUSE, ActionType.OBSERVE}),
                        max_rounds=4),
            StageConfig("private", "私聊",
                        frozenset({ActionType.PRIVATE_CHAT_SEND}),
                        kind="private"),
            StageConfig("public", "公聊",
                        frozenset({ActionType.TALK, ActionType.QUESTION,
                                   ActionType.ACCUSE, ActionType.OBSERVE}),
                        max_rounds=2),
            StageConfig("vote", "投票",
                        frozenset({ActionType.VOTE}),
                        kind="vote"),
        )),
    }


class ActStateMachine:
    """五幕状态机：分阶段校验行动、累计轮次、私聊会话计数、全角色投票、推进。"""

    def __init__(self,
                 player_count: int = 6,
                 current_act: int = 1,
                 status: str = "playing"):
        if player_count < 1:
            raise ValueError("player_count 必须 ≥ 1")
        if current_act not in range(1, 6):
            raise ValueError(f"current_act 非法: {current_act}（应为 1-5）")
        self.player_count = player_count
        self.current_act = current_act
        self.status = status                    # playing/voted/completed
        self.stage_index = 0                    # 当前阶段序号（当前幕内）
        self.round_in_stage = 0                 # 本阶段已完成的轮次
        # 私聊会话：initiator → {target, count, closed}
        self.private_sessions: Dict[str, Dict[str, Any]] = {}
        self.votes: Dict[str, str] = {}         # 投票人 id → 目标角色 id
        self.act_log: List[Dict[str, Any]] = []
        self._acts = _build_acts()

    # ---------- 配置 ----------

    @property
    def act_config(self) -> ActConfig:
        return self._acts[self.current_act]

    @property
    def stage_config(self) -> StageConfig:
        return self.act_config.stages[self.stage_index]

    @staticmethod
    def _pair_key(a: str, b: str) -> str:
        return "|".join(sorted((a, b)))

    # ---------- 行动校验 ----------

    def validate_action(self,
                        action_type: ActionType,
                        actor_id: Optional[str] = None) -> Tuple[bool, str]:
        """校验一个玩家动作在当前阶段是否被允许。返回 (是否允许, 原因)。"""
        if action_type in GM_ACTIONS:
            return True, ""
        cfg = self.stage_config
        if action_type not in cfg.allowed_actions:
            return False, f"第{self.current_act}幕（{self.act_config.name}·{cfg.label}）禁止该行动: {action_type.value}"

        if cfg.kind == "rounds":
            if self.round_in_stage >= cfg.max_rounds:
                return False, "本阶段已达轮次上限"
            return True, ""

        if cfg.kind == "private":
            if action_type is ActionType.PRIVATE_CHAT_SEND and not actor_id:
                return False, "缺少私聊发起人"
            return True, ""

        if cfg.kind == "vote":
            if action_type is ActionType.VOTE and actor_id and actor_id in self.votes:
                return False, "你已经投过票了"
            return True, ""

        return True, ""

    # ---------- 行动记录（普通轮次） ----------

    def on_action(self,
                  action_type: ActionType,
                  actor_id: Optional[str] = None,
                  target_id: Optional[str] = None,
                  payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """记录一次普通行动并推进本阶段轮次。非法行动抛 ValueError。"""
        ok, reason = self.validate_action(action_type, actor_id)
        if not ok:
            raise ValueError(reason)
        event = {
            "act": self.current_act,
            "stage": self.stage_config.name,
            "round": self.round_in_stage + 1,
            "action_type": action_type.value,
            "actor_id": actor_id,
            "target_id": target_id,
            "payload": payload or {},
        }
        if self.stage_config.kind == "rounds":
            self.round_in_stage += 1
        self.act_log.append(event)
        return event

    # ---------- 私聊会话 ----------

    def begin_private_chat(self, initiator: str, target: str) -> Tuple[bool, str]:
        """发起一次私聊。每个角色只能发起一次；被选择的目标不计入发起次数。"""
        if self.stage_config.kind != "private":
            return False, "当前不在私聊阶段"
        if not initiator or not target:
            return False, "缺少私聊对象"
        if initiator in self.private_sessions:
            return False, "你已经发起过私聊了"
        self.private_sessions[initiator] = {"target": target, "count": 0, "closed": False}
        return True, ""

    def record_private_message(self, initiator: str, n: int = 1) -> Tuple[bool, int, bool]:
        """记录私聊消息。返回 (ok, 当前消息数, 是否达到上限强制结束)。"""
        session = self.private_sessions.get(initiator)
        if not session:
            return False, 0, False
        count = int(session["count"]) + n
        session["count"] = count
        if count >= PRIVATE_CHAT_MAX_MESSAGES:
            session["closed"] = True
        return True, count, session["closed"]

    def close_private_session(self, initiator: str) -> None:
        """主动结束某角色发起的私聊会话（未达上限也结束）。"""
        session = self.private_sessions.get(initiator)
        if session:
            session["closed"] = True

    def private_session(self, initiator: str) -> Optional[Dict[str, Any]]:
        return self.private_sessions.get(initiator)

    # ---------- 投票 ----------

    def register_vote(self, actor_id: str, target_id: str) -> Tuple[bool, bool]:
        """登记一票。返回 (ok, 是否已全部投完)。"""
        if self.stage_config.kind != "vote":
            return False, False
        if actor_id in self.votes:
            return False, False
        self.votes[actor_id] = target_id
        complete = len(self.votes) >= self.player_count
        return True, complete

    # ---------- 结束判定与推进 ----------

    def should_advance(self) -> bool:
        """当前阶段是否满足结束条件。"""
        cfg = self.stage_config
        if cfg.kind == "rounds":
            return self.round_in_stage >= cfg.max_rounds
        if cfg.kind == "private":
            all_initiated = len(self.private_sessions) >= self.player_count
            all_closed = all(s["closed"] for s in self.private_sessions.values())
            return all_initiated and all_closed
        if cfg.kind == "vote":
            return len(self.votes) >= self.player_count
        return False

    def advance(self) -> Dict[str, Any]:
        """推进到下一阶段/下一幕；第五幕投票完成后进入揭晓（status=voted）。"""
        if not self.should_advance():
            return {"advanced": False, "reason": "当前阶段结束条件未达成"}

        from_act = self.current_act
        from_stage = self.stage_config.name

        # 第五幕投票完成 → 揭晓
        if self.current_act == 5 and self.stage_config.kind == "vote":
            self.status = "voted"
            return {
                "advanced": True,
                "from_act": from_act,
                "from_stage": from_stage,
                "to_act": 5,
                "status": self.status,
                "message": "投票完成，进入真相揭晓",
            }

        # 推进到当前幕的下一阶段
        if self.stage_index + 1 < len(self.act_config.stages):
            self.stage_index += 1
            self.round_in_stage = 0
            return {
                "advanced": True,
                "from_act": from_act,
                "from_stage": from_stage,
                "to_act": self.current_act,
                "stage": self.stage_config.name,
                "stage_label": self.stage_config.label,
                "status": self.status,
                "message": f"第{self.current_act}幕进入阶段：{self.stage_config.label}",
            }

        # 当前幕阶段耗尽 → 下一幕
        self.current_act += 1
        self.stage_index = 0
        self.round_in_stage = 0
        # 私聊会话与投票仅属于所在幕：切幕时重置（第三/五幕各有一次私聊与投票）
        self.private_sessions = {}
        self.votes = {}
        return {
            "advanced": True,
            "from_act": from_act,
            "from_stage": from_stage,
            "to_act": self.current_act,
            "stage": self.stage_config.name,
            "stage_label": self.stage_config.label,
            "status": self.status,
            "message": f"推进到第{self.current_act}幕（{self.act_config.name}）",
        }

    def force_advance_instruction(self) -> str:
        """TRD 5.6 防无法结束：SYSTEM OVERRIDE 强制推进指令。"""
        return (
            "⚠️ SYSTEM OVERRIDE: 当前阶段已达到互动上限。你必须立即推进到下一阶段/下一幕。\n"
            "不允许：新线索、新对话、新场景。\n"
            '格式：{"action": "advance_act", "narration": "..."}'
        )

    # ---------- 序列化 ----------

    def summary(self) -> Dict[str, Any]:
        """供 LLM prompt 注入的状态摘要。"""
        cfg = self.stage_config
        return {
            "current_act": self.current_act,
            "act_name": self.act_config.name,
            "stage": cfg.name,
            "stage_label": cfg.label,
            "status": self.status,
            "round_in_stage": self.round_in_stage,
            "max_rounds": cfg.max_rounds if cfg.kind == "rounds" else None,
            "allowed_actions": sorted(a.value for a in cfg.allowed_actions),
            "private_sessions": {
                k: {"target": v["target"], "count": v["count"], "closed": v["closed"]}
                for k, v in self.private_sessions.items()
            },
            "votes": dict(self.votes),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "player_count": self.player_count,
            "current_act": self.current_act,
            "status": self.status,
            "stage_index": self.stage_index,
            "round_in_stage": self.round_in_stage,
            "private_sessions": self.private_sessions,
            "votes": dict(self.votes),
            "act_log": self.act_log,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActStateMachine":
        sm = cls(
            player_count=data.get("player_count", 6),
            current_act=data.get("current_act", 1),
            status=data.get("status", "playing"),
        )
        sm.stage_index = int(data.get("stage_index", 0))
        sm.round_in_stage = int(data.get("round_in_stage", 0))
        sm.private_sessions = dict(data.get("private_sessions") or {})
        sm.votes = dict(data.get("votes") or {})
        sm.act_log = data.get("act_log", [])
        if sm.stage_index >= len(sm.act_config.stages):
            sm.stage_index = len(sm.act_config.stages) - 1
        return sm
