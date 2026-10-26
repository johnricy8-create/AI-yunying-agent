from __future__ import annotations

from ecom_ops.mvp.landing import build_mvp_context, render_mvp_landing
from ecom_ops.utils.files import read_text


def _analysis():
    return {
        "date_min": "2020-02-01",
        "date_max": "2020-02-29",
        "source": {
            "name": "天猫订单成交数据",
            "url": "https://tianchi.aliyun.com/dataset/111551",
            "license": "CC BY-SA-NC 4.0",
            "note": "测试数据来源说明。",
        },
        "funnel": {
            "placed_count": 100,
            "paid_count": 80,
            "completed_count": 60,
            "placed_to_paid": 0.8,
            "placed_to_completed": 0.6,
        },
        "kpis": {
            "paid_sum": 12345.67,
            "refund_sum": 2345.67,
            "refund_amount_ratio": 0.16,
        },
    }


def test_mvp_landing_discovers_reports_and_renders(tmp_path):
    reports = tmp_path / "reports"
    (reports / "tmall").mkdir(parents=True)
    (reports / "tmall/2020-02_tmall_dashboard.html").write_text(
        "<html>tmall</html>", encoding="utf-8"
    )
    (reports / "tmall/2020-02_tmall_order_report.md").write_text(
        "# tmall", encoding="utf-8"
    )
    (reports / "dashboard").mkdir()
    (reports / "dashboard/index.html").write_text("<html>dash</html>", encoding="utf-8")
    (reports / "2020-02-29_daily_report.md").write_text("# daily", encoding="utf-8")

    context = build_mvp_context(reports, tmall_analysis=_analysis())
    assert context["available_count"] >= 4
    assert context["tmall"]["placed"] == 100
    assert context["tmall"]["paid"] == 80
    assert context["tmall_paths"]["html"] == "tmall/2020-02_tmall_dashboard.html"

    output = render_mvp_landing(context, reports / "mvp/index.html")
    html = read_text(output)
    assert "电商运营 Agent" in html
    assert "打开天猫看板" in html
    assert "../tmall/2020-02_tmall_dashboard.html" in html
    assert "商品级运营看板" in html
    assert "tianchi.aliyun.com/dataset/111551" in html
    assert "CC BY-SA-NC 4.0" in html
    assert "https://cdn" not in html


def test_mvp_landing_without_tmall_still_renders(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    context = build_mvp_context(reports, tmall_error="文件不存在")
    output = render_mvp_landing(context, reports / "mvp/index.html")
    html = read_text(output)
    assert "天猫数据未生成" in html
    assert "文件不存在" in html
    assert "天猫模块提示" in html
