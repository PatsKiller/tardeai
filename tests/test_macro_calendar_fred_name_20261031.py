"""FRED renamed release 95; the calendar must still verify it (2026-10-31).

From 2026-10-23 every macro-calendar-refresh run failed id verification with
``95 (durable_goods): FRED name "Manufacturer's Shipments, Inventories, and Orders (M3) Survey"``
(n8n run receipts d:macro-calendar-refresh:dry_run:20261023T0505 … 20261025T0505). After three failures the
dispatcher's breaker opened, so no calendar was ever written and the Market Risk Engine's event category had no
CPI/NFP dates. The pattern now accepts the apostrophe before or after the s. A genuinely different name still
fails closed. No network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import macro_calendar_refresh as m  # noqa: E402

LIVE_NAMES_20261031 = {
    9: "Advance Monthly Sales for Retail and Food Services",
    10: "Consumer Price Index",
    27: "New Residential Construction",
    46: "Producer Price Index",
    50: "Employment Situation",
    53: "Gross Domestic Product",
    54: "Personal Income and Outlays",
    95: "Manufacturer's Shipments, Inventories, and Orders (M3) Survey",
    180: "Unemployment Insurance Weekly Claims Report",
}


def _releases(override: dict[int, str] | None = None) -> list[dict]:
    names = {**LIVE_NAMES_20261031, **(override or {})}
    return [
        {"id": r.release_id, "name": names.get(r.release_id, r.label), "press_release": True} for r in m.RELEASE_MAP
    ]


def test_fred_name_of_95_as_of_2026_10_31_verifies():
    rows = m.verify_release_ids(_releases())
    row = next(r for r in rows if r["release_id"] == 95)
    assert row["ok"] is True


@pytest.mark.parametrize(
    "name",
    [
        "Manufacturers' Shipments, Inventories, and Orders",
        "Manufacturer's Shipments, Inventories, and Orders (M3) Survey",
        "Manufacturers Shipments, Inventories & Orders",
        "Advance Report on Durable Goods",
    ],
)
def test_known_spellings_of_95_verify(name):
    assert next(r for r in m.verify_release_ids(_releases({95: name})) if r["release_id"] == 95)["ok"]


def test_a_different_release_still_fails_closed():
    with pytest.raises(m.RefreshError):
        m.verify_release_ids(_releases({95: "Construction Spending"}))
