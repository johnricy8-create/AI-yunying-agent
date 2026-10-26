"""字段契约辅助函数。

内部统一英文 snake_case；加载阶段负责表头归一化，
校验阶段负责逐行类型转换与业务规则检查。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ecom_ops.config import FieldsConfig
from ecom_ops.exceptions import DataLoadError


def _clean_column_name(name: Any) -> str:
    text = "" if name is None else str(name)
    text = text.replace("\ufeff", "").strip()
    return text


def normalize_columns(df: pd.DataFrame, fields: FieldsConfig) -> pd.DataFrame:
    """把中文/别名表头统一映射为内部字段名。

    - 去 BOM、去首尾空白；
    - 先精确匹配字段名与别名，再忽略大小写匹配英文别名；
    - 同一内部字段出现两列时直接报错，避免静默覆盖。
    """
    canonical = set(fields.fields)
    alias_exact = {**fields.aliases}
    alias_lower = {key.lower(): value for key, value in fields.aliases.items()}
    canonical_lower = {name.lower(): name for name in canonical}

    rename: dict[Any, str] = {}
    seen: dict[str, Any] = {}
    unknown: list[str] = []

    for column in df.columns:
        cleaned = _clean_column_name(column)
        target: str | None = None
        if cleaned in canonical:
            target = cleaned
        elif cleaned in alias_exact:
            target = alias_exact[cleaned]
        elif cleaned.lower() in canonical_lower:
            target = canonical_lower[cleaned.lower()]
        elif cleaned.lower() in alias_lower:
            target = alias_lower[cleaned.lower()]

        if target is None:
            unknown.append(cleaned)
            continue
        if target in seen:
            raise DataLoadError(
                f"字段 {target} 出现了多列（{seen[target]!r} 与 {column!r}），请检查数据表头"
            )
        seen[target] = column
        rename[column] = target

    result = df.rename(columns=rename)
    if unknown:
        # 未知列不参与分析，但保留提示，便于阶段三排查真实数据。
        result.attrs["unknown_columns"] = unknown
    return result


def ensure_canonical_columns(df: pd.DataFrame, fields: FieldsConfig) -> pd.DataFrame:
    """补齐缺失的可选列；缺失的必填列直接报错。"""
    missing_required = [name for name in fields.required_names if name not in df.columns]
    if missing_required:
        labels = [f"{name}（{fields.label(name)}）" for name in missing_required]
        raise DataLoadError("数据缺少必要字段: " + "、".join(labels))

    result = df.copy()
    for name in fields.canonical_names:
        if name not in result.columns:
            result[name] = ""
    return result


def add_row_numbers(df: pd.DataFrame) -> pd.DataFrame:
    """记录原始行号（CSV 第 1 行为表头，数据从第 2 行开始）。"""
    result = df.copy()
    result["_row_number"] = range(2, len(result) + 2)
    return result
