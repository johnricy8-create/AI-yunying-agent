from __future__ import annotations

import pandas as pd
import pytest

from ecom_ops.catalog.analyzer import analyze_catalog
from ecom_ops.catalog.renderer import render_catalog_report
from ecom_ops.exceptions import CatalogError


CATALOG_ROWS = [
    {
        "store_domain": "store-a.com",
        "store_name": "Store A",
        "product_id": "p1",
        "title": "T-Shirt",
        "product_type": "T-Shirt",
        "tags": "apparel",
        "variant_id": "v1",
        "sku": "SKU-1",
        "variant_title": "M",
        "price": "25.00",
        "compare_at_price": "35.00",
        "available": "True",
        "image_count": "2",
        "fetched_at": "2026-08-01T00:00:00+00:00",
        "niche": "apparel",
    },
    {
        "store_domain": "store-a.com",
        "store_name": "Store A",
        "product_id": "p2",
        "title": "Zero Price Item",
        "product_type": "",
        "tags": "",
        "variant_id": "v2",
        "sku": "",
        "variant_title": "Default Title",
        "price": "0",
        "compare_at_price": "",
        "available": "False",
        "image_count": "0",
        "fetched_at": "2026-08-01T00:00:00+00:00",
        "niche": "other",
    },
    {
        "store_domain": "store-b.com",
        "store_name": "",
        "product_id": "p3",
        "title": "Home Lamp",
        "product_type": "",
        "tags": "home",
        "variant_id": "v3",
        "sku": "SKU-3",
        "variant_title": "Default Title",
        "price": "100.00",
        "compare_at_price": "",
        "available": "True",
        "image_count": "1",
        "fetched_at": "2026-08-01T00:00:00+00:00",
        "niche": "home_garden",
    },
]

CHANGE_ROWS = [
    {
        "store": "store-a.com",
        "product_id": "p1",
        "variant_id": "v1",
        "date": "2026-08-03",
        "change_type": "price_drop",
        "old_price": "20",
        "new_price": "10",
        "old_available": "True",
        "new_available": "True",
    },
    {
        "store": "store-a.com",
        "product_id": "p1",
        "variant_id": "v1",
        "date": "2026-08-03",
        "change_type": "out_of_stock",
        "old_price": "",
        "new_price": "10",
        "old_available": "True",
        "new_available": "False",
    },
    {
        "store": "store-b.com",
        "product_id": "p3",
        "variant_id": "v3",
        "date": "2026-08-03",
        "change_type": "price_increase",
        "old_price": "100",
        "new_price": "150",
        "old_available": "True",
        "new_available": "True",
    },
    {
        "store": "store-b.com",
        "product_id": "p3",
        "variant_id": "v3",
        "date": "2026-08-03",
        "change_type": "new_listing",
        "old_price": "",
        "new_price": "150",
        "old_available": "",
        "new_available": "True",
    },
]


def _write_inputs(tmp_path):
    catalog_path = tmp_path / "catalog.csv"
    changes_path = tmp_path / "changes.csv"
    pd.DataFrame(CATALOG_ROWS).to_csv(catalog_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(CHANGE_ROWS).to_csv(changes_path, index=False, encoding="utf-8-sig")
    return catalog_path, changes_path


def test_catalog_analysis_and_report(tmp_path):
    catalog_path, changes_path = _write_inputs(tmp_path)
    analysis = analyze_catalog(catalog_path, changes_path, top=5)

    assert analysis["catalog_rows"] == 3
    assert analysis["stores"] == 2
    assert analysis["products"] == 3
    assert analysis["variants"] == 3
    assert analysis["available_true"] == 2
    assert analysis["available_false"] == 1
    assert analysis["zero_price_rows"]
    assert analysis["duplicate_variants"] == 0
    assert analysis["missing_counts"]["product_type"] == 2
    assert analysis["missing_counts"]["tags"] == 1
    assert analysis["missing_counts"]["sku"] == 1

    changes = analysis["changes"]
    assert changes["available"] is True
    assert changes["rows"] == 4
    assert changes["event_counts"]["price_drop"] == 1
    assert changes["event_counts"]["price_increase"] == 1
    assert changes["event_counts"]["out_of_stock"] == 1
    assert changes["event_counts"]["new_listing"] == 1
    assert changes["store_overlap"] == 2
    assert changes["variant_overlap"] == 2
    assert changes["large_change_count"] == 2
    assert len(changes["top_price_changes"]) == 2

    report_path = render_catalog_report(analysis, tmp_path / "reports")
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "Shopify 商品目录与价格监控报告" in content
    assert "零价格变体" in content
    assert "价格变动" in content
    assert "缺货" in content
    assert "数据限制" in content


def test_catalog_missing_required_columns_raises(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame([{"store_domain": "x"}]).to_csv(
        path, index=False, encoding="utf-8-sig"
    )
    with pytest.raises(CatalogError):
        analyze_catalog(path)
