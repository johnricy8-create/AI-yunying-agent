"""天猫订单经营分析静态 HTML 看板。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

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


def _bar_width(value: Any, maximum: Any) -> float:
    if _missing(value) or _missing(maximum):
        return 0.0
    try:
        maximum_value = float(maximum)
        if maximum_value <= 0:
            return 0.0
        return round(min(100.0, max(0.0, float(value) / maximum_value * 100)), 1)
    except (TypeError, ValueError):
        return 0.0


def render_tmall_dashboard(
    analysis: dict[str, Any],
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    ensure_dir(path.parent)
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=("html",), default=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters.update(
        {
            "fmt_int": _fmt_int,
            "fmt_money": _fmt_money,
            "fmt_pct": _fmt_pct,
            "bar_width": _bar_width,
        }
    )

    context = dict(analysis)
    context["generated_at"] = format_datetime()
    context["max_daily_paid"] = max(
        (row.get("paid_amount") or 0 for row in analysis.get("daily", [])),
        default=0,
    )
    context["max_province_paid"] = max(
        (row.get("paid_amount") or 0 for row in analysis.get("top_provinces", [])),
        default=0,
    )

    try:
        template = environment.get_template("tmall_dashboard.html.j2")
        content = template.render(**context)
        write_text_atomic(path, content, encoding="utf-8")
    except Exception as exc:
        raise TmallError(f"天猫看板渲染失败: {exc}") from exc
    return path
