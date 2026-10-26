from __future__ import annotations

from ecom_ops.analysis.sensitivity import (
    prepare_frames,
    run_grid,
    run_ofat,
    run_profiles,
    select_dates,
)
from ecom_ops.data.loader import load_sales_data
from ecom_ops.data.validator import validate_sales_data


def test_sensitivity_core_runs(settings, fields, mock_csv):
    raw = load_sales_data(mock_csv, fields)
    validation = validate_sales_data(raw, fields)
    dates = select_dates(validation.valid_df, 3)
    metrics, baselines = prepare_frames(
        validation.valid_df,
        dates,
        settings.baseline,
    )

    ofat = run_ofat(
        settings.anomaly,
        {"min_pv_for_zero_conversion": [50, 100]},
        metrics,
        baselines,
    )
    assert len(ofat) == 3
    assert ofat[0].label == "v0.1 基线"
    assert all(row.avg_per_day >= 0 for row in ofat)
    assert all(row.product_days > 0 for row in ofat)

    grid = run_grid(
        settings.anomaly,
        "min_pv_for_zero_conversion",
        [50, 100],
        "order_drop_ratio",
        [0.5, 0.7],
        metrics,
        baselines,
    )
    assert len(grid) == 4

    profiles = run_profiles(
        settings.anomaly,
        {
            "v0.1": {},
            "strict": {"min_orders_for_drop": 5},
        },
        metrics,
        baselines,
    )
    assert len(profiles) == 2
    assert profiles[0].label == "v0.1"
    assert profiles[1].label == "strict"
