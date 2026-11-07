"""The Finviz cache's ``as_of`` leaves the producer in UTC ISO-8601, not in the file's ``… ET`` spelling.

``finviz_quote_cache.json`` stamps ``last_fetched`` as ``"%Y-%m-%d %H:%M:%S ET"`` (what the repricer writes).
``finviz_cache()`` handed that spelling straight to every consumer. Measured consumers:

* ``cio_ask_research._src_price`` -> ``make_fact`` -> ``_iso()`` (``datetime.fromisoformat``) returns None, so
  the price fact is **dropped** with ``FactRejected`` (reproduced live against the real cache);
* ``prospectus.domains.r_quote`` -> ``Bundle.add`` stores the ET string verbatim, so a fact carries a
  timestamp no strict parser can read and the day-granularity age check truncates it to the date;
* ``advisory_desk._age_hours`` returns **None** for the spelling (its ``"T" in ts`` test matches the "T" in
  "ET" and ``fromisoformat`` then raises), i.e. "age unknown" rather than an age. Latent today: the holdings
  document it reads carries a date-only per-row ``as_of``, so it is not fed this spelling on this host;
* ``reentry_rules._age_hours`` (which ``reentry_decision_desk`` and ``watch_decision_desk`` actually use)
  parses the ET spelling correctly, so re-entry and watch freshness are not affected.

``_age_s``/``newest_clock`` are safe for the same reason, which is why the defect never showed on the
portfolio page. Normalising in ``finviz_cache()`` fixes every consumer at once, including ``resolve_mark``'s
own cache rung. Fakes only: no network, no database, no broker.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import portfolio_positions as pp  # noqa: E402
from lib.data_broker import advisory_desk as ad  # noqa: E402

# 2026-11-01 ended US daylight time: 07 Nov is EST (UTC-5), 05 Oct is EDT (UTC-4).
WINTER_ET = "2026-11-07 01:45:01 ET"
WINTER_UTC = "2026-11-07T06:45:01Z"
SUMMER_ET = "2026-10-05 23:50:00 ET"
SUMMER_UTC = "2026-10-06T03:50:00Z"
NOW = dt.datetime(2026, 11, 7, 6, 50, tzinfo=dt.timezone.utc)


def _cache(tmp_path: Path, rows: dict) -> Path:
    p = tmp_path / "finviz_quote_cache.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


def _one(tmp_path: Path, row: dict) -> dict:
    doc = pp.finviz_cache(_cache(tmp_path, {"ZZAA": row}))
    return doc["ZZAA"]


# ── the producer ────────────────────────────────────────────────────────────────────────────────


def test_et_spelling_leaves_the_cache_as_utc_iso(tmp_path):
    assert _one(tmp_path, {"price": 18.0, "last_fetched": WINTER_ET})["as_of"] == WINTER_UTC


def test_the_offset_follows_daylight_time(tmp_path):
    """A summer stamp is EDT (UTC-4): a fixed -5 would silently shift every price by an hour Mar-Nov."""
    assert _one(tmp_path, {"price": 18.0, "last_fetched": SUMMER_ET})["as_of"] == SUMMER_UTC


@pytest.mark.parametrize("given", [WINTER_UTC, "2026-11-07T06:45:01+00:00", "2026-11-07T06:45:01+00:00"])
def test_an_iso_stamp_is_kept_and_canonicalised(tmp_path, given):
    assert _one(tmp_path, {"price": 18.0, "last_fetched": given})["as_of"] == WINTER_UTC


def test_last_updated_still_serves_when_last_fetched_is_absent(tmp_path):
    assert _one(tmp_path, {"price": 18.0, "last_updated": WINTER_ET})["as_of"] == WINTER_UTC


def test_an_unparseable_stamp_is_passed_through_not_invented(tmp_path):
    """Pass-through, not None: a display consumer may still show it, and freshness already reads it as unknown."""
    assert _one(tmp_path, {"price": 18.0, "last_fetched": "yesterday-ish"})["as_of"] == "yesterday-ish"


def test_a_missing_stamp_stays_missing(tmp_path):
    assert _one(tmp_path, {"price": 18.0})["as_of"] is None


def test_price_and_freshness_are_unchanged_by_the_normalisation(tmp_path):
    row = _one(tmp_path, {"price": 18.0, "last_fetched": WINTER_ET})
    assert row["price"] == 18.0
    assert pp._age_s(row["as_of"], NOW) == 299.0  # 06:45:01Z -> 06:50:00Z, the same instant as before


# ── the consumers that were dropping or misreading it ───────────────────────────────────────────


def test_the_strict_fact_builder_accepts_the_price_fact(tmp_path):
    """This is the measured failure: _src_price -> make_fact -> FactRejected 'fact without as_of'."""
    from lib import cio_ask_research as car

    as_of = _one(tmp_path, {"price": 18.0, "last_fetched": WINTER_ET})["as_of"]
    fact = car.make_fact(
        source="market.quote",
        family="price",
        kind="last_price",
        subject_key="ZZAA",
        claim="ZZAA last price 18.0",
        as_of=as_of,
        citation={"ref": "finviz_quote_cache"},
        value=18.0,
        symbol="ZZAA",
    )
    assert fact.as_of == WINTER_UTC  # not dropped

    with pytest.raises(car.FactRejected):
        car.make_fact(
            source="market.quote",
            family="price",
            kind="last_price",
            subject_key="ZZAA",
            claim="ZZAA last price 18.0",
            as_of=WINTER_ET,  # the raw cache spelling: the fact did not survive this
            citation={"ref": "finviz_quote_cache"},
            value=18.0,
            symbol="ZZAA",
        )


def test_advisory_age_hours_reads_the_produced_stamp_instead_of_none(tmp_path):
    """``advisory_desk._age_hours`` has no ET branch and its ``"T" in ts`` test matches the "T" of "ET".

    Then ``fromisoformat`` raises and the helper answers None ("age unknown"), which its holdings caller reads
    as not-stale. The normalised stamp is a number again. Latent today (that caller is fed a date-only per-row
    ``as_of``); this asserts the helper's real behaviour so the reason for normalising at the producer stays
    visible.
    """
    as_of = _one(tmp_path, {"price": 18.0, "last_fetched": WINTER_ET})["as_of"]
    assert ad._age_hours(WINTER_ET) is None
    assert ad._age_hours(as_of) >= 0.0


def test_the_reentry_rules_read_the_et_spelling_either_way(tmp_path):
    """The re-entry and watch desks use ``reentry_rules._age_hours``, which does parse " ET" — not affected."""
    from lib import reentry_rules

    as_of = _one(tmp_path, {"price": 18.0, "last_fetched": WINTER_ET})["as_of"]
    raw_age = reentry_rules._age_hours(WINTER_ET)
    assert raw_age is not None
    assert raw_age == pytest.approx(reentry_rules._age_hours(as_of), abs=0.01)


def test_resolve_mark_carries_the_normalised_as_of_and_stays_live(tmp_path, monkeypatch):
    from datetime import datetime

    monkeypatch.setattr(pp, "store_path", lambda root=None: tmp_path / "holdings.json")
    _cache(tmp_path, {"ZZAA": {"price": 18.0, "last_fetched": WINTER_ET}})
    m = pp.resolve_mark({"symbol": "ZZAA", "shares": 10}, now=datetime(2026, 11, 7, 6, 50, tzinfo=dt.timezone.utc))
    assert m["source"] == "finviz" and m["price"] == 18.0
    assert m["as_of"] == WINTER_UTC
    assert (m["live"], m["stale"]) == (True, False)


def test_the_prospectus_bundle_keeps_a_parseable_as_of(tmp_path):
    from lib.prospectus import inputs

    as_of = _one(tmp_path, {"price": 18.0, "last_fetched": WINTER_ET})["as_of"]
    b = inputs.Bundle("ZZAA", "position", "Zeta Alpha")
    b.add("valuation", "Last price", value=18.0, source="Finviz", as_of=as_of)
    assert b.facts[0]["as_of"] == WINTER_UTC
    # The bundle stores as_of verbatim (its _iso is a pass-through), so the raw cache spelling reached the
    # generated prospectus as an unparseable timestamp — provenance the page could not check.
    b.add("valuation", "Last price (old producer)", value=18.0, source="Finviz", as_of=WINTER_ET)
    assert b.facts[1]["as_of"] == WINTER_ET
