"""文件与路径工具。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def ensure_dir(path: Path) -> Path:
    """确保目录存在并返回该目录。"""
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_path(value: str | Path, root: Path) -> Path:
    """把配置中的相对路径解析到项目根目录；绝对路径原样返回。"""
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def write_text_atomic(path: Path, content: str, encoding: str = "utf-8") -> None:
    """原子写入文本，避免中途失败留下半个报告。

    先写同目录临时文件，再用 os.replace 覆盖目标文件。
    """
    ensure_dir(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding=encoding)
    os.replace(tmp, path)


def read_text(path: Path, encoding: str = "utf-8") -> str:
    return path.read_text(encoding=encoding)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
