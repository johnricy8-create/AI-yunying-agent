"""静态 HTML 看板渲染。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ecom_ops.exceptions import EcomOpsError
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


def _fmt_pct(value: Any) -> str:
    if _missing(value):
        return "—"
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return "—"


def _fmt_change(value: Any) -> str:
    if _missing(value):
        return "—"
    try:
        return f"{float(value):+.1%}"
    except (TypeError, ValueError):
        return "—"


def _source_label(value: Any) -> str:
    return {"ai": "AI", "rule": "规则"}.get(str(value), str(value))


def _event_label(value: Any) -> str:
    return {
        "price_drop": "降价",
        "price_increase": "涨价",
        "out_of_stock": "缺货",
        "restocked": "补货",
        "new_listing": "新上架",
    }.get(str(value), str(value))


def render_dashboard(data: dict[str, Any], output_path: str | Path) -> Path:
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
            "fmt_num": _fmt_num,
            "fmt_pct": _fmt_pct,
            "fmt_change": _fmt_change,
            "source_label": _source_label,
            "event_label": _event_label,
        }
    )
    try:
        template = environment.get_template("dashboard.html.j2")
        content = template.render(**data)
        write_text_atomic(path, content, encoding="utf-8")
    except Exception as exc:
        raise EcomOpsError(f"看板渲染失败: {exc}") from exc
    return path
