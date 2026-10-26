"""天猫订单数据读取与清洗。

已知源文件特点：
- 实际编码为 GBK（README 写的是 UTF-8，但样本字节是 GBK）；
- 部分中文表头带尾部空格；
- 未支付订单的付款时间为空字符串；
- 金额字段可能为 0；
- 没有 SKU、PV/UV、库存。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ecom_ops.exceptions import TmallError

REQUIRED_COLUMNS = [
    "订单编号",
    "总金额",
    "买家实际支付金额",
    "收货地址",
    "订单创建时间",
    "订单付款时间",
    "退款金额",
]

COLUMN_MAP = {
    "订单编号": "order_id",
    "总金额": "total_amount",
    "买家实际支付金额": "paid_amount",
    "收货地址": "province",
    "订单创建时间": "created_at",
    "订单付款时间": "paid_at",
    "退款金额": "refund_amount",
}


@dataclass(frozen=True)
class TmallIssue:
    row_number: int
    order_id: str
    code: str
    message: str
    severity: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "order_id": self.order_id,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class TmallLoadResult:
    valid_df: pd.DataFrame
    invalid_df: pd.DataFrame
    issues: list[TmallIssue]
    summary: dict[str, Any]


def _read_csv(path: Path) -> tuple[pd.DataFrame, str]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            df = pd.read_csv(
                path,
                dtype=str,
                keep_default_na=False,
                na_filter=False,
                encoding=encoding,
            )
            return df, encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    raise TmallError(f"无法读取天猫 CSV: {path}\n{last_error}")


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def _number(value: Any) -> float | None:
    text = _text(value).replace(",", "")
    if not text:
        return 0.0
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def _date(value: Any) -> pd.Timestamp | None:
    text = _text(value)
    if not text:
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    return None if pd.isna(parsed) else parsed


def load_tmall_orders(path: str | Path) -> TmallLoadResult:
    file_path = Path(path)
    if not file_path.exists():
        raise TmallError(f"天猫数据文件不存在: {file_path}")
    if file_path.suffix.lower() != ".csv":
        raise TmallError("当前天猫分支只支持 CSV")

    raw, encoding = _read_csv(file_path)
    raw.columns = [str(column).replace("\ufeff", "").strip() for column in raw.columns]
    missing = [name for name in REQUIRED_COLUMNS if name not in raw.columns]
    if missing:
        raise TmallError(f"天猫数据缺少字段: {', '.join(missing)}")
    if raw.empty:
        raise TmallError("天猫数据没有数据行")

    raw = raw.rename(columns=COLUMN_MAP)
    raw["_row_number"] = range(2, len(raw) + 2)

    candidates: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []
    issues: list[TmallIssue] = []

    for record in raw.to_dict("records"):
        row_number = int(record.get("_row_number", 0))
        order_id = _text(record.get("order_id"))
        errors: list[TmallIssue] = []
        warnings: list[TmallIssue] = []

        def add(code: str, message: str, severity: str = "error") -> None:
            issue = TmallIssue(row_number, order_id, code, message, severity)
            (errors if severity == "error" else warnings).append(issue)
            issues.append(issue)

        created_at = _date(record.get("created_at"))
        paid_raw = _text(record.get("paid_at"))
        paid_at = _date(paid_raw)
        total_amount = _number(record.get("total_amount"))
        paid_amount = _number(record.get("paid_amount"))
        refund_amount = _number(record.get("refund_amount"))
        province = _text(record.get("province")) or "未知"

        if not order_id:
            add("missing_order_id", "订单编号为空")
        if created_at is None:
            add("invalid_created_at", "订单创建时间无法解析")
        if total_amount is None:
            add("invalid_total_amount", "总金额不是有效数字")
        elif total_amount < 0:
            add("negative_total_amount", "总金额为负数")
        if paid_amount is None:
            add("invalid_paid_amount", "买家实际支付金额不是有效数字")
        elif paid_amount < 0:
            add("negative_paid_amount", "买家实际支付金额为负数")
        if refund_amount is None:
            add("invalid_refund_amount", "退款金额不是有效数字")
        elif refund_amount < 0:
            add("negative_refund_amount", "退款金额为负数")
        if paid_raw and paid_at is None:
            add("invalid_paid_at", "订单付款时间无法解析")
        if created_at is not None and paid_at is not None and paid_at < created_at:
            add("paid_before_created", "付款时间早于下单时间")
        if total_amount is not None and paid_amount is not None and total_amount < paid_amount:
            add("total_lt_paid", "总金额小于实际支付金额")
        if not _text(record.get("province")):
            add("missing_province", "收货地址为空，已填“未知”", "warning")
        if paid_at is not None and paid_amount == 0:
            add("paid_zero_amount", "已支付但实际支付金额为 0（通常为全额退款/取消）", "warning")

        if errors:
            raw_row = {key: value for key, value in record.items() if key != "_row_number"}
            raw_row["_row_number"] = row_number
            raw_row["_errors"] = "；".join(issue.message for issue in errors)
            invalid_rows.append(raw_row)
            continue

        candidates.append(
            {
                "order_id": order_id,
                "total_amount": total_amount or 0.0,
                "paid_amount": paid_amount or 0.0,
                "province": province,
                "created_at": created_at,
                "paid_at": paid_at,
                "refund_amount": refund_amount or 0.0,
                "_row_number": row_number,
            }
        )

    # 订单编号重复：保留最后一条。
    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        groups.setdefault(candidate["order_id"], []).append(candidate)
    for order_id, group in groups.items():
        if len(group) <= 1:
            continue
        group_sorted = sorted(group, key=lambda item: item["_row_number"])
        for duplicate in group_sorted[:-1]:
            duplicate["_duplicate"] = True
            issues.append(
                TmallIssue(
                    duplicate["_row_number"],
                    order_id,
                    "duplicate_order_id",
                    f"订单编号重复，保留第 {group_sorted[-1]['_row_number']} 行",
                    "error",
                )
            )
            raw_row = {key: value for key, value in duplicate.items() if key != "_row_number"}
            raw_row["_row_number"] = duplicate["_row_number"]
            raw_row["_errors"] = "订单编号重复，已保留最后一条"
            invalid_rows.append(raw_row)

    valid_records = [item for item in candidates if not item.get("_duplicate")]
    valid_df = pd.DataFrame(valid_records)
    if valid_df.empty:
        raise TmallError("天猫数据清洗后没有可用订单")
    valid_df = valid_df.drop(columns=["_duplicate", "_row_number"], errors="ignore")
    invalid_df = pd.DataFrame(invalid_rows)

    error_issues = [issue for issue in issues if issue.severity == "error"]
    warning_issues = [issue for issue in issues if issue.severity == "warning"]
    error_counts: dict[str, int] = {}
    for issue in error_issues:
        error_counts[issue.code] = error_counts.get(issue.code, 0) + 1
    warning_counts: dict[str, int] = {}
    for issue in warning_issues:
        warning_counts[issue.code] = warning_counts.get(issue.code, 0) + 1
    duplicate_count = sum(
        max(0, len(group) - 1) for group in groups.values() if len(group) > 1
    )
    paid_mask = valid_df["paid_at"].notna()
    identity_mask = (
        (valid_df["total_amount"] - valid_df["paid_amount"] - valid_df["refund_amount"])
        .abs()
        <= 0.01
    )
    paid_identity_count = int((paid_mask & identity_mask).sum())
    paid_count = int(paid_mask.sum())
    zero_paid_count = int((paid_mask & (valid_df["paid_amount"] == 0)).sum())
    refund_count = int((valid_df["refund_amount"] > 0).sum())

    summary = {
        "source_path": str(file_path),
        "encoding": encoding,
        "total_rows": int(len(raw)),
        "valid_rows": int(len(valid_df)),
        "invalid_rows": int(len(invalid_df)),
        "error_counts": error_counts,
        "warning_counts": warning_counts,
        "duplicate_order_ids": int(duplicate_count),
        "paid_rows": paid_count,
        "zero_paid_rows": zero_paid_count,
        "refund_rows": refund_count,
        "paid_identity_rows": paid_identity_count,
        "paid_identity_rate": (
            paid_identity_count / paid_count if paid_count else None
        ),
        "issues": [issue.to_dict() for issue in issues],
    }
    return TmallLoadResult(
        valid_df=valid_df,
        invalid_df=invalid_df,
        issues=issues,
        summary=summary,
    )
