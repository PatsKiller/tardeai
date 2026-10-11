"""Incident fan-in severity for the W1-9 breach kinds (operator ruling R11, 2026-10-11: "R11 yes").

STALE_OUTPUT takes its freshness contract's own `severity` (carried by supervisor_breach_detector on the row as
evidence.severity): P1 -> P1, P2 -> P2, P3 -> P3 (P0 -> P1); a row without one is P2, never the P3 default.
INPUT_STARVATION: STARVED -> P2, NO_ELIGIBLE_INPUT / UNKNOWN -> P3. Items stay `<lane>:<KIND>` so
n8n_siem_bridge.lane_kind still splits them; STALE_OUTPUT is one finding per contract, INPUT_STARVATION one per
status. Fixture ledgers under tmp_path only; the live state root and the DB are never read.

COVERS = ["scripts/n8n_incident_fanin.py"]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts.lib import n8n_siem_bridge as siem  # noqa: E402

import supervisor_breach_detector as sbd  # noqa: E402

NOW = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)


def _contract(key: str, severity: str | None, lane_id: str | None = None) -> dict:
    c = {"key": key, "signal": {"kind": "file_mtime", "path": f"data/{key}.json"}, "max_age_hours": 24,
         "basis": "wall_clock", "source": "test", "replaces": ["job-coverage-monitor"]}
    if severity is not None:
        c["severity"] = severity
    if lane_id:
        c["lane_id"] = lane_id
    return c


def _stale_rows(contracts: list[dict], lanes: list[dict] | None = None) -> list[dict]:
    """Real detector rows (detect_freshness), every signal never produced."""
    return sbd.detect_freshness(contracts=contracts, lanes=lanes or [], sla_by_lane={},
                                observe=lambda _sig: {"readable": True, "last_output_at": None}, now=NOW)


def _starvation_rows(statuses: list[tuple[str, str]]) -> list[dict]:
    return sbd.detect_input_starvation(liveness={"lanes": [{"lane": lane, "status": st, "attempted": 3, "produced": 0}
                                                           for lane, st in statuses]}, now=NOW)


def _ledger(tmp_path: Path, rows: list[dict]) -> Path:
    rt = tmp_path / "data" / "runtime"
    rt.mkdir(parents=True, exist_ok=True)
    (rt / "supervisor_breaches.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return rt


def _by_item(found: list[dict]) -> dict[str, dict]:
    return {f["item"]: f for f in found}


def test_detector_stale_output_row_carries_the_contract_severity():
    (row,) = _stale_rows([_contract("pfm.x", "P1")])
    assert row["kind"] == "STALE_OUTPUT" and row["evidence"]["severity"] == "P1"


@pytest.mark.parametrize("contract_sev,want", [("P1", "P1"), ("P2", "P2"), ("P3", "P3"), ("P0", "P1"), ("p1", "P1")])
def test_stale_output_takes_the_contract_severity(contract_sev, want):
    (row,) = _stale_rows([_contract("sfm.x", contract_sev)])
    sev, basis = fanin.breach_severity(row)
    assert sev == want and basis == f"contract:{contract_sev}"


@pytest.mark.parametrize("contract_sev", [None, "", "HIGH", "P9"])
def test_stale_output_without_a_readable_severity_is_p2_never_the_p3_default(contract_sev):
    (row,) = _stale_rows([_contract("jcm.x", None)])
    row["evidence"]["severity"] = contract_sev
    assert fanin.breach_severity(row) == ("P2", "contract:missing->P2")


@pytest.mark.parametrize("status,want", [("STARVED", "P2"), ("NO_ELIGIBLE_INPUT", "P3"), ("UNKNOWN", "P3")])
def test_input_starvation_severity_by_status(status, want):
    (row,) = _starvation_rows([("lineage_completions", status)])
    assert fanin.breach_severity(row) == (want, f"liveness:{status}")


def test_other_kinds_keep_the_sev_map():
    assert fanin.breach_severity({"kind": "HUNG"}) == ("P1", "kind:HUNG")
    assert fanin.breach_severity({"kind": "NO_OUTPUT"}) == ("P2", "kind:NO_OUTPUT")
    assert fanin.breach_severity({"kind": "SOMETHING_NEW"}) == ("P3", "kind:SOMETHING_NEW")


def test_breach_findings_one_per_contract_and_status_with_r11_severity(tmp_path):
    lanes = [{"lane_id": "holdings-llm-refresh", "state": "ACTIVE"}]
    rows = _stale_rows([_contract("jcm.holdings_llm_refresh", "P2", lane_id="holdings-llm-refresh"),
                        _contract("sfm.news_articles", "P1"), _contract("pfm.trade_closed", "P3")], lanes)
    rows += _starvation_rows([("lineage_completions", "STARVED"), ("lineage_completions", "NO_ELIGIBLE_INPUT"),
                              ("memory_admissions", "UNKNOWN")])
    rows.append({"lane_id": "holdings-llm-refresh", "kind": "NO_OUTPUT", "state": "OPEN", "detected_at": NOW.isoformat(),
                 "evidence": {"basis": "cron"}})
    found = _by_item(fanin._breach_findings(_ledger(tmp_path, rows), NOW))
    assert {k: v["severity"] for k, v in found.items()} == {
        "holdings-llm-refresh/jcm.holdings_llm_refresh:STALE_OUTPUT": "P2",
        "freshness:sfm.news_articles:STALE_OUTPUT": "P1",
        "freshness:pfm.trade_closed:STALE_OUTPUT": "P3",
        "liveness:lineage_completions/STARVED:INPUT_STARVATION": "P2",
        "liveness:lineage_completions/NO_ELIGIBLE_INPUT:INPUT_STARVATION": "P3",
        "liveness:memory_admissions/UNKNOWN:INPUT_STARVATION": "P3",
        "holdings-llm-refresh:NO_OUTPUT": "P2",  # the producer lane's own NO_OUTPUT is a separate finding
    }
    assert found["freshness:sfm.news_articles:STALE_OUTPUT"]["severity_basis"] == "contract:P1"


def test_items_still_split_into_lane_and_kind_for_the_siem_bridge(tmp_path):
    rows = _stale_rows([_contract("jcm.a", "P2", lane_id="lane-a"), _contract("pfm.b", "P2")],
                       [{"lane_id": "lane-a", "state": "ACTIVE"}])
    rows += _starvation_rows([("lineage_completions", "STARVED")])
    kinds = {siem.lane_kind("breach_detector", f["item"]) for f in fanin._breach_findings(_ledger(tmp_path, rows), NOW)}
    assert kinds == {("lane-a/jcm.a", "STALE_OUTPUT"), ("freshness:pfm.b", "STALE_OUTPUT"),
                     ("liveness:lineage_completions/STARVED", "INPUT_STARVATION")}


def test_old_and_closed_rows_are_not_open_findings(tmp_path):
    (old,) = _stale_rows([_contract("pfm.old", "P1")])
    old["detected_at"] = (NOW - timedelta(hours=49)).isoformat()
    (closed,) = _stale_rows([_contract("pfm.closed", "P1")])
    closed["state"] = "CLOSED"
    assert fanin._breach_findings(_ledger(tmp_path, [old, closed]), NOW) == []


def test_collect_routes_breach_rows_through_breach_findings(tmp_path, monkeypatch):
    # Same isolation as the relay tests: every other collect() source reads files under tmp_path (absent) or is
    # stubbed, so no DB, no gateway and no live state root are touched.
    monkeypatch.setenv("TRADEAI_FANIN_LANE_REGISTRY", "0")
    monkeypatch.setenv("TRADEAI_FANIN_RUNS", "0")
    monkeypatch.setattr(fanin, "_outbox_findings", lambda now: [])
    monkeypatch.setattr(fanin, "PREV_RECEIPT", None)
    es = tmp_path / "expected_services.json"
    es.write_text(json.dumps({"schema": "ExpectedServices@v1", "units": []}))
    monkeypatch.setattr(fanin, "EXPECTED_SERVICES_PATH", es)
    _ledger(tmp_path, _stale_rows([_contract("sfm.ticker_prices", "P1")]))
    seen = []
    real = fanin._breach_findings
    monkeypatch.setattr(fanin, "_breach_findings", lambda rt, now: seen.append(rt) or real(rt, now))
    found = fanin.collect(tmp_path, NOW, prev={})
    assert seen == [tmp_path / "data" / "runtime"]
    (f,) = [f for f in found if f["source"] == "breach_detector"]
    assert f["item"] == "freshness:sfm.ticker_prices:STALE_OUTPUT" and f["severity"] == "P1"
