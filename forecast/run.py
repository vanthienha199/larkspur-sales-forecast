"""Generate the data, run the backtest, fit the final model, write the report data.

    python -m forecast.run
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .data import LOCATIONS, OUTAGE, generate, holiday_calendar, location_names, promo_calendar
from .products import MENU, bake_list
from .model import HORIZON, backtest, final_forecast

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    sales = generate()
    (ROOT / "data").mkdir(exist_ok=True)
    sales.to_csv(ROOT / "data" / "sales.csv", index=False)
    metrics, bt = backtest(sales)
    fc = final_forecast(sales)
    fc.to_csv(ROOT / "data" / "forecast_next_28_days.csv", index=False)
    bt.to_csv(ROOT / "data" / "backtest_predictions.csv", index=False)
    (ROOT / "data" / "metrics.json").write_text(json.dumps(metrics, indent=2))

    names = location_names()
    last = sales["date"].max()

    # Real annotations only: planned promotions and US holidays that the data
    # already carries. Nothing is invented for the chart.
    promos = promo_calendar()
    promo_by = {}
    for d, loc in zip(promos["date"], promos["location"]):
        promo_by.setdefault(loc, set()).add(d.date().isoformat())
    hol = holiday_calendar()
    holiday_by = {d.date().isoformat(): n for d, n in zip(hol["date"], hol["holiday"])}
    site = {"generated_for": last.date().isoformat(), "horizon": HORIZON, "metrics": metrics,
            "menu": [{"key": p.key, "name": p.name, "unit": p.unit, "price": p.price, "batch": p.batch} for p in MENU],
            "outage": {"location": OUTAGE[0], "start": OUTAGE[1], "end": OUTAGE[2]}, "locations": []}
    for loc in LOCATIONS:
        hist = sales[sales["location"] == loc.key]
        f = fc[fc["location"] == loc.key]
        b = bt[bt["location"] == loc.key]
        # Every forecast day gets its list, so the baker can look past tomorrow
        # and so a closed day is visible rather than hypothetical.
        days = []
        for _, row in f.iterrows():
            d = pd.Timestamp(row["date"])
            closed = bool(row["closed"])
            days.append({
                "date": d.date().isoformat(),
                "weekday": d.day_name(),
                "closed": closed,
                "revenue": round(float(row["forecast"]), 2),
                "low": round(float(row["low_80"]), 2),
                "high": round(float(row["high_80"]), 2),
                "items": [] if closed else bake_list(
                    float(row["forecast"]), float(row["low_80"]), float(row["high_80"]), int(d.weekday())),
            })
        tomorrow = days[0] if days else None

        notes = []
        for d in f["date"]:
            key = d.date().isoformat()
            if key in promo_by.get(loc.key, ()):  # planned, and a model feature
                notes.append({"date": key, "text": "Promotion running"})
            elif key in holiday_by:
                notes.append({"date": key, "text": holiday_by[key]})

        site["locations"].append({
            "key": loc.key, "name": names[loc.key], "opened": loc.opened,
            "closed_monday": loc.closed_monday,
            "tomorrow": tomorrow,
            "days": days,
            "notes": notes,
            "history": [[d.date().isoformat(), None if pd.isna(v) else round(float(v), 2)] for d, v in zip(hist["date"], hist["revenue"])],
            "forecast": [[d.date().isoformat(), float(p), float(lo), float(hi)] for d, p, lo, hi in zip(f["date"], f["forecast"], f["low_80"], f["high_80"])],
            "backtest": [[d.date().isoformat(), None if pd.isna(a) else float(a), float(m), float(n)] for d, a, m, n in zip(b["date"], b["revenue"], b["model"], b["naive"])],
        })
    (ROOT / "site" / "data.js").write_text("window.FORECAST = " + json.dumps(site, separators=(",", ":")) + ";\n")

    o = metrics["overall"]
    print(f"days scored {o['days_scored']}, WAPE model {o['wape_model']:.1%} vs weekly naive {o['wape_naive']:.1%}, "
          f"MAPE (open days) {o['mape_model']:.1%} vs {o['mape_naive']:.1%}, 80% interval coverage {o['interval_coverage_80']:.1%}, "
          f"bias {o['bias_model']:+.1%}")
    for k, v in metrics["per_location"].items():
        print(f"  {k:11s} WAPE {v['wape_model']:.1%} vs {v['wape_naive']:.1%}")
    print("top features:", ", ".join(f"{i['feature']} ({i['mae_increase']:.0f})" for i in metrics["importance"][:6]))


if __name__ == "__main__":
    main()
