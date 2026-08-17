#游戏进行 API（PRD v0.2.0 / TRD 第五、六、十一章）
"""游戏进行 API：
    POST /api/game/start                  开始新游戏（选角色，写历史）
    POST /api/game/{id}/action            玩家行动（SSE 流式；阶段完成后自动转场）
    GET  /api/game/{id}/state             当前游戏状态
    GET  /api/game/{id}/clues             玩家已发现线索
    GET  /api/game/{id}/draw              抽卡搜证：返回 5 张背卡（第二/四幕）
    POST /api/game/{id}/draw/{card_id}    翻牌：返回线索详情
    GET  /api/game/{id}/private-chat/{npc_id}          私聊历史
    POST /api/game/{id}/private-chat/{npc_id}/send     发送私聊消息
    POST /api/game/{id}/vote               投票指认（全角色投票 + 汇总）
    POST /api/game/{id}/advance            进入下一阶段/下一幕（含 GM 转场）
    GET  /api/game/{id}/character-cards    各人物卡已写入的公开线索
    POST /api/game/{id}/finish             游戏结束：保存剧本到本地库 / 退出
    POST /api/game/{id}/save               对局存档
    GET  /api/game/{id}/reveal             真相揭晓 & 复盘
    GET  /api/game/list                    对局列表
"""

