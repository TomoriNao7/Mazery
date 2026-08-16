#LLM客户端（统一封装 AsyncOpenAI）
"""LLM 客户端：统一封装 AsyncOpenAI，提供结构化输出（schema）与流式输出。

与 TRD 7.6 注入点伪代码中的 `llm.call(prompt, schema=...)` / `llm.stream(prompt)`
对应。所有 Agent 注入点通过 get_llm_client() 获取同一客户端。
"""

import json
import logging
import re
from typing import Any, AsyncIterator, Dict, Optional, Type

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel

from backend.app.config import LLM_CONFIG

logger = logging.getLogger(__name__)


def _default_timeout() -> httpx.Timeout:
    """连接超时设短（模型未启动时快速降级），读写超时留足（长生成不截断）。

    读超时需覆盖剧本生成这类大 JSON 输出：思考型模型（如 qwen3-max 系列）
    首 token 前可能思考数分钟，90s 会误判超时，故放宽到 600s。
    """
    return httpx.Timeout(connect=5.0, read=600.0, write=600.0, pool=10.0)


def _extract_json(text: str) -> str:
    """从 LLM 输出中提取 JSON：优先整体解析，其次取 ```json ... ``` 块，最后取首个 {...}。"""
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return text

    fence = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.S)
    if fence:
        return fence.group(1)

    obj = re.search(r"\{.*\}", text, re.S)
    if obj:
        return obj.group(0)

    return text


class LlmClient:
    """基于 AsyncOpenAI 的轻量封装（兼容 Ollama / OpenAI 兼容端点）。"""

    def __init__(self,
                 base_url: str = LLM_CONFIG["base_url"],
                 api_key: str = LLM_CONFIG["api_key"],
                 model: str = LLM_CONFIG["model"],
                 temperature: float = LLM_CONFIG["temperature"],
                 max_tokens: int = LLM_CONFIG["max_tokens"]):
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key,
                                  timeout=_default_timeout(), max_retries=1)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def call(self,
                   prompt: str,
                   schema: Optional[Type[BaseModel]] = None,
                   temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None,
                   **kwargs) -> Any:
        """
        调用 LLM 并返回结果。

        Args:
            prompt: 完整提示词
            schema: Pydantic 模型类。传入时要求 JSON 输出并解析为该模型；
                    解析失败返回原始文本（不抛出，便于降级）。
            temperature / max_tokens: 覆盖默认值

        Returns:
            传入 schema 时返回模型实例（失败时返回 str），否则返回文本 str。
        """
        messages = [{"role": "user", "content": prompt}]
        if schema is not None:
            messages.append({
                "role": "user",
                "content": (
                    "请严格输出 JSON 对象，字段与下列 Schema 一致：\n"
                    f"{schema.model_json_schema()}\n"
                    "只输出 JSON，不要输出解释文字。"
                ),
            })

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
            **kwargs,
        )
        text = response.choices[0].message.content or ""

        if schema is None:
            return text

        try:
            return schema.model_validate_json(_extract_json(text))
        except Exception as e:
            logger.warning("LLM 结构化输出解析失败，返回原始文本: %s", e)
            return text

    async def stream(self, prompt: str,
                     temperature: Optional[float] = None,
                     max_tokens: Optional[int] = None,
                     **kwargs) -> AsyncIterator[str]:
        """流式调用，逐段产出文本。temperature / max_tokens 可覆盖默认值。"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
            stream=True,
            **kwargs,
        )
        async for chunk in response:
            # 部分兼容端点（如 DashScope）的流式 chunk 可能带空 choices，需跳过
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


_llm_client: Optional[LlmClient] = None


def get_llm_client() -> LlmClient:
    """获取全局单例 LLM 客户端"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LlmClient()
    return _llm_client
