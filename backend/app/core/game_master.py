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
import json
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
    # 主持是流式自然语言，不是结构化输出：GM 只做场景/背景/氛围旁白，不替 NPC 说话
    prompt += (
        "\n\n请只输出主持人的场景/背景/氛围旁白（自然中文叙述，3-5 句，不超过 150 字）。"
        "绝不要替任何 NPC 说话、绝不要输出任何 NPC 的台词或对话、不要用引号引用 NPC 的话"
        "（NPC 的发言由各自的发言气泡承担）。"
        "不要输出 JSON、不要输出字段名、不要输出 schema、不要加代码块。"
    )
    async for chunk in get_llm_client().stream(prompt, max_tokens=2000):
        yield chunk


async def generate_opening_background(full: Dict[str, Any],
                                     title: str,
                                     scene: str,
                                     llm=None) -> str:
    """生成游戏开场背景旁白（GM 只叙事，不替 NPC 说话）。失败时用剧本信息拼兜底。"""
    from backend.app.core.skill_manager import get_skill_manager
    sm = get_skill_manager()
    ws = full.get("world_setting") or {}
    outline = full.get("outline") or ""
    llm = llm or get_llm_client()
    prompt = sm.build_system_prompt(
        ["game_master"],
        opening=True,
        title=title,
        scene=scene or "",
        world_setting=ws,
        outline=outline,
    )
    prompt += (
        "\n\n请只输出一段游戏开场背景旁白（自然中文，4-6 句，约 120-180 字），介绍案发前的场景、"
        "氛围与当晚将要发生的事。绝不要替任何 NPC 说话、绝不要出现任何 NPC 的台词或对话、"
        "不要用引号引用 NPC 的话。不要输出 JSON。"
    )
    try:
        text = await llm.call(prompt, max_tokens=400)
        if text and str(text).strip():
            return str(text).strip()[:300]
    except Exception as e:
        logger.warning("开场背景生成失败（使用模板）: %s", e)
    parts = []
    if isinstance(ws, dict):
        for v in ws.values():
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
            elif isinstance(v, dict):
                for vv in v.values():
                    if isinstance(vv, str) and vv.strip():
                        parts.append(vv.strip())
    if outline:
        parts.append(outline)
    text = "；".join(parts)[:300]
    return text or f"—— {title} · 开场 ——"


async def reveal_truth(game) -> Any:
    """
    真相揭晓：注入 case_analyst，返回 CaseReveal（LLM 失败时从剧本核心信息拼装降级版）。
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
    try:
        return await get_llm_client().call(prompt, schema=CaseReveal, max_tokens=3000)
    except Exception as e:
        logger.warning("真相揭晓 LLM 生成失败（已降级）: %s", e)
        return _offline_reveal(truth, _get(game, None, "player_vote", None))


def _offline_reveal(truth: Any, player_vote: Any = None) -> "CaseReveal":
    """LLM 不可用时，从剧本 case_core / characters 拼装真相揭晓。"""
    cc = (truth or {}).get("case_core") or {}
    chars = (truth or {}).get("characters") or {}
    murderer_id = cc.get("murderer_id")
    mname = murderer_id
    for c in chars.get("characters", []):
        if isinstance(c, dict) and c.get("id") == murderer_id:
            mname = c.get("name") or murderer_id
            break
    method = cc.get("murder_method") or ""
    motive = cc.get("murder_motive") or ""
    time_loc = f"{cc.get('murder_time', '')} · {cc.get('murder_location', '')}".strip(" ·")
    summary = f"真凶是「{mname}」。"
    if method:
        summary += f"作案手法：{method}。"
    if motive:
        summary += f"作案动机：{motive}。"
    if time_loc:
        summary += f"案发：{time_loc}。"
    correct = bool(player_vote) and player_vote == murderer_id
    return CaseReveal(
        verdict="player_correct" if correct else "player_wrong",
        truth_summary=summary or "（真相揭晓生成失败，请参考剧本核心信息）",
        clue_chain_retrospective=[],
        missed_details=[],
        npc_outcomes=[],
        player_score={"total": 100 if correct else 0, "breakdown": []},
        grade="S" if correct else "C",
    )


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
    prompt += (
        "\n\n请只输出一段纯文字的场景/转场旁白（自然中文，3-5 句，不超过 150 字）。"
        "绝不要替任何 NPC 说话、绝不要输出 NPC 台词、不要用引号引用 NPC 的话。"
        "不要输出 JSON、不要输出字段名。"
    )
    narration = f"—— 第{act}幕 · {stage_label or ''} ——"
    try:
        text = await get_llm_client().call(prompt, max_tokens=600)
        if text and str(text).strip():
            text = str(text).strip()
            # 防御：若模型仍返回 JSON，提取其中文案
            if text.startswith("{"):
                try:
                    obj = json.loads(text)
                    inner = obj.get("content") or obj.get("narration") or ""
                    if isinstance(inner, str) and inner.strip():
                        text = inner.strip()
                except json.JSONDecodeError:
                    pass
            narration = text
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
