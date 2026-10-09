"""n8n maturity B5.4: retry policies, verdicts, ledger additive schema, dead-letter queue + breaker, host CLI.

Hermetic: tmp_path ledgers and receipt files, fixed unix clock; no live ledger, no sockets, no sends.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_retry_policy as rp  # noqa: E402
from scripts.lib.n8n_coordination_ledger import (  # noqa: E402
    CoordinationLedger,
    LedgerError,
    LedgerRunStore,
    breaker_is_open,
)

POLICY_FILE = ROOT / "config" / "n8n_retry_policies.json"
SCHEMA_FILE = ROOT / "docs" / "implementation" / "n8n-maturity" / "schemas" / "retry-policy.schema.json"
T0 = 1_791_550_800.0  # fixed fake clock (2026-10-09 ET morning)
LANE = "demo-lane-report"


def _doc() -> dict:
    return json.loads(POLICY_FILE.read_text(encoding="utf-8"))


@pytest.fixture()
def store(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield LedgerRunStore(ledger)
    ledger.close()


@pytest.fixture()
def policies():
    return rp.load_policies(POLICY_FILE)


# ── policy file ──


def test_policy_file_loads_with_program_values(policies):
    assert policies.default_policy == "transient-2"
    assert policies.breaker_threshold == 3
    assert dict(policies.class_caps) == {"global": 3, "reserved_priority_max": 1, "heavy": 1, "llm": 1, "ingest": 1,
                                         "send": 1, "pipeline": 2, "learn": 1}
    assert set(policies.policies) == {"none", "transient-2", "transient-1-slow", "llm-transient"}
    assert policies.get() is rp.UNRESOLVED_POLICY and policies.get("bogus") is rp.UNRESOLVED_POLICY
    assert policies.default().name == "transient-2"
    assert policies.get("transient-2").backoff_s == (30, 120)
    assert len(policies.sha256) == 64
    with pytest.raises(TypeError):
        policies.class_caps["global"] = 9  # type: ignore[index]


def test_policy_file_validates_against_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(_doc(), json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))


def test_policy_file_passes_program_rules():
    assert rp.validate_policies(_doc()) == []


def _break(fn):
    doc = copy.deepcopy(_doc())
    fn(doc)
    return rp.validate_policies(doc)


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d["policies"]["transient-2"].__setitem__("backoff_s", [30]), "backoff_s length"),
    (lambda d: d["policies"]["transient-2"]["permitted_classes"].append("send"), "send/learn"),
    (lambda d: d["policies"]["transient-1-slow"]["permitted_classes"].append("learn"), "send/learn"),
    (lambda d: d["policies"]["llm-transient"].__setitem__("terminal_reason_patterns", ["(?i)cost_cap"]), "PEAK_SKIP"),
    (lambda d: d["policies"]["llm-transient"].__setitem__("terminal_reason_patterns", ["COST_CAP", "PEAK_SKIP"]),
     "any case"),
    (lambda d: d["policies"]["none"].__setitem__("terminal_reason_patterns", []), "COST_CAP"),
    (lambda d: d.__setitem__("default_policy", "nope"), "default_policy"),
    (lambda d: d.__setitem__("breaker_threshold", 1), "breaker_threshold"),
    (lambda d: d.__setitem__("schema", "Other@v1"), "schema"),
    (lambda d: d["class_caps"].pop("global"), "class_caps: missing global"),
    (lambda d: d["class_caps"].__setitem__("bogus", 1), "unknown key bogus"),
    (lambda d: d["policies"]["transient-2"].__setitem__("max_attempts", 9), "max_attempts"),
    (lambda d: d["policies"]["transient-2"].__setitem__("retryable_states", ["RUN_REFUSED"]), "retryable_states"),
    (lambda d: d["policies"]["transient-2"].__setitem__("terminal_reason_patterns", ["(unclosed"]), "bad regex"),
    (lambda d: d["policies"]["transient-2"].pop("catchup_min"), "missing catchup_min"),
    (lambda d: d["policies"].__setitem__("Bad_Name", d["policies"]["none"]), "bad policy name"),
    (lambda d: d.__setitem__("extra", 1), "unknown key extra"),
])
def test_each_rule_violation_is_reported(mutate, needle):
    errs = _break(mutate)
    assert any(needle in e for e in errs), errs


def test_load_policies_raises_typed_error(tmp_path):
    bad = tmp_path / "p.json"
    doc = _doc()
    doc["policies"]["transient-2"]["backoff_s"] = []
    bad.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(rp.RetryPolicyError) as ei:
        rp.load_policies(bad)
    assert ei.value.errors
    with pytest.raises(rp.RetryPolicyError):
        rp.load_policies(tmp_path / "missing.json")


# ── verdicts ──


@pytest.mark.parametrize("policy, state, code, reason, want", [
    ("transient-2", "RUN_DONE", 0, None, "ok"),
    ("transient-2", "RUN_SKIPPED_LOCK", 75, "flock_held", "skipped"),
    ("transient-2", "RUN_REFUSED", None, "lane_not_allowlisted", "terminal"),
    ("transient-2", "RUN_TIMEOUT", 124, "timeout_exit_124", "retryable"),
    ("transient-2", "RUN_FAILED", 75, "exit_75", "retryable"),
    ("transient-2", "RUN_FAILED", 69, "exit_69", "retryable"),
    ("transient-2", "RUN_FAILED", 111, "exit_111", "retryable"),
    ("transient-2", "RUN_FAILED", 1, "exit_1", "terminal"),
    ("transient-2", "RUN_FAILED", 2, "exit_2", "terminal"),
    ("transient-2", "RUN_FAILED", None, "executor_lost", "retryable"),
    ("transient-2", "RUN_TIMEOUT", None, "executor_lost", "retryable"),
    ("transient-2", "RUN_FAILED", None, "spawn:BlockingIOError EAGAIN", "retryable"),
    ("transient-2", "RUN_FAILED", 75, "COST_CAP hit", "terminal"),           # terminal pattern beats retryable code
    ("transient-2", "RUN_TIMEOUT", None, "cost_cap", "terminal"),
    ("transient-1-slow", "RUN_FAILED", 69, "exit_69", "terminal"),
    ("transient-1-slow", "RUN_FAILED", 75, "exit_75", "retryable"),
    ("none", "RUN_TIMEOUT", 124, "timeout_exit_124", "terminal"),
    ("none", "RUN_FAILED", 75, "exit_75", "terminal"),
    ("none", "RUN_DONE", 0, None, "ok"),
    ("llm-transient", "RUN_FAILED", 1, "upstream 503 Service Unavailable", "retryable"),
    ("llm-transient", "RUN_FAILED", 1, "DNS resolution failed", "retryable"),
    ("llm-transient", "RUN_FAILED", 1, "HTTP 429 too many requests", "terminal"),
    ("llm-transient", "RUN_FAILED", 75, "PEAK_SKIP deferred", "terminal"),
    ("llm-transient", "RUN_FAILED", 75, "peak_skip", "terminal"),
    ("llm-transient", "RUN_FAILED", 75, "COST_CAP", "terminal"),
    ("llm-transient", "RUN_FAILED", 2, "connection reset", "terminal"),     # terminal exit beats retryable reason
])
def test_verdict_table(policies, policy, state, code, reason, want):
    assert rp.verdict(state, code, reason, policies.get(policy)) == want


def test_next_attempt_at_and_class_permission(policies):
    t2 = policies.get("transient-2")
    fin = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)
    assert (rp.next_attempt_at(t2, 1, fin) - fin).total_seconds() == 30
    assert (rp.next_attempt_at(t2, 2, fin.isoformat()) - fin).total_seconds() == 120
    assert rp.next_attempt_at(t2, 3, fin) is None
    assert rp.next_attempt_at(policies.get("none"), 1, fin) is None
    assert rp.policy_permits_class(t2, "report") and not rp.policy_permits_class(t2, "send")
    assert rp.policy_permits_class(policies.get("none"), "send")
    assert rp.slot_local_of("d:lane-x:live:20261009T1000") == "20261009T1000"
    assert rp.slot_local_of("legacy-run-id-0001") is None


# ── ledger migration + request() ──

_OLD_RUNS = """
CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT NOT NULL, mode TEXT NOT NULL, state TEXT NOT NULL,
  requested_by TEXT, caller_id TEXT, requested_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  exit_code INTEGER, duration_s REAL, receipt_json TEXT);