import asyncio
import json
import logging
import random
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.game_master import (
    process_player_action, reveal_truth, generate_transition, generate_opening_background,
)
from backend.app.core.game_state_machine import (
    ActionType, ActStateMachine, PRIVATE_CHAT_MAX_MESSAGES,
)
from backend.app.core.llm import get_llm_client
from backend.app.core.npc_simulator import (
    NpcSimulator, NpcState, npc_states_from_character_set,
)
from backend.app.core.discussion import (
    DiscussionEngine, init_discussion, is_discussion_stage,
)
from backend.app.core.script_privacy import public_field
from backend.app.db.database import AsyncSessionFactory
from backend.app.db.models import Game, Script, GameSave
from backend.app.db.repository import (
    GameRepo, NpcStateRepo, ScriptRepo, PlayHistoryRepo,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------- 请求模型 ----------

class StartGameRequest(BaseModel):
    script_id: str
    player_char_id: Optional[str] = None


class PlayerActionRequest(BaseModel):
    action: str = Field(..., description="玩家行动描述")
    action_type: str = Field(
        ..., description="introduce/question/introduce_clue/talk/accuse/observe"
    )
    actor_id: Optional[str] = None
    target_id: Optional[str] = None
    clue_id: Optional[str] = Field(None, description="介绍线索时携带的线索 id")
    reveal: bool = Field(
        False, description="是否如实公开该线索（仅 introduce_clue 生效；为 False 时只发言不公开）"
    )


class PrivateChatRequest(BaseModel):
    content: str


class DiscussionAnswerRequest(BaseModel):
    content: str = Field(..., description="玩家对 NPC 提问的回答")


class DiscussionActionRequest(BaseModel):
    content: str = Field(..., description="玩家在自己轮次的发言/提问")
    target_id: Optional[str] = Field(None, description="提问对象 id（可选，提问时填）")
    clue_id: Optional[str] = Field(None, description="公开自己线索时携带的线索 id（可选）")
    reveal: bool = Field(False, description="是否如实公开该线索")


class VoteRequest(BaseModel):
    actor_id: Optional[str] = None
    target_char_id: str


class FinishRequest(BaseModel):
    save_to_library: bool = True


# ---------- 依赖 ----------

async def get_session() -> AsyncSession:
    async with AsyncSessionFactory() as session:
        yield session


# ---------- 内部工具 ----------

def _parse_json(text: Optional[str], default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _load_game_log(game: Game) -> Dict[str, Any]:
    data = _parse_json(game.game_log, {})
    return data if isinstance(data, dict) else {}


def _act_machine_from_game(game: Game, player_count: int) -> ActStateMachine:
    """从 game.game_log（JSON）恢复分幕状态机。"""
    game_log = _load_game_log(game)
    machine_data = game_log.get("act_machine") if isinstance(game_log, dict) else None
    if machine_data:
        try:
            return ActStateMachine.from_dict(machine_data)
        except Exception as e:
            logger.warning("分幕状态机恢复失败，回退默认: %s", e)
    return ActStateMachine(player_count=player_count or 6,
                           current_act=game.current_act or 1,
                           status=game.status or "playing")


async def _save_act_machine(session: AsyncSession, game: Game,
                            machine: ActStateMachine) -> None:
    game_log = _load_game_log(game)
    game_log["act_machine"] = machine.to_dict()
    game.game_log = json.dumps(game_log, ensure_ascii=False)
    game.current_act = machine.current_act
    game.status = machine.status
    await session.commit()


def _fill_public_from_script(states: List[NpcState], full: Dict[str, Any]) -> None:
    """DB 只存动态状态，公开层/私有知识从剧本角色卡恢复。"""
    chars = (full.get("characters") or {}).get("characters", [])
    by_id = {c.get("id"): c for c in chars if isinstance(c, dict)}
    for st in states:
        c = by_id.get(st.npc_id, {})
        st.public_identity = c.get("public") or {"name": c.get("name", st.npc_id)}
        st.knowledge_boundary = list(c.get("knowledge_boundary") or [])
        private = []
        if c.get("secrets"):
            private.append("secrets: " + json.dumps(c["secrets"], ensure_ascii=False))
        if c.get("motive"):
            private.append("motive: " + json.dumps(c["motive"], ensure_ascii=False))
        if c.get("truth"):
            private.append("truth: " + json.dumps(c["truth"], ensure_ascii=False))
        st.private_knowledge = private


async def _load_game(session: AsyncSession, game_id: str) -> Tuple[Game, Script, Dict[str, Any]]:
    game = await GameRepo(session).get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="对局不存在")
    script = await ScriptRepo(session).get(game.script_id, load_relation=False)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    full = _parse_json(script.full_script, {})
    return game, script, full


async def _load_simulator(session: AsyncSession, game_id: str,
                          full: Dict[str, Any]) -> NpcSimulator:
    raw = await NpcStateRepo(session).load_states(game_id)
    states = [NpcState.from_dict(d) for d in raw]
    _fill_public_from_script(states, full)
    return NpcSimulator(states)


async def _save_npc_states(session: AsyncSession, game_id: str,
                           sim: NpcSimulator) -> None:
    await NpcStateRepo(session).save_states(
        game_id, [s.to_dict() for s in sim.all_states()]
    )


# ---------- 线索工具 ----------

def _all_clues(full: Dict[str, Any]) -> List[Dict[str, Any]]:
    clues = full.get("clues") or {}
    return (clues.get("key_clues") or []) + \
           (clues.get("misleading_clues") or []) + \
           (clues.get("neutral_clues") or [])


def _clue_by_id(full: Dict[str, Any], clue_id: str) -> Optional[Dict[str, Any]]:
    for c in _all_clues(full):
        if isinstance(c, dict) and c.get("id") == clue_id:
            return c
    return None


def _act_clue_ids(full: Dict[str, Any], act: int) -> List[str]:
    """当前幕的可抽线索：优先取 clue.act == act；无标注则回退全部。"""
    ids = [c.get("id") for c in _all_clues(full)
           if isinstance(c, dict) and c.get("act") == act and c.get("id")]
    if not ids:
        ids = [c.get("id") for c in _all_clues(full)
               if isinstance(c, dict) and c.get("id")]
    return ids


def _name_of(full: Dict[str, Any], char_id: Optional[str]) -> str:
    if not char_id:
        return ""
    chars = (full.get("characters") or {}).get("characters", [])
    for c in chars:
        if isinstance(c, dict) and c.get("id") == char_id:
            return c.get("name") or char_id
    return char_id


async def _mark_clue_public(session: AsyncSession, game: Game, game_log: Dict[str, Any],
                            sim: NpcSimulator, full: Dict[str, Any],
                            clue_id: str, act: int) -> None:
    """把一条线索标记为公开：进入人物卡，并广播给所有 NPC 的已知信息（幂等）。"""
    public = set(game_log.get("public_clue_ids") or [])
    if clue_id in public:
        return
    public.add(clue_id)
    game_log["public_clue_ids"] = sorted(public)
    clue = _clue_by_id(full, clue_id)
    # 真实线索也进左侧公开陈述列表
    _append_statement(game_log, {
        "id": clue_id,
        "name": clue.get("name") or clue_id,
        "speaker_id": None,
        "content": clue.get("description") or "",
        "location": clue.get("location") or None,
    })
    info = f"[公开线索] {clue_id}: {clue.get('name') if clue else ''}"
    sim.propagate_public_info(info, act)
    await NpcStateRepo(session).log_info(
        game_id=game.id, act=act, info_type="clue_reveal",
        info_content=info, source_id=None,
    )


def _append_statement(game_log: Dict[str, Any], stmt: Dict[str, Any]) -> None:
    """向 game_log.public_statements 追加一条公开陈述（按 id 幂等）。"""
    stmts = game_log.setdefault("public_statements", [])
    if not any(s.get("id") == stmt["id"] for s in stmts):
        stmts.append(stmt)


def _record_public_statement(game_log: Dict[str, Any], sp: Dict[str, Any],
                             full: Dict[str, Any]) -> None:
    """把一句（编造/隐瞒）发言记为公开陈述，供左侧列表与人物卡显示。

    sp 需含 statement_speaker / content；name 取发言摘要。
    """
    speaker = sp.get("statement_speaker") or sp.get("speaker_name")
    content = (sp.get("content") or "").strip()
    if not speaker or not content:
        return
    stmts = game_log.setdefault("public_statements", [])
    # 幂等：同发言者 + 同内容 不重复
    if any(s.get("speaker_id") == speaker and s.get("content") == content for s in stmts):
        return
    label = content if len(content) <= 16 else content[:16] + "…"
    stmts.append({
        "id": f"stmt_{speaker}_{len(stmts) + 1}",
        "name": f"{_name_of(full, speaker) or speaker}声称：{label}",
        "speaker_id": speaker,
        "content": content,
    })


# ---------- 阶段副作用与转场 ----------

async def _setup_npc_private_chats(session: AsyncSession, game: Game,
                                   machine: ActStateMachine,
                                   sim: NpcSimulator, full: Dict[str, Any]) -> None:
    """私聊阶段开始：为每个 NPC 建立一次性私聊会话（玩家会话由发送时创建），并生成玩家可见表象。"""
    player_char_id = game.player_char_id
    npc_ids = [s.npc_id for s in sim.all_states() if s.npc_id != player_char_id]

    candidates = sim.evaluate_private_chat_candidates(max_groups=3)
    for c in candidates:
        a, b = c["initiator"], c["target"]
        if (a != player_char_id and a not in machine.private_sessions
                and b and a != b):
            ok, _ = machine.begin_private_chat(a, b)
            if ok:
                machine.close_private_session(a)
    for npc in npc_ids:
        if npc in machine.private_sessions:
            continue
        others = [x for x in npc_ids if x != npc]
        tgt = random.choice(others) if others else None
        if tgt:
            ok, _ = machine.begin_private_chat(npc, tgt)
            if ok:
                machine.close_private_session(npc)

    surface = await sim.surface_npc_private_chats(full, get_llm_client())
    for text in surface:
        if text:
            await GameRepo(session).add_message(game.id, {
                "act": machine.current_act, "role": "system", "speaker_name": "GM",
                "content": text, "action_type": "narration",
            })


async def _advance(session: AsyncSession, game: Game, machine: ActStateMachine,
                   sim: NpcSimulator, full: Dict[str, Any]) -> Dict[str, Any]:
    """推进状态机并处理阶段副作用（交换信息公开、NPC 私聊、GM 转场/幕间通知）。"""
    result = machine.advance()
    if not result.get("advanced"):
        return {"advanced": False, **result}

    game_log = _load_game_log(game)
    game.current_act = machine.current_act
    game.status = machine.status
    stage = machine.stage_config.name

    # 讨论阶段：初始化轮次制讨论状态（exchange 的公开线索轮由下方 stage_speech 处理）
    if is_discussion_stage(stage):
        game_log["discussion"] = init_discussion(
            stage, machine.current_act, full, game.player_char_id,
            game_log.get("discussion"))

    npc_speeches: List[Dict[str, Any]] = []
    if stage == "exchange":
        # 交换信息：NPC 依次发言（三态：如实/隐瞒/编造）。如实发言带 reveal_clue_id，
        # 由前端在发言结束后调 /clue/{id}/public 公开；隐瞒/编造发言记为公开陈述并写入
        # NPC 记忆（_remember_statement），此处不提前公开真实线索。
        npc_speeches = await sim.generate_stage_speeches(
            "exchange", full, game.player_char_id, get_llm_client(),
            act=machine.current_act)
        for sp in npc_speeches:
            await GameRepo(session).add_message(game.id, {
                "act": machine.current_act, "role": sp["role"],
                "speaker_name": sp["speaker_name"], "content": sp["content"],
                "action_type": sp.get("action_type", "dialogue"),
            })
            if sp.get("reveal_clue_id"):
                game_log.setdefault("exchange_truthful", {})[sp["speaker_name"]] = \
                    sp["reveal_clue_id"]
            if sp.get("public_statement"):
                _record_public_statement(game_log, sp, full)
    if stage == "private":
        await _setup_npc_private_chats(session, game, machine, sim, full)

    game.game_log = json.dumps(game_log, ensure_ascii=False)
    await _save_act_machine(session, game, machine)

    transition = await generate_transition(
        {"summary": machine.summary()}, machine, full, sim
    )
    transition["act"] = machine.current_act
    transition["stage"] = stage
    if is_discussion_stage(stage):
        d = game_log.get("discussion") or {}
        transition["discussion_active"] = True
        transition["discussion_max_rounds"] = d.get("max_rounds", 1)
    # 幕间通知只在真正进入新一幕时弹出（阶段内转场不打扰玩家）
    if result.get("to_act") == result.get("from_act"):
        transition["notifications"] = []
    if npc_speeches:
        transition["npc_speeches"] = npc_speeches
    return {"advanced": True, **result, **transition}


# ---------- 端点 ----------

@router.post("/start", summary="开始新游戏")
async def start_game(req: StartGameRequest,
                     session: AsyncSession = Depends(get_session)):
    script = await ScriptRepo(session).get(req.script_id, load_relation=False)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")

    full = _parse_json(script.full_script, {})
    states = npc_states_from_character_set(full.get("characters") or {})
    chars = (full.get("characters") or {}).get("characters", [])
    char_ids = [c.get("id") for c in chars if isinstance(c, dict)]
    if req.player_char_id and req.player_char_id not in char_ids:
        raise HTTPException(status_code=400, detail="player_char_id 不在该剧本角色中")

    game = await GameRepo(session).create({
        "script_id": script.id,
        "status": "playing",
        "current_act": 1,
        "player_char_id": req.player_char_id,
    })
    machine = ActStateMachine(player_count=script.player_count or len(states) or 6)
    await _save_act_machine(session, game, machine)
    await NpcStateRepo(session).save_states(game.id, [s.to_dict() for s in states])

    # 记录历史游玩（按剧本去重，刷新时间）
    await PlayHistoryRepo(session).upsert(script.id)
    await GameRepo(session).add_message(game.id, {
        "act": 1, "role": "system", "speaker_name": "GM",
        "content": f"剧本《{script.title}》开始，第 1 幕（介绍）。", "action_type": "system",
    })
    # 开场：GM 先介绍前置背景（只叙事），再进入各 NPC 自我介绍。
    # 背景与自我介绍并行生成（各自失败各自兜底），减少串行 LLM 等待。
    intro_sim = NpcSimulator(states)

    async def _gen_background() -> str:
        try:
            return await generate_opening_background(
                full, script.title, full.get("scene") or script.scene, get_llm_client())
        except Exception:
            return full.get("outline") or f"—— {script.title} · 开场 ——"

    async def _gen_intros():
        return await intro_sim.generate_stage_speeches(
            "intro_r1", full, req.player_char_id, get_llm_client())

    background, intro_speeches = await asyncio.gather(_gen_background(), _gen_intros())

    await GameRepo(session).add_message(game.id, {
        "act": 1, "role": "system", "speaker_name": "GM",
        "content": background, "action_type": "narration",
    })
    for sp in intro_speeches:
        await GameRepo(session).add_message(game.id, {
            "act": 1, "role": sp["role"], "speaker_name": sp["speaker_name"],
            "content": sp["content"], "action_type": sp.get("action_type", "dialogue"),
        })

    return {
        "game_id": game.id,
        "current_act": 1,
        "status": "playing",
        "npc_count": len(states),
        "player_char_id": req.player_char_id,
        "npc_speeches": intro_speeches,
    }


@router.post("/{game_id}/action", summary="玩家行动（SSE 流式）")
async def player_action(game_id: str,
                        req: PlayerActionRequest,
                        session: AsyncSession = Depends(get_session)):
    game, script, full = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    sim = await _load_simulator(session, game_id, full)

    try:
        action_type = ActionType(req.action_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"非法 action_type: {req.action_type}")

    ok, reason = machine.validate_action(action_type, req.actor_id)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    # 讨论阶段：讨论一旦启动，玩家行动走 /discussion/* 端点，不走通用 /action
    if is_discussion_stage(machine.stage_config.name):
        d = (_load_game_log(game)).get("discussion") or {}
        if d.get("started") and not d.get("done"):
            raise HTTPException(status_code=400, detail="当前是讨论轮次，请在讨论区发言")

    # 介绍线索：仅当玩家选择「如实揭示」时才公开真实线索；否则把发言记为公开陈述
    # （左侧已公开线索/人物卡会显示这段发言，但「我的线索」仍只显示真实拿到的）。
    if action_type is ActionType.INTRODUCE_CLUE and req.clue_id:
        game_log = _load_game_log(game)
        if req.reveal and _clue_by_id(full, req.clue_id):
            await _mark_clue_public(session, game, game_log, sim, full,
                                    req.clue_id, machine.current_act)
        elif not req.reveal and (req.action or "").strip():
            _record_public_statement(game_log, {
                "statement_speaker": req.actor_id or game.player_char_id,
                "content": req.action.strip(),
            }, full)
            # 玩家说出的（编造/隐瞒）内容同样写进 NPC 记忆，便于后续被追问
            sim.propagate_public_info(
                f"[公开陈述] {_name_of(full, req.actor_id or game.player_char_id)}："
                f"{req.action.strip()}", machine.current_act)
        game.game_log = json.dumps(game_log, ensure_ascii=False)
        await session.commit()

    machine.on_action(action_type, actor_id=req.actor_id, target_id=req.target_id,
                      payload={"content": req.action, "clue_id": req.clue_id})

    game_view = {
        "summary": machine.summary(),
        "current_act": machine.current_act,
        "round_in_act": machine.round_in_stage,
        "truth_snippet": full,
    }

    async def event_stream():
        try:
            async for chunk in process_player_action(
                req.action, game_view, act_machine=machine, npc_simulator=sim
            ):
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.warning("玩家行动流式生成失败（已降级）: %s", e)
            yield f"data: {json.dumps({'warning': '主持生成失败，已记录你的行动'}, ensure_ascii=False)}\n\n"
        finally:
            # 行动已记录：无论流式是否成功，都检查阶段完成并推进、持久化
            try:
                if machine.should_advance():
                    adv = await _advance(session, game, machine, sim, full)
                    yield f"data: {json.dumps({'transition': adv}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.exception("阶段推进失败")
            try:
                await _save_act_machine(session, game, machine)
                await _save_npc_states(session, game_id, sim)
                await GameRepo(session).add_message(game_id, {
                    "act": machine.current_act,
                    "role": req.actor_id or "player",
                    "speaker_name": req.actor_id,
                    "content": req.action,
                    "action_type": action_type.value,
                })
            except Exception as e:
                logger.exception("玩家行动持久化失败")
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{game_id}/state", summary="当前游戏状态")
async def game_state(game_id: str,
                     session: AsyncSession = Depends(get_session)):
    game, script, _ = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    d = (_load_game_log(game)).get("discussion") or {}
    return {
        "game_id": game.id,
        "script_id": game.script_id,
        "status": game.status,
        "player_char_id": game.player_char_id,
        "discussion": {
            "active": bool(d) and not d.get("done")
                      and is_discussion_stage(machine.stage_config.name),
            "round": d.get("round", 1),
            "max_rounds": d.get("max_rounds", 1),
            "pending": d.get("pending"),
        },
        **machine.summary(),
    }


@router.get("/{game_id}/clues", summary="已发现线索")
async def game_clues(game_id: str,
                     session: AsyncSession = Depends(get_session)):
    game, _, full = await _load_game(session, game_id)
    found = _parse_json(game.found_clues, [])
    return [
        {"id": c.get("id"), "name": c.get("name"),
         "description": c.get("description"), "location": c.get("location")}
        for c in _all_clues(full)
        if isinstance(c, dict) and c.get("id") in found
    ]


@router.get("/{game_id}/messages", summary="聊天记录")
async def game_messages(game_id: str,
                        session: AsyncSession = Depends(get_session)):
    await _load_game(session, game_id)  # 校验对局存在
    msgs = await GameRepo(session).get_messages(game_id)
    return [
        {"id": m.id, "act": m.act, "role": m.role, "speaker_name": m.speaker_name,
         "content": m.content, "action_type": m.action_type, "created_at": m.created_at}
        for m in msgs
    ]


@router.post("/{game_id}/clue/{clue_id}/public", summary="公开一条线索（该线索发言结束后调用）")
async def publicize_clue(game_id: str, clue_id: str,
                         session: AsyncSession = Depends(get_session)):
    """把某条线索标记为公开（幂等）。由前端在对应 NPC 发言播放完毕后调用。"""
    game, script, full = await _load_game(session, game_id)
    if not _clue_by_id(full, clue_id):
        raise HTTPException(status_code=404, detail="线索不存在")
    sim = await _load_simulator(session, game_id, full)
    game_log = _load_game_log(game)
    await _mark_clue_public(session, game, game_log, sim, full,
                            clue_id, game.current_act)
    game.game_log = json.dumps(game_log, ensure_ascii=False)
    await session.commit()
    await _save_npc_states(session, game_id, sim)
    return {"public": True, "clue_id": clue_id}


@router.post("/{game_id}/exchange/reconcile", summary="重载时补公开已发言的如实线索")
async def reconcile_exchange(game_id: str,
                             session: AsyncSession = Depends(get_session)):
    """进入/重载交换阶段时，把「已如实发言」的线索补标记为公开，保证与前端一致。"""
    game, script, full = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    sim = await _load_simulator(session, game_id, full)
    game_log = _load_game_log(game)
    public = set(game_log.get("public_clue_ids") or [])
    added: List[str] = []
    # 用 _advance 时已存的「如实发言 → 真实线索」映射，避免重掷随机计划导致不一致
    truthful_map = game_log.get("exchange_truthful") or {}
    for cid, clue_id in truthful_map.items():
        if not clue_id or clue_id in public:
            continue
        await _mark_clue_public(session, game, game_log, sim, full,
                                clue_id, machine.current_act)
        public.add(clue_id)
        added.append(clue_id)
    game.game_log = json.dumps(game_log, ensure_ascii=False)
    await session.commit()
    await _save_npc_states(session, game_id, sim)
    return {"publicized": sorted(added)}


# ---------- 轮次制讨论（intro_r2 / exchange / public） ----------

async def _discussion_loop(session: AsyncSession, game: Game, machine: ActStateMachine,
                           sim: NpcSimulator, full: Dict[str, Any]) -> Dict[str, Any]:
    """从当前讨论状态生成 NPC 轮次，直到轮到玩家 / 待玩家回答 / 讨论结束。

    返回批次：{done, npc_messages, player_turn, round, max_rounds, transition?}。
    """
    game_log = _load_game_log(game)
    d = game_log.get("discussion")
    if not d or d.get("done"):
        raise HTTPException(status_code=400, detail="当前不在讨论中")
    d["started"] = True
    disc = DiscussionEngine(sim, full, game.player_char_id, game_log)

    messages: List[Dict[str, Any]] = []
    while not disc.is_done() and not d.get("pending"):
        participant = disc.current_participant()
        if not participant or participant == game.player_char_id:
            break
        for m in await disc.process_npc_turn(participant, machine.current_act, get_llm_client()):
            await GameRepo(session).add_message(game.id, {
                "act": machine.current_act, "role": m["role"],
                "speaker_name": m["speaker_name"], "content": m["content"],
                "action_type": m["action_type"],
            })
            messages.append(m)

    if disc.is_done():
        d["done"] = True
        # 讨论轮次不经过通用 /action，状态机轮次可能未满 → 置满以允许推进
        if machine.stage_config.kind == "rounds":
            machine.round_in_stage = machine.stage_config.max_rounds
        game.game_log = json.dumps(game_log, ensure_ascii=False)
        await session.commit()
        await _save_npc_states(session, game.id, sim)
        adv = await _advance(session, game, machine, sim, full)
        return {"done": True, "npc_messages": messages, "player_turn": None,
                "round": d.get("round"), "max_rounds": d.get("max_rounds"),
                "transition": adv}

    if d.get("pending"):
        player_turn = {"kind": "answer", "asker": d["pending"].get("asker"),
                       "question": d["pending"].get("question")}
    else:
        player_turn = {"kind": "question"}
    game.game_log = json.dumps(game_log, ensure_ascii=False)
    await session.commit()
    await _save_npc_states(session, game.id, sim)
    return {"done": False, "npc_messages": messages, "player_turn": player_turn,
            "round": d.get("round"), "max_rounds": d.get("max_rounds"),
            "transition": None}


def _ensure_discussion_active(game_log: Dict[str, Any], stage: str) -> Dict[str, Any]:
    d = game_log.get("discussion") or {}
    if not d or d.get("done") or d.get("stage") != stage:
        raise HTTPException(status_code=400, detail="当前不在讨论中")
    return d


@router.post("/{game_id}/discussion/next", summary="讨论：推进到下一步，取回一批 NPC 发言与玩家待办")
async def discussion_next(game_id: str,
                          session: AsyncSession = Depends(get_session)):
    game, script, full = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    sim = await _load_simulator(session, game_id, full)
    _ensure_discussion_active(_load_game_log(game), machine.stage_config.name)
    return await _discussion_loop(session, game, machine, sim, full)


@router.post("/{game_id}/discussion/answer", summary="讨论：玩家回答某 NPC 的问题")
async def discussion_answer(game_id: str, req: DiscussionAnswerRequest,
                            session: AsyncSession = Depends(get_session)):
    game, script, full = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    sim = await _load_simulator(session, game_id, full)
    game_log = _load_game_log(game)
    d = _ensure_discussion_active(game_log, machine.stage_config.name)
    if not d.get("pending"):
        raise HTTPException(status_code=400, detail="当前没有待回答的问题")
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="回答不能为空")
    await GameRepo(session).add_message(game.id, {
        "act": machine.current_act, "role": "player",
        "speaker_name": game.player_char_id, "content": content,
        "action_type": "dialogue",
    })
    sim.propagate_public_info(
        f"[回答] {_name_of(full, game.player_char_id)}：{content}", machine.current_act)
    d["pending"] = None
    game.game_log = json.dumps(game_log, ensure_ascii=False)
    await session.commit()
    await _save_npc_states(session, game.id, sim)
    return await _discussion_loop(session, game, machine, sim, full)


