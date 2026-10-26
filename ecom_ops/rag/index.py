"""本地向量索引。

语料规模预计在几百到几千块，使用 NumPy 余弦相似度即可，
不引入 Chroma/FAISS，降低 Windows 安装与维护成本。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from ecom_ops.exceptions import RAGError
from ecom_ops.rag.chunker import Chunk
from ecom_ops.utils.dates import now
from ecom_ops.utils.files import ensure_dir


@dataclass(frozen=True)
class SearchHit:
    id: str
    source: str
    title: str
    date: str | None
    section: str
    text: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "date": self.date,
            "section": self.section,
            "text": self.text,
            "score": round(self.score, 4),
        }


def _normalize(matrix: np.ndarray) -> np.ndarray:
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class RAGIndex:
    def __init__(
        self,
        vectors: np.ndarray,
        chunks: list[dict[str, Any]],
        model: str,
        dimensions: int,
        built_at: str,
    ) -> None:
        self.vectors = vectors.astype(np.float32, copy=False)
        self.chunks = chunks
        self.model = model
        self.dimensions = dimensions
        self.built_at = built_at

    @classmethod
    def build(
        cls,
        chunks: list[Chunk],
        embeddings: Any,
        model: str,
        dimensions: int,
        batch_size: int = 32,
    ) -> "RAGIndex":
        if not chunks:
            raise RAGError("语料为空，无法构建索引")
        texts = [chunk.text for chunk in chunks]
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            batch_vectors = embeddings.embed_documents(batch)
            if len(batch_vectors) != len(batch):
                raise RAGError(
                    f"向量数量不一致：期望 {len(batch)}，实际 {len(batch_vectors)}"
                )
            vectors.extend(batch_vectors)
        matrix = _normalize(np.asarray(vectors, dtype=np.float32))
        if matrix.shape[1] != dimensions:
            raise RAGError(
                f"向量维度不一致：期望 {dimensions}，实际 {matrix.shape[1]}"
            )
        return cls(
            vectors=matrix,
            chunks=[chunk.to_dict() for chunk in chunks],
            model=model,
            dimensions=dimensions,
            built_at=now().isoformat(timespec="seconds"),
        )

    def save(self, index_dir: Path) -> None:
        ensure_dir(index_dir)
        np.savez_compressed(index_dir / "vectors.npz", vectors=self.vectors)
        (index_dir / "chunks.json").write_text(
            json.dumps(self.chunks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manifest = {
            "model": self.model,
            "dimensions": self.dimensions,
            "count": len(self.chunks),
            "built_at": self.built_at,
            "vector_shape": list(self.vectors.shape),
        }
        (index_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, index_dir: Path) -> "RAGIndex | None":
        vectors_path = index_dir / "vectors.npz"
        chunks_path = index_dir / "chunks.json"
        manifest_path = index_dir / "manifest.json"
        if not (vectors_path.exists() and chunks_path.exists() and manifest_path.exists()):
            return None
        try:
            with np.load(vectors_path, allow_pickle=False) as data:
                vectors = data["vectors"]
            chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RAGError(f"RAG 索引读取失败: {exc}") from exc
        if not isinstance(chunks, list):
            raise RAGError("RAG chunks.json 格式错误")
        if int(manifest.get("count", -1)) != len(chunks):
            raise RAGError("RAG 索引与 chunks 数量不一致，请重建索引")
        return cls(
            vectors=vectors,
            chunks=chunks,
            model=str(manifest.get("model", "")),
            dimensions=int(manifest.get("dimensions", 0)),
            built_at=str(manifest.get("built_at", "")),
        )

    def search(
        self,
        query_vector: Iterable[float],
        top_k: int = 4,
        date_before: str | None = None,
        min_score: float = 0.0,
    ) -> list[SearchHit]:
        vector = np.asarray(list(query_vector), dtype=np.float32).reshape(1, -1)
        if vector.shape[1] != self.dimensions:
            raise RAGError(
                f"查询向量维度不一致：期望 {self.dimensions}，实际 {vector.shape[1]}"
            )
        vector = _normalize(vector)
        scores = (self.vectors @ vector.T).reshape(-1)

        candidates: list[tuple[float, int]] = []
        for index, chunk in enumerate(self.chunks):
            chunk_date = chunk.get("date")
            if date_before and chunk_date and str(chunk_date) >= date_before:
                continue
            score = float(scores[index])
            if score < min_score:
                continue
            candidates.append((score, index))
        candidates.sort(key=lambda item: item[0], reverse=True)

        hits: list[SearchHit] = []
        for score, index in candidates[:top_k]:
            chunk = self.chunks[index]
            hits.append(
                SearchHit(
                    id=str(chunk.get("id", "")),
                    source=str(chunk.get("source", "")),
                    title=str(chunk.get("title", "")),
                    date=chunk.get("date"),
                    section=str(chunk.get("section", "")),
                    text=str(chunk.get("text", "")),
                    score=score,
                )
            )
        return hits


def stats(index: RAGIndex) -> dict[str, Any]:
    return {
        "count": len(index.chunks),
        "dimensions": index.dimensions,
        "model": index.model,
        "built_at": index.built_at,
    }
