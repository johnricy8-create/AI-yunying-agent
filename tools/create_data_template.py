"""生成真实数据导入模板（CSV + Excel）。

用法：
    .venv\\Scripts\\python.exe tools\\create_data_template.py
    .venv\\Scripts\\python.exe tools\\create_data_template.py --output-dir data/templates
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.config import load_settings
from ecom_ops.data.template import TEMPLATE_HEADERS, create_templates


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="生成销售数据导入模板")
    parser.add_argument(
        "--output-dir",
        default="data/templates",
        help="模板输出目录，默认 data/templates",
    )
    args = parser.parse_args()

    settings = load_settings()
    csv_path, xlsx_path = create_templates(args.output_dir, settings.fields)
    print("模板已生成：")
    print(f"  CSV : {csv_path}")
    print(f"  XLSX: {xlsx_path}（含“销售数据”和“字段说明”两个工作表）")
    print("表头：")
    print("  " + " | ".join(TEMPLATE_HEADERS))
    print("提示：模板表头为中文别名，程序会通过 config/fields.yaml 自动映射。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