@router.post("/{game_id}/discussion/action", summary="讨论：玩家在自己轮次提问或发言")
async def discussion_action(game_id: str, req: DiscussionActionRequest,
                            session: AsyncSession = Depends(get_session)):
    game, script, full = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    sim = await _load_simulator(session, game_id, full)
    game_log = _load_game_log(game)
    d = _ensure_discussion_active(game_log, machine.stage_config.name)
    if d.get("pending"):
        raise HTTPException(status_code=400, detail="你还有待回答的问题")
    disc = DiscussionEngine(sim, full, game.player_char_id, game_log)
    if disc.current_participant() != game.player_char_id:
        raise HTTPException(status_code=400, detail="还没轮到你发言")
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="发言不能为空")
    await GameRepo(session).add_message(game.id, {
        "act": machine.current_act, "role": "player",
        "speaker_name": game.player_char_id, "content": content,
        "action_type": "dialogue",
    })
    # 玩家选择如实公开自己的线索 → 公开真实线索；否则记录发言为公开陈述（可撒谎）
    if req.clue_id and _clue_by_id(full, req.clue_id):
        if req.reveal:
            await _mark_clue_public(session, game, game_log, sim, full,
                                    req.clue_id, machine.current_act)
        else:
            _record_public_statement(game_log, {
                "statement_speaker": game.player_char_id, "content": content,
            }, full)
            sim.propagate_public_info(
                f"[公开陈述] {_name_of(full, game.player_char_id)}：{content}",
                machine.current_act)
    sim.propagate_public_info(
        f"[发言] {_name_of(full, game.player_char_id)}：{content}", machine.current_act)
    if req.target_id and req.target_id != game.player_char_id:
        reply = await disc.gen_npc_reply(req.target_id, game.player_char_id, content,
                                         get_llm_client())
        await GameRepo(session).add_message(game.id, {
            "act": machine.current_act, "role": f"character_{req.target_id}",
            "speaker_name": req.target_id, "content": reply.content,
            "action_type": "stage_speech",
        })
        sim.propagate_public_info(
            f"[回答] {_name_of(full, req.target_id)}：{reply.content}", machine.current_act)
    disc.advance_turn()
    game.game_log = json.dumps(game_log, ensure_ascii=False)
    await session.commit()
    await _save_npc_states(session, game.id, sim)
    return await _discussion_loop(session, game, machine, sim, full)


