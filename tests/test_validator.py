from __future__ import annotations

from datetime import date

import pandas as pd

from ecom_ops.data.validator import validate_sales_data


CURRENT_DATE = date(2026, 10, 26)


def _row(fields, row_number: int, **overrides) -> dict:
    base = {name: "" for name in fields.canonical_names}
    base.update(
        {
            "stat_date": "2026-10-25",
            "product_id": "P1",
            "product_name": "测试商品",
            "product_desc": "测试简介",
            "shop": "测试店",
            "platform": "淘宝",
            "category": "Excel模板",
            "price": "10",
            "cost": "5",
            "stock": "10",
            "pv": "100",
            "uv": "",
            "orders": "5",
            "sales_amount": "50",
            "refund_amount": "0",
            "_row_number": row_number,
        }
    )
    base.update(overrides)
    return base


def _validate(fields, rows):
    return validate_sales_data(pd.DataFrame(rows), fields, current_date=CURRENT_DATE)


def test_valid_row_passes(fields):
    result = _validate(fields, [_row(fields, 2)])
    assert result.summary["total_rows"] == 1
    assert result.summary["valid_rows"] == 1
    assert result.summary["invalid_rows"] == 0
    assert result.valid_df.iloc[0]["product_id"] == "P1"
    assert result.valid_df.iloc[0]["stat_date"] == "2026-10-25"


def test_missing_required_field_is_invalid(fields):
    result = _validate(fields, [_row(fields, 2, product_name="")])
    assert result.summary["valid_rows"] == 0
    assert result.summary["error_counts"].get("missing_required") == 1


def test_negative_stock_is_invalid(fields):
    result = _validate(fields, [_row(fields, 2, stock="-5")])
    assert result.summary["valid_rows"] == 0
    assert result.summary["error_counts"].get("negative_value") == 1


def test_orders_greater_than_pv_is_invalid(fields):
    result = _validate(fields, [_row(fields, 2, pv="10", orders="20")])
    assert result.summary["valid_rows"] == 0
    assert result.summary["error_counts"].get("orders_gt_pv") == 1


def test_refund_greater_than_sales_is_invalid(fields):
    result = _validate(fields, [_row(fields, 2, sales_amount="10", refund_amount="20")])
    assert result.summary["valid_rows"] == 0
    assert result.summary["error_counts"].get("refund_gt_sales") == 1


def test_duplicate_keeps_last_row(fields):
    rows = [
        _row(fields, 2, pv="100", orders="5"),
        _row(fields, 3, pv="120", orders="6"),
    ]
    result = _validate(fields, rows)
    assert result.summary["valid_rows"] == 1
    assert result.summary["invalid_rows"] == 1
    assert result.summary["error_counts"].get("duplicate_key") == 1
    assert int(result.valid_df.iloc[0]["pv"]) == 120


def test_missing_description_is_warning_but_kept(fields):
    result = _validate(fields, [_row(fields, 2, product_desc="")])
    assert result.summary["valid_rows"] == 1
    assert result.summary["warning_counts"].get("missing_optional") == 1
    assert result.valid_df.iloc[0]["product_desc"] == ""


def test_missing_optional_dimension_fills_default(fields):
    result = _validate(fields, [_row(fields, 2, shop="")])
    assert result.summary["valid_rows"] == 1
    assert result.valid_df.iloc[0]["shop"] == "未填写"
    assert result.summary["warning_counts"].get("missing_optional") == 1


def test_future_date_is_invalid(fields):
    result = _validate(fields, [_row(fields, 2, stat_date="2099-01-01")])
    assert result.summary["valid_rows"] == 0
    assert result.summary["error_counts"].get("future_date") == 1


def test_zero_price_is_invalid(fields):
    result = _validate(fields, [_row(fields, 2, price="0")])
    assert result.summary["valid_rows"] == 0
    assert result.summary["error_counts"].get("non_positive_price") == 1


def test_cost_above_price_is_warning_but_kept(fields):
    result = _validate(fields, [_row(fields, 2, cost="20", price="10")])
    assert result.summary["valid_rows"] == 1
    assert result.summary["warning_counts"].get("cost_gt_price") == 1


def test_all_invalid_produces_empty_valid_frame(fields):
    rows = [
        _row(fields, 2, product_name=""),
        _row(fields, 3, stock="-1"),
    ]
    result = _validate(fields, rows)
    assert result.summary["valid_rows"] == 0
    assert result.summary["invalid_rows"] == 2
    assert len(result.valid_df) == 0
