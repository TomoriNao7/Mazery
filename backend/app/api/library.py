#剧本库 API（PRD v0.2.0 第五/七章）
"""剧本库与人物选择 API：
    GET  /api/scripts/local       本地剧本库列表（书架）
    GET  /api/scripts/history     历史游玩剧本库列表（7 天清除，按剧本去重）
    POST /api/script/{id}/save    保存剧本到本地剧本库
    GET  /api/script/{id}/info    剧本详情弹窗（简介/文本量，L1）
    GET  /api/script/{id}/characters  人物选择列表（L1 公开信息）
    GET  /api/script/{id}/character/{cid}  某角色 L2 完整设定
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.script_privacy import public_field, script_text_size
from backend.app.db.database import AsyncSessionFactory
from backend.app.db.models import Script
from backend.app.db.repository import PlayHistoryRepo, ScriptRepo

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------- 依赖 ----------

async def get_session() -> AsyncSession:
    async with AsyncSessionFactory() as session:
        yield session


# ---------- 工具 ----------

def _parse_full(script: Script) -> Dict[str, Any]:
    try:
        data = json.loads(script.full_script) if script.full_script else {}
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _pub(public: Any, *keys: str) -> Any:
    """从 public 字典容错取字段（支持中英文键），返回第一个非空值。"""
    return public_field(public, *keys)


def _script_card(s: Script) -> Dict[str, Any]:
    return {
        "id": s.id,
        "title": s.title,
        "category": s.category,
        "scene": s.scene,
        "player_count": s.player_count,
        "summary": s.summary,
        "is_saved": s.is_saved,
        "text_size": script_text_size(_parse_full(s)),
        "created_at": s.created_at,
    }


def _characters_l1(full: Dict[str, Any]) -> List[Dict[str, Any]]:
    """人物选择列表：每个角色的 L1 公开信息（姓名/年龄/性别/职业/个性等）。"""
    chars = (full.get("characters") or {}).get("characters", [])
    result = []
    for c in chars:
        if not isinstance(c, dict):
            continue
        public = c.get("public") or {}
        result.append({
            "id": c.get("id"),
            "name": c.get("name"),
            "age": _pub(public, "age", "年龄"),
            "gender": _pub(public, "gender", "性别"),
            "profession": _pub(public, "profession", "职业", "身份", "identity"),
            "personality": _pub(public, "personality", "性格", "公开性格"),
            "identity": _pub(public, "identity", "身份", "职业"),
            "appearance": _pub(public, "appearance", "外貌", "外貌特征"),
            "background": _pub(public, "background", "公开背景", "背景"),
        })
    return result


def _find_character(full: Dict[str, Any], cid: str) -> Dict[str, Any]:
    chars = (full.get("characters") or {}).get("characters", [])
    for c in chars:
        if isinstance(c, dict) and (c.get("id") == cid or c.get("name") == cid):
            return c
    raise HTTPException(status_code=404, detail="角色不存在")


# ---------- 剧本库 ----------

@router.get("/scripts/local", summary="本地剧本库列表")
async def local_scripts(session: AsyncSession = Depends(get_session)):
    query = (select(Script)
             .where(Script.is_saved == 1)
             .order_by(Script.created_at.desc()))
    rows = (await session.execute(query)).scalars().all()
    return [_script_card(s) for s in rows]


@router.get("/scripts/history", summary="历史游玩剧本库列表")
async def history_scripts(session: AsyncSession = Depends(get_session)):
    return await PlayHistoryRepo(session).list_recent()


@router.post("/script/{script_id}/save", summary="保存剧本到本地剧本库")
async def save_script(script_id: str, session: AsyncSession = Depends(get_session)):
    script = await ScriptRepo(session).get(script_id, load_relation=False)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    was_saved = script.is_saved
    await ScriptRepo(session).set_saved(script_id, 1)
    return {"ok": True, "already_saved": bool(was_saved)}


class ScriptUpdateRequest(BaseModel):
    """剧本信息编辑请求：只允许更新展示性元信息，不接受角色/线索等结构字段。"""

    title: Optional[str] = None
    summary: Optional[str] = None
    scene: Optional[str] = None
    category: Optional[str] = None


@router.post("/script/{script_id}/update", summary="更新剧本信息（标题/简介等）")
async def update_script(script_id: str, req: ScriptUpdateRequest,
                        session: AsyncSession = Depends(get_session)):
    script = await ScriptRepo(session).get(script_id, load_relation=False)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if updates:
        script = await ScriptRepo(session).update(script_id, updates)
        if not script:
            raise HTTPException(status_code=404, detail="剧本不存在")
    return _script_card(script)


# ---------- 剧本详情 & 人物选择 ----------

@router.get("/script/{script_id}/info", summary="剧本详情弹窗（L1）")
async def script_info(script_id: str, session: AsyncSession = Depends(get_session)):
    script = await ScriptRepo(session).get(script_id, load_relation=False)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    return _script_card(script)


@router.get("/script/{script_id}/characters", summary="人物选择列表（L1）")
async def script_characters(script_id: str, session: AsyncSession = Depends(get_session)):
    script = await ScriptRepo(session).get(script_id, load_relation=False)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    full = _parse_full(script)
    return {
        "script_id": script.id,
        "title": script.title,
        "category": script.category,
        "characters": _characters_l1(full),
    }


@router.get("/script/{script_id}/character/{cid}", summary="某角色 L2 完整设定")
async def script_character_detail(script_id: str, cid: str,
                                  session: AsyncSession = Depends(get_session)):
    script = await ScriptRepo(session).get(script_id, load_relation=False)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    c = _find_character(_parse_full(script), cid)
    public = c.get("public") or {}
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "identity": _pub(public, "identity", "身份", "职业"),
        "background": _pub(public, "background", "公开背景", "背景"),
        "appearance": _pub(public, "appearance", "外貌", "外貌特征"),
        "relationships": c.get("relationships") or [],
        "goal": c.get("motive") or c.get("goal"),
        "secrets": c.get("secrets") or [],
    }