@router.post("/{game_id}/discussion/pass", summary="讨论：玩家跳过本轮提问")
async def discussion_pass(game_id: str,
                          session: AsyncSession = Depends(get_session)):
    game, script, full = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    sim = await _load_simulator(session, game_id, full)
    game_log = _load_game_log(game)
    d = _ensure_discussion_active(game_log, machine.stage_config.name)
    if d.get("pending"):
        raise HTTPException(status_code=400, detail="你还有待回答的问题")
    disc = DiscussionEngine(sim, full, game.player_char_id, game_log)
    if disc.current_participant() != game.player_char_id:
        raise HTTPException(status_code=400, detail="还没轮到你发言")
    await GameRepo(session).add_message(game.id, {
        "act": machine.current_act, "role": "system", "speaker_name": "GM",
        "content": f"（你选择跳过本轮发言。）", "action_type": "narration",
    })
    disc.advance_turn()
    game.game_log = json.dumps(game_log, ensure_ascii=False)
    await session.commit()
    await _save_npc_states(session, game.id, sim)
    return await _discussion_loop(session, game, machine, sim, full)


# ---------- 抽卡搜证（第二/四幕） ----------

@router.get("/{game_id}/draw", summary="抽卡搜证：返回 5 张背卡")
async def draw(game_id: str,
               session: AsyncSession = Depends(get_session)):
    game, script, full = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    if machine.stage_config.name != "draw":
        raise HTTPException(status_code=400, detail="当前不在抽卡阶段")
    found = _parse_json(game.found_clues, [])
    available = [cid for cid in _act_clue_ids(full, machine.current_act) if cid not in found]
    random.shuffle(available)
    pool = available[:5]
    if not pool:
        raise HTTPException(status_code=400, detail="本幕没有更多可抽的线索了")
    game_log = _load_game_log(game)
    game_log["draw_pool"] = pool
    game.game_log = json.dumps(game_log, ensure_ascii=False)
    await session.commit()
    return {
        "cards": [{"card_id": f"card_{i + 1}", "index": i} for i in range(len(pool))],
        "act": machine.current_act,
    }


