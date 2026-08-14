from fastapi import APIRouter
from .health import router as health_check
from .script import router as script_check
from .game import router as game_check

router=APIRouter()

# 子路由用相对路径；`/api` 前缀统一由 main.py 挂载时添加
router.include_router(health_check)
router.include_router(script_check, prefix="/script")
router.include_router(game_check, prefix="/game")
