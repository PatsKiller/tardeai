"""yfinance_info_snapshot is retired from the prospectus; its usable facts already come from Finviz (LQ-20261107-249).

Live 2026-11-07: ``yfinance_info_snapshot`` has never existed on this host. The migration
(``migrations/2026_10_10_yfinance_info_snapshot.sql``) is in the repo and has never been applied —
``to_regclass('public.yfinance_info_snapshot')`` is NULL — so the reader could only ever report a failed read, and
the owner lane fails every slot with ``unconfigured``.

Retiring the reader loses no reported fact. Of the seven fields it projected, institutional holding and short % of
float are already published from the Finviz enrichment cache through ``inputs.assemble`` →
``blocks.ownership_flows`` (source "Finviz enrichment cache"), and the other five — EV/EBITDA, revenue growth yoy,
5-year average dividend yield, total debt $, EBITDA $ — have no house source at all. These tests drive the shipped
``assemble`` with a synthetic Finviz record to prove the two survive the retirement, and pin the mapping so nobody
quietly rewires a reader back to the dead store.

Hermetic: synthetic ``ZZ*`` record only; no DB, no network, no provider call.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import domains as dm  # noqa: E402
from scripts.lib.prospectus import load_config  # noqa: E402
from scripts.lib.prospectus.inputs import Bundle, assemble  # noqa: E402

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc)
SYM = "ZZTEST"

# A Finviz enrichment record carrying the two ownership fields; synthetic throughout.
REC = {
    "company": "Synthetic Test Co",
    "industry": "Widgets",
    "cached_at": "2026-11-07T18:00:00Z",
    "inst_own_pct": 62.0,
    "inst_trans_pct": 1.5,
    "insider_own_pct": 4.0,
    "insider_trans_pct": -0.5,
    "short_float_pct": 3.1,
    "short_ratio": 2.4,
}


class _Sources:
    """The one method ``assemble`` needs; every other source is optional and fails into coverage."""

    def __init__(self, rec: dict | None):
        self._rec = rec

    def enrichment_cache(self) -> dict:
        return {SYM: dict(self._rec)} if self._rec else {}


def _mapping() -> dict:
    return {"yfinance_info_snapshot": load_config()["registry_domains"]["yfinance_info_snapshot"]}


def _row(bundle: Bundle) -> dict:
    return dm.read_all(dm.Ctx(sources=_Sources(None), bundle=bundle, now=NOW), _mapping())["domains"][0]


# ── the retirement itself ───────────────────────────────────────────────────────────────────────────────────────


def test_no_reader_remains_for_the_retired_store():
    assert "yfinance_info_snapshot" not in dm.READERS, "the retired domain still has a reader wired"
    assert not hasattr(dm, "r_yfinance"), "r_yfinance is back"
    src = (ROOT / "scripts/lib/prospectus/domains.py").read_text()
    assert "data_broker.yfinance_info" not in src, "a prospectus reader still reaches the never-created store"


def test_the_domain_is_covered_by_the_finviz_fundamentals_path():
    spec = load_config()["registry_domains"]["yfinance_info_snapshot"]
    assert spec.get("covered_by") == ["fundamentals"], spec
    assert "reader" not in spec, spec
    assert len(str(spec.get("note") or "").strip()) >= 20, "the mapping must say why the reader is gone"


# ── the domain row grades from Finviz coverage, never as a broken source ───────────────────────────────────────


def test_a_symbol_the_finviz_cache_carries_grades_used():
    b = Bundle(symbol=SYM, scope="watch", name=SYM)
    b.cover("fundamentals", "used", as_of=NOW, key=True, detail="Finviz enrichment cache")
    row = _row(b)
    assert row["status"] == "used", row
    assert row["reason"] == "fundamentals=used", row


def test_a_symbol_the_finviz_cache_does_not_carry_grades_empty_and_quiet():
    # No coverage row means "the cache had nothing for this symbol" — an empty symbol, not a failed source.
    row = _row(Bundle(symbol=SYM, scope="watch", name=SYM))
    assert row["status"] == "empty", row
    assert row["reason"] == "not attempted", row


# ── no loss: the two facts the retired reader emitted are published from Finviz ────────────────────────────────


def test_the_two_facts_it_projected_are_published_from_the_finviz_cache():
    b = assemble(_Sources(REC), SYM, "watch", now=NOW)
    by_label = {f["label"]: f for f in b.facts}
    inst = by_label["Institutional ownership %"]
    short = by_label["Short interest, % of float"]
    assert inst["value"] == 62.0 and "Finviz" in inst["source"], inst
    assert short["value"] == 3.1 and "Finviz" in short["source"], short
    assert b.blocks["ownership_flows"]["institutional_pct"] == 62.0, b.blocks["ownership_flows"]
    assert b.blocks["ownership_flows"]["short_float_pct"] == 3.1, b.blocks["ownership_flows"]
    # The retired reader's labels are gone: nothing in the bundle claims a yfinance snapshot.
    assert not [f for f in b.facts if "yfinance snapshot" in str(f["label"])], b.facts