@router.post("/{game_id}/draw/{card_id}", summary="翻牌：返回线索详情")
async def draw_pick(game_id: str, card_id: str,
                    session: AsyncSession = Depends(get_session)):
    game, script, full = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    if machine.stage_config.name != "draw":
        raise HTTPException(status_code=400, detail="当前不在抽卡阶段")
    game_log = _load_game_log(game)
    pool = game_log.get("draw_pool") or []
    try:
        idx = int(card_id.rsplit("_", 1)[-1]) - 1
        clue_id = pool[idx]
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="无效的卡牌")

    clue = _clue_by_id(full, clue_id)
    if not clue:
        raise HTTPException(status_code=404, detail="线索不存在")

    found = _parse_json(game.found_clues, [])
    if clue_id not in found:
        found.append(clue_id)
    game.found_clues = json.dumps(found, ensure_ascii=False)

    machine.on_action(ActionType.DRAW, actor_id=game.player_char_id)
    sim = await _load_simulator(session, game_id, full)
    sim.assign_draw_clues(_act_clue_ids(full, machine.current_act),
                          player_char_id=game.player_char_id, player_chosen=clue_id)
    await _save_act_machine(session, game, machine)
    await _save_npc_states(session, game_id, sim)
    await GameRepo(session).add_message(game_id, {
        "act": machine.current_act, "role": "narrator", "speaker_name": "GM",
        "content": f"你找到了线索【{clue.get('name')}】", "action_type": "search",
    })
    return {
        "clue": {"id": clue.get("id"), "name": clue.get("name"),
                 "description": clue.get("description"), "location": clue.get("location")},
        "act": machine.current_act,
    }


