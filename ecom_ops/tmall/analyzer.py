"""天猫订单经营分析。

口径（与源数据项目的 SQL 口径保持一致，并按原始字段重新核算）：
- 下单：所有有效订单；
- 支付：有付款时间；
- 成交：实际支付金额 > 0；
- 全额成交：成交且总金额等于实际支付金额；
- 零实付/全额退款：已支付但实际支付金额为 0；
- 退款率：退款金额 / 支付订单原金额；
- 实际支付金额是扣除退款后的净额（源数据满足 总金额 = 实际支付 + 退款），
  因此不再二次扣减退款。

这是订单级分析，不计算商品级 PV/UV、SKU 或库存。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ecom_ops.tmall.loader import load_tmall_orders

SOURCE_NAME = "天猫订单成交数据"
SOURCE_URL = "https://tianchi.aliyun.com/dataset/111551"
SOURCE_LICENSE = "CC BY-SA-NC 4.0"
SOURCE_NOTE = "订单级真实交易数据；页面标注许可为非商业使用，商用前需确认。"


def _num(value: Any, digits: int = 2) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _rate(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _pct(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "—"


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["paid"] = work["paid_at"].notna()
    work["completed"] = work["paid"] & (work["paid_amount"] > 0)
    work["zero_paid"] = work["paid"] & (work["paid_amount"] == 0)
    work["refunded"] = work["refund_amount"] > 0
    work["full_price_completed"] = work["completed"] & (
        work["total_amount"] == work["paid_amount"]
    )
    work["created_date"] = work["created_at"].dt.normalize()
    work["paid_date"] = work["paid_at"].dt.normalize()
    work["paid_hour"] = work["paid_at"].dt.hour
    work["paid_weekday"] = work["paid_at"].dt.day_of_week
    return work


def _daily_kpis(df: pd.DataFrame) -> tuple[list[dict[str, Any]], list[str]]:
    paid_df = df[df["paid"]]
    if paid_df.empty:
        return [], []
    start = paid_df["paid_date"].min()
    end = paid_df["paid_date"].max()
    dates = pd.date_range(start, end, freq="D")
    rows: list[dict[str, Any]] = []
    for current in dates:
        subset = paid_df[paid_df["paid_date"] == current]
        paid_orders = int(len(subset))
        completed = int(subset["completed"].sum())
        full_price = int(subset["full_price_completed"].sum())
        zero_paid = int(subset["zero_paid"].sum())
        refund_orders = int(subset["refunded"].sum())
        paid_amount = float(subset["paid_amount"].sum())
        refund_amount = float(subset["refund_amount"].sum())
        original_amount = float(subset["total_amount"].sum())
        rows.append(
            {
                "date": current.strftime("%Y-%m-%d"),
                "paid_orders": paid_orders,
                "completed": completed,
                "full_price": full_price,
                "zero_paid": zero_paid,
                "refund_orders": refund_orders,
                "paid_amount": _num(paid_amount),
                "refund_amount": _num(refund_amount),
                "original_amount": _num(original_amount),
                "aov": _num(_rate(paid_amount, completed) or 0),
                "refund_order_rate": _rate(refund_orders, paid_orders),
                "refund_amount_ratio": _rate(refund_amount, original_amount),
                "missing": paid_orders == 0,
            }
        )
    return rows, [row["date"] for row in rows if row["missing"]]


def _daily_funnel(df: pd.DataFrame) -> tuple[list[dict[str, Any]], list[str]]:
    dates = pd.date_range(
        df["created_date"].min(),
        df["created_date"].max(),
        freq="D",
    )
    rows: list[dict[str, Any]] = []
    for current in dates:
        subset = df[df["created_date"] == current]
        placed = int(len(subset))
        paid = int(subset["paid"].sum())
        completed = int(subset["completed"].sum())
        full_price = int(subset["full_price_completed"].sum())
        zero_paid = int(subset["zero_paid"].sum())
        rows.append(
            {
                "date": current.strftime("%Y-%m-%d"),
                "placed": placed,
                "paid": paid,
                "completed": completed,
                "full_price": full_price,
                "zero_paid": zero_paid,
                "placed_to_paid": _rate(paid, placed),
                "paid_to_completed": _rate(completed, paid),
                "placed_to_completed": _rate(completed, placed),
                "completed_to_full_price": _rate(full_price, completed),
                "missing": placed == 0,
            }
        )
    return rows, [row["date"] for row in rows if row["missing"]]


def analyze_tmall(path: str | Path) -> dict[str, Any]:
    loaded = load_tmall_orders(path)
    df = _prepare(loaded.valid_df)
    quality = loaded.summary

    placed_count = int(len(df))
    paid_count = int(df["paid"].sum())
    completed_count = int(df["completed"].sum())
    full_price_count = int(df["full_price_completed"].sum())
    zero_paid_count = int(df["zero_paid"].sum())
    refund_order_count = int(df["refunded"].sum())

    paid_sum = float(df["paid_amount"].sum())
    refund_sum = float(df["refund_amount"].sum())
    original_paid_sum = float(df.loc[df["paid"], "total_amount"].sum())
    full_price_paid_sum = float(
        df.loc[df["full_price_completed"], "paid_amount"].sum()
    )
    unpaid_amount = float(df.loc[~df["paid"], "total_amount"].sum())

    funnel = {
        "placed_count": placed_count,
        "paid_count": paid_count,
        "completed_count": completed_count,
        "full_price_count": full_price_count,
        "zero_paid_count": zero_paid_count,
        "refund_order_count": refund_order_count,
        "placed_to_paid": _rate(paid_count, placed_count),
        "paid_to_completed": _rate(completed_count, paid_count),
        "placed_to_completed": _rate(completed_count, placed_count),
        "completed_to_full_price": _rate(full_price_count, completed_count),
        "full_price_share": _rate(full_price_count, placed_count),
    }
    kpis = {
        "total_amount_sum": _num(float(df["total_amount"].sum())),
        "original_paid_sum": _num(original_paid_sum),
        "paid_sum": _num(paid_sum),
        "refund_sum": _num(refund_sum),
        "full_price_paid_sum": _num(full_price_paid_sum),
        "unpaid_amount": _num(unpaid_amount),
        "completed_aov": _num(_rate(paid_sum, completed_count) or 0),
        "full_price_aov": _num(_rate(full_price_paid_sum, full_price_count) or 0),
        "refund_amount_ratio": _rate(refund_sum, original_paid_sum),
        "refund_order_rate": _rate(refund_order_count, paid_count),
    }

    daily, missing_payment_dates = _daily_kpis(df)
    funnel_daily, missing_created_dates = _daily_funnel(df)

    province_rows: list[dict[str, Any]] = []
    for province, subset in df.groupby("province", sort=False):
        placed = int(len(subset))
        paid = int(subset["paid"].sum())
        completed = int(subset["completed"].sum())
        full_price = int(subset["full_price_completed"].sum())
        paid_amount = float(subset["paid_amount"].sum())
        refund_amount = float(subset["refund_amount"].sum())
        original_amount = float(subset["total_amount"].sum())
        province_rows.append(
            {
                "province": str(province),
                "placed": placed,
                "paid": paid,
                "completed": completed,
                "full_price": full_price,
                "paid_amount": _num(paid_amount),
                "refund_amount": _num(refund_amount),
                "original_amount": _num(original_amount),
                "paid_rate": _rate(paid, placed),
                "completed_rate": _rate(completed, placed),
                "aov": _num(_rate(paid_amount, completed) or 0),
                "refund_amount_ratio": _rate(refund_amount, original_amount),
            }
        )
    province_rows.sort(key=lambda item: item["paid_amount"] or 0, reverse=True)

    hour_labels = [f"{hour:02d}:00" for hour in range(24)]
    hour_rows: list[dict[str, Any]] = []
    for hour in range(24):
        subset = df[df["paid_hour"] == hour]
        paid_orders = int(len(subset))
        completed = int(subset["completed"].sum())
        refund_orders = int(subset["refunded"].sum())
        paid_amount = float(subset["paid_amount"].sum())
        refund_amount = float(subset["refund_amount"].sum())
        original_amount = float(subset["total_amount"].sum())
        hour_rows.append(
            {
                "hour": hour_labels[hour],
                "paid_orders": paid_orders,
                "completed": completed,
                "refund_orders": refund_orders,
                "paid_amount": _num(paid_amount),
                "refund_amount": _num(refund_amount),
                "aov": _num(_rate(paid_amount, completed) or 0),
                "refund_order_rate": _rate(refund_orders, paid_orders),
                "refund_amount_ratio": _rate(refund_amount, original_amount),
            }
        )

    weekday_labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday_rows: list[dict[str, Any]] = []
    for weekday in range(7):
        subset = df[df["paid_weekday"] == weekday]
        paid_orders = int(len(subset))
        completed = int(subset["completed"].sum())
        refund_orders = int(subset["refunded"].sum())
        paid_amount = float(subset["paid_amount"].sum())
        refund_amount = float(subset["refund_amount"].sum())
        original_amount = float(subset["total_amount"].sum())
        weekday_rows.append(
            {
                "weekday": weekday_labels[weekday],
                "paid_orders": paid_orders,
                "completed": completed,
                "refund_orders": refund_orders,
                "paid_amount": _num(paid_amount),
                "refund_amount": _num(refund_amount),
                "aov": _num(_rate(paid_amount, completed) or 0),
                "refund_order_rate": _rate(refund_orders, paid_orders),
                "refund_amount_ratio": _rate(refund_amount, original_amount),
            }
        )

    top_days = sorted(
        [row for row in daily if row["paid_orders"] > 0],
        key=lambda item: item["paid_amount"] or 0,
        reverse=True,
    )[:5]
    top_provinces = province_rows[:10]
    top_hours = sorted(
        [row for row in hour_rows if row["paid_orders"] > 0],
        key=lambda item: item["paid_amount"] or 0,
        reverse=True,
    )[:5]

    findings: list[str] = [
        (
            f"下单 {placed_count:,} 单，支付 {paid_count:,} 单，"
            f"支付率 {_pct(_rate(paid_count, placed_count))}；"
            f"成交（实付>0）{completed_count:,} 单，"
            f"成交率 {_pct(_rate(completed_count, placed_count))}。"
        ),
        (
            f"全价成交 {full_price_count:,} 单，"
            f"零实付/全额退款 {zero_paid_count:,} 单；"
            f"退款订单 {refund_order_count:,} 单，"
            f"退款订单率（退款订单/支付订单）"
            f"{_pct(_rate(refund_order_count, paid_count))}。"
        ),
        (
            f"支付订单原金额 {original_paid_sum:,.2f}，"
            f"退款 {refund_sum:,.2f}，"
            f"实际支付净额 {paid_sum:,.2f}，"
            f"退款金额占原金额 {_pct(_rate(refund_sum, original_paid_sum))}。"
        ),
        (
            "源数据中支付订单满足“总金额 = 实际支付 + 退款”，"
            "实际支付字段已是退款后的净额，报告不再二次扣减退款。"
        ),
    ]
    if missing_created_dates:
        findings.append(
            "按订单创建日期，没有订单的日期："
            + "、".join(missing_created_dates)
            + "（可能是缺失数据，也可能是真实零单）。"
        )
    if missing_payment_dates:
        findings.append(
            "按付款日期，没有支付记录的日期：" + "、".join(missing_payment_dates) + "。"
        )
    if top_days:
        findings.append(
            "支付净额最高的日期："
            + "、".join(
                f"{row['date']}（{row['paid_amount']:,.2f}）" for row in top_days[:3]
            )
        )
    if top_provinces:
        findings.append(
            "支付净额最高的省份："
            + "、".join(
                f"{row['province']}（{row['paid_amount']:,.2f}）"
                for row in top_provinces[:3]
            )
        )
    if top_hours:
        findings.append(
            "支付净额最高的时段："
            + "、".join(
                f"{row['hour']}（{row['paid_amount']:,.2f}）" for row in top_hours[:3]
            )
        )

    limitations = [
        "这是天猫订单级数据，没有 SKU、商品名称、PV/UV、库存，不能做商品级异常日报。",
        "源文件实际编码为 GBK，表头存在尾部空格；已做清洗。",
        "未支付订单的付款时间为空；成交口径为“实际支付金额 > 0”。",
        "源数据支付订单满足“总金额 = 实际支付 + 退款”，实际支付为退款后净额；不要再次减退款。",
        "数据只覆盖 2020 年 2 月，且按创建日存在无订单日期；不能外推到全年。",
        "按当前 CSV 直接计算的全价成交为 18,441 单；源 Tableau/SQL 项目展示 16,650 单，差异可能来自清洗版本，本报告未强行对齐。",
        "源项目 Tableau/SQL 的清洗版本可能与原始 CSV 有差异，本报告以当前 CSV 重新计算。",
        "省份、金额、时间均来自源数据；未做汇率、税费或平台佣金调整。",
        "数据来源为天池公开数据集《天猫订单成交数据》，许可标注为 CC BY-SA-NC 4.0；非商业使用，商用前需确认许可。",
        "本报告不调用大模型，结论来自固定口径统计。",
    ]

    return {
        "source_path": str(path),
        "source": {
            "name": SOURCE_NAME,
            "url": SOURCE_URL,
            "license": SOURCE_LICENSE,
            "note": SOURCE_NOTE,
        },
        "quality": quality,
        "funnel": funnel,
        "kpis": kpis,
        "daily": daily,
        "funnel_daily": funnel_daily,
        "missing_created_dates": missing_created_dates,
        "missing_payment_dates": missing_payment_dates,
        "provinces": province_rows,
        "top_provinces": top_provinces,
        "hours": hour_rows,
        "top_hours": top_hours,
        "weekdays": weekday_rows,
        "top_days": top_days,
        "findings": findings,
        "limitations": limitations,
        "date_min": df["created_at"].min().strftime("%Y-%m-%d"),
        "date_max": df["created_at"].max().strftime("%Y-%m-%d"),
        "payment_date_min": (
            df["paid_at"].min().strftime("%Y-%m-%d")
            if df["paid_at"].notna().any()
            else None
        ),
        "payment_date_max": (
            df["paid_at"].max().strftime("%Y-%m-%d")
            if df["paid_at"].notna().any()
            else None
        ),
    }
