from contextlib import asynccontextmanager
import logging
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.api.router import router as api_router
from backend.app.api.setting import apply_stored_llm_config
from backend.app.config import PORT, ensure_log_dir
from backend.app.db.database import AsyncSessionFactory, init_db
from backend.app.db.seed import seed_example_scripts


def _setup_logging() -> None:
    """统一日志输出：写入 log/mazery.log（轮转）+ 控制台，覆盖所有 logger。"""
    root = logging.getLogger()
    # 避免热重载/重复 import 时重复添加 handler
    if any(getattr(h, "baseFilename", None) for h in root.handlers):
        return

    log_dir = ensure_log_dir()
    file_handler = RotatingFileHandler(
        log_dir / "mazery.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.setLevel(logging.INFO)


_setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    #启动时初始化数据库
    await init_db()
    # 写入内置示例剧本（幂等，仅首次）
    try:
        await seed_example_scripts()
    except Exception as e:
        import logging
        logging.getLogger("uvicorn.error").warning("示例剧本种子写入失败（忽略）: %s", e)
    # 应用设置页保存的 LLM 配置（含模型/BaseURL/API Key），重启后仍生效
    async with AsyncSessionFactory() as session:
        await apply_stored_llm_config(session)
    yield
app = FastAPI(lifespan=lifespan,title="Mazery - AI剧本杀", version="0.1.0")

# 配置 CORS（允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router,prefix="/api")



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True, log_config=None)
