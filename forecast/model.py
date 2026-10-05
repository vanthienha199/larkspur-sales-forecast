"""Features, models, backtest and the final forecast.

Direct 28-day forecast: every lag is at least 28 days old, so a forecast for
any day in the horizon only uses data that exists at the forecast origin.
Known-ahead inputs (calendar, holidays, planned promos, open/closed days) are
allowed. Point forecast: gradient boosting on absolute error. Interval: two
quantile models (10th and 90th percentile), an 80 percent band whose real
coverage is measured in the backtest.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

from .data import LOCATIONS, holiday_calendar, promo_calendar

HORIZON = 28
FEATURES = [
    "loc_code", "dow", "doy_sin", "doy_cos", "month", "is_holiday", "holiday_eve", "closed",
    "promo", "store_age_days", "lag_28", "lag_35", "lag_364", "mean_28_lag28", "same_dow_mean_lag28",
]
LABELS = {
    "loc_code": "Location", "dow": "Day of week", "doy_sin": "Season (sin)", "doy_cos": "Season (cos)",
    "month": "Month", "is_holiday": "Holiday", "holiday_eve": "Day before closure", "closed": "Closed day",
    "promo": "Planned promo", "store_age_days": "Store age", "lag_28": "Sales 28 days ago",
    "lag_35": "Sales 35 days ago", "lag_364": "Sales a year ago", "mean_28_lag28": "28-day average, 4 weeks back",
    "same_dow_mean_lag28": "Same weekday average, 4 weeks back",
}


def calendar(dates: pd.DatetimeIndex) -> pd.DataFrame:
    hol = holiday_calendar()
    hol_dates = set(hol["date"])
    closures = set(hol.loc[hol["holiday"].str.contains("Thanksgiving") | hol["holiday"].str.startswith("Christmas"), "date"])
    cal = pd.DataFrame({"date": dates})
    cal["dow"] = cal["date"].dt.dayofweek
    doy = cal["date"].dt.dayofyear
    cal["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    cal["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    cal["month"] = cal["date"].dt.month
    cal["is_holiday"] = cal["date"].isin(hol_dates).astype(int)
    cal["holiday_eve"] = (cal["date"] + pd.Timedelta(days=1)).isin(closures).astype(int)
    cal["closure"] = cal["date"].isin(closures).astype(int)
    return cal


def build_frame(sales: pd.DataFrame, until: str | pd.Timestamp) -> pd.DataFrame:
    """Full daily grid per location up to `until` (inclusive), with features.

    Revenue after the last observed day is NaN; lags only look back >= 28 days.
    """
    until = pd.Timestamp(until)
    promos = promo_calendar()
    promo_set = set(zip(promos["date"], promos["location"]))
    rows = []
    for code, loc in enumerate(LOCATIONS):
        dates = pd.date_range(loc.opened, until, freq="D")
        f = calendar(dates)
        f["location"] = loc.key
        f["loc_code"] = code
        f["store_age_days"] = (f["date"] - pd.Timestamp(loc.opened)).dt.days
        f["promo"] = [int((d, loc.key) in promo_set) for d in f["date"]]
        f["closed"] = f["closure"] | ((f["dow"] == 0) & loc.closed_monday).astype(int)
        s = sales[sales["location"] == loc.key].set_index("date")["revenue"]
        f["revenue"] = f["date"].map(s)
        rev = f.set_index("date")["revenue"]
        for lag in (28, 35, 364):
            f[f"lag_{lag}"] = rev.shift(lag).values
        f["mean_28_lag28"] = rev.shift(28).rolling(28, min_periods=14).mean().values
        same = [rev.shift(28 + 7 * k) for k in range(4)]
        f["same_dow_mean_lag28"] = pd.concat(same, axis=1).mean(axis=1).values
        rows.append(f)
    return pd.concat(rows, ignore_index=True)


def _model(loss: str, quantile: float | None = None) -> HistGradientBoostingRegressor:
    kw = dict(max_iter=400, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=20,
              categorical_features=[0], random_state=0)
    if quantile is None:
        return HistGradientBoostingRegressor(loss=loss, **kw)
    return HistGradientBoostingRegressor(loss="quantile", quantile=quantile, **kw)


class Forecaster:
    CALIBRATION_DAYS = 56

    def fit(self, train: pd.DataFrame) -> "Forecaster":
        """Point model on all training rows. The band is conformalized quantile
        regression: quantile models fit on all but the last 56 days, then widened
        by the size of their misses on those 56 held-out days, so the 80 percent
        band is calibrated on data the quantile models never saw."""
        t = train.dropna(subset=["revenue"])
        t = t[t["closed"] == 0]
        X, y = t[FEATURES], t["revenue"]
        self.point = _model("absolute_error").fit(X, y)
        cut = t["date"].max() - pd.Timedelta(days=self.CALIBRATION_DAYS)
        fit_part, cal = t[t["date"] <= cut], t[t["date"] > cut]
        self.low = _model("quantile", 0.1).fit(fit_part[FEATURES], fit_part["revenue"])
        self.high = _model("quantile", 0.9).fit(fit_part[FEATURES], fit_part["revenue"])
        lo, hi = self.low.predict(cal[FEATURES]), self.high.predict(cal[FEATURES])
        scores = np.maximum(lo - cal["revenue"].values, cal["revenue"].values - hi)
        n = len(scores)
        self.widen = float(np.quantile(scores, min(1.0, np.ceil((n + 1) * 0.8) / n))) if n else 0.0
        return self

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        X = frame[FEATURES]
        out = frame[["date", "location", "closed"]].copy()
        p = self.point.predict(X)
        lo, hi = self.low.predict(X) - self.widen, self.high.predict(X) + self.widen
        lo, hi = np.minimum(lo, p), np.maximum(hi, p)
        closed = frame["closed"].values == 1
        out["forecast"] = np.where(closed, 0.0, np.maximum(p, 0)).round(2)
        out["low_80"] = np.where(closed, 0.0, np.maximum(lo, 0)).round(2)
        out["high_80"] = np.where(closed, 0.0, np.maximum(hi, 0)).round(2)
        return out


def seasonal_naive(frame: pd.DataFrame, origin: pd.Timestamp) -> pd.Series:
    """Baseline: repeat the last full week before the origin, closed days as zero."""
    out = pd.Series(np.nan, index=frame.index)
    for loc, g in frame.groupby("location"):
        hist = g[(g["date"] <= origin)].dropna(subset=["revenue"]).tail(7)
        by_dow = dict(zip(hist["dow"], hist["revenue"]))
        fut = g[g["date"] > origin]
        out.loc[fut.index] = fut["dow"].map(by_dow).values
    return out.where(frame["closed"] == 0, 0.0)


def wape(actual, pred) -> float:
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    m = ~np.isnan(a) & ~np.isnan(p)
    return float(np.abs(a[m] - p[m]).sum() / np.abs(a[m]).sum())


def mape_open_days(actual, pred) -> float:
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    m = ~np.isnan(a) & ~np.isnan(p) & (a > 0)
    return float(np.mean(np.abs(a[m] - p[m]) / a[m]))


def backtest(sales: pd.DataFrame, folds: int = 6) -> dict:
    """Rolling origin: train on everything up to the origin, forecast the next 28 days."""
    last = sales["date"].max()
    frame = build_frame(sales, last)
    origins = [last - pd.Timedelta(days=HORIZON * k) for k in range(folds, 0, -1)]
    results, fold_rows, last_model, last_test = [], [], None, None
    for origin in origins:
        train = frame[frame["date"] <= origin]
        test_mask = (frame["date"] > origin) & (frame["date"] <= origin + pd.Timedelta(days=HORIZON))
        test = frame[test_mask]
        fc = Forecaster().fit(train)
        pred = fc.predict(test)
        naive = seasonal_naive(frame[(frame["date"] <= origin + pd.Timedelta(days=HORIZON))], origin).loc[test.index]
        r = test[["date", "location", "revenue"]].copy()
        r["model"], r["naive"] = pred["forecast"].values, naive.values
        r["low_80"], r["high_80"] = pred["low_80"].values, pred["high_80"].values
        r["origin"] = origin
        results.append(r)
        ok = r.dropna(subset=["revenue"])
        fold_rows.append({"origin": origin.date().isoformat(), "days": int(len(ok)),
                          "wape_model": wape(ok["revenue"], ok["model"]), "wape_naive": wape(ok["revenue"], ok["naive"])})
        last_model, last_test = fc, test
    allr = pd.concat(results, ignore_index=True).dropna(subset=["revenue"])
    open_ = allr[allr["revenue"] > 0]
    inside = ((open_["revenue"] >= open_["low_80"]) & (open_["revenue"] <= open_["high_80"])).mean()
    per_loc = {}
    for loc, g in allr.groupby("location"):
        per_loc[loc] = {"wape_model": wape(g["revenue"], g["model"]), "wape_naive": wape(g["revenue"], g["naive"]),
                        "mape_model": mape_open_days(g["revenue"], g["model"]), "mape_naive": mape_open_days(g["revenue"], g["naive"])}
    imp = permutation_importance(last_model.point, last_test.dropna(subset=["revenue"])[FEATURES],
                                 last_test.dropna(subset=["revenue"])["revenue"], n_repeats=8, random_state=0,
                                 scoring="neg_mean_absolute_error")
    importance = sorted(({"feature": LABELS[f], "mae_increase": float(m)} for f, m in zip(FEATURES, imp.importances_mean)),
                        key=lambda x: -x["mae_increase"])
    return {
        "horizon_days": HORIZON, "folds": fold_rows,
        "overall": {"wape_model": wape(allr["revenue"], allr["model"]), "wape_naive": wape(allr["revenue"], allr["naive"]),
                    "mape_model": mape_open_days(allr["revenue"], allr["model"]), "mape_naive": mape_open_days(allr["revenue"], allr["naive"]),
                    "bias_model": float((allr["model"] - allr["revenue"]).sum() / allr["revenue"].sum()),
                    "interval_coverage_80": float(inside), "days_scored": int(len(allr))},
        "per_location": per_loc, "importance": importance,
    }, pd.concat(results, ignore_index=True)


def final_forecast(sales: pd.DataFrame) -> pd.DataFrame:
    last = sales["date"].max()
    frame = build_frame(sales, last + pd.Timedelta(days=HORIZON))
    fc = Forecaster().fit(frame[frame["date"] <= last])
    return fc.predict(frame[frame["date"] > last])
