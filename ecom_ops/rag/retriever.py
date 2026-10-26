"""RAG 检索器。

运行时不重建索引；索引由 tools/build_rag_index.py 离线生成。
索引缺失或缺少 Key 时返回空结果，不阻塞主流程。
"""

from __future__ import annotations

import logging
from typing import Any

from ecom_ops.config import Settings
from ecom_ops.llm.client import build_embeddings
from ecom_ops.rag.index import RAGIndex

logger = logging.getLogger(__name__)


class RAGRetriever:
    def __init__(
        self,
        settings: Settings,
        embeddings: Any | None = None,
        index: RAGIndex | None = None,
    ) -> None:
        self.settings = settings
        self.embeddings = embeddings if embeddings is not None else build_embeddings(settings)
        self.index = index
        self.error: str | None = None

        if self.settings.rag.enabled and self.index is None:
            try:
                self.index = RAGIndex.load(settings.rag.index_dir)
            except Exception as exc:  # 索引损坏不应拖垮整次任务
                self.error = str(exc)
                logger.warning("RAG 索引加载失败，将不启用检索: %s", exc)
                self.index = None
        if self.index is None and self.settings.rag.enabled:
            self.error = self.error or (
                f"未找到 RAG 索引: {settings.rag.index_dir}；"
                "请先运行 tools/build_rag_index.py"
            )

    @property
    def available(self) -> bool:
        return (
            self.settings.rag.enabled
            and self.embeddings is not None
            and self.index is not None
        )

    @property
    def info(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.rag.enabled,
            "available": self.available,
            "embedding_model": self.settings.rag.embedding_model,
            "index_dir": str(self.settings.rag.index_dir),
            "chunk_count": len(self.index.chunks) if self.index else 0,
            "error": self.error,
        }

    def retrieve_many(
        self,
        queries: list[str],
        date_before: str | None = None,
    ) -> list[list[dict[str, Any]]]:
        if not self.available or not queries:
            return [[] for _ in queries]
        try:
            vectors = self.embeddings.embed_documents(queries)
        except Exception as exc:
            self.error = f"查询向量化失败: {exc}"
            logger.warning(self.error)
            return [[] for _ in queries]

        results: list[list[dict[str, Any]]] = []
        for vector in vectors:
            try:
                hits = self.index.search(
                    vector,
                    top_k=self.settings.rag.top_k,
                    date_before=date_before,
                    min_score=self.settings.rag.min_score,
                )
                results.append([hit.to_dict() for hit in hits])
            except Exception as exc:
                self.error = f"向量检索失败: {exc}"
                logger.warning(self.error)
                results.append([])
        return results

    def retrieve(self, query: str, date_before: str | None = None) -> list[dict[str, Any]]:
        return self.retrieve_many([query], date_before=date_before)[0]
