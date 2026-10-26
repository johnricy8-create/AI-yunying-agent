"""商品目录/价格事件 Markdown 报告渲染。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from ecom_ops.exceptions import CatalogError
from ecom_ops.utils.dates import format_datetime
from ecom_ops.utils.files import ensure_dir, write_text_atomic

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

EVENT_LABELS = {
    "price_drop": "降价",
    "price_increase": "涨价",
    "out_of_stock": "缺货",
    "restocked": "补货",
    "new_listing": "新上架",
}


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
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "—"


def _fmt_change(value: Any) -> str:
    if _missing(value):
        return "—"
    try:
        return f"{float(value):+.1%}"
    except (TypeError, ValueError):
        return "—"


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def _event_label(value: Any) -> str:
    return EVENT_LABELS.get(str(value), str(value))


def render_catalog_report(analysis: dict[str, Any], output_dir: str | Path) -> Path:
    snapshot = analysis.get("snapshot_start") or "catalog"
    snapshot_end = analysis.get("snapshot_end") or ""
    snapshot_range = (
        f"{snapshot} ~ {snapshot_end}"
        if snapshot_end and snapshot_end != snapshot
        else snapshot
    )
    output = ensure_dir(Path(output_dir))
    report_path = output / f"{snapshot}_catalog_report.md"

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
            "fmt_pct": _fmt_pct,
            "fmt_change": _fmt_change,
            "md": _md,
            "event_label": _event_label,
        }
    )

    try:
        template = environment.get_template("catalog_report.md.j2")
        content = template.render(
            report_time=format_datetime(),
            report_path=str(report_path),
            snapshot_range=snapshot_range,
            **analysis,
        )
        write_text_atomic(report_path, content, encoding="utf-8")
    except Exception as exc:
        raise CatalogError(f"目录报告渲染失败: {exc}") from exc
    return report_path
