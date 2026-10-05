"""Generate the data, run the backtest, fit the final model, write the report data.

    python -m forecast.run
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .data import LOCATIONS, OUTAGE, generate, location_names
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
    site = {"generated_for": last.date().isoformat(), "horizon": HORIZON, "metrics": metrics,
            "outage": {"location": OUTAGE[0], "start": OUTAGE[1], "end": OUTAGE[2]}, "locations": []}
    for loc in LOCATIONS:
        hist = sales[sales["location"] == loc.key]
        f = fc[fc["location"] == loc.key]
        b = bt[bt["location"] == loc.key]
        site["locations"].append({
            "key": loc.key, "name": names[loc.key], "opened": loc.opened,
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
