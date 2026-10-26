"""阈值敏感度工程测试。

在固定数据上改变异常阈值，观察：
- 日均异常数、异常率、高危数；
- 各异常类型数量；
- 单参数敏感度、二维网格、工程档位对比。

不修改 config/settings.yaml，不调用大模型。
参考样本结果只用于工程评估，不作为业务定案。

用法：
    .venv\\Scripts\\python.exe tools\\threshold_sensitivity.py
    .venv\\Scripts\\python.exe tools\\threshold_sensitivity.py --data data/reference/online_retail_reference.csv --days 30
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.analysis.sensitivity import (
    SensitivityRow,
    prepare_frames,
    run_grid,
    run_ofat,
    run_profiles,
    select_dates,
)
from ecom_ops.config import load_settings
from ecom_ops.data.loader import load_sales_data
from ecom_ops.data.validator import validate_sales_data
from ecom_ops.exceptions import EcomOpsError
from ecom_ops.utils.files import ensure_dir

OFAT_SPECS: dict[str, list[Any]] = {
    "min_pv_for_zero_conversion": [50, 100, 150, 200, 300],
    "min_pv_for_ratio": [30, 50, 80, 100],
    "min_orders_for_drop": [2, 3, 5, 8],
    "pv_drop_ratio": [0.5, 0.6, 0.7, 0.8],
    "order_drop_ratio": [0.5, 0.6, 0.7, 0.8],
    "high_pv_ratio": [1.1, 1.2, 1.3, 1.5],
    "low_cr_ratio": [0.4, 0.5, 0.6, 0.7],
}

PROFILES: dict[str, dict[str, Any]] = {
    "v0.1 基线": {},
    "工程严格档": {
        "min_pv_for_zero_conversion": 200,
        "min_pv_for_ratio": 80,
        "min_orders_for_drop": 5,
        "pv_drop_ratio": 0.6,
        "order_drop_ratio": 0.6,
        "high_pv_ratio": 1.3,
        "low_cr_ratio": 0.5,
    },
    "工程敏感档": {
        "min_pv_for_zero_conversion": 50,
        "min_pv_for_ratio": 30,
        "min_orders_for_drop": 2,
        "pv_drop_ratio": 0.8,
        "order_drop_ratio": 0.8,
        "high_pv_ratio": 1.1,
        "low_cr_ratio": 0.7,
    },
}

def _pct(value: float) -> str:
    return f"{value:.1%}"


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def _row_cells(row: SensitivityRow) -> list[Any]:
    return [
        row.label,
        row.avg_per_day,
        _pct(row.anomaly_rate),
        row.high_risk_avg,
        row.unique_products,
        row.type_counts.get("零转化", 0),
        row.type_counts.get("浏览量骤降", 0),
        row.type_counts.get("订单量骤降", 0),
        row.type_counts.get("高浏览低转化", 0),
    ]


def _build_markdown(
    data_path: str,
    days: int,
    product_count: int,
    baseline_config: Any,
    ofat: list[SensitivityRow],
    grid: list[SensitivityRow],
    profiles: list[SensitivityRow],
) -> str:
    baseline = ofat[0]
    grid_min = min(grid, key=lambda item: item.avg_per_day)
    grid_max = max(grid, key=lambda item: item.avg_per_day)
    parameter_ranges: list[tuple[str, float, float]] = []
    for parameter in OFAT_SPECS:
        values = [row.avg_per_day for row in ofat if row.parameter == parameter]
        if values:
            parameter_ranges.append((parameter, min(values), max(values)))
    strongest = max(parameter_ranges, key=lambda item: item[2] - item[1]) if parameter_ranges else None

    lines = [
        "# 阈值敏感度分析（参考样本工程测试）",
        "",
        "> 本报告只用于工程评估，**不修改 v0.1 配置，也不作为业务定案**。",
        "> 参考样本来自 UCI Online Retail，PV/UV、成本、库存等为派生字段，不能代表真实数字商品业务。",
        "",
        "## 1. 测试数据与基线",
        "",
        f"- 数据文件：`{data_path}`",
        f"- 测试天数：{days} 天（取数据最后 {days} 天）",
        f"- 商品数：{product_count}",
        f"- 基线阈值：零转化 PV ≥ {baseline_config.min_pv_for_zero_conversion}，"
        f"PV 骤降 ≤ {baseline_config.pv_drop_ratio}（基线 PV ≥ {baseline_config.min_pv_for_ratio}），"
        f"订单骤降 ≤ {baseline_config.order_drop_ratio}（基线订单 ≥ {baseline_config.min_orders_for_drop}），"
        f"高浏览低转化 PV ≥ 基线 × {baseline_config.high_pv_ratio} 且 CR ≤ 基线 CR × {baseline_config.low_cr_ratio}",
        "",
        "### v0.1 基线结果",
        "",
        _table(
            ["日均异常", "异常率", "高危日均", "涉及商品", "零转化", "PV骤降", "订单骤降", "高浏览低转化"],
            [[
                baseline.avg_per_day,
                _pct(baseline.anomaly_rate),
                baseline.high_risk_avg,
                baseline.unique_products,
                baseline.type_counts.get("零转化", 0),
                baseline.type_counts.get("浏览量骤降", 0),
                baseline.type_counts.get("订单量骤降", 0),
                baseline.type_counts.get("高浏览低转化", 0),
            ]],
        ),
        "",
        "## 2. 单参数敏感度（OFAT）",
        "",
        "固定其他参数，只改变一个参数，观察日均异常与类型分布。",
        "",
        _table(
            ["场景", "日均异常", "异常率", "高危日均", "涉及商品", "零转化", "PV骤降", "订单骤降", "高浏览低转化"],
            [_row_cells(row) for row in ofat],
        ),
        "",
        "## 3. 二维网格：零转化 PV 门槛 × 订单骤降比例",
        "",
        "单元格为日均异常数；括号内为异常率。",
        "",
    ]

    x_values = [50, 100, 150, 200, 300]
    y_values = [0.5, 0.6, 0.7, 0.8]
    grid_lookup = {
        (row.label.split(", ")[0].split("=")[1], row.label.split(", ")[1].split("=")[1]): row
        for row in grid
    }
    grid_rows: list[list[Any]] = []
    for x in x_values:
        cells: list[Any] = [x]
        for y in y_values:
            row = grid_lookup.get((str(x), str(y)))
            cells.append(f"{row.avg_per_day} ({_pct(row.anomaly_rate)})" if row else "—")
        grid_rows.append(cells)
    lines.append(
        _table(["零转化 PV 门槛 \\ 订单骤降比例"] + [str(value) for value in y_values], grid_rows)
    )

    lines.extend(
        [
            "",
            "## 4. 工程档位对比",
            "",
            _table(
                ["档位", "日均异常", "异常率", "高危日均", "涉及商品", "零转化", "PV骤降", "订单骤降", "高浏览低转化"],
                [_row_cells(row) for row in profiles],
            ),
            "",
            "> “严格档/敏感档”是为了观察阈值方向而构造的工程档位，不是建议上线的业务参数。",
            "",
            "## 5. 观察",
            "",
            f"- v0.1 在参考样本上日均异常 **{baseline.avg_per_day}** 个，异常率 **{_pct(baseline.anomaly_rate)}**，高危日均 **{baseline.high_risk_avg}**。",
            f"- 二维网格中，日均异常最少为 **{grid_min.avg_per_day}**（{grid_min.label}），最多为 **{grid_max.avg_per_day}**（{grid_max.label}）。",
        ]
    )
    if strongest:
        lines.append(
            f"- 单参数中，`{strongest[0]}` 对日均异常影响最大：从 {strongest[1]} 到 {strongest[2]}。"
        )
    lines.extend(
        [
            "- 参考样本是英国礼品零售，且 PV/UV/成本/库存为派生字段；这里的敏感度只能说明“阈值方向”，不能直接用于真实数字商品业务。",
            "- 建议保留 v0.1，等真实业务数据到位后，用同一工具重新跑一遍，再决定是否调整。",
            "",
            "## 6. 结论",
            "",
            "- 本次测试不修改任何生产配置。",
            "- 阈值调整必须基于真实业务数据、异常处理成本和人工复核能力，而不是只看“异常数量少”。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="阈值敏感度工程测试")
    parser.add_argument(
        "--data",
        default="data/reference/online_retail_reference.csv",
        help="CSV/Excel 数据路径",
    )
    parser.add_argument("--sheet", default=None, help="Excel 工作表")
    parser.add_argument("--days", type=int, default=30, help="取最后 N 天，默认 30")
    parser.add_argument(
        "--output-dir",
        default="reports/threshold_sensitivity",
        help="CSV 输出目录",
    )
    parser.add_argument(
        "--summary-path",
        default="docs/threshold_sensitivity_reference.md",
        help="Markdown 摘要输出路径；设为空字符串则不写",
    )
    parser.add_argument("--config", default=None, help="settings.yaml 路径")
    parser.add_argument("--fields", default=None, help="fields.yaml 路径")
    args = parser.parse_args()

    try:
        settings = load_settings(args.config, args.fields)
        raw = load_sales_data(args.data, settings.fields, sheet_name=args.sheet)
        validation = validate_sales_data(raw, settings.fields)
    except EcomOpsError as exc:
        print(f"数据读取失败: {exc}", file=sys.stderr)
        return 1

    if validation.valid_df.empty:
        print("数据校验后没有可用行。", file=sys.stderr)
        return 1

    dates = select_dates(validation.valid_df, args.days)
    if not dates:
        print("没有可用日期。", file=sys.stderr)
        return 1

    print(f"准备 {len(dates)} 天数据：{dates[0]} ~ {dates[-1]}")
    metrics_by_date, baselines_by_date = prepare_frames(
        validation.valid_df,
        dates,
        settings.baseline,
    )

    print("运行单参数敏感度...")
    ofat = run_ofat(settings.anomaly, OFAT_SPECS, metrics_by_date, baselines_by_date)
    print("运行二维网格...")
    grid = run_grid(
        settings.anomaly,
        "min_pv_for_zero_conversion",
        [50, 100, 150, 200, 300],
        "order_drop_ratio",
        [0.5, 0.6, 0.7, 0.8],
        metrics_by_date,
        baselines_by_date,
    )
    print("运行工程档位...")
    profiles = run_profiles(settings.anomaly, PROFILES, metrics_by_date, baselines_by_date)

    output_dir = ensure_dir(Path(args.output_dir))
    pd.DataFrame([row.to_dict() for row in ofat]).to_csv(
        output_dir / "ofat.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame([row.to_dict() for row in grid]).to_csv(
        output_dir / "grid.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame([row.to_dict() for row in profiles]).to_csv(
        output_dir / "profiles.csv", index=False, encoding="utf-8-sig"
    )

    markdown = _build_markdown(
        args.data,
        len(dates),
        validation.valid_df["product_id"].nunique(),
        settings.anomaly,
        ofat,
        grid,
        profiles,
    )
    if args.summary_path:
        summary_path = Path(args.summary_path)
        ensure_dir(summary_path.parent)
        summary_path.write_text(markdown, encoding="utf-8")
        print(f"Markdown 摘要: {summary_path}")
    print(f"CSV 输出目录: {output_dir}")
    print()
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
