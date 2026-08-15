#LLM配置端点
"""LLM 设置 API（TRD 十一/十二章）：
    GET  /api/settings/llm      获取当前 LLM 配置（API Key 脱敏）
    POST /api/settings/llm      保存 LLM 配置（API Key 加密存储）
    GET  /api/settings/models   预设模型列表
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import DB_DIR, LLM_CONFIG
from backend.app.db.database import AsyncSessionFactory
from backend.app.db.repository import SettingsRepo

logger = logging.getLogger(__name__)

router = APIRouter()

# API Key 加密密钥文件（机器级，生成后复用）
KEY_FILE = DB_DIR / "llm_key.key"

# 7 种预设模型（TRD 十一）
PRESET_MODELS: List[Dict[str, Any]] = [
    {"id": "ollama", "name": "Ollama（本地免费）", "requires_key": False,
     "default_base_url": "http://localhost:11434/v1", "models": ["qwen3.5:4b", "llama3.1", "qwen2.5"]},
    {"id": "gpt", "name": "OpenAI GPT", "requires_key": True,
     "default_base_url": "https://api.openai.com/v1", "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1"]},
    {"id": "claude", "name": "Anthropic Claude", "requires_key": True,
     "default_base_url": "https://api.anthropic.com/v1", "models": ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"]},
    {"id": "deepseek", "name": "DeepSeek", "requires_key": True,
     "default_base_url": "https://api.deepseek.com/v1", "models": ["deepseek-chat", "deepseek-reasoner"]},
    {"id": "kimi", "name": "Kimi（Moonshot）", "requires_key": True,
     "default_base_url": "https://api.moonshot.cn/v1", "models": ["moonshot-v1-8k", "moonshot-v1-32k"]},
    {"id": "qwen", "name": "通义千问（阿里云）", "requires_key": True,
     "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "models": ["qwen-plus", "qwen-max"]},
    {"id": "custom", "name": "自定义（OpenAI 兼容）", "requires_key": False,
     "default_base_url": "", "models": []},
]


# ---------- 依赖 ----------

async def get_session() -> AsyncSession:
    async with AsyncSessionFactory() as session:
        yield session


# ---------- 请求/响应模型 ----------

class LlmConfigUpdate(BaseModel):
    model: str = Field(..., description="模型名称")
    base_url: str = Field(..., description="OpenAI 兼容端点")
    api_key: Optional[str] = Field(None, description="API Key；不传表示保持不变")
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(16384, ge=1, le=131072)


class LlmConfigResponse(BaseModel):
    model: str
    base_url: str
    temperature: float
    max_tokens: int
    api_key_set: bool
    api_key_masked: str


# ---------- API Key 加密 ----------

def _get_fernet() -> Fernet:
    """读取或生成机器级 Fernet 密钥。"""
    try:
        if KEY_FILE.exists():
            return Fernet(KEY_FILE.read_bytes())
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        KEY_FILE.write_bytes(key)
        return Fernet(key)
    except Exception as e:
        logger.error("LLM Key 加密初始化失败: %s", e)
        raise HTTPException(status_code=500, detail=f"API Key 加密初始化失败: {e}")


def _encrypt(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def _decrypt(token: str) -> Optional[str]:
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


def _mask(key: str) -> str:
    if len(key) <= 8:
        return "*" * len(key)
    return key[:3] + "*" * (len(key) - 7) + key[-4:]


# ---------- 端点 ----------

@router.get("/llm", summary="获取 LLM 配置")
async def get_llm_config(session: AsyncSession = Depends(get_session)):
    repo = SettingsRepo(session)
    stored = await repo.get("llm_config", {}) or {}
    model = stored.get("model") or LLM_CONFIG["model"]
    base_url = stored.get("base_url") or LLM_CONFIG["base_url"]
    temperature = stored.get("temperature", LLM_CONFIG["temperature"])
    max_tokens = stored.get("max_tokens", LLM_CONFIG["max_tokens"])

    api_key_plain = ""
    if stored.get("api_key_encrypted"):
        api_key_plain = _decrypt(stored["api_key_encrypted"]) or ""
    return LlmConfigResponse(
        model=model,
        base_url=base_url,
        temperature=float(temperature),
        max_tokens=int(max_tokens),
        api_key_set=bool(api_key_plain),
        api_key_masked=_mask(api_key_plain) if api_key_plain else "",
    )


@router.post("/llm", summary="保存 LLM 配置")
async def save_llm_config(req: LlmConfigUpdate,
                          session: AsyncSession = Depends(get_session)):
    repo = SettingsRepo(session)
    stored = await repo.get("llm_config", {}) or {}

    if req.api_key:
        stored["api_key_encrypted"] = _encrypt(req.api_key)
    stored.update({
        "model": req.model,
        "base_url": req.base_url,
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
    })
    await repo.set("llm_config", stored)

    # 运行时生效：更新配置并让下一次 LLM 客户端重建
    LLM_CONFIG["model"] = req.model
    LLM_CONFIG["base_url"] = req.base_url
    LLM_CONFIG["temperature"] = req.temperature
    LLM_CONFIG["max_tokens"] = req.max_tokens
    if req.api_key:
        LLM_CONFIG["api_key"] = req.api_key
    try:
        import backend.app.core.llm as llm_mod
        llm_mod._llm_client = None
    except Exception:
        pass

    return {"ok": True, "message": "LLM 配置已保存并生效"}


@router.get("/models", summary="预设模型列表")
async def list_models():
    return PRESET_MODELS