# ---------- 私聊（第三/五幕） ----------

@router.get("/{game_id}/private-chat/{npc_id}", summary="私聊历史")
async def private_chat_history(game_id: str, npc_id: str,
                               session: AsyncSession = Depends(get_session)):
    messages = await GameRepo(session).get_messages(game_id)
    rows = [m for m in messages if m.action_type == "private_chat"]
    return [
        {"role": m.role, "speaker_name": m.speaker_name, "content": m.content,
         "created_at": m.created_at}
        for m in rows
    ]


@router.post("/{game_id}/private-chat/{npc_id}/send", summary="发送私聊消息")
async def private_chat_send(game_id: str, npc_id: str,
                            req: PrivateChatRequest,
                            session: AsyncSession = Depends(get_session)):
    game, script, full = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    if machine.stage_config.kind != "private":
        raise HTTPException(status_code=400, detail="当前不在私聊阶段")
    player_char_id = game.player_char_id
    if not player_char_id:
        raise HTTPException(status_code=400, detail="未指定玩家角色")
    chars = (full.get("characters") or {}).get("characters", [])
    if npc_id not in [c.get("id") for c in chars if isinstance(c, dict)]:
        raise HTTPException(status_code=404, detail="私聊对象不存在")

    existing = machine.private_session(player_char_id)
    if existing and existing.get("target") != npc_id:
        raise HTTPException(status_code=400, detail="你已经选择与其他角色私聊了")
    if existing and existing.get("closed"):
        raise HTTPException(status_code=400, detail="本次私聊已达上限")
    if existing is None:
        ok, reason = machine.begin_private_chat(player_char_id, npc_id)
        if not ok:
            raise HTTPException(status_code=400, detail=reason)

    # 记录玩家消息并计数（流开始前完成，保证流失败时状态一致）
    await GameRepo(session).add_message(game_id, {
        "act": machine.current_act, "role": "player", "speaker_name": player_char_id,
        "content": req.content, "action_type": "private_chat",
    })
    sim = await _load_simulator(session, game_id, full)
    ok, count, ended = machine.record_private_message(player_char_id, 2)

    # 玩家角色的公开信息（仅 L1 public 层，不含秘密/真相，供 NPC 判断立场）
    player_profile = None
    for c in chars:
        if isinstance(c, dict) and c.get("id") == player_char_id:
            player_profile = {"id": c.get("id"), "name": c.get("name"),
                              "public": c.get("public", {})}
            break

    async def event_stream():
        reply_text = ""
        try:
            async for chunk in sim.generate_npc_reply_stream(
                npc_id, req.content, get_llm_client(),
                player_char_id=player_char_id,
                player_profile=player_profile,
            ):
                reply_text += chunk
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.warning("私聊回复流式生成失败（已降级）: %s", e)
            reply_text = "……（对方似乎不愿多说）"
            yield f"data: {json.dumps({'chunk': reply_text}, ensure_ascii=False)}\n\n"
        finally:
            await GameRepo(session).add_message(game_id, {
                "act": machine.current_act, "role": f"character_{npc_id}",
                "speaker_name": npc_id, "content": reply_text,
                "action_type": "private_chat",
            })
            transition = None
            if ended and machine.should_advance():
                transition = await _advance(session, game, machine, sim, full)
            await _save_act_machine(session, game, machine)
            await _save_npc_states(session, game_id, sim)
            meta = {
                "count": count,
                "max": PRIVATE_CHAT_MAX_MESSAGES,
                "remaining": max(0, PRIVATE_CHAT_MAX_MESSAGES - count),
                "forced_end": ended,
                "transition": transition,
            }
            yield f"data: {json.dumps({'meta': meta}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{game_id}/private-chat/{npc_id}/end", summary="提前结束私聊")
