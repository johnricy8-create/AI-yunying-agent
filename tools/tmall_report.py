"""生成天猫订单经营分析报告。

用法：
    .venv\\Scripts\\python.exe tools\\tmall_report.py
    .venv\\Scripts\\python.exe tools\\tmall_report.py --data "D:\\path\\tmall_order_report.csv"
    .venv\\Scripts\\python.exe tools\\tmall_report.py --output reports/tmall/custom.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.exceptions import EcomOpsError
from ecom_ops.tmall.analyzer import analyze_tmall
from ecom_ops.tmall.dashboard import render_tmall_dashboard
from ecom_ops.tmall.renderer import render_tmall_report

DEFAULT_DATA = Path(
    r"D:\天猫销售数据\Tmall_Tableau_Visualization_Project\data\tmall_order_report.csv"
)
DEFAULT_OUTPUT = Path("reports/tmall/2020-02_tmall_order_report.md")
DEFAULT_DASHBOARD = Path("reports/tmall/2020-02_tmall_dashboard.html")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="生成天猫订单经营分析 Markdown 报告")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="天猫订单 CSV 路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Markdown 输出路径")
    parser.add_argument(
        "--html",
        default=str(DEFAULT_DASHBOARD),
        help="HTML 看板输出路径",
    )
    parser.add_argument("--no-html", action="store_true", help="不生成 HTML 看板")
    args = parser.parse_args()

    try:
        analysis = analyze_tmall(args.data)
        output = render_tmall_report(analysis, args.output)
        dashboard = None
        if not args.no_html:
            dashboard = render_tmall_dashboard(analysis, args.html)
    except EcomOpsError as exc:
        print(f"生成天猫报告失败: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"未预期错误: {exc}", file=sys.stderr)
        return 1

    funnel = analysis["funnel"]
    kpis = analysis["kpis"]
    refund_ratio = kpis["refund_amount_ratio"]
    refund_ratio_text = f"{refund_ratio:.2%}" if refund_ratio is not None else "—"
    print(f"天猫报告已生成: {output}")
    if dashboard is not None:
        print(f"天猫看板已生成: {dashboard}")
    print(
        f"日期: {analysis['date_min']} ~ {analysis['date_max']}，"
        f"下单 {funnel['placed_count']:,}，支付 {funnel['paid_count']:,}，"
        f"成交 {funnel['completed_count']:,}"
    )
    print(
        f"实际支付净额: {kpis['paid_sum']:,.2f}，退款: {kpis['refund_sum']:,.2f}，"
        f"退款金额占比: {refund_ratio_text}"
    )
    if analysis["missing_created_dates"]:
        print("按创建日无订单日期: " + "、".join(analysis["missing_created_dates"]))
    if analysis["missing_payment_dates"]:
        print("按付款日无支付日期: " + "、".join(analysis["missing_payment_dates"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
