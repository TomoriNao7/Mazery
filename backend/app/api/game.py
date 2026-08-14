#游戏行动/状态/投票端点
"""游戏进行 API（TRD 十二章 + P5）：
    POST /api/game/start        开始新游戏（建 Game + NPC 状态）
    POST /api/game/{id}/action  玩家行动（SSE 流式）
    GET  /api/game/{id}/state   当前游戏状态（玩家可见）
    GET  /api/game/{id}/clues   已发现线索
    POST /api/game/{id}/vote    投票指认（第五幕）
    GET  /api/game/{id}/reveal  真相揭晓 & 复盘
    POST /api/game/{id}/save    保存进度
    GET  /api/game/list         对局列表
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.game_master import process_player_action, reveal_truth
from backend.app.core.game_state_machine import ActionType, ActStateMachine
from backend.app.core.npc_simulator import (
    NpcSimulator, NpcState, npc_states_from_character_set,
)
from backend.app.db.database import AsyncSessionFactory
from backend.app.db.models import Game, Script, GameSave
from backend.app.db.repository import GameRepo, NpcStateRepo, ScriptRepo

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------- 请求模型 ----------

class StartGameRequest(BaseModel):
    script_id: str
    player_char_id: Optional[str] = None


class PlayerActionRequest(BaseModel):
    action: str = Field(..., description="玩家行动描述")
    action_type: str = Field(..., description="introduce/search/talk/accuse/vote/private_chat/observe")
    actor_id: Optional[str] = None
    target_id: Optional[str] = None


class VoteRequest(BaseModel):
    actor_id: Optional[str] = None
    target_char_id: str


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


def _act_machine_from_game(game: Game, player_count: int) -> ActStateMachine:
    """从 game.game_log（JSON）恢复分幕状态机。"""
    game_log = _parse_json(game.game_log, {})
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
    game_log = _parse_json(game.game_log, {})
    if not isinstance(game_log, dict):
        game_log = {}
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


# ---------- 端点 ----------

@router.post("/start", summary="开始新游戏")
async def start_game(req: StartGameRequest,
                     session: AsyncSession = Depends(get_session)):
    script = await ScriptRepo(session).get(req.script_id, load_relation=False)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")

    full = _parse_json(script.full_script, {})
    states = npc_states_from_character_set(full.get("characters") or {})
    game = await GameRepo(session).create({
        "script_id": script.id,
        "status": "playing",
        "current_act": 1,
        "player_char_id": req.player_char_id,
    })
    machine = ActStateMachine(player_count=script.player_count or len(states) or 6)
    await _save_act_machine(session, game, machine)
    await NpcStateRepo(session).save_states(game.id, [s.to_dict() for s in states])

    return {
        "game_id": game.id,
        "current_act": 1,
        "status": "playing",
        "npc_count": len(states),
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
    machine.on_action(action_type, actor_id=req.actor_id,
                      target_id=req.target_id, payload={"content": req.action})

    game_view = {
        "summary": machine.summary(),
        "current_act": machine.current_act,
        "round_in_act": machine.round_in_act,
        "truth_snippet": full,
    }

    async def event_stream():
        try:
            async for chunk in process_player_action(
                req.action, game_view, act_machine=machine, npc_simulator=sim
            ):
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
            # 流结束后持久化状态与消息
            await _save_act_machine(session, game, machine)
            await _save_npc_states(session, game_id, sim)
            await GameRepo(session).add_message(game_id, {
                "act": machine.current_act,
                "role": req.actor_id or "player",
                "speaker_name": req.actor_id,
                "content": req.action,
                "action_type": action_type.value,
            })
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("玩家行动处理失败")
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{game_id}/state", summary="当前游戏状态")
async def game_state(game_id: str,
                     session: AsyncSession = Depends(get_session)):
    game, script, _ = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    return {
        "game_id": game.id,
        "script_id": game.script_id,
        "status": game.status,
        **machine.summary(),
    }


@router.get("/{game_id}/clues", summary="已发现线索")
async def game_clues(game_id: str,
                     session: AsyncSession = Depends(get_session)):
    game, _, full = await _load_game(session, game_id)
    found = _parse_json(game.found_clues, [])
    clues = (full.get("clues") or {}).get("key_clues", []) + \
            (full.get("clues") or {}).get("misleading_clues", []) + \
            (full.get("clues") or {}).get("neutral_clues", [])
    return [
        {"id": c.get("id"), "name": c.get("name"),
         "description": c.get("description"), "location": c.get("location")}
        for c in clues if isinstance(c, dict) and c.get("id") in found
    ]


@router.post("/{game_id}/vote", summary="投票指认凶手（第五幕）")
async def vote(game_id: str,
               req: VoteRequest,
               session: AsyncSession = Depends(get_session)):
    game, script, _ = await _load_game(session, game_id)
    machine = _act_machine_from_game(game, script.player_count)
    ok, reason = machine.validate_action(ActionType.VOTE, req.actor_id)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    machine.on_action(ActionType.VOTE, actor_id=req.actor_id, target_id=req.target_char_id)
    result = machine.advance()
    await _save_act_machine(session, game, machine)
    return {"vote": req.target_char_id, **result}


@router.get("/{game_id}/reveal", summary="真相揭晓 & 复盘")
async def reveal(game_id: str,
                 session: AsyncSession = Depends(get_session)):
    game, _, full = await _load_game(session, game_id)
    found = _parse_json(game.found_clues, [])
    result = await reveal_truth({
        "summary": {"game_id": game.id, "status": game.status},
        "found_clues": found,
        "player_vote": None,
        "script": {"truth": full},
    })
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result if isinstance(result, dict) else {"raw": result}


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


@router.get("/list", summary="对局列表")
async def list_games(session: AsyncSession = Depends(get_session)):
    games = await GameRepo(session).list(limit=50)
    return [
        {"id": g.id, "script_id": g.script_id, "status": g.status,
         "current_act": g.current_act, "updated_at": g.updated_at}
        for g in games
    ]
