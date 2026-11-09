"""LQ-20261107-1613 — the frozen-output contract: a lane that keeps succeeding while its output fingerprint stays
identical across its last k runs and its inputs move is DEGRADED, with one system_health escalation per cooldown and
one rerun proposal, never a send.

ANCHOR: FROZEN_OUTPUT_20261109

Database cases need an isolated postgres (synthetic rows only), e.g.:
    FROZEN_TEST_DSN=postgresql://postgres:x@127.0.0.1:55435/frozentest pytest tests/test_frozen_output_20261109.py
They refuse any DSN naming trade_ai. The pure cases run everywhere.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import frozen_output_monitor as mon  # noqa: E402
from lib import frozen_output as fo  # noqa: E402

DSN = os.getenv("FROZEN_TEST_DSN")
CONTRACTS = ROOT / "config" / "frozen_output_contracts.json"


def _runs(outputs, inputs):
    return [{"at": f"t{i}", "output_fp": o, "input_fp": n} for i, (o, n) in enumerate(zip(outputs, inputs))]


# ---------------------------------------------------------------- pure evaluator

def test_verdicts_over_the_newest_k_runs():
    assert fo.evaluate(_runs("aaaa", "abcd"), 4)["verdict"] == "FROZEN"
    assert fo.evaluate(_runs("aaab", "abcd"), 4)["verdict"] == "OK"
    assert fo.evaluate(_runs("aaaa", "xxxx"), 4)["verdict"] == "STABLE_INPUTS"
    short = fo.evaluate(_runs("aaa", "abc"), 4)
    assert short["verdict"] == "UNVERIFIABLE" and short["reason"] == "insufficient_history"
    # only the newest k count: an old output change does not hide a frozen recent window
    assert fo.evaluate(_runs("baaaa", "abcde"), 4)["verdict"] == "FROZEN"
    missing = _runs("aaaa", "abcd")
    missing[2]["input_fp"] = None
    assert fo.evaluate(missing, 4)["reason"] == "fingerprint_missing"
    assert {fo.HEALTH[v] for v in fo.VERDICTS} == {"OK", "DEGRADED", "UNVERIFIABLE"}


def test_fingerprint_is_canonical_and_excludes_per_run_ids():
    a = {"label": "x", "conf": 0.62, "inputs": {"vix": 22.1, "_indicator_snapshot_id": 1}}
    b = {"conf": 0.6200000001, "label": "x", "inputs": {"_indicator_snapshot_id": 2, "vix": 22.1}}
    assert fo.fingerprint(a, ["label", "conf"]) == fo.fingerprint(b, ["label", "conf"])
    ex = ["inputs._indicator_snapshot_id"]
    assert fo.fingerprint(a, ["inputs"], ex) == fo.fingerprint(b, ["inputs"], ex)
    assert fo.fingerprint(a, ["inputs"]) != fo.fingerprint(b, ["inputs"])
    assert fo.fingerprint({}, ["label"]) is None


def test_every_frozen_run_is_a_successful_count_and_still_frozen():
    """What the per-attempt output verdict sees (one row written per run, produced_count 1) is identical for a
    frozen window and a healthy one; only the window verdict tells them apart."""
    frozen, healthy = _runs("aaaa", "abcd"), _runs("abab", "abcd")
    assert len(frozen) == len(healthy) == 4
    assert fo.evaluate(frozen, 4)["verdict"] == "FROZEN" and fo.evaluate(healthy, 4)["verdict"] == "OK"


def test_contract_validation_refuses_bad_contracts():
    good = json.loads(CONTRACTS.read_text())["contracts"][0]
    assert fo.validate_contract(good) == []
    for mutate, needle in (
        (lambda c: c.update(k=2), "k must be"),
        (lambda c: c.update(k=True), "k must be"),
        (lambda c: c["source"].update(table="x; drop table y"), "source.table"),
        (lambda c: c["source"]["input_join"].update(value_column="Value"), "input_join.value_column"),
        (lambda c: c.update(input_fields=["regime_label"]), "both output and input"),
        (lambda c: c.update(input_exclude=["inputs"]), "input_exclude"),
        (lambda c: c.update(why=" "), "why is required"),
    ):
        c = copy.deepcopy(good)
        mutate(c)
        assert any(needle in e for e in fo.validate_contract(c)), needle


def test_shipped_contracts_are_valid_and_name_registry_lanes():
    doc = json.loads(CONTRACTS.read_text())
    lanes = [ln["lane_id"] for ln in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]]
    assert fo.validate_document(doc, lanes) == []
    assert "market-regime-classifier" in {c["lane_id"] for c in doc["contracts"]}
    dup = {**doc, "contracts": doc["contracts"] * 2}
    assert any("duplicate" in e for e in fo.validate_document(dup))


# ---------------------------------------------------------------- monitor without a database

def test_no_database_is_unverifiable_not_a_crash(monkeypatch):
    def boom(**_):
        raise RuntimeError("down")
    monkeypatch.setattr(mon, "_connect", lambda read_only: boom())
    out = mon.run(apply=True, contracts=mon.load_contracts(),
                  escalate=lambda ln: pytest.fail("must not escalate without a reading"))
    assert out["verdict"] == "UNVERIFIABLE" and out["proposals"] == [] and out["escalated"] == []


class _Conn:
    def __init__(self):
        self.commits = self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_dry_run_proposes_but_never_escalates_or_commits(monkeypatch):
    monkeypatch.setattr(mon, "load_history", lambda conn, c: _runs("aaaa", "abcd"))
    conn = _Conn()
    out = mon.run(apply=False, contracts=mon.load_contracts(), conn=conn,
                  escalate=lambda ln: pytest.fail("dry run must not escalate"))
    assert out["verdict"] == "DEGRADED" and out["frozen"] == 1 and out["sends"] == 0
    assert out["proposals"] == [{"action": "rerun_with_fresh_inputs", "lane_id": "market-regime-classifier",
                                 "window_to": "t3"}]
    assert conn.commits == 0


def test_one_unreadable_contract_is_that_lanes_verdict(monkeypatch):
    def hist(conn, c):
        if c["lane_id"] == "broken":
            raise LookupError("relation missing")
        return _runs("abab", "abcd")
    monkeypatch.setattr(mon, "load_history", hist)
    contracts = mon.load_contracts()
    contracts = contracts + [{**contracts[0], "lane_id": "broken"}]
    conn = _Conn()
    out = mon.run(apply=False, contracts=contracts, conn=conn)
    by = {ln["lane_id"]: ln for ln in out["lanes"]}
    assert by["broken"]["verdict"] == "UNVERIFIABLE" and by["broken"]["reason"] == "read_error:LookupError"
    assert by["market-regime-classifier"]["verdict"] == "OK" and out["verdict"] == "OK" and conn.rollbacks == 1


# ---------------------------------------------------------------- isolated postgres (emulated slot)

@pytest.fixture
def pg():
    if not DSN:
        pytest.skip("FROZEN_TEST_DSN not set (isolated postgres only)")
    if "trade_ai" in DSN:
        pytest.fail("refusing a DSN that names trade_ai: synthetic database only")
    import psycopg2
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute("""
            DROP TABLE IF EXISTS market_regime_indicators, market_regime_snapshots, alert_events;
            CREATE TABLE market_regime_snapshots (id serial PRIMARY KEY, created_at timestamptz NOT NULL,
                regime_label text, confidence numeric, volatility_state text, trend_state text,
                breadth_state text, inputs jsonb);
            CREATE TABLE market_regime_indicators (id serial PRIMARY KEY, snapshot_id integer,
                indicator_key text, value numeric);
            CREATE TABLE alert_events (id serial PRIMARY KEY, created_at timestamptz DEFAULT now(),
                alert_type text, source_script text, parsed_payload jsonb);
        """)
    conn.commit()
    yield conn
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS market_regime_indicators, market_regime_snapshots, alert_events")
    conn.commit()
    conn.close()


def _seed(conn, labels, vix_values):
    with conn.cursor() as cur:
        for i, (label, vix) in enumerate(zip(labels, vix_values)):
            snap = 100 + i
            cur.execute(
                "INSERT INTO market_regime_snapshots (created_at, regime_label, confidence, volatility_state,"
                " trend_state, breadth_state, inputs) VALUES (now() - make_interval(hours => %s), %s, 0.62,"
                " 'high', 'down', 'not_measured', %s)",
                (24 - i, label, json.dumps({"_indicator_snapshot_id": snap, "vix_bucket": "high"})))
            cur.execute("INSERT INTO market_regime_indicators (snapshot_id, indicator_key, value) VALUES (%s, 'vix', %s)",
                        (snap, vix))
    conn.commit()


def _record(conn):
    def esc(ln):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO alert_events (alert_type, source_script, parsed_payload) VALUES"
                        " ('system_health', %s, %s)", (mon.ESCALATION_SOURCE, json.dumps({"lane_id": ln["lane_id"]})))
        return True
    return esc


def test_emulated_slot_frozen_rows_dry_run_then_apply_escalates_once(pg):
    contracts = mon.load_contracts()
    # same label and confidence across 4 runs; the joined indicator values move, the inputs blob does not
    _seed(pg, ["high_volatility"] * 4, [21.0, 22.5, 24.0, 23.1])
    dry = mon.run(apply=False, contracts=contracts, conn=pg, escalate=lambda ln: pytest.fail("dry run escalated"))
    lane = dry["lanes"][0]
    assert (lane["verdict"], lane["distinct_inputs"], lane["distinct_outputs"]) == ("FROZEN", 4, 1)
    with pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM alert_events")
        assert cur.fetchone()[0] == 0

    first = mon.run(apply=True, contracts=contracts, conn=pg, escalate=_record(pg))
    assert first["escalated"] == ["market-regime-classifier"] and first["sends"] == 0
    again = mon.run(apply=True, contracts=contracts, conn=pg, escalate=_record(pg))
    assert again["verdict"] == "DEGRADED" and again["escalated"] == []
    assert again["escalation_suppressed_cooldown"] == ["market-regime-classifier"]


def test_emulated_slot_moving_output_and_stable_inputs_are_ok(pg):
    contracts = mon.load_contracts()
    _seed(pg, ["high_volatility", "risk_off", "high_volatility", "risk_off"], [21.0, 22.5, 24.0, 23.1])
    assert mon.run(apply=False, contracts=contracts, conn=pg)["lanes"][0]["verdict"] == "OK"
    with pg.cursor() as cur:
        cur.execute("TRUNCATE market_regime_snapshots, market_regime_indicators")
    pg.commit()
    _seed(pg, ["risk_off"] * 4, [20.0] * 4)
    assert mon.run(apply=False, contracts=contracts, conn=pg)["lanes"][0]["verdict"] == "STABLE_INPUTS"
