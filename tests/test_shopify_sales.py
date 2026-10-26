from __future__ import annotations

import pandas as pd
import pytest

from ecom_ops.demo.shopify_sales import build_shopify_sales_demo
from ecom_ops.exceptions import CatalogError


def _catalog() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "store_domain": "store-a.com",
                "product_id": "p1",
                "variant_id": "v1",
                "title": "T-Shirt",
                "variant_title": "M",
                "product_type": "T-Shirt",
                "vendor": "BrandA",
                "tags": "apparel",
                "niche": "apparel",
                "price": "25",
                "available": "True",
            },
            {
                "store_domain": "store-a.com",
                "product_id": "p2",
                "variant_id": "v2",
                "title": "Zero Price Item",
                "variant_title": "Default Title",
                "product_type": "",
                "vendor": "",
                "tags": "",
                "niche": "other",
                "price": "0",
                "available": "False",
            },
            {
                "store_domain": "store-b.com",
                "product_id": "p3",
                "variant_id": "v3",
                "title": "Home Lamp",
                "variant_title": "",
                "product_type": "Lamp",
                "vendor": "BrandB",
                "tags": "home",
                "niche": "home_garden",
                "price": "100",
                "available": "True",
            },
        ]
    )


def test_shopify_sales_demo_is_valid_and_deterministic():
    first = build_shopify_sales_demo(_catalog(), days=8, end_date="2026-07-31", seed=7)
    second = build_shopify_sales_demo(_catalog(), days=8, end_date="2026-07-31", seed=7)

    assert len(first) == 24
    assert first.equals(second)
    assert first["stat_date"].min() == "2026-07-24"
    assert first["stat_date"].max() == "2026-07-31"
    assert first["product_id"].nunique() == 3
    assert (first["price"] > 0).all()
    assert (first["orders"] <= first["pv"]).all()
    assert (first["orders"] <= first["uv"]).all()
    assert (first["sales_amount"] >= 0).all()
    assert (first["refund_amount"] <= first["sales_amount"] + 0.01).all()
    assert (first["stock"] >= 0).all()
    assert (first["platform"] == "Shopify").all()
    assert not first.duplicated(["product_id", "stat_date"]).any()


def test_shopify_sales_demo_requires_minimum_days():
    with pytest.raises(ValueError):
        build_shopify_sales_demo(_catalog(), days=7)


def test_shopify_sales_demo_missing_catalog_fields():
    with pytest.raises(CatalogError):
        build_shopify_sales_demo(pd.DataFrame([{"product_id": "p1"}]))
