#内置示例剧本种子
"""首次启动时把内置示例剧本写入数据库（幂等）。

只插入 backend/app/data/seed_scripts/ 下的剧本故事数据；
不读取、不修改、不导出用户的其他数据，也不接触任何密钥/数据库配置。
"""

import json
import logging
from pathlib import Path

from sqlalchemy import select

from backend.app.db.database import AsyncSessionFactory
from backend.app.db.models import Script

logger = logging.getLogger(__name__)

_SEEDS_DIR = Path(__file__).parent.parent / "data" / "seed_scripts"


async def seed_example_scripts() -> int:
    """把内置示例剧本写入本地库（若 id 已存在则跳过）。返回本次插入数。"""
    if not _SEEDS_DIR.is_dir():
        return 0
    inserted = 0
    async with AsyncSessionFactory() as session:
        for f in sorted(_SEEDS_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("示例剧本种子解析失败 %s: %s", f.name, e)
                continue
            sid = data.get("id")
            if not sid:
                continue
            exists = (await session.execute(
                select(Script).where(Script.id == sid))).scalar_one_or_none()
            if exists:
                continue
            session.add(Script(
                id=sid,
                title=data.get("title") or "示例剧本",
                category=data.get("category") or "modern",
                scene=data.get("scene") or "示例场景",
                player_count=int(data.get("player_count") or 6),
                outline=data.get("outline"),
                full_script=json.dumps(data.get("full_script") or {},
                                       ensure_ascii=False),
                summary=data.get("summary"),
                is_saved=1,
                is_custom=0,
            ))
            inserted += 1
        if inserted:
            await session.commit()
            logger.info("已写入内置示例剧本 %d 个", inserted)
    return inserted
