"""销售数据读取。

支持 CSV 与 Excel（.xlsx，openpyxl）。
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


def _read_excel(path: Path, sheet_name: str | None) -> tuple[pd.DataFrame, str]:
    try:
        excel = pd.ExcelFile(path, engine="openpyxl")
    except Exception as exc:
        raise DataLoadError(f"Excel 读取失败: {path}\n{exc}") from exc

    sheet_names = list(excel.sheet_names)
    target = sheet_name or sheet_names[0]
    if target not in sheet_names:
        excel.close()
        raise DataLoadError(
            f"Excel 工作表不存在: {target}；可用工作表: {'、'.join(sheet_names)}"
        )
    excel.close()
    try:
        df = pd.read_excel(
            path,
            sheet_name=target,
            dtype=str,
            keep_default_na=False,
            engine="openpyxl",
        )
    except Exception as exc:
        raise DataLoadError(f"Excel 工作表解析失败: {target}\n{exc}") from exc
    if df.empty:
        raise DataLoadError(f"Excel 工作表没有数据行: {target}")
    logger.info("读取 Excel 成功: %s（工作表 %s，%d 行）", path, target, len(df))
    return df, target


def load_sales_data(
    path: str | Path,
    fields: FieldsConfig,
    sheet_name: str | None = None,
) -> pd.DataFrame:
    """读取 CSV/Excel 并完成表头归一化。

    返回的 DataFrame 全部为字符串列，另含 `_row_number`。
    Excel 默认读取第一个工作表，可用 sheet_name 指定。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise DataLoadError(f"数据文件不存在: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        raw = _read_csv(file_path)
    elif suffix == ".xlsx":
        raw, _ = _read_excel(file_path, sheet_name)
    elif suffix == ".xls":
        raise DataLoadError("旧版 .xls 不支持，请用 Excel 另存为 .xlsx 后再导入")
    else:
        raise DataLoadError(
            f"不支持的数据格式: {file_path.suffix}，当前支持 .csv / .xlsx"
        )

    if raw.empty:
        raise DataLoadError(f"数据文件没有数据行: {file_path}")

    normalized = normalize_columns(raw, fields)
    unknown = normalized.attrs.get("unknown_columns", [])
    if unknown:
        logger.warning("以下列不在字段契约中，已忽略: %s", "、".join(map(str, unknown)))

    normalized = ensure_canonical_columns(normalized, fields)
    normalized = add_row_numbers(normalized)
    return normalized
