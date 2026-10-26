from __future__ import annotations

import pandas as pd
import pytest

from ecom_ops.exceptions import TmallError
from ecom_ops.tmall.analyzer import analyze_tmall
from ecom_ops.tmall.dashboard import render_tmall_dashboard
from ecom_ops.tmall.loader import load_tmall_orders
from ecom_ops.tmall.renderer import render_tmall_report
from ecom_ops.utils.files import read_text


def _write_tmall_csv(path, rows):
    columns = [
        "订单编号",
        "总金额",
        "买家实际支付金额",
        "收货地址 ",
        "订单创建时间",
        "订单付款时间 ",
        "退款金额",
    ]
    df = pd.DataFrame(rows, columns=columns)
    df.to_csv(path, index=False, encoding="gbk")


def _base_rows():
    return [
        ["1001", "100", "100", "上海", "2020/2/1 10:00", "2020/2/1 10:05", "0"],
        ["1002", "50", "0", "北京", "2020/2/1 11:00", "", "0"],
        ["1003", "80", "0", "江苏", "2020/2/3 09:00", "2020/2/3 09:05", "80"],
        ["1004", "120", "100", "浙江", "2020/2/3 12:00", "2020/2/3 12:05", "20"],
        ["1005", "30", "30", "上海", "2020/2/3 13:00", "2020/2/3 13:05", "0"],
        ["1006", "-10", "0", "广东", "2020/2/3 14:00", "", "0"],
    ]


def test_tmall_load_analyze_and_render(tmp_path):
    data_path = tmp_path / "tmall.csv"
    _write_tmall_csv(data_path, _base_rows())

    loaded = load_tmall_orders(data_path)
    assert loaded.summary["encoding"] == "gbk"
    assert loaded.summary["total_rows"] == 6
    assert loaded.summary["valid_rows"] == 5
    assert loaded.summary["invalid_rows"] == 1
    assert loaded.summary["error_counts"]["negative_total_amount"] == 1
    assert list(loaded.valid_df.columns) == [
        "order_id",
        "total_amount",
        "paid_amount",
        "province",
        "created_at",
        "paid_at",
        "refund_amount",
    ]

    analysis = analyze_tmall(data_path)
    funnel = analysis["funnel"]
    assert funnel["placed_count"] == 5
    assert funnel["paid_count"] == 4
    assert funnel["completed_count"] == 3
    assert funnel["full_price_count"] == 2
    assert funnel["zero_paid_count"] == 1
    assert funnel["refund_order_count"] == 2
    assert funnel["placed_to_paid"] == pytest.approx(0.8)
    assert funnel["placed_to_completed"] == pytest.approx(0.6)

    kpis = analysis["kpis"]
    assert kpis["paid_sum"] == 230.0
    assert kpis["original_paid_sum"] == 330.0
    assert kpis["refund_sum"] == 100.0
    assert kpis["completed_aov"] == pytest.approx(76.67)
    assert kpis["refund_amount_ratio"] == pytest.approx(100 / 330)
    assert kpis["refund_order_rate"] == pytest.approx(0.5)

    assert analysis["missing_created_dates"] == ["2020-02-02"]
    assert analysis["missing_payment_dates"] == ["2020-02-02"]
    assert analysis["daily"][1]["missing"] is True
    assert analysis["funnel_daily"][1]["missing"] is True
    assert analysis["quality"]["paid_rows"] == 4
    assert analysis["quality"]["zero_paid_rows"] == 1
    assert analysis["quality"]["refund_rows"] == 2
    assert analysis["quality"]["paid_identity_rate"] == 1.0

    report_path = render_tmall_report(analysis, tmp_path / "report.md")
    content = read_text(report_path)
    assert "天猫订单经营分析" in content
    assert "零实付/全额退款" in content
    assert "2020-02-02（无支付/缺失）" in content
    assert "2020-02-02（无订单/缺失）" in content
    assert "上海" in content
    assert "2020-02-01" in content

    dashboard_path = render_tmall_dashboard(analysis, tmp_path / "dashboard.html")
    html = read_text(dashboard_path)
    assert "天猫订单经营分析" in html
    assert "转化漏斗" in html
    assert "每日成交趋势" in html
    assert "tianchi.aliyun.com/dataset/111551" in html
    assert "CC BY-SA-NC 4.0" in html
    assert "https://cdn" not in html


def test_tmall_duplicate_order_keeps_last(tmp_path):
    data_path = tmp_path / "duplicate.csv"
    _write_tmall_csv(
        data_path,
        [
            ["2001", "100", "100", "上海", "2020/2/1 10:00", "2020/2/1 10:05", "0"],
            ["2001", "200", "200", "北京", "2020/2/3 10:00", "2020/2/3 10:05", "0"],
        ],
    )

    loaded = load_tmall_orders(data_path)
    assert loaded.summary["valid_rows"] == 1
    assert loaded.summary["invalid_rows"] == 1
    assert loaded.summary["duplicate_order_ids"] == 1
    assert loaded.valid_df.iloc[0]["order_id"] == "2001"
    assert loaded.valid_df.iloc[0]["province"] == "北京"
    assert loaded.valid_df.iloc[0]["paid_amount"] == 200.0


def test_tmall_missing_columns(tmp_path):
    data_path = tmp_path / "missing.csv"
    pd.DataFrame([{"订单编号": "1"}]).to_csv(
        data_path, index=False, encoding="gbk"
    )

    with pytest.raises(TmallError, match="缺少字段"):
        load_tmall_orders(data_path)