async def private_chat_end(game_id: str, npc_id: str,
                           session: AsyncSession = Depends(get_session)):
    game, script, full = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    player = game.player_char_id
    sess = machine.private_session(player) if player else None
    if not sess or sess.get("target") != npc_id:
        raise HTTPException(status_code=400, detail="没有进行中的该私聊")
    machine.close_private_session(player)
    transition = None
    sim = await _load_simulator(session, game_id, full)
    if machine.should_advance():
        transition = await _advance(session, game, machine, sim, full)
    await _save_act_machine(session, game, machine)
    await _save_npc_states(session, game_id, sim)
    return {"ok": True, "closed": True, "transition": transition}


# ---------- 投票（第五幕，全角色） ----------

@router.post("/{game_id}/vote", summary="投票指认凶手（全角色投票）")
async def vote(game_id: str,
               req: VoteRequest,
               session: AsyncSession = Depends(get_session)):
    game, script, full = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    if machine.stage_config.kind != "vote":
        raise HTTPException(status_code=400, detail="当前不在投票阶段")
    actor_id = req.actor_id or game.player_char_id
    if not actor_id:
        raise HTTPException(status_code=400, detail="缺少投票人")
    chars = (full.get("characters") or {}).get("characters", [])
    valid = [c.get("id") for c in chars if isinstance(c, dict)]
    if req.target_char_id not in valid:
        raise HTTPException(status_code=400, detail="投票目标非法")

    ok, _ = machine.register_vote(actor_id, req.target_char_id)
    if not ok:
        raise HTTPException(status_code=400, detail="你已经投过票了")

    sim = await _load_simulator(session, game_id, full)
    npc_votes = await sim.cast_npc_votes(get_llm_client(), player_char_id=game.player_char_id)
    for npc, tgt in npc_votes.items():
        if npc in valid and tgt in valid:
            machine.register_vote(npc, tgt)

    complete = len(machine.votes) >= machine.player_count
    counts: Dict[str, int] = {}
    for tgt in machine.votes.values():
        counts[tgt] = counts.get(tgt, 0) + 1
    advance_result = machine.advance() if complete else {"advanced": False}

    await _save_act_machine(session, game, machine)
    await _save_npc_states(session, game_id, sim)
    await GameRepo(session).add_message(game_id, {
        "act": 5, "role": "player", "speaker_name": actor_id,
        "content": f"投票指认：{_name_of(full, req.target_char_id)}", "action_type": "vote",
    })
    return {
        "player_vote": req.target_char_id,
        "npc_votes": npc_votes,
        "vote_counts": counts,
        "complete": complete,
        "status": machine.status,
        "advance": advance_result,
    }


