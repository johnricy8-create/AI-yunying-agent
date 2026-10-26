"""历史复盘报告渲染。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from ecom_ops.exceptions import HistoryError
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


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def _truncate(value: Any, length: int = 60) -> str:
    text = str(value or "").strip()
    return text if len(text) <= length else text[:length] + "…"


def _source_label(value: Any) -> str:
    return {"ai": "AI 建议", "rule": "规则建议"}.get(str(value), str(value))


def render_history_report(analysis: dict[str, Any], output_path: str | Path) -> Path:
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
            "fmt_pct": _fmt_pct,
            "fmt_change": _fmt_change,
            "md": _md,
            "truncate_text": _truncate,
            "source_label": _source_label,
        }
    )
    try:
        template = environment.get_template("history_report.md.j2")
        content = template.render(
            report_time=format_datetime(),
            report_path=str(path),
            **analysis,
        )
        write_text_atomic(path, content, encoding="utf-8")
    except Exception as exc:
        raise HistoryError(f"历史复盘报告渲染失败: {exc}") from exc
    return path
