#剧本生成端点
"""剧本生成 API（TRD 十二章）：
    POST /api/script/generate         简单模式（选分类/场景/人数）
    POST /api/script/generate-custom  自定义模式（大纲/角色/诡计偏好）
    GET  /api/script/categories       可选分类与场景列表
    GET  /api/script/{id}             剧本详情
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.script_generator import generate_full_script
from backend.app.core.script_privacy import public_script_view
from backend.app.db.database import AsyncSessionFactory
from backend.app.db.repository import ScriptRepo

logger = logging.getLogger(__name__)

router = APIRouter()

# RAG 检索器懒加载：None=未初始化，False=初始化失败（不再重试）
_RAG_MANAGER: Any = None
_RAG_INIT_FAILED = False


def _get_rag_manager():
    """懒加载全局 RAG 检索器；失败后降级为无知识注入，不阻塞生成。"""
    global _RAG_MANAGER, _RAG_INIT_FAILED
    if _RAG_MANAGER is None and not _RAG_INIT_FAILED:
        try:
            from backend.app.core.rag import get_retriever
            _RAG_MANAGER = get_retriever()
        except Exception as e:
            _RAG_INIT_FAILED = True
            logger.warning("RAG 初始化失败，本次生成跳过知识注入: %s", e)
    return _RAG_MANAGER


# ---------- 请求模型 ----------

class GenerateRequest(BaseModel):
    """剧本生成请求（简单模式与自定义模式共用）。"""

    title: Optional[str] = None
    category: str = Field(..., description="分类: modern/ancient/republic/japanese/campus")
    scene: str = Field(..., description="场景")
    player_count: int = Field(6, ge=1, le=12, description="游玩人数 1-12")
    outline: Optional[str] = None
    characters: Optional[List[Dict[str, Any]]] = None
    trick_preferences: Optional[List[str]] = None
    is_custom: int = 0


# ---------- 依赖 ----------

async def get_session() -> AsyncSession:
    async with AsyncSessionFactory() as session:
        yield session


# ---------- 内部工具 ----------

def _user_input(req: GenerateRequest) -> Dict[str, Any]:
    return {
        "title": req.title,
        "category": req.category,
        "scene": req.scene,
        "player_count": req.player_count,
        "outline": req.outline,
        "characters": req.characters,
        "trick_preferences": req.trick_preferences,
        "is_custom": req.is_custom,
    }


async def _run_pipeline(req: GenerateRequest,
                        session: AsyncSession) -> Dict[str, Any]:
    try:
        return await generate_full_script(
            _user_input(req), session, rag_manager=_get_rag_manager()
        )
    except Exception as e:
        logger.exception("剧本生成失败")
        raise HTTPException(
            status_code=502,
            detail=f"剧本生成失败，请确认 LLM（Ollama/API）已配置并启动: {e}",
        )


# ---------- 端点 ----------

@router.post("/generate", summary="生成剧本（简单模式）")
async def generate_script(req: GenerateRequest,
                          session: AsyncSession = Depends(get_session)):
    req.is_custom = 0
    return await _run_pipeline(req, session)


@router.post("/generate-custom", summary="生成剧本（自定义模式）")
async def generate_custom_script(req: GenerateRequest,
                                 session: AsyncSession = Depends(get_session)):
    req.is_custom = 1
    return await _run_pipeline(req, session)


@router.get("/categories", summary="可选分类与场景列表")
async def list_categories():
    """按 PRD 七章提供 MVP 分类与场景示例。"""
    return [
        {"id": "modern", "name": "现代本格", "scenes": ["暴风雪山庄", "密室", "游轮"]},
        {"id": "ancient", "name": "古风悬疑", "scenes": ["王府", "皇宫", "武林", "古镇"]},
        {"id": "republic", "name": "民国谍战", "scenes": ["租界公馆", "火车站", "戏院"]},
        {"id": "japanese", "name": "日式推理", "scenes": ["温泉旅馆", "校园", "神社"]},
        {"id": "campus", "name": "校园青春", "scenes": ["教学楼", "社团", "宿舍"]},
    ]


@router.get("/{script_id}", summary="获取剧本详情")
async def get_script(script_id: str,
                     session: AsyncSession = Depends(get_session)):
    script = await ScriptRepo(session).get(script_id)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    return public_script_view(script)
