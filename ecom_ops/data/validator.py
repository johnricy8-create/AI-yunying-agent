"""数据校验与坏行隔离。

原则：
- 坏行不拖垮整批任务；能定位到行号和字段；
- 必填缺失、类型错误、负值、逻辑冲突 → 错误，行被隔离；
- 商品简介/店铺/平台/类目缺失 → 警告，行保留；
- 商品 + 日期重复 → 保留最后一条，之前的标记为错误；
- 校验后没有可用数据时，由工作流决定失败退出。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from ecom_ops.config import FieldsConfig
from ecom_ops.exceptions import DataValidationError
from ecom_ops.utils.dates import parse_date, today as today_fn


@dataclass(frozen=True)
class ValidationIssue:
    row_number: int
    product_id: str
    stat_date: str
    field: str
    code: str
    message: str
    severity: str  # error / warning

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "product_id": self.product_id,
            "stat_date": self.stat_date,
            "field": self.field,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class ValidationResult:
    valid_df: pd.DataFrame
    invalid_df: pd.DataFrame
    issues: list[ValidationIssue]
    summary: dict[str, Any]


@dataclass
class _Candidate:
    row_number: int
    record: dict[str, Any]
    raw: dict[str, Any]
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).replace("\ufeff", "").strip()


def _parse_int(text: str, label: str) -> int:
    normalized = text.replace(",", "").replace("，", "")
    number = float(normalized)
    if not math.isfinite(number):
        raise ValueError(f"{label} 不是有效数字")
    if not number.is_integer():
        raise ValueError(f"{label} 必须是整数")
    return int(number)


def _parse_float(text: str, label: str) -> float:
    normalized = text.replace(",", "").replace("，", "")
    number = float(normalized)
    if not math.isfinite(number):
        raise ValueError(f"{label} 不是有效数字")
    return number


def _default_optional_text(name: str) -> str:
    if name in {"shop", "platform", "category"}:
        return "未填写"
    return ""


def _issue(
    row_number: int,
    product_id: str,
    stat_date: str,
    field: str,
    code: str,
    message: str,
    severity: str = "error",
) -> ValidationIssue:
    return ValidationIssue(
        row_number=row_number,
        product_id=product_id,
        stat_date=stat_date,
        field=field,
        code=code,
        message=message,
        severity=severity,
    )


def _empty_frame(fields: FieldsConfig, with_errors: bool = False) -> pd.DataFrame:
    columns = list(fields.canonical_names) + ["_row_number"]
    if with_errors:
        columns.append("_errors")
    return pd.DataFrame(columns=columns)


def validate_sales_data(
    df: pd.DataFrame,
    fields: FieldsConfig,
    current_date: date | None = None,
) -> ValidationResult:
    """逐行校验，返回有效数据、无效数据、问题清单与摘要。"""
    if df is None or df.empty:
        raise DataValidationError("数据为空，无法校验")

    current_date = current_date or today_fn()
    candidates: list[_Candidate] = []

    for raw in df.to_dict("records"):
        row_number = int(raw.get("_row_number", 0))
        product_id = _text(raw.get("product_id", ""))
        stat_date_raw = _text(raw.get("stat_date", ""))
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        record: dict[str, Any] = {"_row_number": row_number}

        for name, spec in fields.fields.items():
            value = raw.get(name, "")
            text = _text(value)

            if spec.dtype == "date":
                if not text:
                    if spec.required:
                        errors.append(
                            _issue(
                                row_number,
                                product_id,
                                stat_date_raw,
                                name,
                                "missing_required",
                                f"必填字段 {spec.label} 为空",
                            )
                        )
                    else:
                        record[name] = ""
                    continue
                try:
                    record[name] = parse_date(text).isoformat()
                except ValueError as exc:
                    errors.append(
                        _issue(
                            row_number,
                            product_id,
                            stat_date_raw,
                            name,
                            "invalid_date",
                            f"{spec.label} 格式错误: {text!r}（{exc}）",
                        )
                    )
                continue

            if spec.dtype == "string":
                if not text:
                    if spec.required:
                        errors.append(
                            _issue(
                                row_number,
                                product_id,
                                stat_date_raw,
                                name,
                                "missing_required",
                                f"必填字段 {spec.label} 为空",
                            )
                        )
                    else:
                        record[name] = _default_optional_text(name)
                        warnings.append(
                            _issue(
                                row_number,
                                product_id,
                                stat_date_raw,
                                name,
                                "missing_optional",
                                f"可选字段 {spec.label} 为空，已填默认值",
                                "warning",
                            )
                        )
                else:
                    record[name] = text
                continue

            if spec.dtype in {"int", "float"}:
                if not text:
                    if spec.required:
                        errors.append(
                            _issue(
                                row_number,
                                product_id,
                                stat_date_raw,
                                name,
                                "missing_required",
                                f"必填字段 {spec.label} 为空",
                            )
                        )
                    else:
                        if name == "uv":
                            record[name] = None
                        elif spec.dtype == "int":
                            record[name] = 0
                        else:
                            record[name] = 0.0
                    continue
                try:
                    number = _parse_int(text, spec.label) if spec.dtype == "int" else _parse_float(
                        text, spec.label
                    )
                except (TypeError, ValueError) as exc:
                    errors.append(
                        _issue(
                            row_number,
                            product_id,
                            stat_date_raw,
                            name,
                            "invalid_number",
                            f"{spec.label} 不是有效数字: {text!r}",
                        )
                    )
                    continue
                if number < 0:
                    errors.append(
                        _issue(
                            row_number,
                            product_id,
                            stat_date_raw,
                            name,
                            "negative_value",
                            f"{spec.label} 不能为负数: {number}",
                        )
                    )
                    continue
                record[name] = number
                continue

        # 字段级解析完成后，做跨字段业务校验。
        if not errors:
            price = record.get("price")
            cost = record.get("cost")
            stock = record.get("stock")
            pv = record.get("pv")
            uv = record.get("uv")
            orders = record.get("orders")
            sales = record.get("sales_amount")
            refund = record.get("refund_amount")
            stat_date_value = record.get("stat_date", "")

            if price is not None and price <= 0:
                errors.append(
                    _issue(
                        row_number,
                        product_id,
                        stat_date_raw,
                        "price",
                        "non_positive_price",
                        f"单价必须大于 0，当前值: {price}",
                    )
                )
            if stock is not None and stock < 0:
                errors.append(
                    _issue(
                        row_number,
                        product_id,
                        stat_date_raw,
                        "stock",
                        "negative_value",
                        f"库存不能为负数，当前值: {stock}",
                    )
                )
            if cost is not None and price is not None and cost > price:
                warnings.append(
                    _issue(
                        row_number,
                        product_id,
                        stat_date_raw,
                        "cost",
                        "cost_gt_price",
                        f"成本 {cost} 高于单价 {price}，请核对",
                        "warning",
                    )
                )
            # 销售额是净额，退款金额可能大于净销售额（例如退款超过毛利），
            # 因此不能用 refund > sales 判定数据错误。
            if orders is not None and pv is not None and orders > pv:
                errors.append(
                    _issue(
                        row_number,
                        product_id,
                        stat_date_raw,
                        "orders",
                        "orders_gt_pv",
                        f"订单量 {orders} 大于浏览量 {pv}",
                    )
                )
            if uv is not None and uv > 0 and orders is not None and orders > uv:
                errors.append(
                    _issue(
                        row_number,
                        product_id,
                        stat_date_raw,
                        "orders",
                        "orders_gt_uv",
                        f"订单量 {orders} 大于访客数 {uv}",
                    )
                )
            if stat_date_value:
                try:
                    if parse_date(stat_date_value) > current_date:
                        errors.append(
                            _issue(
                                row_number,
                                product_id,
                                stat_date_raw,
                                "stat_date",
                                "future_date",
                                f"统计日期 {stat_date_value} 晚于今天 {current_date.isoformat()}",
                            )
                        )
                except ValueError:
                    pass
            if sales is not None and orders is not None and sales == 0 and orders > 0:
                warnings.append(
                    _issue(
                        row_number,
                        product_id,
                        stat_date_raw,
                        "sales_amount",
                        "zero_sales_with_orders",
                        "有订单但销售额为 0，请核对是否为赠品或数据缺失",
                        "warning",
                    )
                )

        candidates.append(
            _Candidate(
                row_number=row_number,
                record=record,
                raw=raw,
                errors=errors,
                warnings=warnings,
            )
        )

    # 重复键：同一商品 + 同一统计日期只保留最后一条。
    groups: dict[tuple[str, str], list[_Candidate]] = {}
    for candidate in candidates:
        if candidate.errors:
            continue
        product_id = str(candidate.record.get("product_id", ""))
        stat_date = str(candidate.record.get("stat_date", ""))
        if not product_id or not stat_date:
            continue
        groups.setdefault((product_id, stat_date), []).append(candidate)

    for (product_id, stat_date), group in groups.items():
        if len(group) <= 1:
            continue
        group_sorted = sorted(group, key=lambda item: item.row_number)
        for duplicate in group_sorted[:-1]:
            duplicate.errors.append(
                _issue(
                    duplicate.row_number,
                    product_id,
                    stat_date,
                    "product_id+stat_date",
                    "duplicate_key",
                    f"商品 {product_id} 在 {stat_date} 存在重复行，已保留最后一条（第 {group_sorted[-1].row_number} 行）",
                )
            )

    issues: list[ValidationIssue] = []
    valid_records: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []

    for candidate in candidates:
        issues.extend(candidate.errors)
        issues.extend(candidate.warnings)
        if candidate.errors:
            raw = {key: value for key, value in candidate.raw.items() if key != "_row_number"}
            raw["_row_number"] = candidate.row_number
            raw["_errors"] = "；".join(issue.message for issue in candidate.errors)
            invalid_rows.append(raw)
        else:
            valid_records.append(candidate.record)

    valid_columns = list(fields.canonical_names) + ["_row_number"]
    if valid_records:
        valid_df = pd.DataFrame(valid_records)
        for column in valid_columns:
            if column not in valid_df.columns:
                valid_df[column] = None
        valid_df = valid_df[valid_columns]
    else:
        valid_df = _empty_frame(fields)

    if invalid_rows:
        invalid_df = pd.DataFrame(invalid_rows)
    else:
        invalid_df = _empty_frame(fields, with_errors=True)

    error_issues = [issue for issue in issues if issue.severity == "error"]
    warning_issues = [issue for issue in issues if issue.severity == "warning"]
    error_counts: dict[str, int] = {}
    for issue in error_issues:
        error_counts[issue.code] = error_counts.get(issue.code, 0) + 1
    warning_counts: dict[str, int] = {}
    for issue in warning_issues:
        warning_counts[issue.code] = warning_counts.get(issue.code, 0) + 1

    affected_products = sorted(
        {
            str(row.get("product_id", "")).strip()
            for row in invalid_rows
            if str(row.get("product_id", "")).strip()
        }
    )

    summary = {
        "total_rows": int(len(df)),
        "valid_rows": int(len(valid_df)),
        "invalid_rows": int(len(invalid_df)),
        "warning_rows": len({issue.row_number for issue in warning_issues}),
        "error_counts": error_counts,
        "warning_counts": warning_counts,
        "affected_products": affected_products,
        "sample_issues": [issue.to_dict() for issue in (error_issues + warning_issues)[:20]],
        "unknown_columns": df.attrs.get("unknown_columns", []),
    }

    return ValidationResult(
        valid_df=valid_df,
        invalid_df=invalid_df,
        issues=issues,
        summary=summary,
    )
