"""本地 MVP 启动入口。

默认行为：
1. 读取真实天猫订单 CSV；
2. 生成 Markdown 报告和 HTML 看板；
3. 生成统一入口页 reports/mvp/index.html；
4. 启动本地静态服务并打开浏览器。

用法：
    .venv\\Scripts\\python.exe run_mvp.py
    .venv\\Scripts\\python.exe run_mvp.py --no-serve
    .venv\\Scripts\\python.exe run_mvp.py --no-open
    .venv\\Scripts\\python.exe run_mvp.py --skip-tmall --no-serve
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ecom_ops.exceptions import EcomOpsError
from ecom_ops.mvp.landing import build_mvp_context, render_mvp_landing
from ecom_ops.tmall.analyzer import analyze_tmall
from ecom_ops.tmall.dashboard import render_tmall_dashboard
from ecom_ops.tmall.renderer import render_tmall_report

DEFAULT_DATA = Path(
    r"D:\天猫销售数据\Tmall_Tableau_Visualization_Project\data\tmall_order_report.csv"
)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def _serve(reports_dir: Path, port: int, no_open: bool) -> int:
    handler = partial(_QuietHandler, directory=str(reports_dir))
    last_error: OSError | None = None
    for candidate in range(port, port + 6):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), handler)
        except OSError as exc:
            last_error = exc
            continue

        url = f"http://127.0.0.1:{candidate}/mvp/index.html"
        print(f"本地 MVP 已启动: {url}")
        print("按 Ctrl+C 停止服务。")
        if not no_open:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n本地 MVP 已停止。")
        finally:
            server.server_close()
        return 0

    print(f"无法启动本地服务: {last_error}", file=sys.stderr)
    return 1


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="本地电商运营 Agent MVP")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="天猫订单 CSV 路径")
    parser.add_argument("--reports-dir", default="reports", help="报告根目录")
    parser.add_argument("--port", type=int, default=8765, help="本地服务端口")
    parser.add_argument("--no-serve", action="store_true", help="只生成页面，不启动本地服务")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--skip-tmall", action="store_true", help="不重新生成天猫报告/看板")
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir)
    analysis = None
    tmall_error = None

    if not args.skip_tmall:
        try:
            analysis = analyze_tmall(args.data)
            month = analysis["date_min"][:7]
            report_path = reports_dir / "tmall" / f"{month}_tmall_order_report.md"
            dashboard_path = reports_dir / "tmall" / f"{month}_tmall_dashboard.html"
            render_tmall_report(analysis, report_path)
            render_tmall_dashboard(analysis, dashboard_path)
            print(f"天猫报告已生成: {report_path}")
            print(f"天猫看板已生成: {dashboard_path}")
        except EcomOpsError as exc:
            tmall_error = str(exc)
            print(f"天猫模块生成失败: {exc}", file=sys.stderr)
        except Exception as exc:
            tmall_error = str(exc)
            print(f"天猫模块未预期错误: {exc}", file=sys.stderr)

    landing_path = reports_dir / "mvp/index.html"
    try:
        context = build_mvp_context(
            reports_dir,
            tmall_analysis=analysis,
            tmall_error=tmall_error,
        )
        render_mvp_landing(context, landing_path)
    except EcomOpsError as exc:
        print(f"MVP 入口页生成失败: {exc}", file=sys.stderr)
        return 1

    print(f"MVP 入口页已生成: {landing_path}")
    print(f"已生成模块: {context['available_count']} / {len(context['cards'])}")
    if args.no_serve:
        print("未启动本地服务；可用浏览器直接打开入口页，或运行 run_mvp.py。")
        return 0
    return _serve(reports_dir, args.port, args.no_open)


if __name__ == "__main__":
    raise SystemExit(main())
