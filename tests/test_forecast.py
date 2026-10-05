import numpy as np
import pandas as pd
import pytest

from forecast.data import LOCATIONS, OUTAGE, generate
from forecast.model import FEATURES, HORIZON, Forecaster, build_frame, final_forecast, mape_open_days, seasonal_naive, wape


@pytest.fixture(scope="module")
def sales():
    return generate()


def test_generation_is_deterministic(sales):
    again = generate()
    pd.testing.assert_frame_equal(sales, again)


def test_data_has_the_real_world_quirks(sales):
    # the register outage is a gap, not zeros
    loc, start, end = OUTAGE
    gap = sales[(sales["location"] == loc) & (sales["date"].between(start, end))]
    assert len(gap) == 12 and gap["revenue"].isna().all()
    # the newer store has a shorter history
    nh = sales[sales["location"] == "north-hill"]
    assert nh["date"].min() == pd.Timestamp("2025-03-14")
    # closed on Christmas, a rush the day before
    old = sales[sales["location"] == "old-town"].set_index("date")["revenue"]
    assert old[pd.Timestamp("2025-12-25")] == 0
    assert old[pd.Timestamp("2025-12-24")] > 1.4 * old[pd.Timestamp("2025-12-17")]
    # Eastgate is closed on Mondays
    east = sales[sales["location"] == "eastgate"]
    assert (east[east["date"].dt.dayofweek == 0]["revenue"].fillna(0) == 0).all()


def test_lag_features_never_look_inside_the_horizon(sales):
    frame = build_frame(sales, sales["date"].max())
    g = frame[frame["location"] == "old-town"].set_index("date")
    day = pd.Timestamp("2026-06-30")
    assert g.loc[day, "lag_28"] == g.loc[day - pd.Timedelta(days=28), "revenue"]
    lag_cols = [c for c in FEATURES if c.startswith("lag_")]
    assert all(int(c.split("_")[1]) >= HORIZON for c in lag_cols)


def test_no_future_revenue_used_when_training(sales):
    origin = pd.Timestamp("2026-06-01")
    frame = build_frame(sales, origin + pd.Timedelta(days=HORIZON))
    test = frame[frame["date"] > origin]
    # every lag value in the forecast window comes from on or before the origin
    for col, lag in (("lag_28", 28), ("lag_35", 35)):
        src_dates = test["date"] - pd.Timedelta(days=lag)
        assert (src_dates <= origin).all()


def test_metrics():
    assert wape([100, 200, 0], [110, 180, 0]) == pytest.approx(30 / 300)
    assert mape_open_days([100, 200, 0], [110, 180, 5]) == pytest.approx((0.1 + 0.1) / 2)
    assert wape([100, np.nan], [90, 50]) == pytest.approx(0.1)


def test_seasonal_naive_repeats_last_week_and_respects_closures(sales):
    origin = pd.Timestamp("2026-06-01")
    frame = build_frame(sales, origin + pd.Timedelta(days=HORIZON))
    base = seasonal_naive(frame, origin)
    east = frame[(frame["location"] == "eastgate") & (frame["date"] > origin)]
    assert (base.loc[east[east["dow"] == 0].index] == 0).all()
    old = frame[frame["location"] == "old-town"]
    last_week = old[(old["date"] <= origin) & (old["date"] > origin - pd.Timedelta(days=7))].set_index("dow")["revenue"]
    fut = old[(old["date"] > origin) & (old["closed"] == 0)]
    assert np.allclose(base.loc[fut.index].values, fut["dow"].map(last_week).values)


def test_forecast_shape_bounds_and_closures(sales):
    fc = final_forecast(sales)
    assert len(fc) == HORIZON * len(LOCATIONS)
    assert set(fc.columns) >= {"date", "location", "forecast", "low_80", "high_80"}
    assert (fc["low_80"] <= fc["forecast"]).all() and (fc["forecast"] <= fc["high_80"]).all()
    assert (fc["forecast"] >= 0).all()
    assert (fc.loc[fc["closed"] == 1, "forecast"] == 0).all()
    assert fc["date"].min() == sales["date"].max() + pd.Timedelta(days=1)


def test_model_beats_naive_on_a_holdout(sales):
    origin = pd.Timestamp("2026-08-01")
    frame = build_frame(sales, origin + pd.Timedelta(days=HORIZON))
    test = frame[(frame["date"] > origin)].dropna(subset=["revenue"])
    pred = Forecaster().fit(frame[frame["date"] <= origin]).predict(test)
    naive = seasonal_naive(frame, origin).loc[test.index]
    assert wape(test["revenue"], pred["forecast"]) < wape(test["revenue"], naive)
