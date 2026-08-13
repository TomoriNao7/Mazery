#SQLAlchemy引擎
import logging
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine,AsyncSession,async_sessionmaker

from sqlalchemy.orm import declarative_base

from backend.app.config import DATABASE_URL


#ORM基类
Base=declarative_base()

engine=create_async_engine(
    DATABASE_URL,
    echo=False,                       # 开发时改 True 可看 SQL 语句
    future=True,
    connect_args={"check_same_thread": False},
)

AsyncSessionFactory=async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=True,
    autocommit=False
)

#初始化数据库
async def init_db() -> None:
    async with engine.begin() as conn:
        # 开启 WAL 模式（提升并发读写性能）
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        # 开启外键约束（SQLite 默认不开启）
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        # 创建所有表（如果不存在）
        await conn.run_sync(Base.metadata.create_all)

#FastAPI 依赖注入（获取数据库会话）
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        # 退出上下文时自动关闭 session
