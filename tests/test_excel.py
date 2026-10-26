from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from ecom_ops.data.loader import load_sales_data
from ecom_ops.data.mock import generate_mock_data
from ecom_ops.data.template import TEMPLATE_HEADERS, create_templates
from ecom_ops.exceptions import DataLoadError
from ecom_ops.graph.workflow import run_workflow


def _sample_frame(fields) -> pd.DataFrame:
    rows = [
        {
            "stat_date": "2026-10-24",
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
        },
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
            "pv": "120",
            "uv": "",
            "orders": "6",
            "sales_amount": "60",
            "refund_amount": "0",
        },
    ]
    labels = {name: fields.label(name) for name in fields.canonical_names}
    return pd.DataFrame(rows).rename(columns=labels)


def test_excel_with_chinese_headers_maps_fields(fields, tmp_path):
    frame = _sample_frame(fields)
    path = tmp_path / "sales.xlsx"
    frame.to_excel(path, index=False, engine="openpyxl")

    loaded = load_sales_data(path, fields)
    assert len(loaded) == 2
    assert "stat_date" in loaded.columns
    assert "product_id" in loaded.columns
    assert loaded.iloc[0]["product_id"] == "P1"


def test_excel_sheet_selection(fields, tmp_path):
    frame = _sample_frame(fields)
    path = tmp_path / "multi.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({"说明": ["请填写销售数据"]}).to_excel(
            writer, sheet_name="说明", index=False
        )
        frame.to_excel(writer, sheet_name="销售数据", index=False)

    with pytest.raises(DataLoadError):
        load_sales_data(path, fields)  # 默认第一个工作表，不是销售数据

    loaded = load_sales_data(path, fields, sheet_name="销售数据")
    assert len(loaded) == 2

    with pytest.raises(DataLoadError):
        load_sales_data(path, fields, sheet_name="不存在")


def test_xls_is_rejected(fields, tmp_path):
    path = tmp_path / "old.xls"
    path.write_bytes(b"not a real xls")
    with pytest.raises(DataLoadError):
        load_sales_data(path, fields)


def test_template_files_are_generated(fields, tmp_path):
    csv_path, xlsx_path = create_templates(tmp_path / "templates", fields)
    assert csv_path.exists()
    assert xlsx_path.exists()

    csv_frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    assert list(csv_frame.columns) == TEMPLATE_HEADERS

    excel = pd.ExcelFile(xlsx_path, engine="openpyxl")
    assert "销售数据" in excel.sheet_names
    assert "字段说明" in excel.sheet_names
    excel.close()
    data_sheet = pd.read_excel(
        xlsx_path,
        sheet_name="销售数据",
        dtype=str,
        keep_default_na=False,
        engine="openpyxl",
    )
    assert list(data_sheet.columns) == TEMPLATE_HEADERS


def test_excel_end_to_end_workflow(context, fields, tmp_path):
    df = generate_mock_data(
        products=30,
        days=14,
        seed=7,
        end_date=date(2026, 10, 25),
    )
    labels = {
        name: fields.label(name) for name in fields.canonical_names if name in df.columns
    }
    path = tmp_path / "sales.xlsx"
    df.rename(columns=labels).to_excel(path, index=False, engine="openpyxl")

    result = run_workflow(
        context,
        run_id="excel-e2e",
        source_path=str(path),
        stat_date="2026-10-25",
    )
    assert result["status"] == "completed"
    assert Path(result["report_path"]).exists()
    assert result["data_quality"]["summary"]["valid_rows"] > 0
