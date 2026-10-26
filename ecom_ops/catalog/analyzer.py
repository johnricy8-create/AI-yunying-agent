"""Shopify 商品目录与价格事件分析。

只做目录/价格/可用性统计，不推断销量或流量。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ecom_ops.exceptions import CatalogError

REQUIRED_CATALOG = [
    "store_domain",
    "product_id",
    "variant_id",
    "title",
    "price",
    "available",
    "fetched_at",
]
REQUIRED_CHANGES = [
    "store",
    "product_id",
    "variant_id",
    "date",
    "change_type",
    "old_price",
    "new_price",
]


def _read_csv(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return pd.read_csv(
                path,
                dtype=str,
                keep_default_na=False,
                na_filter=False,
                encoding=encoding,
            )
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except pd.errors.EmptyDataError as exc:
            raise CatalogError(f"文件为空: {path}") from exc
        except pd.errors.ParserError as exc:
            raise CatalogError(f"CSV 解析失败: {path}\n{exc}") from exc
    raise CatalogError(f"无法读取文件: {path}\n{last_error}")


def _require_columns(df: pd.DataFrame, required: list[str], kind: str) -> None:
    missing = [name for name in required if name not in df.columns]
    if missing:
        raise CatalogError(f"{kind}缺少必要字段: {', '.join(missing)}")


def _as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})


def _as_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _date_values(series: pd.Series) -> list[str]:
    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    values = sorted({item.strftime("%Y-%m-%d") for item in parsed.dropna()})
    return values


def _empty_changes(top: int) -> dict[str, Any]:
    return {
        "available": False,
        "path": "",
        "rows": 0,
        "date_min": "",
        "date_max": "",
        "date_count": 0,
        "event_counts": {},
        "stores": 0,
        "products": 0,
        "variants": 0,
        "top_price_changes": [],
        "availability_events": [],
        "store_summary": [],
        "large_change_count": 0,
        "store_overlap": 0,
        "variant_overlap": 0,
    }


def analyze_catalog(
    catalog_path: str | Path,
    changes_path: str | Path | None = None,
    top: int = 10,
) -> dict[str, Any]:
    catalog_file = Path(catalog_path)
    if not catalog_file.exists():
        raise CatalogError(f"目录文件不存在: {catalog_file}")
    catalog = _read_csv(catalog_file)
    _require_columns(catalog, REQUIRED_CATALOG, "目录文件")
    if catalog.empty:
        raise CatalogError("目录文件没有数据行")

    for column in ("price", "compare_at_price", "image_count"):
        if column in catalog.columns:
            catalog[column] = _as_number(catalog[column])
    catalog["available"] = _as_bool(catalog["available"])
    if "product_type" in catalog.columns:
        catalog["product_type"] = catalog["product_type"].replace("", "未分类")
    else:
        catalog["product_type"] = "未分类"
    if "niche" in catalog.columns:
        catalog["niche"] = catalog["niche"].replace("", "other")
    else:
        catalog["niche"] = "other"
    if "store_name" in catalog.columns:
        store_name = catalog["store_name"].astype(str).str.strip()
        catalog["store_name"] = store_name.where(store_name != "", catalog["store_domain"])
    else:
        catalog["store_name"] = catalog["store_domain"]
    if "variant_title" in catalog.columns:
        variant_suffix = catalog["variant_title"].replace("Default Title", "").str.strip()
        catalog["display_name"] = catalog["title"] + variant_suffix.map(
            lambda value: f" / {value}" if value else ""
        )
    else:
        catalog["display_name"] = catalog["title"]

    snapshot_dates = _date_values(catalog["fetched_at"])
    price = catalog["price"].dropna()
    zero_price_rows = catalog[catalog["price"].notna() & (catalog["price"] <= 0)]
    duplicate_variants = int(catalog["variant_id"].duplicated().sum())

    price_bins = []
    if not price.empty:
        bins = [-0.001, 0.001, 10, 30, 100, 500, float("inf")]
        labels = ["0", "0–10", "10–30", "30–100", "100–500", ">500"]
        cut = pd.cut(price, bins=bins, labels=labels, include_lowest=True)
        counts = cut.value_counts().reindex(labels, fill_value=0)
        price_bins = [{"label": label, "count": int(counts[label])} for label in labels]

    niche_summary: list[dict[str, Any]] = []
    if "niche" in catalog.columns:
        for niche, group in catalog.groupby("niche", sort=False):
            niche_summary.append(
                {
                    "niche": str(niche),
                    "variants": int(len(group)),
                    "stores": int(group["store_domain"].nunique()),
                    "median_price": round(float(group["price"].median()), 2)
                    if group["price"].notna().any()
                    else None,
                    "available_rate": float(group["available"].mean()),
                }
            )
        niche_summary.sort(key=lambda item: item["variants"], reverse=True)

    store_summary: list[dict[str, Any]] = []
    for store, group in catalog.groupby("store_domain", sort=False):
        store_summary.append(
            {
                "store": str(store),
                "store_name": str(group["store_name"].iloc[0]),
                "variants": int(len(group)),
                "available": int(group["available"].sum()),
                "median_price": round(float(group["price"].median()), 2)
                if group["price"].notna().any()
                else None,
            }
        )
    store_summary.sort(key=lambda item: item["variants"], reverse=True)

    missing_counts = {
        "product_type": int((catalog["product_type"] == "未分类").sum())
        if "product_type" in catalog.columns
        else 0,
        "tags": int((catalog["tags"].astype(str).str.strip() == "").sum())
        if "tags" in catalog.columns
        else 0,
        "sku": int((catalog["sku"].astype(str).str.strip() == "").sum())
        if "sku" in catalog.columns
        else 0,
        "compare_at_price": int(catalog["compare_at_price"].isna().sum())
        if "compare_at_price" in catalog.columns
        else 0,
    }

    changes = _empty_changes(top)
    if changes_path:
        changes_file = Path(changes_path)
        if not changes_file.exists():
            raise CatalogError(f"价格事件文件不存在: {changes_file}")
        change_df = _read_csv(changes_file)
        _require_columns(change_df, REQUIRED_CHANGES, "价格事件文件")
        for column in ("old_price", "new_price"):
            change_df[column] = _as_number(change_df[column])
        for column in ("old_available", "new_available"):
            if column in change_df.columns:
                change_df[column] = _as_bool(change_df[column])
        change_dates = _date_values(change_df["date"])
        event_counts = {
            str(key): int(value)
            for key, value in change_df["change_type"].value_counts().items()
        }

        catalog_variants = set(catalog["variant_id"].astype(str))
        change_variants = set(change_df["variant_id"].astype(str))
        catalog_stores = set(catalog["store_domain"].astype(str))
        change_stores = set(change_df["store"].astype(str))

        title_map = (
            catalog.drop_duplicates("variant_id").set_index("variant_id")["display_name"].to_dict()
        )
        change_df["display_name"] = change_df["variant_id"].map(title_map).fillna("")

        price_events = change_df[
            change_df["change_type"].isin(["price_drop", "price_increase"])
            & change_df["old_price"].notna()
            & change_df["new_price"].notna()
            & (change_df["old_price"] > 0)
        ].copy()
        price_events["change_pct"] = (
            (price_events["new_price"] - price_events["old_price"])
            / price_events["old_price"]
        )
        price_events["abs_pct"] = price_events["change_pct"].abs()
        price_events = price_events.sort_values("abs_pct", ascending=False)

        top_price_changes = []
        for _, row in price_events.head(top).iterrows():
            top_price_changes.append(
                {
                    "store": str(row["store"]),
                    "product_id": str(row["product_id"]),
                    "variant_id": str(row["variant_id"]),
                    "display_name": str(row.get("display_name", "")),
                    "date": str(row["date"]),
                    "type": str(row["change_type"]),
                    "old_price": float(row["old_price"]),
                    "new_price": float(row["new_price"]),
                    "change_pct": float(row["change_pct"]),
                }
            )

        availability_events = []
        availability_df = change_df[
            change_df["change_type"].isin(["out_of_stock", "restocked", "new_listing"])
        ].sort_values("date", ascending=False)
        for _, row in availability_df.head(top).iterrows():
            availability_events.append(
                {
                    "store": str(row["store"]),
                    "product_id": str(row["product_id"]),
                    "variant_id": str(row["variant_id"]),
                    "display_name": str(row.get("display_name", "")),
                    "date": str(row["date"]),
                    "type": str(row["change_type"]),
                }
            )

        store_events: dict[str, dict[str, Any]] = {}
        for store, group in change_df.groupby("store", sort=False):
            counts = group["change_type"].value_counts().to_dict()
            store_events[str(store)] = {
                "store": str(store),
                "events": int(len(group)),
                "price_drop": int(counts.get("price_drop", 0)),
                "price_increase": int(counts.get("price_increase", 0)),
                "out_of_stock": int(counts.get("out_of_stock", 0)),
                "restocked": int(counts.get("restocked", 0)),
                "new_listing": int(counts.get("new_listing", 0)),
            }
        change_store_summary = sorted(
            store_events.values(), key=lambda item: item["events"], reverse=True
        )

        changes = {
            "available": True,
            "path": str(changes_file),
            "rows": int(len(change_df)),
            "date_min": change_dates[0] if change_dates else "",
            "date_max": change_dates[-1] if change_dates else "",
            "date_count": len(change_dates),
            "event_counts": event_counts,
            "stores": int(change_df["store"].nunique()),
            "products": int(change_df["product_id"].nunique()),
            "variants": int(change_df["variant_id"].nunique()),
            "top_price_changes": top_price_changes,
            "availability_events": availability_events,
            "store_summary": change_store_summary[:top],
            "large_change_count": int((price_events["abs_pct"] >= 0.2).sum()),
            "store_overlap": len(catalog_stores & change_stores),
            "variant_overlap": len(catalog_variants & change_variants),
        }

    manual_checks: list[str] = []
    if len(zero_price_rows):
        manual_checks.append(f"修复 {len(zero_price_rows)} 个价格为 0 的变体")
    unavailable = int((~catalog["available"]).sum())
    if unavailable:
        manual_checks.append(f"核对 {unavailable} 个不可用变体的缺货原因")
    if changes["available"] and changes["large_change_count"]:
        manual_checks.append(
            f"人工复核 {changes['large_change_count']} 条价格变动幅度 ≥ 20% 的事件"
        )
    if missing_counts["product_type"] or missing_counts["tags"] or missing_counts["sku"]:
        manual_checks.append(
            "补齐 product_type / tags / SKU，提升目录可分析性："
            f"{missing_counts['product_type']} / {missing_counts['tags']} / {missing_counts['sku']}"
        )
    if changes["available"] and changes["variant_overlap"] == 0:
        manual_checks.append("目录快照与价格事件样本无变体交集，不能直接按变体关联")

    limitations = [
        "当前目录是单日快照，不能观察价格/可用性的连续趋势。",
        "目录数据没有订单、销售额、PV/UV、退款、成本和库存数量。",
        "价格事件只覆盖样本门店/变体，且日期可能集中在一天，不能代表全量业务。",
        "商品价格为店铺币种原值，未做统一汇率换算。",
        "本报告不推断销量影响，也不调用大模型。",
        "样本许可为 CC BY-NC 4.0，商用前需确认完整数据集的商业许可。",
    ]

    return {
        "catalog_path": str(catalog_file),
        "changes_path": str(changes_path) if changes_path else "",
        "catalog_rows": int(len(catalog)),
        "stores": int(catalog["store_domain"].nunique()),
        "products": int(catalog["product_id"].nunique()),
        "variants": int(catalog["variant_id"].nunique()),
        "snapshot_dates": snapshot_dates,
        "snapshot_start": snapshot_dates[0] if snapshot_dates else "",
        "snapshot_end": snapshot_dates[-1] if snapshot_dates else "",
        "available_true": int(catalog["available"].sum()),
        "available_false": int((~catalog["available"]).sum()),
        "price_stats": {
            "min": round(float(price.min()), 2) if not price.empty else None,
            "p50": round(float(price.quantile(0.5)), 2) if not price.empty else None,
            "p90": round(float(price.quantile(0.9)), 2) if not price.empty else None,
            "p99": round(float(price.quantile(0.99)), 2) if not price.empty else None,
            "max": round(float(price.max()), 2) if not price.empty else None,
        },
        "price_bins": price_bins,
        "niche_summary": niche_summary,
        "store_summary": store_summary[:top],
        "missing_counts": missing_counts,
        "duplicate_variants": duplicate_variants,
        "compare_at_present": int((catalog["compare_at_price"] > 0).sum())
        if "compare_at_price" in catalog.columns
        else 0,
        "zero_price_rows": [
            {
                "store": str(row["store_domain"]),
                "display_name": str(row["display_name"]),
                "variant_id": str(row["variant_id"]),
                "price": float(row["price"]),
            }
            for _, row in zero_price_rows.head(top).iterrows()
        ],
        "changes": changes,
        "manual_checks": manual_checks,
        "limitations": limitations,
    }
