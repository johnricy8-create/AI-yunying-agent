"""销售数据读取。

阶段一只支持 CSV；Excel 留到阶段三，届时再引入 openpyxl。
读取时统一按字符串处理，逐行类型转换交给 validator，
这样可以在报告中精确指出哪一行、哪个字段有问题。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ecom_ops.config import FieldsConfig
from ecom_ops.data.schema import add_row_numbers, ensure_canonical_columns, normalize_columns
from ecom_ops.exceptions import DataLoadError

logger = logging.getLogger(__name__)

_ENCODINGS = ("utf-8-sig", "utf-8", "gbk")


def _read_csv(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in _ENCODINGS:
        try:
            df = pd.read_csv(
                path,
                dtype=str,
                keep_default_na=False,
                na_filter=False,
                encoding=encoding,
            )
            logger.info("读取数据文件成功: %s（编码 %s，%d 行）", path, encoding, len(df))
            return df
        except UnicodeDecodeError as exc:
            last_error = exc
            logger.warning("使用 %s 读取失败，尝试下一种编码: %s", encoding, exc)
            continue
        except pd.errors.EmptyDataError as exc:
            raise DataLoadError(f"数据文件为空: {path}") from exc
        except pd.errors.ParserError as exc:
            raise DataLoadError(f"CSV 解析失败: {path}\n{exc}") from exc
    raise DataLoadError(f"无法用 UTF-8/GBK 读取数据文件: {path}\n{last_error}")


def load_sales_data(path: str | Path, fields: FieldsConfig) -> pd.DataFrame:
    """读取 CSV 并完成表头归一化。

    返回的 DataFrame 全部为字符串列，另含 `_row_number`。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise DataLoadError(f"数据文件不存在: {file_path}")
    if file_path.suffix.lower() in {".xlsx", ".xls"}:
        raise DataLoadError(
            "阶段一暂不支持 Excel，请先使用 CSV；Excel 接入安排在阶段三。"
        )
    if file_path.suffix.lower() != ".csv":
        raise DataLoadError(f"不支持的数据格式: {file_path.suffix}，阶段一只支持 CSV")

    raw = _read_csv(file_path)
    if raw.empty:
        raise DataLoadError(f"数据文件没有数据行: {file_path}")

    normalized = normalize_columns(raw, fields)
    unknown = normalized.attrs.get("unknown_columns", [])
    if unknown:
        logger.warning("以下列不在字段契约中，已忽略: %s", "、".join(map(str, unknown)))

    normalized = ensure_canonical_columns(normalized, fields)
    normalized = add_row_numbers(normalized)
    return normalized
