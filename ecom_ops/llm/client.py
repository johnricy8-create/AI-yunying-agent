"""LangChain 客户端构造。

智谱 BigModel 提供 OpenAI 兼容接口，因此统一使用 langchain-openai：
- ChatOpenAI：GLM-4.7-Flash 对话；
- OpenAIEmbeddings：embedding-3 向量化。

密钥只从环境变量读取，不进入配置文件或日志。
"""

from __future__ import annotations

import os
import logging

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from ecom_ops.config import Settings

logger = logging.getLogger(__name__)

API_KEY_ENV = "ZHIPU_API_KEY"


def get_api_key() -> str | None:
    value = os.getenv(API_KEY_ENV, "").strip()
    if not value:
        value = os.getenv("LLM_API_KEY", "").strip()
    return value or None


def build_chat_model(settings: Settings) -> ChatOpenAI | None:
    """构造对话模型；未启用或缺 Key 时返回 None。"""
    if not settings.llm.enabled:
        return None
    api_key = get_api_key()
    if not api_key:
        logger.warning("未配置 %s，跳过对话模型调用", API_KEY_ENV)
        return None
    return ChatOpenAI(
        model=settings.llm.model,
        api_key=api_key,
        base_url=settings.llm.base_url.rstrip("/"),
        temperature=settings.llm.temperature,
        max_tokens=settings.llm.max_tokens,
        timeout=settings.llm.timeout_seconds,
        max_retries=0,  # 重试由 AIService 统一控制，便于按 1305/429 退避
        extra_body={"thinking": {"type": settings.llm.thinking}},
    )


def build_embeddings(settings: Settings) -> OpenAIEmbeddings | None:
    """构造向量模型；未启用或缺 Key 时返回 None。"""
    if not settings.rag.enabled:
        return None
    api_key = get_api_key()
    if not api_key:
        logger.warning("未配置 %s，跳过向量检索", API_KEY_ENV)
        return None
    return OpenAIEmbeddings(
        model=settings.rag.embedding_model,
        api_key=api_key,
        base_url=settings.llm.base_url.rstrip("/"),
        dimensions=settings.rag.embedding_dimensions,
        check_embedding_ctx_length=False,
        timeout=settings.llm.timeout_seconds,
        max_retries=0,
    )
