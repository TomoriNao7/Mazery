#RAG检索端点
"""RAG 知识检索 API（TRD 十二章）：
    GET /api/knowledge/search?query=...&top_k=...&mode=...&tags_filter=...
"""

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter()

# RAG 检索器懒加载：None=未初始化，False=初始化失败（不再重试）
_RAG_MANAGER: Any = None
_RAG_INIT_FAILED = False


def _get_rag_manager():
    global _RAG_MANAGER, _RAG_INIT_FAILED
    if _RAG_MANAGER is None and not _RAG_INIT_FAILED:
        try:
            from backend.app.core.rag import get_retriever
            _RAG_MANAGER = get_retriever()
        except Exception as e:
            _RAG_INIT_FAILED = True
            logger.warning("RAG 初始化失败: %s", e)
    return _RAG_MANAGER


@router.get("/search", summary="RAG 知识检索")
async def search(query: str = Query(..., min_length=1, description="查询文本"),
                 top_k: int = Query(5, ge=1, le=20),
                 mode: str = Query("precise", pattern="^(precise|expansive)$"),
                 tags_filter: Optional[str] = Query(None, description="逗号分隔的标签过滤")):
    rag = _get_rag_manager()
    if rag is None:
        raise HTTPException(status_code=503, detail="RAG 检索器不可用（模型加载失败或未配置）")

    tags = [t.strip() for t in tags_filter.split(",")] if tags_filter else None
    try:
        hits = await rag.search(query, top_k=top_k, mode=mode, tags_filter=tags)
    except Exception as e:
        logger.exception("知识检索失败")
        raise HTTPException(status_code=502, detail=f"知识检索失败: {e}")

    return [
        {
            "content": h.doc.content,
            "title": h.doc.title,
            "source_file": h.doc.source_file,
            "score": round(h.score, 4),
            "is_reference": h.is_reference,
        }
        for h in hits
    ]
