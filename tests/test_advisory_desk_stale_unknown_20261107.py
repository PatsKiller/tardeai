"""LQ-20261107-36 — the holdings freshness gate treats an UNDATED snapshot as fresh.

``advisory_desk._age_hours`` answered ``None`` for the ``"… ET"`` spelling its own price state writes
(the ``"T" in ts`` ISO test matches the **T of "ET"**, ``fromisoformat`` raises, the bare ``except``
answers ``None``), and ``_load_holdings`` read that ``None`` as *not stale*:

    "state": "STALE" if (age_h and age_h > STALE_HOURS_HOLDINGS) else "AVAILABLE"

So the 24 h holdings STALE gate could not fire on any stamp it could not read — it failed **open**.
The same ``None`` fed three ``_age_hours(x) / 24`` staleness builders, where it is a ``TypeError`` out
of the desk build.

The rule this pins: an unreadable (or absent) stamp is *unknown*, and unknown is stale — never fresh.
A recent stamp still reads AVAILABLE; the fix must not turn every holdings snapshot red.

Synthetic fixtures only; ``STATE_DIR`` is redirected to a tmp tree, no live state is read or written.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ET = ZoneInfo("America/New_York")


def _et(hours_ago: float) -> str:
    """The price state's own spelling: '%Y-%m-%d %H:%M:%S ET'."""
    return (datetime.now(ET) - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S ET")


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def _holdings(as_of: str | None, row_as_of: str | None = None) -> dict:
    doc: dict = {
        "portfolio_totals": {"total_value": 10_000.0, "cash_weight_pct": 5.0},
        "holdings": [
            {
                "symbol": "SYNTHA",
                "shares": 10,
                "market_value": 1_000.0,
                "price": 100.0,
                "as_of": row_as_of if row_as_of is not None else as_of,
            }
        ],
    }
    if as_of is not None:
        doc["as_of"] = as_of
    if row_as_of is None and as_of is None:
        doc["holdings"][0].pop("as_of", None)
    return doc


class HoldingsFreshnessGate(unittest.TestCase):
    def _state(self, doc: dict) -> dict:
        from lib.data_broker import advisory_desk

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "holdings.json").write_text(json.dumps(doc), encoding="utf-8")
            with patch.object(advisory_desk, "STATE_DIR", root):
                return advisory_desk._load_holdings()

    # ---- the fail-open defect -------------------------------------------------
    def test_old_et_stamp_is_stale(self) -> None:
        """48 h old in the '… ET' spelling: the gate must fire (base: AVAILABLE, age None)."""
        out = self._state(_holdings(_et(48)))
        self.assertEqual(out["state"], "STALE", f"age_hours={out['age_hours']!r}")
        self.assertIsNotNone(out["age_hours"])
        self.assertGreater(out["age_hours"], advisory_desk_stale_hours())

    def test_old_et_row_stamp_is_stale(self) -> None:
        """The row-level as_of carries the ET spelling in live state; same gate."""
        out = self._state(_holdings(_et(48), row_as_of=_et(48)))
        self.assertEqual(out["state"], "STALE")
        self.assertIsNotNone(out["age_hours"])

    def test_unparseable_stamp_is_stale_not_fresh(self) -> None:
        out = self._state(_holdings("last tuesday-ish"))
        self.assertEqual(out["state"], "STALE", "an unreadable stamp is unknown, and unknown is stale")
        self.assertIsNone(out["age_hours"], "the age stays honestly unknown — it is not invented")

    def test_undated_snapshot_is_stale_not_fresh(self) -> None:
        out = self._state(_holdings(None))
        self.assertEqual(out["state"], "STALE", "a snapshot that cannot be dated cannot be called current")
        self.assertIsNone(out["age_hours"])

    # ---- the ordinary path must not regress ----------------------------------
    def test_recent_et_stamp_is_available(self) -> None:
        out = self._state(_holdings(_et(1)))
        self.assertEqual(out["state"], "AVAILABLE")
        self.assertIsNotNone(out["age_hours"], "a readable ET stamp has a real age, not 'unknown'")
        self.assertLess(out["age_hours"], 3.0)

    def test_recent_iso_stamp_is_available(self) -> None:
        out = self._state(_holdings(_iso(1)))
        self.assertEqual(out["state"], "AVAILABLE")
        self.assertLess(out["age_hours"], 3.0)

    def test_old_iso_stamp_is_stale(self) -> None:
        out = self._state(_holdings(_iso(48)))
        self.assertEqual(out["state"], "STALE")
        self.assertGreater(out["age_hours"], advisory_desk_stale_hours())

    # ---- the helper itself ----------------------------------------------------
    def test_age_hours_reads_the_et_spelling(self) -> None:
        from lib.data_broker import advisory_desk

        age = advisory_desk._age_hours(_et(2))
        self.assertIsNotNone(age, "'… ET' must parse — 'T' in 'ET' must not defeat the ISO test")
        self.assertAlmostEqual(age, 2.0, delta=2.0)

    def test_age_hours_answers_none_only_when_there_is_no_readable_stamp(self) -> None:
        from lib.data_broker import advisory_desk

        self.assertIsNone(advisory_desk._age_hours(None))
        self.assertIsNone(advisory_desk._age_hours("   "))
        self.assertIsNone(advisory_desk._age_hours("not a stamp"))


class StalenessDaysBuilders(unittest.TestCase):
    """The same None used to reach ``/ 24`` in three builders: a TypeError out of the desk build."""

    def test_catalysts_survive_an_et_stamp(self) -> None:
        from lib.data_broker import advisory_desk

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "portfolio_news.json").write_text(
                json.dumps(
                    {
                        "generated_at": _et(24),
                        "scored_catalysts": [{"symbol": "SYNTHA", "headline": "synthetic catalyst"}],
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(advisory_desk, "STATE_DIR", root):
                out = advisory_desk._load_catalysts()
        rows = out["by_symbol"]["SYNTHA"]
        self.assertTrue(rows)
        days = rows[0]["staleness_days"]
        self.assertIsNotNone(days, "an ET stamp has an age; it is not None/24 (TypeError)")
        self.assertAlmostEqual(days, 1.0, delta=1.0)

    def test_earnings_survive_an_et_stamp(self) -> None:
        from lib.data_broker import advisory_desk

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "earnings_dates.json").write_text(
                json.dumps(
                    {
                        "SYNTHA": {"earnings_date": "2026-12-01", "fetched_at": _et(24)},
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(advisory_desk, "STATE_DIR", root):
                out = advisory_desk._load_earnings()
        row = out["by_symbol"]["SYNTHA"]
        self.assertIsNotNone(row["staleness_days"])
        self.assertAlmostEqual(row["staleness_days"], 1.0, delta=1.0)


def advisory_desk_stale_hours() -> float:
    from lib.data_broker.advisory_desk import STALE_HOURS_HOLDINGS

    return STALE_HOURS_HOLDINGS


if __name__ == "__main__":
    unittest.main(verbosity=2)
