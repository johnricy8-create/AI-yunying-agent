"""生成 Shopify 商品目录/价格监控报告。

用法：
    .venv\\Scripts\\python.exe tools\\catalog_report.py ^
      --catalog "D:\\olist电商数据\\shopify-products-dataset-sample\\data\\catalog_sample_500.csv" ^
      --changes "D:\\olist电商数据\\shopify-products-dataset-sample\\data\\price_changes_sample.csv"

说明：这是与每日销售日报并列的目录监控分支，不计算订单、销售额、PV/UV，也不调用大模型。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.catalog.analyzer import analyze_catalog
from ecom_ops.catalog.renderer import render_catalog_report
from ecom_ops.exceptions import CatalogError


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Shopify 商品目录与价格监控报告")
    parser.add_argument("--catalog", required=True, help="catalog CSV 路径")
    parser.add_argument("--changes", default=None, help="price_changes CSV 路径（可选）")
    parser.add_argument(
        "--output-dir",
        default="reports/catalog",
        help="报告输出目录，默认 reports/catalog",
    )
    parser.add_argument("--top", type=int, default=10, help="每类展示 Top N，默认 10")
    args = parser.parse_args()

    try:
        analysis = analyze_catalog(args.catalog, args.changes, top=args.top)
        report_path = render_catalog_report(analysis, args.output_dir)
    except CatalogError as exc:
        print(f"生成目录报告失败: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"未预期错误: {exc}", file=sys.stderr)
        return 1

    print(f"目录报告已生成: {report_path}")
    print(f"目录变体: {analysis['catalog_rows']:,}，店铺: {analysis['stores']:,}，商品: {analysis['products']:,}")
    print(f"可用/不可用: {analysis['available_true']:,} / {analysis['available_false']:,}")
    if analysis["changes"]["available"]:
        print(
            f"价格事件: {analysis['changes']['rows']:,}，"
            f"事件类型: {analysis['changes']['event_counts']}"
        )
    print("注意: 本报告只分析目录/价格/可用性，不计算订单、销售额、PV/UV。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