# ---------- 推进 ----------

@router.post("/{game_id}/advance", summary="进入下一阶段/下一幕")
async def advance(game_id: str,
                  session: AsyncSession = Depends(get_session)):
    game, script, full = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    if not machine.should_advance():
        raise HTTPException(status_code=400, detail="当前阶段结束条件未达成")
    sim = await _load_simulator(session, game_id, full)
    result = await _advance(session, game, machine, sim, full)
    await _save_npc_states(session, game_id, sim)
    return result


# ---------- 人物卡 ----------

@router.get("/{game_id}/character-cards", summary="各人物卡已写入的公开线索")
async def character_cards(game_id: str,
                          session: AsyncSession = Depends(get_session)):
    game, _, full = await _load_game(session, game_id)
    game_log = _load_game_log(game)
    public_ids = set(game_log.get("public_clue_ids") or [])
    stmts = game_log.get("public_statements") or []
    chars = (full.get("characters") or {}).get("characters", [])
    cards = []
    for c in chars:
        if not isinstance(c, dict):
            continue
        public = c.get("public") or {}
        clues = []
        for clue in _all_clues(full):
            if (isinstance(clue, dict) and clue.get("id") in public_ids
                    and clue.get("points_to") == c.get("id")):
                clues.append({"id": clue.get("id"), "name": clue.get("name"),
                              "description": clue.get("description")})
        # 编造/隐瞒陈述挂到发言者人物卡上（前缀"声称"）
        for st in stmts:
            if st.get("speaker_id") == c.get("id"):
                clues.append({"id": st.get("id"),
                              "name": f"声称 · {st.get('name') or ''}",
                              "description": st.get("content") or ""})
        cards.append({
            "id": c.get("id"),
            "name": c.get("name"),
            "identity": public_field(public, "identity", "身份", "职业"),
            "clues": clues,
        })
    # 左侧「已公开线索」：全部公开陈述（真实线索 + 编造/隐瞒发言）
    public_clues = [{"id": s.get("id"), "name": s.get("name") or "",
                     "location": s.get("location")} for s in stmts]
    return {"cards": cards, "public_clues": public_clues}


# ---------- 结束 / 存档 / 揭晓 ----------

@router.post("/{game_id}/finish", summary="游戏结束：保存剧本到本地库 / 退出")
async def finish(game_id: str,
                 req: FinishRequest,
                 session: AsyncSession = Depends(get_session)):
    game, script, _ = await _load_game(session, game_id)
    saved = False
    if req.save_to_library:
        await ScriptRepo(session).set_saved(script.id, 1)
        saved = True
    await GameRepo(session).update(game.id, {"status": "completed"})
    return {"ok": True, "saved_to_library": saved, "status": "completed"}


@router.post("/{game_id}/save", summary="保存游戏进度")
async def save_game(game_id: str,
                    session: AsyncSession = Depends(get_session)):
    game, script, full = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    sim = await _load_simulator(session, game_id, full)
    save = GameSave(
        game_id=game_id,
        save_data=json.dumps({
            "act_machine": machine.to_dict(),
            "npc_states": [s.to_dict() for s in sim.all_states()],
        }, ensure_ascii=False),
    )
    session.add(save)
    await session.commit()
    await session.refresh(save)
    return {"save_id": save.id}


@router.get("/{game_id}/reveal", summary="真相揭晓 & 复盘")
async def reveal(game_id: str,
                 session: AsyncSession = Depends(get_session)):
    game, script, full = await _load_game(session, game_id)
    found = _parse_json(game.found_clues, [])
    machine = _act_machine_from_game(game, script.player_count)
    player_vote = machine.votes.get(game.player_char_id) if game.player_char_id else None
    result = await reveal_truth({
        "summary": {"game_id": game.id, "status": game.status},
        "found_clues": found,
        "player_vote": player_vote,
        "script": {"truth": full},
    })
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result if isinstance(result, dict) else {"raw": result}


@router.get("/list", summary="对局列表")
async def list_games(session: AsyncSession = Depends(get_session)):
    games = await GameRepo(session).list(limit=50)
    return [
        {"id": g.id, "script_id": g.script_id, "status": g.status,
         "current_act": g.current_act, "updated_at": g.updated_at}
        for g in games
    ]
