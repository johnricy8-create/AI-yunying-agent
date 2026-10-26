"""天猫订单经营分析 Markdown 报告。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from ecom_ops.exceptions import TmallError
from ecom_ops.utils.dates import format_datetime
from ecom_ops.utils.files import ensure_dir, write_text_atomic

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and value != value:
        return True
    return False


def _fmt_int(value: Any) -> str:
    if _missing(value):
        return "—"
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_num(value: Any, digits: int = 2) -> str:
    if _missing(value):
        return "—"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_money(value: Any) -> str:
    if _missing(value):
        return "—"
    try:
        return f"¥{float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(value: Any) -> str:
    if _missing(value):
        return "—"
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return "—"


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def render_tmall_report(analysis: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    ensure_dir(path.parent)
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters.update(
        {
            "fmt_int": _fmt_int,
            "fmt_num": _fmt_num,
            "fmt_money": _fmt_money,
            "fmt_pct": _fmt_pct,
            "md": _md,
        }
    )
    try:
        template = environment.get_template("tmall_report.md.j2")
        content = template.render(report_time=format_datetime(), **analysis)
        write_text_atomic(path, content, encoding="utf-8")
    except Exception as exc:
        raise TmallError(f"天猫报告渲染失败: {exc}") from exc
    return path
