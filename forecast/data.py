"""Synthetic daily sales for Larkspur Bakehouse, an invented four-location bakery.

The data is made up, but it carries the patterns real small-business sales
have, so the forecasting problem is honest:

- a weekly cycle (weekends up, Mondays slow, one location closed Mondays)
- yearly seasonality (holiday-season peak, a summer dip)
- US holidays: closed on Christmas and Thanksgiving, a rush the day before
- planned promotions (known ahead, so they are allowed as a feature)
- slow growth, a newer location that opened in 2025, and noise
- a 12-day point-of-sale outage with no data at one location
"""

from __future__ import annotations

from dataclasses import dataclass

import holidays
import numpy as np
import pandas as pd

START = "2024-01-01"
END = "2026-09-30"


@dataclass(frozen=True)
class Location:
    key: str
    name: str
    base: float          # typical weekday revenue in dollars
    growth: float        # yearly growth
    weekend_lift: float
    closed_monday: bool
    opened: str


LOCATIONS = (
    Location("old-town", "Old Town", 2480.0, 0.04, 0.38, False, START),
    Location("riverside", "Riverside", 1910.0, 0.07, 0.52, False, START),
    Location("eastgate", "Eastgate Market", 1385.0, 0.02, 0.21, True, START),
    Location("north-hill", "North Hill", 1120.0, 0.18, 0.44, False, "2025-03-14"),
)

OUTAGE = ("riverside", "2025-07-08", "2025-07-19")


def holiday_calendar(start: str = START, end: str = "2026-12-31") -> pd.DataFrame:
    """US holidays by date with the name, plus closures."""
    years = range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1)
    us = holidays.US(years=years)
    rows = [{"date": pd.Timestamp(d), "holiday": n} for d, n in us.items()]
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def promo_calendar(start: str = START, end: str = "2026-12-31", seed: int = 7) -> pd.DataFrame:
    """Planned three-day promotions, about one a month per location."""
    rng = np.random.default_rng(seed)
    rows = []
    for loc in LOCATIONS:
        month_starts = pd.date_range(start, end, freq="MS")
        for ms in month_starts:
            if rng.random() < 0.8:
                day = ms + pd.Timedelta(days=int(rng.integers(3, 24)))
                for k in range(3):
                    rows.append({"date": day + pd.Timedelta(days=k), "location": loc.key})
    return pd.DataFrame(rows).drop_duplicates()


def generate(seed: int = 42) -> pd.DataFrame:
    """One row per location and day: date, location, revenue (NaN when unknown), promo."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(START, END, freq="D")
    hol = holiday_calendar()
    hol_dates = set(hol["date"])
    thanksgiving = set(hol.loc[hol["holiday"].str.contains("Thanksgiving"), "date"])
    christmas = set(hol.loc[hol["holiday"].str.startswith("Christmas"), "date"])
    promos = promo_calendar()
    promo_set = set(zip(promos["date"], promos["location"]))

    frames = []
    for loc in LOCATIONS:
        t = (dates - dates[0]).days.values / 365.25
        doy = dates.dayofyear.values
        dow = dates.dayofweek.values
        weekly = np.select([dow >= 5, dow == 0, dow == 4], [1 + loc.weekend_lift, 0.86, 1.08], 1.0)
        yearly = 1 + 0.10 * np.cos(2 * np.pi * (doy - 350) / 365.25) - 0.06 * np.exp(-((doy - 200) / 25.0) ** 2)
        trend = (1 + loc.growth) ** t
        level = loc.base * weekly * yearly * trend
        # newer store ramps up over its first ~4 months
        opened = pd.Timestamp(loc.opened)
        age = (dates - opened).days.values
        level = np.where(age < 0, np.nan, level * (1 - 0.45 * np.exp(-np.maximum(age, 0) / 40.0)))

        promo = np.array([(d, loc.key) in promo_set for d in dates])
        level = level * np.where(promo, 1.18, 1.0)

        is_hol = np.array([d in hol_dates for d in dates])
        level = level * np.where(is_hol, 0.82, 1.0)
        eve = np.array([(d + pd.Timedelta(days=1)) in thanksgiving or (d + pd.Timedelta(days=1)) in christmas for d in dates])
        level = level * np.where(eve, 1.65, 1.0)
        closed = np.array([d in thanksgiving or d in christmas for d in dates])
        if loc.closed_monday:
            closed = closed | (dow == 0)

        noise = rng.normal(0, 0.075, len(dates))
        revenue = np.round(level * np.exp(noise), 2)
        revenue = np.where(closed & ~np.isnan(revenue), 0.0, revenue)

        df = pd.DataFrame({"date": dates, "location": loc.key, "revenue": revenue, "promo": promo.astype(int)})
        df = df[dates >= opened]
        if loc.key == OUTAGE[0]:
            gap = (df["date"] >= OUTAGE[1]) & (df["date"] <= OUTAGE[2])
            df.loc[gap, "revenue"] = np.nan
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def location_names() -> dict[str, str]:
    return {loc.key: loc.name for loc in LOCATIONS}
