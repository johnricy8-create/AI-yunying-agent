"""生成本地静态运营看板。

用法：
    .venv\\Scripts\\python.exe tools\\build_dashboard.py
    .venv\\Scripts\\python.exe tools\\build_dashboard.py --days 30
    .venv\\Scripts\\python.exe tools\\build_dashboard.py --no-catalog
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.config import load_settings
from ecom_ops.dashboard.builder import build_dashboard_data
from ecom_ops.dashboard.renderer import render_dashboard
from ecom_ops.exceptions import EcomOpsError

DEFAULT_CATALOG = Path(
    r"D:\olist电商数据\shopify-products-dataset-sample\data\catalog_sample_500.csv"
)
DEFAULT_CHANGES = Path(
    r"D:\olist电商数据\shopify-products-dataset-sample\data\price_changes_sample.csv"
)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="生成本地静态运营看板")
    parser.add_argument("--db", default=None, help="历史库路径")
    parser.add_argument("--days", type=int, default=14, help="趋势天数")
    parser.add_argument(
        "--output",
        default="reports/dashboard/index.html",
        help="HTML 输出路径",
    )
    parser.add_argument("--catalog", default=None, help="目录 CSV 路径")
    parser.add_argument("--changes", default=None, help="价格事件 CSV 路径")
    parser.add_argument("--no-catalog", action="store_true", help="不加载目录数据")
    parser.add_argument("--config", default=None, help="settings.yaml 路径")
    args = parser.parse_args()

    try:
        settings = load_settings(args.config)
        db_path = Path(args.db) if args.db else settings.history.db_path
        if not db_path.exists():
            print(
                f"历史库不存在: {db_path}\n请先运行 run.py 或 scheduler.py 生成日报。",
                file=sys.stderr,
            )
            return 1

        catalog_path = None
        changes_path = None
        if not args.no_catalog:
            catalog_path = Path(args.catalog) if args.catalog else DEFAULT_CATALOG
            changes_path = Path(args.changes) if args.changes else DEFAULT_CHANGES
            if not catalog_path.exists():
                catalog_path = None
            if changes_path and not changes_path.exists():
                changes_path = None

        data = build_dashboard_data(
            settings,
            db_path=db_path,
            days=args.days,
            catalog_path=catalog_path,
            changes_path=changes_path,
        )
        output = render_dashboard(data, args.output)
    except EcomOpsError as exc:
        print(f"生成看板失败: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"未预期错误: {exc}", file=sys.stderr)
        return 1

    print(f"看板已生成: {output}")
    print(
        f"历史天数: {data['overview']['runs']}，"
        f"最新异常: {len(data['anomalies'])}，"
        f"重复异常商品: {len(data['recurring'])}"
    )
    if data["catalog"]:
        print(
            f"目录变体: {data['catalog']['catalog_rows']}，"
            f"价格事件: {data['catalog']['changes']['rows']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
