#GM主持人（状态机+单调用编排）
"""游戏进行阶段注入点（TRD 7.6）。

process_player_action：game_master + character_actor 两个 Skill 注入单次 LLM 调用，
负责场景旁白 + NPC 回应 + NPC 行动 + 线索揭示 + 幕推进。
reveal_truth：case_analyst 单次调用，负责真相揭晓与评分。

GameState / Game 目前尚未实现（backend/app/models 仍为占位），因此本模块对
传入对象采用鸭子类型：支持属性访问即可（.active_npcs / .summary() /
.get_relevant_truth() / .current_act / .round_in_act / .script.truth 等）。
"""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.app.core.llm import get_llm_client
from backend.app.core.schemas import CaseReveal, GameMasterResponse
from backend.app.core.skill_manager import get_skill_manager


@dataclass
class NpcState:
    """NPC 运行时状态（供 process_player_action 构建上下文）。"""

    id: str
    public_identity: Dict[str, Any] = field(default_factory=dict)
    knowledge_boundary: List[str] = field(default_factory=list)
    emotional_state: Dict[str, Any] = field(default_factory=dict)
    strategy: str = ""


def _build_npc_contexts(active_npcs) -> Dict[str, Dict[str, Any]]:
    """从 game_state.active_npcs 构建 NPC 上下文（支持对象或字典）。"""
    contexts: Dict[str, Dict[str, Any]] = {}
    for npc in active_npcs or []:
        if isinstance(npc, dict):
            npc_id = npc.get("id") or npc.get("npc_id")
            if not npc_id:
                continue
            contexts[str(npc_id)] = {
                "public_identity": npc.get("public_identity", {}),
                "knowledge_boundary": npc.get("knowledge_boundary", []),
                "emotional_state": npc.get("emotional_state", {}),
                "strategy": npc.get("strategy") or npc.get("current_strategy", ""),
            }
        else:
            npc_id = getattr(npc, "id", None) or getattr(npc, "npc_id", None)
            if not npc_id:
                continue
            contexts[str(npc_id)] = {
                "public_identity": getattr(npc, "public_identity", {}),
                "knowledge_boundary": getattr(npc, "knowledge_boundary", []),
                "emotional_state": getattr(npc, "emotional_state", {}),
                "strategy": (
                    getattr(npc, "strategy", None)
                    or getattr(npc, "current_strategy", "")
                ),
            }
    return contexts


def _get(obj: Any, method: str, attr: str, default: Any = None) -> Any:
    """优先调用方法，其次读属性，最后取字典键。"""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    if method and hasattr(obj, method) and callable(getattr(obj, method)):
        return getattr(obj, method)()
    return getattr(obj, attr, default)


async def process_player_action(action: str, game_state) -> AsyncIterator[str]:
    """
    每轮玩家行动处理：注入 game_master + character_actor，流式返回主持结果。

    Args:
        action: 玩家本轮行动描述（文本）
        game_state: 游戏状态对象，需暴露 active_npcs、summary()、
                    get_relevant_truth()、current_act、round_in_act
    """
    sm = get_skill_manager()
    npc_contexts = _build_npc_contexts(_get(game_state, None, "active_npcs", []))

    prompt = sm.build_system_prompt(
        ["game_master", "character_actor"],
        player_action=action,
        game_state=_get(game_state, "summary", "summary", {}),
        npc_contexts=npc_contexts,
        truth_snippet=_get(game_state, "get_relevant_truth", "truth_snippet", {}),
        current_act=_get(game_state, None, "current_act", 1),
        round_number=_get(game_state, None, "round_in_act", 1),
    )
    async for chunk in get_llm_client().stream(prompt):
        yield chunk


async def reveal_truth(game) -> Any:
    """
    真相揭晓：注入 case_analyst，返回 CaseReveal（解析失败时返回原始文本）。

    Args:
        game: 对局对象，需暴露 found_clues、player_vote、script.truth（或
              直接提供 summary()），支持字典形态。
    """
    sm = get_skill_manager()
    script = game.get("script") if isinstance(game, dict) else getattr(game, "script", None)
    truth = None
    if isinstance(script, dict):
        truth = script.get("truth")
    elif script is not None:
        truth = getattr(script, "truth", None)

    prompt = sm.build_system_prompt(
        ["case_analyst"],
        game_summary=_get(game, "summary", "summary", {}),
        found_clues=_get(game, None, "found_clues", []),
        player_vote=_get(game, None, "player_vote", None),
        truth=truth,
    )
    return await get_llm_client().call(prompt, schema=CaseReveal)
