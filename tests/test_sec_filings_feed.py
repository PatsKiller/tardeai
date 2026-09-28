"""Wave 2 tranche 4 — SEC filings feed → FilingEvent@v1 → GIR EVENT nodes + detector material changes."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import sec_filings_feed as sff  # noqa: E402

NOW = dt.datetime(2026, 9, 28, 2, 0, tzinfo=dt.timezone.utc)
FILINGS = [
    {"form": "8-K", "filing_date": "2026-09-25", "accession_number": "0001-26-001", "items": "2.02,9.01", "sec_url": "https://www.sec.gov/x/1"},
    {"form": "10-Q", "filing_date": "2026-09-24", "accession_number": "0001-26-002", "items": "", "sec_url": "https://www.sec.gov/x/2"},
    {"form": "8-K", "filing_date": "2026-09-26", "accession_number": "0001-26-003", "items": "7.01", "sec_url": ""},
    {"form": "8-K", "filing_date": "2026-01-02", "accession_number": "0001-26-000", "items": "2.02", "sec_url": ""},   # outside window
    {"form": "8-K", "filing_date": "2026-09-26", "accession_number": "0001-26-004", "items": "9.01", "sec_url": ""},   # no mapped item
    {"form": "4", "filing_date": "2026-09-26", "accession_number": "0001-26-005", "items": "", "sec_url": ""},
]


def test_events_from_filings_maps_forms_and_is_stable():
    evs = sff.events_from_filings("dell", FILINGS, subject_guid="sg", issuer_guid="ig", cik="0000826083", since_days=7, now=NOW)
    by_acc = {e["accession"]: e for e in evs}
    assert set(by_acc) == {"0001-26-001", "0001-26-002", "0001-26-003"}
    e = by_acc["0001-26-001"]
    assert e["schema"] == "FilingEvent@v1" and e["symbol"] == "DELL" and e["form"] == "8-K"
    assert e["catalyst_type"] == "earnings" and e["severity"] == "high" and e["items"] == ["2.02", "9.01"]
    assert by_acc["0001-26-002"]["severity"] == "medium" and by_acc["0001-26-003"]["severity"] == "low"
    assert e["memory_behavior_influence"] == 0 and e["authority"] == "READ_ONLY_ADVISORY"
    again = sff.events_from_filings("DELL", FILINGS, subject_guid="sg", issuer_guid="ig", cik="0000826083", since_days=7, now=NOW)
    assert [x["event_guid"] for x in again] == [x["event_guid"] for x in evs]
    # a sibling listing of the same issuer names the SAME event
    assert sff.event_guid("ig", "1", "8-K", "0001-26-001") == e["event_guid"]
    assert sff.event_guid(None, "0000826083", "8-K", "0001-26-001") != e["event_guid"]  # no issuer → CIK namespace


def test_ticker_map_cache_and_universe(tmp_path):
    calls = []

    def fetcher(url):
        calls.append(url)
        return {"0": {"cik_str": 826083, "ticker": "DELL", "title": "Dell"}, "1": {"cik_str": 1133421, "ticker": "NOC", "title": "Northrop"}}

    m = sff.load_ticker_map(tmp_path, fetcher, now=NOW)
    assert m == {"DELL": "0000826083", "NOC": "0001133421"} and len(calls) == 1
    m2 = sff.load_ticker_map(tmp_path, fetcher, now=NOW + dt.timedelta(hours=1))
    assert m2 == m and len(calls) == 1                         # served from the cache inside the TTL
    (tmp_path / "data" / "cio").mkdir(parents=True)
    (tmp_path / "data" / "cio" / "holdings_snapshot_latest.json").write_text(json.dumps({"holdings": [{"symbol": "noc"}, {"symbol": "12507E201"}, {"symbol": "NOC"}]}))
    assert sff.universe(tmp_path, 10)[:1] == ["NOC"]            # alpha tickers only, deduped, held first


def test_existing_guids_dedup(tmp_path):
    p = tmp_path / "f.jsonl"
    p.write_text(json.dumps({"event_guid": "a"}) + "\nnot json\n" + json.dumps({"event_guid": "b"}) + "\n")
    assert sff.existing_guids(p) == {"a", "b"} and sff.existing_guids(tmp_path / "missing") == set()


def test_projector_projects_events_and_affected_by_edges(tmp_path):
    import gir_projector as gp
    (tmp_path / "data" / "cio").mkdir(parents=True); (tmp_path / "data" / "runtime").mkdir(parents=True)
    reg = {"entities": {"e1": {"security_guid": "sg1", "ticker_alias": "DELL", "active": True, "identity_status": "CONFIRMED"}}, "by_symbol": {}}
    (tmp_path / "data" / "runtime" / "identity_registry.json").write_text(json.dumps(reg))
    evs = sff.events_from_filings("DELL", FILINGS[:2], subject_guid="sg1", issuer_guid="ig", cik="1", since_days=7, now=NOW)
    evs.append({**evs[0], "event_guid": "orphan", "subject_guid": None, "symbol": "ZZZZ", "accession": "x"})
    (tmp_path / "data" / "cio" / "sec_filing_events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in evs))
    pj = gp.build(tmp_path, now=NOW, env={})
    ev_nodes = [g for g in pj.entities if g.startswith("EVENT:")]
    assert len(ev_nodes) == 3 and pj.counts["filing_events"] == 3 and pj.counts["filing_events_unresolved"] == 1
    edges = [e for e in pj.edges.values() if e["relation"] == "AFFECTED_BY"]
    assert len(edges) == 2 and all(e["to_guid"] == "SEC:sg1" and e["from_guid"].startswith("EVENT:") for e in edges)
    env = pj.envelopes[f"EVENT:{evs[0]['event_guid']}"]
    assert env["freshness"]["state"] == "IMMUTABLE" and env["memory"]["catalyst_type"] == "earnings"
    assert pj.entities[ev_nodes[0]]["class"] == "MARKET" and pj.entities[ev_nodes[0]]["kind"] == "EVENT"
    assert "sec_filing_events" in gp._source_fingerprints(tmp_path, {})


def test_detector_new_filings_only_high_severity_tracked_and_recent(tmp_path):
    import material_change_detector as mcd
    evs = sff.events_from_filings("DELL", FILINGS[:3], subject_guid="sg", issuer_guid="ig", cik="1", since_days=7, now=NOW)
    evs += sff.events_from_filings("ZZZZ", FILINGS[:1], subject_guid="sg2", issuer_guid="ig2", cik="2", since_days=7, now=NOW)
    old = {**evs[0], "event_guid": "old", "observed_at": (NOW - dt.timedelta(hours=100)).isoformat()}
    feed = tmp_path / "feed.jsonl"
    feed.write_text("".join(json.dumps(e) + "\n" for e in evs + [old]))
    syms = {"DELL": {"reasons": {"held"}, "precedence": 90}}
    changes, stats = mcd.new_filings(syms, feed_path=feed, now=NOW + dt.timedelta(hours=1))
    assert stats["fired"] == 1 and stats["untracked"] == 1 and stats["below_severity"] == 2 and stats["outside_window"] == 1
    c = changes[0]
    assert c["kind"] == "sec_filing" and c["symbol"] == "DELL" and c["magnitude"] == 3.0 and c["precedence"] == 90
    assert c["evidence"]["catalyst_type"] == "earnings" and c["evidence"]["feed"] == "sec_filing_events"
    assert mcd.change_guid(c["symbol"], c["kind"], c["observed_at"]) == mcd.change_guid("DELL", "sec_filing", "2026-09-25T00:00:00+00:00")
    assert mcd.new_filings(syms, feed_path=tmp_path / "missing", now=NOW)[1]["feed"] == "absent"
