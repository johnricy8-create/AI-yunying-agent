"""真实数据画像工具。

在不生成报告、不调用大模型的前提下，先检查一份 CSV/Excel：
- 表头映射与缺失字段；
- 行数、商品数、日期覆盖、缺失日期；
- 缺失值、重复、格式错误、逻辑冲突；
- 价格/库存/浏览量/订单/销售额/退款分布；
- 转化率分布，辅助阈值校准。

用法：
    .venv\\Scripts\\python.exe tools\\profile_data.py --data data/raw/sales.csv
    .venv\\Scripts\\python.exe tools\\profile_data.py --data data/raw/sales.xlsx --sheet 销售数据
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.config import load_settings
from ecom_ops.data.loader import load_sales_data
from ecom_ops.data.validator import validate_sales_data
from ecom_ops.exceptions import EcomOpsError
from ecom_ops.utils.dates import parse_date


def _section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def _date_coverage(valid_df: pd.DataFrame, top: int) -> tuple[list[str], int, list[dict]]:
    dates = sorted(str(item) for item in valid_df["stat_date"].dropna().unique())
    if not dates:
        return [], 0, []
    gaps: list[dict] = []
    short_history: list[dict] = []
    for product_id, group in valid_df.groupby("product_id", sort=False):
        actual = sorted(str(item) for item in group["stat_date"].dropna().unique())
        if not actual:
            continue
        first = parse_date(actual[0])
        last = parse_date(actual[-1])
        expected = (last - first).days + 1
        missing = expected - len(actual)
        if missing > 0:
            gaps.append(
                {
                    "product_id": str(product_id),
                    "first": actual[0],
                    "last": actual[-1],
                    "valid_days": len(actual),
                    "missing_days": missing,
                }
            )
        if len(actual) < 3:
            short_history.append(
                {"product_id": str(product_id), "valid_days": len(actual)}
            )
    gaps.sort(key=lambda item: item["missing_days"], reverse=True)
    short_history.sort(key=lambda item: item["valid_days"])
    return dates, len(gaps), gaps[:top] + short_history[:top]


def _numeric_profile(valid_df: pd.DataFrame) -> None:
    fields = [
        "price",
        "cost",
        "stock",
        "pv",
        "orders",
        "sales_amount",
        "refund_amount",
    ]
    print(f"{'字段':<16}{'最小':>12}{'P50':>12}{'P90':>12}{'P99':>12}{'最大':>12}")
    for field in fields:
        if field not in valid_df.columns:
            continue
        series = pd.to_numeric(valid_df[field], errors="coerce").dropna()
        if series.empty:
            continue
        print(
            f"{field:<16}"
            f"{series.min():>12,.2f}"
            f"{series.quantile(0.5):>12,.2f}"
            f"{series.quantile(0.9):>12,.2f}"
            f"{series.quantile(0.99):>12,.2f}"
            f"{series.max():>12,.2f}"
        )

    pv = pd.to_numeric(valid_df["pv"], errors="coerce")
    orders = pd.to_numeric(valid_df["orders"], errors="coerce")
    mask = pv > 0
    if mask.any():
        cr = (orders[mask] / pv[mask]).dropna()
        print()
        print("转化率（订单/浏览量）分布：")
        print(
            f"  P50={cr.quantile(0.5):.2%}  P90={cr.quantile(0.9):.2%}  "
            f"P99={cr.quantile(0.99):.2%}  最大={cr.max():.2%}"
        )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="检查真实销售数据")
    parser.add_argument("--data", required=True, help="CSV/Excel 文件路径")
    parser.add_argument("--sheet", default=None, help="Excel 工作表名称")
    parser.add_argument("--config", default=None, help="settings.yaml 路径")
    parser.add_argument("--fields", default=None, help="fields.yaml 路径")
    parser.add_argument("--top", type=int, default=10, help="展示前 N 条问题，默认 10")
    args = parser.parse_args()

    try:
        settings = load_settings(args.config, args.fields)
        raw = load_sales_data(args.data, settings.fields, sheet_name=args.sheet)
        result = validate_sales_data(raw, settings.fields)
    except EcomOpsError as exc:
        print(f"数据检查失败: {exc}", file=sys.stderr)
        return 1

    summary = result.summary
    valid_df = result.valid_df
    invalid_df = result.invalid_df

    _section("1. 基本信息")
    print(f"数据文件        : {args.data}")
    print(f"工作表          : {args.sheet or '默认第一个'}")
    print(f"总行数          : {summary.get('total_rows', 0):,}")
    print(f"有效行          : {summary.get('valid_rows', 0):,}")
    print(f"隔离行          : {summary.get('invalid_rows', 0):,}")
    print(f"警告行          : {summary.get('warning_rows', 0):,}")
    unknown = raw.attrs.get("unknown_columns", [])
    print(f"未识别列        : {('、'.join(map(str, unknown)) if unknown else '无')}")
    if not valid_df.empty:
        print(f"商品数          : {valid_df['product_id'].nunique():,}")
        print(
            f"日期范围        : {valid_df['stat_date'].min()} ~ {valid_df['stat_date'].max()}"
        )
        print(f"日期数          : {valid_df['stat_date'].nunique():,}")
        per_date = valid_df.groupby("stat_date").size()
        print(
            f"每日行数        : 最少 {per_date.min():,}，最多 {per_date.max():,}"
        )
    print("提示            : 以下输出可能包含真实业务数据，请勿直接公开粘贴。")

    _section("2. 表头与缺失值")
    print(f"内部字段数      : {len(settings.fields.fields)}")
    print(f"必填字段        : {', '.join(settings.fields.required_names)}")
    empty_counts = []
    for name in settings.fields.canonical_names:
        if name not in raw.columns:
            continue
        series = raw[name].astype(str).str.strip()
        count = int((series == "").sum())
        if count:
            spec = settings.fields.fields[name]
            empty_counts.append((name, settings.fields.label(name), count, spec.required))
    if empty_counts:
        print("空值统计：")
        for name, label, count, required in empty_counts:
            if count == len(raw) and not required:
                print(f"  {name:<16} {label:<8} 未提供（可选）")
            else:
                print(f"  {name:<16} {label:<8} {count:,}")
    else:
        print("空值统计        : 无")

    _section("3. 数据质量")
    print(f"错误总数        : {sum(summary.get('error_counts', {}).values()):,}")
    print(f"警告总数        : {sum(summary.get('warning_counts', {}).values()):,}")
    if summary.get("error_counts"):
        print("错误类型：")
        for code, count in summary["error_counts"].items():
            print(f"  {code:<24} {count:,}")
    if summary.get("warning_counts"):
        print("警告类型：")
        for code, count in summary["warning_counts"].items():
            print(f"  {code:<24} {count:,}")
    if not invalid_df.empty:
        print("隔离行样例：")
        sample = invalid_df.head(args.top)
        for _, row in sample.iterrows():
            print(
                f"  行 {row.get('_row_number', '')}: "
                f"{row.get('product_id', '')} {row.get('stat_date', '')} "
                f"{row.get('_errors', '')}"
            )

    _section("4. 日期覆盖与基线风险")
    if valid_df.empty:
        print("没有可用行，无法检查日期覆盖。")
    else:
        dates, gap_products, samples = _date_coverage(valid_df, args.top)
        print(f"有效日期数      : {len(dates):,}")
        print(f"存在缺日的商品  : {gap_products:,}")
        if samples:
            print("缺日/短历史样例：")
            for item in samples:
                if item.get("missing_days", 0):
                    print(
                        f"  {item['product_id']}: 有效 {item.get('valid_days', 0)} 天，"
                        f"缺失 {item.get('missing_days', 0)} 天"
                    )
                else:
                    print(
                        f"  {item['product_id']}: 仅 {item.get('valid_days', 0)} 天历史，"
                        "基线置信度会偏低"
                    )

    _section("5. 数值分布")
    if valid_df.empty:
        print("没有可用行。")
    else:
        _numeric_profile(valid_df)

    _section("6. 阈值校准提示")
    print("当前阈值 v0.1 未自动修改。请结合上面的 PV/订单分位数、转化率分布，")
    print("人工评估以下参数是否适合真实业务：")
    print("  - baseline.min_valid_days / windows / cv_low / cv_high")
    print("  - anomaly.min_pv_for_ratio / min_pv_for_zero_conversion")
    print("  - anomaly.min_orders_for_drop / pv_drop_ratio / order_drop_ratio")
    print("  - anomaly.high_pv_ratio / low_cr_ratio")
    print("修改 config/settings.yaml 后，建议先跑 pytest 和 --no-ai 验证。")

    return 0 if not valid_df.empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
