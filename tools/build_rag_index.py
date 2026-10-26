"""构建 RAG 向量索引。

用法：
    .venv\\Scripts\\python.exe tools\\build_rag_index.py

前置：
- .env 中配置 ZHIPU_API_KEY；
- knowledge/ 下至少有一篇 Markdown；
- 可选：先运行 tools/build_history.py 生成 reports/history/ 历史日报。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.config import load_settings
from ecom_ops.llm.client import build_embeddings
from ecom_ops.rag.chunker import load_corpus
from ecom_ops.rag.index import RAGIndex


def main() -> int:
    settings = load_settings()
    if not settings.rag.enabled:
        print("RAG 已在 settings.yaml 中关闭（rag.enabled=false）。")
        return 1

    chunks = load_corpus(
        settings.rag.knowledge_dir,
        settings.rag.history_dir,
        chunk_size=settings.rag.chunk_size,
        chunk_overlap=settings.rag.chunk_overlap,
        source_root=settings.root,
    )
    if not chunks:
        print("没有找到可索引的语料：请检查 knowledge/ 与 reports/history/。")
        return 1

    counts = Counter("history" if "reports/history" in chunk.source else "knowledge" for chunk in chunks)
    print(f"语料块数: {len(chunks)}（knowledge={counts.get('knowledge', 0)}, history={counts.get('history', 0)}）")

    embeddings = build_embeddings(settings)
    if embeddings is None:
        print("无法构造向量模型：请检查 .env 的 ZHIPU_API_KEY 与 rag.enabled。")
        return 1

    print(f"开始向量化：模型 {settings.rag.embedding_model}，维度 {settings.rag.embedding_dimensions} ...")
    index = RAGIndex.build(
        chunks,
        embeddings,
        model=settings.rag.embedding_model,
        dimensions=settings.rag.embedding_dimensions,
        batch_size=settings.rag.embedding_batch_size,
    )
    index.save(settings.rag.index_dir)
    print(f"索引已保存: {settings.rag.index_dir}")
    print(f"向量矩阵: {index.vectors.shape}, 模型: {index.model}, 构建时间: {index.built_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
