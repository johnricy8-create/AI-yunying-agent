"""Markdown 语料切分。

语料来源：
- knowledge/：运营知识库，全部索引；
- reports/history/：历史日报，只索引“异常详情”和“运营建议”章节，
  避免把数据概览、执行状态等模板内容带进检索。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

HEADING_RE = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str
    title: str
    date: str | None
    section: str
    text: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "date": self.date,
            "section": self.section,
            "text": self.text,
        }


def _file_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _split_sections(text: str) -> list[tuple[str, str]]:
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [("", text.strip())]
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group(2).strip()
        section_text = text[start:end].strip()
        if section_text:
            sections.append((heading, section_text))
    return sections


def _split_long_section(
    heading_line: str,
    body: str,
    max_chars: int,
    overlap: int,
) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    if not paragraphs:
        return []

    # 单段过长时先按字符预算切片，保证最终块不会超过 max_chars 太多。
    budget = max(100, max_chars - len(heading_line) - 4)
    pieces: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= budget:
            pieces.append(paragraph)
            continue
        for start in range(0, len(paragraph), budget):
            piece = paragraph[start : start + budget].strip()
            if piece:
                pieces.append(piece)

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}".strip() if current else piece
        if len(heading_line) + 2 + len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(f"{heading_line}\n\n{current}".strip())
        tail = current[-overlap:] if overlap and current else ""
        current = f"{tail}\n\n{piece}".strip() if tail else piece
    if current:
        chunks.append(f"{heading_line}\n\n{current}".strip())
    return chunks


def chunk_markdown(
    text: str,
    source: str,
    date: str | None,
    max_chars: int = 900,
    overlap: int = 120,
    include_section_prefixes: tuple[str, ...] | None = None,
) -> list[Chunk]:
    """把一个 Markdown 文件切成带元数据的块。"""
    if not text.strip():
        return []

    title = _file_title(text, Path(source).stem)
    chunks: list[Chunk] = []
    counter = 0

    for heading, section_text in _split_sections(text):
        if include_section_prefixes and not any(
            heading.startswith(prefix) for prefix in include_section_prefixes
        ):
            continue

        lines = section_text.splitlines()
        heading_line = lines[0].strip() if lines else heading
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

        if len(section_text) <= max_chars:
            pieces = [section_text]
        else:
            pieces = _split_long_section(heading_line, body, max_chars, overlap)

        for piece in pieces:
            piece = piece.strip()
            if len(piece) < 10:
                continue
            counter += 1
            digest = hashlib.sha1(
                f"{source}|{heading}|{counter}|{piece[:120]}".encode("utf-8")
            ).hexdigest()[:12]
            chunks.append(
                Chunk(
                    id=f"c{digest}",
                    source=source,
                    title=title,
                    date=date,
                    section=heading or title,
                    text=piece,
                )
            )
    return chunks


def load_corpus(
    knowledge_dir: Path,
    history_dir: Path,
    chunk_size: int = 900,
    chunk_overlap: int = 120,
    source_root: Path | None = None,
) -> list[Chunk]:
    """加载知识库与历史日报，返回去重后的块。"""
    chunks: list[Chunk] = []

    def relative(path: Path) -> str:
        if source_root is not None:
            try:
                return path.resolve().relative_to(source_root.resolve()).as_posix()
            except ValueError:
                pass
        return path.as_posix()

    if knowledge_dir.exists():
        for path in sorted(knowledge_dir.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            chunks.extend(
                chunk_markdown(
                    text,
                    source=relative(path),
                    date=None,
                    max_chars=chunk_size,
                    overlap=chunk_overlap,
                )
            )

    if history_dir.exists():
        for path in sorted(history_dir.rglob("*.md")):
            match = DATE_RE.search(path.name)
            date = match.group(1) if match else None
            text = path.read_text(encoding="utf-8")
            chunks.extend(
                chunk_markdown(
                    text,
                    source=relative(path),
                    date=date,
                    max_chars=chunk_size,
                    overlap=chunk_overlap,
                    include_section_prefixes=("4.", "7."),
                )
            )

    # 去重：同一文本只保留第一次出现。
    seen: set[str] = set()
    unique: list[Chunk] = []
    for chunk in chunks:
        fingerprint = hashlib.sha1(chunk.text.encode("utf-8")).hexdigest()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(chunk)
    return unique
