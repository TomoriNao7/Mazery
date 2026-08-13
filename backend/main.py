from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.api.router import router as api_router
from backend.app.config import PORT
from backend.app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    #启动时初始化数据库
    await init_db()
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
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
