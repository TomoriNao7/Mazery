#GM分幕状态机（TRD 第五章）
"""GM 分幕状态机：五幕硬约束、行动校验、轮次管理、结束条件与强制推进。

依据 TRD 五「每幕硬约束」表：
    第一幕 开场：允许旁白/自我介绍；禁止搜证/指控/投票；结束=全部角色介绍完毕；上限 2N 轮
    第二幕 搜证1：允许区域搜索/对话NPC；禁止投票/私聊；结束=探索轮次耗尽；4 轮探索
    第三幕 讨论：允许对质/质疑/私聊(≤2)；禁止发现新线索；结束=全员发言≥1；公开 8 轮 + 私聊 2 次
    第四幕 搜证2：允许深入搜索/对话；禁止投票/私聊；结束=探索轮次耗尽；3 轮探索
    第五幕 投票：允许推理陈述/投票指认；禁止新线索/新对话/私聊；结束=完成投票；8 轮

GM 自身动作（narration / system / advance_act）不受玩家行动约束限制。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class ActionType(str, Enum):
    """玩家与 GM 的动作类型。"""

    NARRATION = "narration"        # GM 旁白（GM 动作）
    SYSTEM = "system"              # 系统消息（GM 动作）
    ADVANCE = "advance_act"        # 幕推进（GM 动作）
    INTRODUCE = "introduce"        # 角色自我介绍
    SEARCH = "search"              # 区域搜证
    TALK = "talk"                  # 对话 NPC
    ACCUSE = "accuse"              # 公开对质/质询
    VOTE = "vote"                  # 投票指认
    PRIVATE_CHAT = "private_chat"  # 私聊
    OBSERVE = "observe"            # 观察


# GM 专属动作：不受幕约束限制
GM_ACTIONS = {ActionType.NARRATION, ActionType.SYSTEM, ActionType.ADVANCE}


@dataclass(frozen=True)
class ActConfig:
    """一幕的硬约束配置。"""

    act: int
    name: str
    allowed_actions: Set[ActionType]      # 玩家允许的行动
    end_condition: str                     # 结束条件描述
    max_rounds: int                        # 本轮上限（玩家行动轮）
    search_rounds: Optional[int] = None    # 探索幕固定搜索轮次
    max_private_chats: int = 0             # 本幕私聊次数上限

    @property
    def forbidden_actions(self) -> Set[ActionType]:
        """玩家禁止行动 = 全部玩家动作 - 允许动作。"""
        all_player = set(ActionType) - GM_ACTIONS
        return all_player - self.allowed_actions


def _build_acts(player_count: int) -> Dict[int, ActConfig]:
    """按玩家人数构建五幕配置（第一幕上限 = 2N 轮）。"""
    return {
        1: ActConfig(
            act=1, name="开场",
            allowed_actions={ActionType.INTRODUCE, ActionType.TALK, ActionType.OBSERVE},
            end_condition="所有角色介绍完毕",
            max_rounds=2 * player_count,
        ),
        2: ActConfig(
            act=2, name="搜证1",
            allowed_actions={ActionType.SEARCH, ActionType.TALK, ActionType.OBSERVE},
            end_condition="探索轮次耗尽",
            max_rounds=4,
            search_rounds=4,
        ),
        3: ActConfig(
            act=3, name="讨论",
            allowed_actions={ActionType.TALK, ActionType.ACCUSE, ActionType.PRIVATE_CHAT, ActionType.OBSERVE},
            end_condition="所有角色发言≥1次",
            max_rounds=8,
            max_private_chats=2,
        ),
        4: ActConfig(
            act=4, name="搜证2",
            allowed_actions={ActionType.SEARCH, ActionType.TALK, ActionType.OBSERVE},
            end_condition="探索轮次耗尽",
            max_rounds=3,
            search_rounds=3,
        ),
        5: ActConfig(
            act=5, name="投票",
            allowed_actions={ActionType.TALK, ActionType.ACCUSE, ActionType.VOTE, ActionType.OBSERVE},
            end_condition="用户完成投票",
            max_rounds=8,
        ),
    }


class ActStateMachine:
    """五幕状态机：校验行动、累计轮次、判定结束、推进/强制推进。"""

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
        self.status = status                 # playing/paused/voted/completed
        self.round_in_act = 0                # 本幕玩家行动轮数
        self.search_rounds_used = 0          # 探索幕已用搜索轮次
        self.private_chats_used = 0          # 本幕已用私聊次数
        self.introduced: Set[str] = set()    # 已介绍角色 id
        self.spoken: Set[str] = set()        # 已发言角色 id（第三幕结束条件）
        self.voted = False                   # 第五幕是否完成投票
        self.act_log: List[Dict[str, Any]] = []

        self._acts = _build_acts(player_count)

    # ---------- 配置 ----------

    @property
    def config(self) -> ActConfig:
        return self._acts[self.current_act]

    # ---------- 行动校验 ----------

    def validate_action(self,
                        action_type: ActionType,
                        actor_id: Optional[str] = None) -> Tuple[bool, str]:
        """校验一个玩家动作在当前幕是否被允许。返回 (是否允许, 原因)。"""
        if action_type in GM_ACTIONS:
            return True, ""

        cfg = self.config
        if action_type in cfg.forbidden_actions:
            return False, f"第{cfg.act}幕（{cfg.name}）禁止该行动: {action_type.value}"

        if self.round_in_act >= cfg.max_rounds:
            return False, "本幕已达轮次上限，即将强制推进"

        if action_type is ActionType.PRIVATE_CHAT and self.private_chats_used >= cfg.max_private_chats:
            return False, f"本幕私聊次数已达上限（{cfg.max_private_chats} 次）"

        if action_type is ActionType.VOTE and self.current_act != 5:
            return False, "投票仅限第五幕"

        return True, ""

    # ---------- 行动记录 ----------

    def on_action(self,
                  action_type: ActionType,
                  actor_id: Optional[str] = None,
                  target_id: Optional[str] = None,
                  payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """记录一次行动并更新状态。非法行动会抛 ValueError（调用方应先 validate）。"""
        ok, reason = self.validate_action(action_type, actor_id)
        if not ok:
            raise ValueError(reason)

        event: Dict[str, Any] = {
            "act": self.current_act,
            "round": self.round_in_act + 1,
            "action_type": action_type.value,
            "actor_id": actor_id,
            "target_id": target_id,
            "payload": payload or {},
        }

        if action_type is ActionType.INTRODUCE and actor_id:
            self.introduced.add(actor_id)
        if action_type is ActionType.TALK and actor_id:
            self.spoken.add(actor_id)
        if action_type is ActionType.PRIVATE_CHAT:
            self.private_chats_used += 1
            if actor_id:
                self.spoken.add(actor_id)
            if target_id:
                self.spoken.add(target_id)
        if action_type is ActionType.SEARCH:
            self.search_rounds_used += 1
        if action_type is ActionType.VOTE:
            self.voted = True

        self.round_in_act += 1
        self.act_log.append(event)
        return event

    # ---------- 结束判定 ----------

    def should_advance(self) -> bool:
        """当前幕是否满足结束条件（轮次耗尽或指定条件达成）。"""
        cfg = self.config
        if self.round_in_act >= cfg.max_rounds:
            return True
        if cfg.search_rounds is not None and self.search_rounds_used >= cfg.search_rounds:
            return True
        if cfg.act == 1 and len(self.introduced) >= self.player_count:
            return True
        if cfg.act == 3 and len(self.spoken) >= self.player_count:
            return True
        if cfg.act == 5 and self.voted:
            return True
        return False

    def advance(self) -> Dict[str, Any]:
        """推进到下一幕；第五幕完成后进入揭晓状态（status=voted）。"""
        if not self.should_advance():
            return {"advanced": False, "reason": "本幕结束条件未达成"}

        from_act = self.current_act
        if self.current_act >= 5:
            self.status = "voted"
            return {
                "advanced": True,
                "from_act": from_act,
                "to_act": 5,
                "status": self.status,
                "message": "第五幕投票完成，进入真相揭晓",
            }

        self.current_act += 1
        self.round_in_act = 0
        self.search_rounds_used = 0
        self.private_chats_used = 0
        self.introduced.clear()
        self.spoken.clear()
        return {
            "advanced": True,
            "from_act": from_act,
            "to_act": self.current_act,
            "status": self.status,
            "message": f"推进到第{self.current_act}幕（{self.config.name}）",
        }

    def force_advance_instruction(self) -> str:
        """TRD 五「防无法结束」：SYSTEM OVERRIDE 强制推进指令（注入 LLM prompt）。"""
        return (
            "⚠️ SYSTEM OVERRIDE: 本幕已达到互动上限。你必须立即推进到下一幕。\n"
            "不允许：新线索、新对话、新场景。\n"
            '格式：{"action": "advance_act", "narration": "..."}'
        )

    # ---------- 序列化 ----------

    def summary(self) -> Dict[str, Any]:
        """供 LLM prompt 注入的状态摘要。"""
        cfg = self.config
        return {
            "current_act": self.current_act,
            "act_name": cfg.name,
            "status": self.status,
            "round_in_act": self.round_in_act,
            "max_rounds": cfg.max_rounds,
            "search_rounds_used": self.search_rounds_used,
            "search_rounds": cfg.search_rounds,
            "private_chats_used": self.private_chats_used,
            "allowed_actions": sorted(a.value for a in cfg.allowed_actions),
            "forbidden_actions": sorted(a.value for a in cfg.forbidden_actions),
            "end_condition": cfg.end_condition,
        }

    def to_dict(self) -> Dict[str, Any]:
        """完整状态（用于 Game 存档/恢复）。"""
        return {
            "player_count": self.player_count,
            "current_act": self.current_act,
            "status": self.status,
            "round_in_act": self.round_in_act,
            "search_rounds_used": self.search_rounds_used,
            "private_chats_used": self.private_chats_used,
            "introduced": sorted(self.introduced),
            "spoken": sorted(self.spoken),
            "voted": self.voted,
            "act_log": self.act_log,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActStateMachine":
        sm = cls(
            player_count=data.get("player_count", 6),
            current_act=data.get("current_act", 1),
            status=data.get("status", "playing"),
        )
        sm.round_in_act = data.get("round_in_act", 0)
        sm.search_rounds_used = data.get("search_rounds_used", 0)
        sm.private_chats_used = data.get("private_chats_used", 0)
        sm.introduced = set(data.get("introduced", []))
        sm.spoken = set(data.get("spoken", []))
        sm.voted = data.get("voted", False)
        sm.act_log = data.get("act_log", [])
        return sm
