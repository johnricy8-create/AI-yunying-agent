"""一键演示：目录报告 + 目录/模拟销售日报。

默认使用你提供的 Shopify 目录样本；不需要记住多条命令。

用法：
    .venv\\Scripts\\python.exe tools\\run_demo.py
    .venv\\Scripts\\python.exe tools\\run_demo.py --with-ai
    .venv\\Scripts\\python.exe tools\\run_demo.py --rebuild
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = Path(
    r"D:\olist电商数据\shopify-products-dataset-sample\data\catalog_sample_500.csv"
)
DEFAULT_CHANGES = Path(
    r"D:\olist电商数据\shopify-products-dataset-sample\data\price_changes_sample.csv"
)
DEFAULT_DEMO = ROOT / "data" / "derived" / "shopify_catalog_sales_demo.csv"


def _run(args: list[str]) -> None:
    print()
    print("$ " + " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="一键演示：目录监控 + 模拟销售日报")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="目录 CSV 路径")
    parser.add_argument("--changes", default=str(DEFAULT_CHANGES), help="价格事件 CSV 路径")
    parser.add_argument("--days", type=int, default=60, help="模拟销售天数")
    parser.add_argument("--end-date", default="2026-07-31", help="模拟销售结束日期")
    parser.add_argument("--seed", type=int, default=42, help="模拟销售随机种子")
    parser.add_argument("--rebuild", action="store_true", help="强制重新生成模拟销售数据")
    parser.add_argument("--with-ai", action="store_true", help="尝试调用 GLM 生成 AI 分析")
    args = parser.parse_args()

    catalog = Path(args.catalog)
    changes = Path(args.changes)
    if not catalog.exists():
        print(f"找不到目录文件: {catalog}", file=sys.stderr)
        print("请用 --catalog 指定 catalog_sample_500.csv 的路径。", file=sys.stderr)
        return 1

    try:
        if args.rebuild or not DEFAULT_DEMO.exists():
            _run(
                [
                    sys.executable,
                    "tools/build_shopify_sales_demo.py",
                    "--catalog",
                    str(catalog),
                    "--output",
                    str(DEFAULT_DEMO),
                    "--days",
                    str(args.days),
                    "--end-date",
                    args.end_date,
                    "--seed",
                    str(args.seed),
                ]
            )
        else:
            print(f"复用已有演示数据: {DEFAULT_DEMO}（加 --rebuild 可重建）")

        catalog_args = [
            sys.executable,
            "tools/catalog_report.py",
            "--catalog",
            str(catalog),
            "--output-dir",
            "reports/catalog",
        ]
        if changes.exists():
            catalog_args.extend(["--changes", str(changes)])
        else:
            print(f"提示：找不到价格事件文件 {changes}，目录报告将只分析快照。")
        _run(catalog_args)

        daily_args = [
            sys.executable,
            "run.py",
            "--data",
            str(DEFAULT_DEMO),
            "--date",
            args.end_date,
            "--report-dir",
            "reports/shopify_demo",
            "--data-note",
            "演示数据：订单、PV/UV、销售额、退款、成本、库存为模拟值，不可用于真实业务校准。",
        ]
        if args.with_ai:
            daily_args.append("--refresh-ai")
        else:
            daily_args.append("--no-ai")
        _run(daily_args)

        _run(
            [
                sys.executable,
                "tools/build_dashboard.py",
                "--output",
                "reports/dashboard/index.html",
            ]
        )
        _run(
            [
                sys.executable,
                "tools/export_history_excel.py",
                "--days",
                "30",
            ]
        )
    except subprocess.CalledProcessError as exc:
        print(f"演示步骤失败，退出码 {exc.returncode}", file=sys.stderr)
        return exc.returncode or 1
    except Exception as exc:
        print(f"演示失败: {exc}", file=sys.stderr)
        return 1

    print()
    print("=" * 64)
    print("一键演示完成")
    print("目录报告: reports/catalog/*_catalog_report.md")
    print(f"演示日报: reports/shopify_demo/{args.end_date}_daily_report.md")
    print("可视化看板: reports/dashboard/index.html")
    print("Excel 导出: reports/exports/ops_history_*.xlsx")
    print("说明: 销售/流量/成本/库存为模拟字段，仅用于演示，不可用于真实业务校准。")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
