from fastapi import APIRouter
from .health import router as health_check

router=APIRouter()

# 子路由用相对路径；`/api` 前缀统一由 main.py 挂载时添加
router.include_router(health_check)