INSERT INTO runs (run_id, lane_id, mode, state, requested_at) VALUES ('old-run-000000000001', 'lane-a', 'live',
  'RUN_DONE', '2026-10-08T10:00:00+00:00');
"""


def test_migration_on_old_shape_db_keeps_rows_and_is_idempotent(tmp_path):
    path = tmp_path / "old.sqlite"
    con = sqlite3.connect(path)
    con.executescript(_OLD_RUNS)
    con.commit()
    con.close()
    for _ in range(2):  # second open re-runs the migration: no error, no duplicate column
        ledger = CoordinationLedger(path)
        store = LedgerRunStore(ledger)
        row = store.get("old-run-000000000001")
        assert row["state"] == "RUN_DONE" and row["slot_key"] is None and row["verdict"] is None
        assert row["class"] is None and row["attempt"] is None
        tables = {r[0] for r in ledger._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"dead_letters", "breakers", "event_cursors"} <= tables
        idx = {r[0] for r in ledger._conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {"runs_slot_key", "runs_lane_state"} <= idx
        ledger.close()


def test_request_without_new_kwargs_is_unchanged(store):
    row, dup = store.request(run_id="legacy-key-0000000001", lane_id=LANE, mode="live", requested_by="n8n",
                             caller_id="n8n-relay", now=T0)
    assert not dup and row["state"] == "REQUESTED"
    assert all(row[k] is None for k in ("slot_key", "attempt", "parent_run_id", "class", "priority", "verdict"))
    again, dup = store.request(run_id="legacy-key-0000000001", lane_id=LANE, mode="live", requested_by="n8n",
                               caller_id="n8n-relay", now=T0 + 5)
    assert dup and again["requested_at"] == row["requested_at"]


def test_request_with_new_kwargs_stores_them_and_dedupes(store):
    key = f"d:{LANE}:live:20261009T1000:a2"
    row, dup = store.request(run_id=key, lane_id=LANE, mode="live", requested_by="n8n", caller_id="n8n-relay", now=T0,
                             slot_key=f"d:{LANE}:live:20261009T1000", attempt=2,
                             parent_run_id=f"d:{LANE}:live:20261009T1000", klass="report", priority=5)
    assert not dup
    assert (row["slot_key"], row["attempt"], row["class"], row["priority"]) == (
        f"d:{LANE}:live:20261009T1000", 2, "report", 5)
    again, dup = store.request(run_id=key, lane_id=LANE, mode="live", requested_by="x", caller_id="y", now=T0 + 1,
                               attempt=9, klass="heavy")
    assert dup and again["attempt"] == 2 and again["class"] == "report"


def test_set_verdict_and_cursor(store):
    store.request(run_id="legacy-key-0000000002", lane_id=LANE, mode="live", requested_by=None, caller_id=None, now=T0)
    assert store.set_verdict("legacy-key-0000000002", "retryable")["verdict"] == "retryable"
    with pytest.raises(LedgerError):
        store.set_verdict("legacy-key-0000000002", "maybe")
    with pytest.raises(LedgerError):
        store.set_verdict("missing-run-0000000001", "ok")
    assert store.get_cursor(LANE, "run_done") is None
    store.set_cursor(LANE, "run_done", "c1", T0)
    store.set_cursor(LANE, "run_done", "c2", T0 + 1)
    assert store.get_cursor(LANE, "run_done") == "c2"


def test_breaker_is_open_rule():
    assert not breaker_is_open(None)
    assert not breaker_is_open({"opened_at": None})
    assert breaker_is_open({"opened_at": "2026-10-09T10:00:00+00:00", "released_at": None})
    assert breaker_is_open({"opened_at": "2026-10-09T10:00:00+00:00", "released_at": "2026-10-09T09:00:00+00:00"})
    assert not breaker_is_open({"opened_at": "2026-10-09T10:00:00+00:00", "released_at": "2026-10-09T11:00:00+00:00"})


# ── finalize_outcome: DLQ + breaker ──


def _run_slot(store, minute: str, *, state: str, exit_code, reason, attempt: int = 1, at: float = T0,
              lane: str = LANE) -> dict:
    slot = f"d:{lane}:live:20261009T{minute}"
    run_id = slot if attempt == 1 else f"{slot}:a{attempt}"
    store.request(run_id=run_id, lane_id=lane, mode="live", requested_by="n8n", caller_id="n8n-relay", now=at,
                  slot_key=slot, attempt=attempt, klass="report", priority=5)
    assert store.claim_next(now=at + 1)["run_id"] == run_id
    return store.finish(run_id, state=state, now=at + 2,
                        receipt={"exit_code": exit_code, "reason": reason, "duration_s": 1.0})


def test_retryable_below_max_attempts_is_not_dead(store, policies):
    pol = policies.get("transient-2")
    row = _run_slot(store, "1000", state="RUN_FAILED", exit_code=75, reason="exit_75")
    out = rp.finalize_outcome(store, row, pol, breaker_threshold=3, now=T0 + 3)
    assert out.verdict == "retryable" and out.dead_letter is None and out.findings == []
    assert store.get(row["run_id"])["verdict"] == "retryable"


def test_retryable_at_max_attempts_and_terminal_go_to_dlq(store, policies):
    pol = policies.get("transient-2")
    row = _run_slot(store, "1000", state="RUN_FAILED", exit_code=75, reason="exit_75", attempt=3)
    out = rp.finalize_outcome(store, row, pol, breaker_threshold=3, now=T0 + 3)
    assert out.verdict == "retryable" and out.dead_letter["slot_key"] == f"d:{LANE}:live:20261009T1000"
    assert out.dead_letter["attempts"] == 3 and out.dead_letter["slot_local"] == "20261009T1000"
    assert out.findings[0]["item"] == f"dlq:{LANE}" and out.findings[0]["severity"] == "P2"
    row2 = _run_slot(store, "1100", state="RUN_FAILED", exit_code=2, reason="exit_2", at=T0 + 10)
    out2 = rp.finalize_outcome(store, row2, pol, breaker_threshold=3, now=T0 + 13, severity="P1")
    assert out2.verdict == "terminal" and out2.findings[0]["severity"] == "P1"
    assert out2.consecutive_dead == 2 and not out2.breaker_opened


def test_breaker_opens_after_three_and_run_done_closes_it(store, policies):
    pol = policies.get("transient-2")
    outs = []
    for i, minute in enumerate(("1000", "1100", "1200")):
        row = _run_slot(store, minute, state="RUN_REFUSED", exit_code=None, reason="mode_unavailable:live",
                        at=T0 + 100 * i)
        outs.append(rp.finalize_outcome(store, row, pol, breaker_threshold=3, now=T0 + 100 * i + 3))
    assert [o.breaker_opened for o in outs] == [False, False, True]
    assert any(f["item"] == f"breaker:{LANE}" for f in outs[2].findings)
    assert store.breaker(LANE)["open"] and store.breaker(LANE)["consecutive"] == 3
    # a fourth dead slot does not re-open (no duplicate finding)
    row = _run_slot(store, "1300", state="RUN_REFUSED", exit_code=None, reason="x", at=T0 + 400)
    o4 = rp.finalize_outcome(store, row, pol, breaker_threshold=3, now=T0 + 403)
    assert not o4.breaker_opened and [f["item"] for f in o4.findings] == [f"dlq:{LANE}"]
    ok = _run_slot(store, "1400", state="RUN_DONE", exit_code=0, reason=None, at=T0 + 500)
    o5 = rp.finalize_outcome(store, ok, pol, breaker_threshold=3, now=T0 + 503)
    assert o5.verdict == "ok" and o5.breaker_closed
    brk = store.breaker(LANE)
    assert not brk["open"] and brk["released_by"] == "auto:run_done"
    assert store.consecutive_dead(LANE) == 0


def test_skipped_and_other_lane_do_not_count(store, policies):
    pol = policies.get("transient-2")
    row = _run_slot(store, "1000", state="RUN_SKIPPED_LOCK", exit_code=75, reason="flock_held")
    assert rp.finalize_outcome(store, row, pol, breaker_threshold=3, now=T0 + 3).verdict == "skipped"
    other = _run_slot(store, "1000", state="RUN_REFUSED", exit_code=None, reason="x", lane="other-lane-xyz")
    rp.finalize_outcome(store, other, pol, breaker_threshold=3, now=T0 + 3)
    assert store.consecutive_dead(LANE) == 0 and store.consecutive_dead("other-lane-xyz") == 1


def test_legacy_row_without_slot_key_dead_letters_by_run_id(store, policies):
    store.request(run_id="legacy-key-0000000003", lane_id=LANE, mode="live", requested_by=None, caller_id=None, now=T0)
    store.claim_next(now=T0)
    row = store.finish("legacy-key-0000000003", state="RUN_FAILED", now=T0 + 1, receipt={"exit_code": 1, "reason": "exit_1"})
    out = rp.finalize_outcome(store, row, policies.get("none"), breaker_threshold=3, now=T0 + 2)
    assert out.dead_letter["slot_key"] == "legacy-key-0000000003" and out.dead_letter["slot_local"] is None


def test_release_dead_letter_and_breaker_reset_streak(store, policies):
    pol = policies.get("transient-2")
    for i, minute in enumerate(("1000", "1100", "1200")):
        row = _run_slot(store, minute, state="RUN_FAILED", exit_code=1, reason="exit_1", at=T0 + 100 * i)
        rp.finalize_outcome(store, row, pol, breaker_threshold=3, now=T0 + 100 * i + 3)
    slot = f"d:{LANE}:live:20261009T1000"
    rel = store.release_dead_letter(slot, "operator", "fixed creds", T0 + 1000)
    assert rel["released_at"] and rel["released_by"] == "operator" and rel["release_note"] == "fixed creds"
    assert store.release_dead_letter(slot, "operator", "again", T0 + 1001) is None
    assert store.release_dead_letter("d:none:live:20261009T0000", "operator", "x", T0) is None
    assert len(store.list_dead_letters(LANE)) == 2
    assert len(store.list_dead_letters(LANE, include_released=True)) == 3
    assert store.release_breaker(LANE, "operator", T0 + 1002)["open"] is False
    assert store.release_breaker(LANE, "operator", T0 + 1003) is None  # already closed
    assert store.consecutive_dead(LANE) == 0
    # the re-armed slot dies again: upsert clears its release, streak restarts at 1
    row = _run_slot(store, "1000", state="RUN_FAILED", exit_code=1, reason="exit_1", attempt=2, at=T0 + 1100)
    out = rp.finalize_outcome(store, row, pol, breaker_threshold=3, now=T0 + 1103)
    assert out.dead_letter["released_at"] is None and out.dead_letter["attempts"] == 2
    assert out.consecutive_dead == 1 and not out.breaker_opened


# ── host CLI ──


def _seed_dead_lane(path: Path, policies) -> None:
    ledger = CoordinationLedger(path)
    st = LedgerRunStore(ledger)
    for i, minute in enumerate(("1000", "1100", "1200")):
        row = _run_slot(st, minute, state="RUN_FAILED", exit_code=1, reason="exit_1", at=T0 + 100 * i)
        rp.finalize_outcome(st, row, policies.get("transient-2"), breaker_threshold=3, now=T0 + 100 * i + 3)
    ledger.close()


def _cli(argv, capsys):
    from scripts import n8n_dlq

    code = n8n_dlq.main(argv)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def test_cli_list_and_missing_ledger(tmp_path, policies, capsys, monkeypatch):
    db = tmp_path / "l.sqlite"
    code, _, err = _cli(["--ledger", str(db), "list"], capsys)
    assert code == 3 and "ledger_not_found" in err and not db.exists()
    _seed_dead_lane(db, policies)
    code, out, _ = _cli(["--ledger", str(db), "list", "--json"], capsys)
    body = json.loads(out)
    assert code == 0 and len(body["dead_letters"]) == 3 and body["open_breakers"][0]["lane_id"] == LANE
    code, out, _ = _cli(["--ledger", str(db), "list", "--lane", LANE], capsys)
    assert code == 0 and "BREAKER OPEN" in out and out.count(f"lane={LANE}") == 4
    # default ledger resolution is the gateway's (env), not a home literal
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(db))
    code, out, _ = _cli(["list", "--json"], capsys)
    assert code == 0 and len(json.loads(out)["dead_letters"]) == 3


def test_cli_usage_errors_exit_2(tmp_path, capsys):
    db = tmp_path / "l.sqlite"
    assert _cli(["--ledger", str(db), "release", "--note", "x"], capsys)[0] == 2
    assert _cli(["--ledger", str(db), "release", "--slot-key", "k", "--lane", "l", "--note", "x"], capsys)[0] == 2
    assert _cli(["--ledger", str(db), "release", "--slot-key", "k"], capsys)[0] == 2
    assert _cli(["bogus"], capsys)[0] == 2


def test_cli_release_slot_dry_run_then_real(tmp_path, policies, capsys, monkeypatch):
    db, rec = tmp_path / "l.sqlite", tmp_path / "rel.jsonl"
    _seed_dead_lane(db, policies)
    monkeypatch.setenv("USER", "opuser")
    slot = f"d:{LANE}:live:20261009T1100"
    code, out, _ = _cli(["--ledger", str(db), "release", "--slot-key", slot, "--note", "n", "--dry-run",
                         "--receipts", str(rec)], capsys)
    assert code == 0 and json.loads(out)["dry_run"] is True and not rec.exists()
    ledger = CoordinationLedger(db)
    assert LedgerRunStore(ledger).get_dead_letter(slot)["released_at"] is None
    ledger.close()
    code, out, _ = _cli(["--ledger", str(db), "release", "--slot-key", slot, "--note", "fixed", "--receipts", str(rec)],
                        capsys)
    assert code == 0
    lines = rec.read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["phase"] for x in lines] == ["intent", "committed"]
    r = json.loads(lines[1])
    assert r["schema"] == "DeadLetterRelease@v1" and r["by"] == "opuser" and r["note"] == "fixed"
    assert [x["slot_key"] for x in r["released"]] == [slot] and r["breaker_released"] is False
    ledger = CoordinationLedger(db)
    st = LedgerRunStore(ledger)
    assert st.get_dead_letter(slot)["released_by"] == "opuser" and st.breaker(LANE)["open"]
    ledger.close()
    # already released / unknown -> not found
    code, _, err = _cli(["--ledger", str(db), "release", "--slot-key", slot, "--note", "x", "--receipts", str(rec)],
                        capsys)
    assert code == 3 and "not_found" in err and len(rec.read_text(encoding="utf-8").splitlines()) == 2


def test_cli_release_lane_releases_all_and_breaker(tmp_path, policies, capsys):
    db, rec = tmp_path / "l.sqlite", tmp_path / "rel.jsonl"
    _seed_dead_lane(db, policies)
    code, out, _ = _cli(["--ledger", str(db), "release", "--lane", LANE, "--note", "creds rotated", "--by", "agent-x",
                         "--receipts", str(rec)], capsys)
    assert code == 0
    r = json.loads(rec.read_text(encoding="utf-8").splitlines()[-1])
    assert r["phase"] == "committed" and len(r["released"]) == 3 and r["breaker_released"] is True and r["by"] == "agent-x"
    ledger = CoordinationLedger(db)
    st = LedgerRunStore(ledger)
    assert st.list_dead_letters(LANE) == [] and not st.breaker(LANE)["open"]
    assert st.consecutive_dead(LANE) == 0
    ledger.close()
    code, _, _ = _cli(["--ledger", str(db), "release", "--lane", LANE, "--note", "x", "--receipts", str(rec)], capsys)
    assert code == 3


# ── review of #1594: code-level class rails, refused releases, read-only list, receipt-first, migration race ──


def _lax(policies, name="transient-2", **changes):
    """A deliberately mis-configured policy (bypassing validate_policies) to prove the rails live in code."""
    import dataclasses

    return dataclasses.replace(policies.get(name), **changes)


def test_send_class_exit_75_is_terminal_and_dead_lettered_even_on_a_retrying_policy(store, policies):
    lax = _lax(policies, permitted_classes=frozenset(rp.CLASSES))  # a policy file that wrongly permits send
    slot = f"d:{LANE}:live:20261009T1000"
    store.request(run_id=slot, lane_id=LANE, mode="live", requested_by="n8n", caller_id="n8n-relay", now=T0,
                  slot_key=slot, attempt=1, klass="send", priority=3)
    store.claim_next(now=T0 + 1)
    row = store.finish(slot, state="RUN_FAILED", now=T0 + 2, receipt={"exit_code": 75, "reason": "exit_75"})
    assert rp.verdict("RUN_FAILED", 75, "exit_75", lax) == "retryable"  # the raw policy would retry
    out = rp.finalize_outcome(store, row, lax, breaker_threshold=3, now=T0 + 3)
    assert out.verdict == "terminal" and out.dead_letter["class"] == "send"
    assert out.dead_letter["max_attempts"] == 1 and store.get(slot)["verdict"] == "terminal"
    fin = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)
    assert rp.next_attempt_at(lax, 1, fin, klass="send") is None
    assert rp.next_attempt_at(lax, 1, fin, klass="learn") is None
    assert rp.next_attempt_at(lax, 1, fin, klass="report") is not None
    assert rp.effective_max_attempts(lax, "send") == 1 and rp.effective_max_attempts(lax, "report") == 3
    assert rp.dead_letter_rearmable(out.dead_letter) == (False, "class_send_never_retries")


@pytest.mark.parametrize("policy, klass, state, code, reason, want", [
    ("transient-1-slow", "report", "RUN_FAILED", 75, "exit_75", "terminal"),   # class not permitted
    ("transient-2", "heavy", "RUN_TIMEOUT", 124, "timeout_exit_124", "terminal"),
    ("transient-2", "learn", "RUN_TIMEOUT", 124, "timeout_exit_124", "terminal"),
    ("transient-2", "report", "RUN_TIMEOUT", 124, "timeout_exit_124", "retryable"),
    ("transient-2", None, "RUN_TIMEOUT", 124, "timeout_exit_124", "retryable"),  # legacy row: policy alone
    ("transient-2", "send", "RUN_DONE", 0, None, "ok"),
    ("transient-2", "send", "RUN_SKIPPED_LOCK", 75, "flock_held", "skipped"),
])
def test_class_verdict_rails(policies, policy, klass, state, code, reason, want):
    assert rp.class_verdict(state, code, reason, policies.get(policy), klass) == want


@pytest.mark.parametrize("reason", ["COST_CAP reached", "cost_cap", "PEAK_SKIP", "peak_skip window"])
def test_llm_class_cost_cap_and_peak_skip_terminal_whatever_the_policy(policies, reason):
    lax = _lax(policies, "llm-transient", terminal_reason_patterns=(), retryable_reason_patterns=(".*",))
    assert rp.verdict("RUN_FAILED", 75, reason, lax) == "retryable"
    assert rp.class_verdict("RUN_FAILED", 75, reason, lax, "llm") == "terminal"
    assert rp.class_verdict("RUN_FAILED", 75, "connection reset", lax, "llm") == "retryable"


def test_missing_policy_is_terminal_and_logged(store, policies, caplog):
    import logging

    caplog.set_level(logging.WARNING, logger=rp.__name__)
    assert policies.get(None) is rp.UNRESOLVED_POLICY
    assert "unresolved" in caplog.text
    row = _run_slot(store, "1000", state="RUN_TIMEOUT", exit_code=124, reason="timeout_exit_124")
    out = rp.finalize_outcome(store, row, None, breaker_threshold=3, now=T0 + 3)
    assert out.verdict == "terminal" and out.dead_letter["policy"] == "unresolved"
    assert rp.dead_letter_rearmable(out.dead_letter) == (False, "single_attempt_policy")


def test_store_refuses_release_of_non_rearmable_dead_letters(store, policies):
    row = _run_slot(store, "1000", state="RUN_FAILED", exit_code=1, reason="exit_1")
    rp.finalize_outcome(store, row, policies.get("none"), breaker_threshold=3, now=T0 + 3)
    slot = row["slot_key"]
    with pytest.raises(LedgerError) as ei:
        store.release_dead_letter(slot, "op", "n", T0 + 10)
    assert ei.value.reason == "release_refused:single_attempt_policy"
    with pytest.raises(LedgerError):
        store.release_dead_letters([slot], "op", "n", T0 + 10)
    assert store.get_dead_letter(slot)["released_at"] is None  # due never sees a released single-attempt slot
    store.record_dead_letter(slot_key="legacy-key-0000000009", lane_id=LANE, mode="live", slot_local=None,
                             attempts=1, last_run_id="legacy-key-0000000009", last_state="RUN_FAILED",
                             last_reason="exit_1", verdict="terminal", now=T0)
    with pytest.raises(LedgerError, match="unknown_class_or_policy"):
        store.release_dead_letter("legacy-key-0000000009", "op", "n", T0 + 10)


def _seed_send_dead(path: Path, policies, minute="1500") -> str:
    ledger = CoordinationLedger(path)
    st = LedgerRunStore(ledger)
    slot = f"d:{LANE}:live:20261009T{minute}"
    st.request(run_id=slot, lane_id=LANE, mode="live", requested_by="n8n", caller_id="r", now=T0 + 900,
               slot_key=slot, attempt=1, klass="send", priority=3)
    st.claim_next(now=T0 + 901)
    row = st.finish(slot, state="RUN_FAILED", now=T0 + 902, receipt={"exit_code": 75, "reason": "exit_75"})
    rp.finalize_outcome(st, row, policies.get("none"), breaker_threshold=3, now=T0 + 903)
    ledger.close()
    return slot


def test_cli_refuses_send_slot_release_with_typed_error(tmp_path, policies, capsys):
    db, rec = tmp_path / "l.sqlite", tmp_path / "rel.jsonl"
    slot = _seed_send_dead(db, policies)
    code, _, err = _cli(["--ledger", str(db), "release", "--slot-key", slot, "--note", "n", "--receipts", str(rec)],
                        capsys)
    assert code == 4 and json.loads(err)["error"] == "release_refused" and not rec.exists()
    assert json.loads(err)["refused"][0]["reason"] == "class_send_never_retries"


def test_cli_lane_release_skips_refused_but_releases_breaker(tmp_path, policies, capsys):
    db, rec = tmp_path / "l.sqlite", tmp_path / "rel.jsonl"
    _seed_dead_lane(db, policies)
    send_slot = _seed_send_dead(db, policies)
    code, _, _ = _cli(["--ledger", str(db), "release", "--lane", LANE, "--note", "n", "--receipts", str(rec)], capsys)
    assert code == 0
    r = json.loads(rec.read_text(encoding="utf-8").splitlines()[-1])
    assert len(r["released"]) == 3 and r["refused"] == [{"slot_key": send_slot, "reason": "class_send_never_retries"}]
    ledger = CoordinationLedger(db)
    st = LedgerRunStore(ledger)
    assert st.get_dead_letter(send_slot)["released_at"] is None and not st.breaker(LANE)["open"]
    ledger.close()


def test_cli_receipt_is_written_before_the_ledger_commit(tmp_path, policies, capsys, monkeypatch):
    db, rec = tmp_path / "l.sqlite", tmp_path / "rel.jsonl"
    _seed_dead_lane(db, policies)
    seen = {}

    def boom(self, *a, **k):
        seen["receipt_lines"] = rec.read_text(encoding="utf-8").splitlines()
        raise LedgerError("simulated_commit_failure")

    monkeypatch.setattr(LedgerRunStore, "release_dead_letters", boom)
    code, _, err = _cli(["--ledger", str(db), "release", "--lane", LANE, "--note", "n", "--receipts", str(rec)], capsys)
    assert code == 3 and "release_failed" in err
    assert [json.loads(x)["phase"] for x in seen["receipt_lines"]] == ["intent"]
    assert [json.loads(x)["phase"] for x in rec.read_text(encoding="utf-8").splitlines()] == ["intent", "aborted"]
    monkeypatch.undo()
    ledger = CoordinationLedger(db)
    assert len(LedgerRunStore(ledger).list_dead_letters(LANE)) == 3  # nothing released
    ledger.close()


def test_cli_list_does_not_migrate_an_old_schema(tmp_path, capsys):
    path = tmp_path / "old.sqlite"
    con = sqlite3.connect(path)
    con.executescript(_OLD_RUNS)
    con.commit()
    con.close()
    code, out, _ = _cli(["--ledger", str(path), "list", "--json"], capsys)
    assert code == 0 and json.loads(out)["schema_not_migrated"] is True
    code, _, _ = _cli(["--ledger", str(path), "release", "--lane", LANE, "--note", "n",
                       "--receipts", str(tmp_path / "r.jsonl")], capsys)
    assert code == 3
    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(runs)")}
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "slot_key" not in cols and "dead_letters" not in tables


def test_read_only_ledger_refuses_writes(tmp_path):
    path = tmp_path / "l.sqlite"
    CoordinationLedger(path).close()
    ro = CoordinationLedger(path, read_only=True)
    with pytest.raises(sqlite3.OperationalError):
        LedgerRunStore(ro).set_cursor(LANE, "s", "c", T0)
    ro.close()


def test_migration_tolerates_a_concurrent_duplicate_column(tmp_path):
    ledger = CoordinationLedger(tmp_path / "l.sqlite")  # columns already present

    class StalePragma:
        """Another process added the column after our PRAGMA read: PRAGMA says missing, ALTER says duplicate."""

        def __init__(self, conn):
            self._c = conn

        def execute(self, sql, *a):
            if sql.startswith("PRAGMA table_info"):
                return self._c.execute("SELECT 'x' AS name WHERE 0")
            return self._c.execute(sql, *a)

        def __getattr__(self, name):
            return getattr(self._c, name)

    real = ledger._conn
    ledger._conn = StalePragma(real)
    ledger._add_columns("runs", {"slot_key": "TEXT"})  # duplicate column name -> treated as success
    with pytest.raises(sqlite3.OperationalError):
        ledger._add_columns("no_such_table", {"c": "TEXT"})
    ledger._conn = real
    ledger.close()
