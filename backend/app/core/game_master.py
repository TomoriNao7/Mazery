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
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.app.core.llm import get_llm_client
from backend.app.core.schemas import CaseReveal, GameMasterResponse
from backend.app.core.skill_manager import get_skill_manager

logger = logging.getLogger(__name__)


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


async def process_player_action(action: str,
                                game_state,
                                act_machine=None,
                                npc_simulator=None) -> AsyncIterator[str]:
    """
    每轮玩家行动处理：注入 game_master + character_actor，流式返回主持结果。

    Args:
        action: 玩家本轮行动描述（文本）
        game_state: 游戏状态对象，需暴露 active_npcs、summary()、
                    get_relevant_truth()、current_act、round_in_act
        act_machine: 可选 ActStateMachine，注入当前幕硬约束摘要
        npc_simulator: 可选 NpcSimulator，注入所有 NPC 动态状态卡
    """
    sm = get_skill_manager()
    if npc_simulator is not None:
        npc_contexts = npc_simulator.context_cards()
    else:
        npc_contexts = _build_npc_contexts(_get(game_state, None, "active_npcs", []))

    act_summary = act_machine.summary() if act_machine is not None else {}

    prompt = sm.build_system_prompt(
        ["game_master", "character_actor"],
        player_action=action,
        game_state=_get(game_state, "summary", "summary", {}),
        act_state=act_summary,
        npc_contexts=npc_contexts,
        truth_snippet=_get(game_state, "get_relevant_truth", "truth_snippet", {}),
        current_act=act_summary.get("current_act")
        or _get(game_state, None, "current_act", 1),
        round_number=act_summary.get("round_in_act")
        or _get(game_state, None, "round_in_act", 1),
    )
    # 主持是流式自然语言，不是结构化输出：明确要求输出旁白/台词文本，不要 JSON
    prompt += (
        "\n\n请直接输出主持人的旁白与相关 NPC 的台词（自然中文叙述），"
        "不要输出 JSON、不要输出字段名、不要输出 schema、不要加代码块。"
        "如果是你的回合，直接说话即可。"
    )
    async for chunk in get_llm_client().stream(prompt, max_tokens=2000):
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
    return await get_llm_client().call(prompt, schema=CaseReveal, max_tokens=3000)


async def generate_transition(game_state,
                              act_machine,
                              full: Optional[Dict[str, Any]] = None,
                              npc_simulator=None) -> Dict[str, Any]:
    """生成阶段/幕间转场旁白 + 幕间新隐私/新目标通知（PRD v0.2.0）。

    - 旁白：优先 game_master skill 生成，失败降级为模板。
    - 通知：从剧本 act_structure 提取（best-effort），供前端弹窗。
    """
    sm = get_skill_manager()
    act = act_machine.current_act if act_machine else 1
    stage_label = ""
    if act_machine is not None:
        stage_label = act_machine.stage_config.label

    prompt = sm.build_system_prompt(
        ["game_master"],
        transition=True,
        to_act=act,
        stage_label=stage_label,
        act_state=act_machine.summary() if act_machine is not None else {},
        game_state=game_state,
        npc_contexts=npc_simulator.context_cards() if npc_simulator is not None else {},
    )
    narration = f"—— 第{act}幕 · {stage_label or ''} ——"
    try:
        text = await get_llm_client().call(prompt, max_tokens=600)
        if text and str(text).strip():
            narration = str(text).strip()
    except Exception as e:
        logger.warning("转场旁白生成失败，使用模板: %s", e)

    return {
        "narration": narration,
        "notifications": _extract_act_notifications(full or {}, act),
    }


def _extract_act_notifications(full: Dict[str, Any], act: int) -> List[str]:
    """从剧本 act_structure 提取第 act 幕的'新隐私/新目标'通知（best-effort）。"""
    acts = (full.get("act_structure") or {}).get("acts") or []
    if not acts or act < 1 or act > len(acts):
        return []
    entry = acts[act - 1]
    if not isinstance(entry, dict):
        return []
    notifications: List[str] = []
    for key in ("notifications", "new_secrets", "new_goals", "new_revelations",
                "goal_updates", "act_switch"):
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            notifications.append(val.strip())
        elif isinstance(val, list):
            for v in val:
                if isinstance(v, str) and v.strip():
                    notifications.append(v.strip())
                elif isinstance(v, dict):
                    text = "；".join(str(x) for x in v.values() if x)
                    if text:
                        notifications.append(text)
    return notifications
