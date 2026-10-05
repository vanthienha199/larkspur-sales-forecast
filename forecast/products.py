"""Turn a revenue forecast into tomorrow's bake list.

The model forecasts revenue per location, because that is what the sales system
records and what the backtest scores. A baker cannot put revenue in an oven, so
this module converts a day's forecast into units per product using the shop's
own menu: a price per item and a share of takings that moves with the day of the
week, since sourdough sells at the weekend and pastries sell to the weekday
morning trade.

Nothing here is a second model and nothing here is scored. It is the shop's
recipe for turning money into trays, applied to the forecast and to both ends of
its 80% range, so the baker gets a range rather than a false single number.
"""

from __future__ import annotations

from dataclasses import dataclass

# Monday is 0. Shares are of that day's takings and sum to 1 for every weekday.
@dataclass(frozen=True)
class Product:
    key: str
    name: str
    unit: str
    price: float
    shares: tuple[float, ...]   # seven shares, Monday first
    batch: int                  # trays are baked in whole batches of this size


MENU: tuple[Product, ...] = (
    Product("sourdough", "Sourdough", "loaves", 7.50,
            (0.17, 0.17, 0.18, 0.19, 0.21, 0.26, 0.25), 6),
    Product("country-loaf", "Country loaf", "loaves", 6.25,
            (0.13, 0.13, 0.13, 0.13, 0.14, 0.16, 0.16), 6),
    Product("baguette", "Baguette", "sticks", 3.80,
            (0.11, 0.11, 0.11, 0.12, 0.13, 0.14, 0.13), 12),
    Product("croissant", "Croissant", "pastries", 4.20,
            (0.22, 0.22, 0.21, 0.21, 0.19, 0.16, 0.18), 12),
    Product("pain-au-chocolat", "Pain au chocolat", "pastries", 4.60,
            (0.15, 0.15, 0.15, 0.14, 0.13, 0.11, 0.12), 12),
    Product("cinnamon-bun", "Cinnamon bun", "buns", 5.10,
            (0.12, 0.12, 0.12, 0.11, 0.10, 0.09, 0.09), 9),
    Product("focaccia", "Focaccia", "trays", 9.40,
            (0.10, 0.10, 0.10, 0.10, 0.10, 0.08, 0.07), 4),
)


def _units(revenue: float, product: Product, weekday: int) -> float:
    return revenue * product.shares[weekday] / product.price


def round_to_batch(units: float, batch: int) -> int:
    """Bakers work in whole trays, so round up to the next batch."""
    if units <= 0:
        return 0
    return int(-(-round(units) // batch) * batch)


def bake_list(forecast: float, low: float, high: float, weekday: int) -> list[dict]:
    """Units per product for one day, with the range the forecast allows."""
    rows = []
    for product in MENU:
        middle = _units(forecast, product, weekday)
        rows.append({
            "key": product.key,
            "name": product.name,
            "unit": product.unit,
            "low": int(round(_units(low, product, weekday))),
            "expected": int(round(middle)),
            "high": int(round(_units(high, product, weekday))),
            "bake": round_to_batch(middle, product.batch),
            "batch": product.batch,
        })
    return rows


def shares_sum(weekday: int) -> float:
    return sum(p.shares[weekday] for p in MENU)
