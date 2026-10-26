"""本地 MVP 统一入口页。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ecom_ops.exceptions import EcomOpsError
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


def _latest(root: Path, patterns: list[str]) -> Path | None:
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(path for path in root.glob(pattern) if path.is_file())
    if not paths:
        return None
    return max(paths, key=lambda path: path.stat().st_mtime)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _card(
    root: Path,
    *,
    title: str,
    description: str,
    path: Path | None,
    tag: str,
    kind: str = "report",
    hint: str = "",
) -> dict[str, Any]:
    available = path is not None and path.exists()
    return {
        "title": title,
        "description": description,
        "path": _relative(root, path) if available and path is not None else None,
        "tag": tag,
        "kind": kind,
        "available": available,
        "hint": hint,
    }


def build_mvp_context(
    reports_root: str | Path,
    tmall_analysis: dict[str, Any] | None = None,
    tmall_error: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = Path(reports_root)
    root.mkdir(parents=True, exist_ok=True)

    tmall_html = _latest(root, ["tmall/*_tmall_dashboard.html"])
    tmall_md = _latest(root, ["tmall/*_tmall_order_report.md"])
    dashboard = root / "dashboard/index.html"
    daily = _latest(root, ["*_daily_report.md"])
    catalog = _latest(root, ["catalog/*_catalog_report.md"])
    history = root / "history_review/ops_history_report.md"
    export = _latest(root, ["exports/*.xlsx"])

    cards: list[dict[str, Any]] = [
        _card(
            root,
            title="天猫订单经营看板",
            description="真实订单级 KPI、转化漏斗、每日趋势、省份/时段和数据质量。",
            path=tmall_html,
            tag="真实数据 · HTML",
            kind="primary",
            hint="先运行 tools/tmall_report.py 生成天猫看板。",
        ),
        _card(
            root,
            title="天猫 Markdown 报告",
            description="与看板同口径的分析报告，适合复制到周报、复盘或归档。",
            path=tmall_md,
            tag="真实数据 · Markdown",
            hint="先运行 tools/tmall_report.py 生成天猫报告。",
        ),
        _card(
            root,
            title="商品级运营看板",
            description="每日 PV/订单/异常/建议看板；当前通常是演示数据或历史数据。",
            path=dashboard,
            tag="商品级 · HTML",
            hint="先运行 run.py，或使用 tools/run_demo.py 生成演示数据。",
        ),
        _card(
            root,
            title="最新商品日报",
            description="商品级每日分析报告，包含异常、AI/规则建议和数据限制。",
            path=daily,
            tag="商品级 · Markdown",
            hint="先运行 run.py --data <销售数据>。",
        ),
        _card(
            root,
            title="历史复盘报告",
            description="重复异常、商品历史对比、建议后续变化观察。",
            path=history,
            tag="历史 · Markdown",
            hint="先运行 tools/history_report.py。",
        ),
        _card(
            root,
            title="目录/价格监控",
            description="商品目录、价格变动、缺货/补货/新上架事件。",
            path=catalog,
            tag="目录 · Markdown",
            hint="先运行 tools/catalog_report.py。",
        ),
        _card(
            root,
            title="Excel 导出",
            description="历史指标、异常明细、建议清单和建议追踪，可筛选/批注。",
            path=export,
            tag="下载 · xlsx",
            hint="先运行 tools/export_history_excel.py。",
        ),
    ]

    tmall_summary: dict[str, Any] | None = None
    if tmall_analysis:
        funnel = tmall_analysis.get("funnel", {})
        kpis = tmall_analysis.get("kpis", {})
        tmall_summary = {
            "date_min": tmall_analysis.get("date_min"),
            "date_max": tmall_analysis.get("date_max"),
            "placed": funnel.get("placed_count"),
            "paid": funnel.get("paid_count"),
            "completed": funnel.get("completed_count"),
            "paid_rate": funnel.get("placed_to_paid"),
            "completed_rate": funnel.get("placed_to_completed"),
            "paid_sum": kpis.get("paid_sum"),
            "refund_sum": kpis.get("refund_sum"),
            "refund_ratio": kpis.get("refund_amount_ratio"),
        }

    commands = [
        ".venv\\Scripts\\python.exe run_mvp.py",
        ".venv\\Scripts\\python.exe run_mvp.py --no-serve",
        ".venv\\Scripts\\python.exe tools\\tmall_report.py --no-html",
        ".venv\\Scripts\\python.exe run.py --no-ai",
    ]

    return {
        "generated_at": generated_at or format_datetime(),
        "reports_root": str(root.resolve()),
        "cards": cards,
        "available_count": sum(1 for card in cards if card["available"]),
        "tmall": tmall_summary,
        "tmall_error": tmall_error,
        "tmall_paths": {
            "html": _relative(root, tmall_html) if tmall_html else None,
            "md": _relative(root, tmall_md) if tmall_md else None,
        },
        "source": (tmall_analysis or {}).get("source"),
        "commands": commands,
    }


def render_mvp_landing(context: dict[str, Any], output_path: str | Path) -> Path:
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
        }
    )
    try:
        template = environment.get_template("mvp_index.html.j2")
        content = template.render(**context)
        write_text_atomic(path, content, encoding="utf-8")
    except Exception as exc:
        raise EcomOpsError(f"MVP 入口页渲染失败: {exc}") from exc
    return path
