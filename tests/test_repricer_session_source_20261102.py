"""Holdings reprice around the clock on trading days; reprice_source must name the real session.

Operator 2026-11-02: "repricing needs to run 24 hours as we have 24-hour markets". The old two-way
split (09:30-16:00 = finviz_live, everything else = finviz_afterhours) labelled a 07:30 ET
pre-market reprice "after-hours" on the Command Center header.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location("portfolio_repricer_s", ROOT / "scripts" / "portfolio_repricer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("stamp, source", [
    ("2026-11-02 03:00", "finviz_overnight"),    # Mon before pre-market
    ("2026-11-02 04:00", "finviz_premarket"),
    ("2026-11-02 07:30", "finviz_premarket"),    # the mislabelled header
    ("2026-11-02 09:29", "finviz_premarket"),
    ("2026-11-02 09:30", "finviz_live"),
    ("2026-11-02 15:59", "finviz_live"),
    ("2026-11-02 16:00", "finviz_afterhours"),
    ("2026-11-02 19:59", "finviz_afterhours"),
    ("2026-11-02 20:00", "finviz_overnight"),
    ("2026-11-01 21:00", "finviz_overnight"),    # Sunday evening, 24-hour session open
    ("2026-11-26 10:00", "finviz_overnight"),    # Thanksgiving: no regular session
    ("2026-11-27 14:00", "finviz_afterhours"),   # early close 13:00
])
def test_reprice_source_names_the_session(stamp, source):
    r = _load()
    assert r._reprice_source(datetime.strptime(stamp, "%Y-%m-%d %H:%M")) == source


def test_every_source_has_a_header_label():
    labels = (ROOT / "apps/command-center-v3/src/lib/displayLabels.ts").read_text()
    stamps = (ROOT / "apps/command-center-v3/src/lib/pricingStamp.ts").read_text()
    for src in ("finviz_live", "finviz_premarket", "finviz_afterhours", "finviz_overnight"):
        assert f"{src}:" in labels, src
        assert f"{src}:" in stamps, src


def test_no_fixed_utc_offset_fallback():
    text = (ROOT / "scripts/portfolio_repricer.py").read_text()
    assert "timedelta(hours=4)" not in text and "timedelta(hours=-4)" not in text
