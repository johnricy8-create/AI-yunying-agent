from __future__ import annotations

from pathlib import Path

import numpy as np

from ecom_ops.rag.chunker import Chunk, chunk_markdown, load_corpus
from ecom_ops.rag.index import RAGIndex


class FakeEmbeddings:
    """确定性二维向量，便于断言相似度排序。"""

    def embed_query(self, text: str) -> list[float]:
        if "高浏览" in text or "转化" in text:
            return [1.0, 0.0]
        if "订单" in text:
            return [0.0, 1.0]
        return [0.5, 0.5]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


def test_chunk_markdown_keeps_headings_and_metadata():
    text = """# 测试知识库

## 高浏览低转化

这是第一段内容，用于说明高浏览低转化。

## 订单下降

这是订单下降的排查内容。
"""
    chunks = chunk_markdown(text, source="knowledge/test.md", date=None, max_chars=200)
    assert len(chunks) >= 2
    assert chunks[0].title == "测试知识库"
    assert any("高浏览低转化" in chunk.section for chunk in chunks)
    assert all(chunk.source == "knowledge/test.md" for chunk in chunks)


def test_chunk_long_section_splits_into_multiple_chunks():
    paragraph = "这是一个很长的段落，用于验证切分逻辑。" * 20
    text = f"# 长文\n\n## 长章节\n\n{paragraph}\n\n{paragraph}\n"
    chunks = chunk_markdown(text, source="knowledge/long.md", date=None, max_chars=200, overlap=20)
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 260 for chunk in chunks)
    assert all(chunk.text.startswith("## 长章节") for chunk in chunks)


def test_load_corpus_filters_history_sections(tmp_path):
    knowledge = tmp_path / "knowledge"
    history = tmp_path / "reports" / "history"
    knowledge.mkdir(parents=True)
    history.mkdir(parents=True)
    (knowledge / "a.md").write_text(
        "# 知识\n\n## 适用场景\n\n内容一。\n\n## 排查步骤\n\n内容二。\n",
        encoding="utf-8",
    )
    (history / "2026-10-24_daily_report.md").write_text(
        "# 日报\n\n## 1. 数据概览\n\n不应进入索引。\n\n"
        "## 4. 异常详情\n\n### 4.1 商品P0001\n\n异常内容。\n\n"
        "## 7. 运营建议\n\n建议内容。\n",
        encoding="utf-8",
    )

    chunks = load_corpus(
        knowledge,
        history,
        chunk_size=500,
        chunk_overlap=50,
        source_root=tmp_path,
    )
    sections = {chunk.section for chunk in chunks}
    assert any("适用场景" in section for section in sections)
    assert any("4. 异常详情" in section or "4.1" in section for section in sections)
    assert any("7. 运营建议" in section for section in sections)
    assert not any("1. 数据概览" in section for section in sections)
    assert any(chunk.date == "2026-10-24" for chunk in chunks)


def test_index_search_and_date_filter(tmp_path):
    chunks = [
        Chunk("c1", "knowledge/a.md", "知识A", None, "高浏览低转化", "高浏览低转化 排查"),
        Chunk("c2", "knowledge/b.md", "知识B", None, "订单下降", "订单下降 排查"),
        Chunk("c3", "reports/history/2026-10-25.md", "历史", "2026-10-25", "高浏览低转化", "历史高浏览低转化"),
    ]
    index = RAGIndex.build(
        chunks,
        FakeEmbeddings(),
        model="fake",
        dimensions=2,
        batch_size=2,
    )
    hits = index.search([1.0, 0.0], top_k=2, date_before="2026-10-25", min_score=0.0)
    assert hits[0].id in {"c1"}
    assert all(hit.date != "2026-10-25" for hit in hits)

    strict = index.search(
        [1.0, 0.0], top_k=2, date_before="2026-10-25", min_score=0.99
    )
    assert len(strict) == 1
    assert strict[0].id == "c1"

    index.save(tmp_path / "rag")
    loaded = RAGIndex.load(tmp_path / "rag")
    assert loaded is not None
    assert loaded.dimensions == 2
    assert len(loaded.chunks) == 3
    assert loaded.search([0.0, 1.0], top_k=1)[0].id == "c2"


def test_index_rejects_wrong_dimension():
    chunks = [Chunk("c1", "a.md", "A", None, "s", "内容内容内容内容")]
    index = RAGIndex.build(chunks, FakeEmbeddings(), model="fake", dimensions=2)
    try:
        index.search([1.0, 0.0, 0.0])
    except Exception as exc:
        assert "维度" in str(exc)
    else:
        raise AssertionError("应抛出维度不一致错误")
