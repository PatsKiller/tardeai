"""n8n maturity B5 follow-ups (2026-10-09).

1. Heartbeat watcher: the generated "Assert heartbeat fresh" Code node alarms on its own staleness ONLY once
   heartbeat-watch is n8n-dispatched (registry mode != off, read from this tick's /due reply). Executed in node
   with stubbed $ / $input; skipped when node is not installed.
2. Breach detector (the heartbeat-watch engine): cron deadlines come from cron_schedule.last_fire_at_or_before,
   so a spring-forward gap fire is the first valid instant (no false NO_OUTPUT); names/@aliases keep the legacy
   parser; None (nothing in lookback) falls to the cadence rule.
3. Fan-in: one P2 per unreleased dead letter, one P2 per open breaker (ledger read-only, ExecutorStatus@v1
   cross-check / fallback); released rows close.
4. CI rails: dispatch class permitted by its retry_policy; dispatch.cron == live crontab (skipped without one);
   the workflow drift check covers the generic set.
Hermetic: tmp_path ledgers and receipts, no network, no n8n.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts import check_n8n_workflow_drift as D  # noqa: E402
from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts import n8n_workflow_templates as gen  # noqa: E402
from scripts import supervisor_breach_detector as sbd  # noqa: E402
from scripts.lib import n8n_dispatch_registry_checks as DRC  # noqa: E402
from scripts.lib import n8n_live_inventory as INV  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402
from scripts.lib.n8n_retry_policy import load_policies  # noqa: E402

NODE = shutil.which("node")
LANE = gen.HEARTBEAT_LANE


# ── 1. heartbeat watcher gate ─────────────────────────────────────────────────────────────────────────────


def _fresh_js() -> str:
    wf = gen.build_generic("heartbeat-watcher")
    (node,) = [n for n in wf["nodes"] if n["name"] == gen.GN_FRESH]
    return node["parameters"]["jsCode"]


def _counts(**kw) -> dict:
    c = {k: 0 for k in ("DUE", "RETRY_DUE", "IN_FLIGHT", "DONE", "RETRY_WAIT", "DEAD_LETTER", "WAITING_AFTER",
                        "BREAKER_OPEN", "MISSED")}
    c.update(kw)
    return c


def _due(items=(), held=(), errors=(), **counts) -> dict:
    return {"schema": "DueResponse@v1", "ok": True, "source": "schedule", "items": list(items), "held": list(held),
            "errors": list(errors), "counts": _counts(**counts)}


def _last(state="RUN_DONE", age_s=60, status=200, none=False) -> dict:
    if none:
        return {"statusCode": status, "body": {"last": None}}
    finished = datetime.now(timezone.utc).timestamp() - age_s
    iso = datetime.fromtimestamp(finished, timezone.utc).isoformat()
    return {"statusCode": status, "body": {"last": {"state": state, "finished_at": iso, "mode": "live"}}}


def _run_js(due: dict, last: dict) -> tuple[bool, str]:
    harness = (
        "const DUE = " + json.dumps(due) + ";\n"
        "const LAST = " + json.dumps(last) + ";\n"
        "const $ = (name) => { if (name !== " + json.dumps(gen.GN_DUE) + ") throw new Error('bad ref ' + name);"
        " return { first: () => ({ json: DUE }) }; };\n"
        "const $input = { first: () => ({ json: LAST }) };\n"
        "try { const out = (() => {\n" + _fresh_js() + "\n})();"
        " console.log(JSON.stringify({ ok: true, out })); }\n"
        "catch (e) { console.log(JSON.stringify({ ok: false, err: String(e.message) })); }\n"
    )
    res = subprocess.run([NODE, "-e", harness], capture_output=True, text=True, timeout=30, check=True)
    doc = json.loads(res.stdout.strip().splitlines()[-1])
    return doc["ok"], json.dumps(doc.get("out") if doc["ok"] else doc["err"])


needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")


@needs_node
def test_heartbeat_mode_off_at_w0_never_alarms_even_with_no_run_at_all():
    ok, out = _run_js(_due(), _last(none=True, status=404))
    assert ok and "not_dispatched" in out


@needs_node
def test_heartbeat_dispatched_live_and_stale_alarms():
    item = {"lane_id": LANE, "mode": "live", "idempotency_key": "d:heartbeat-watch:live:20261009T1200"}
    ok, out = _run_js(_due(items=[item], DUE=1), _last(age_s=1200))
    assert not ok and "no live RUN_DONE" in out


@needs_node
def test_heartbeat_dispatched_live_and_fresh_passes():
    item = {"lane_id": LANE, "mode": "live", "idempotency_key": "d:heartbeat-watch:live:20261009T1200"}
    ok, out = _run_js(_due(items=[item], DUE=1), _last(age_s=120))
    assert ok and "age_s" in out


@needs_node
def test_heartbeat_dispatched_dry_run_skips_the_live_check():
    item = {"lane_id": LANE, "mode": "dry_run", "idempotency_key": "d:heartbeat-watch:dry_run:20261009T1200"}
    ok, out = _run_js(_due(items=[item], DUE=1), _last(none=True))
    assert ok and "dispatched_dry_run" in out


@needs_node
def test_heartbeat_mode_unknown_alarms_only_once_a_live_run_has_existed():
    ok, out = _run_js(_due(DONE=1), _last(none=True))
    assert ok and "mode_unknown_never_live" in out
    ok, out = _run_js(_due(DONE=1), _last(age_s=1800))
    assert not ok and "no live RUN_DONE" in out


@needs_node
def test_heartbeat_broken_dispatch_block_or_unreadable_due_alarms():
    ok, out = _run_js(_due(errors=[{"lane_id": LANE, "code": "bad_cron"}]), _last(none=True))
    assert not ok and "bad_cron" in out
    ok, out = _run_js({"schema": "DueResponse@v1", "ok": False}, _last(none=True))
    assert not ok and "unreadable" in out


def test_generated_heartbeat_watcher_stays_inactive_and_committed_set_is_current(tmp_path):
    files = gen.render_generic()
    assert all(not json.loads(t)["active"] for n, t in files.items() if n != "INDEX.json")
    assert gen.generic_main(["--check"]) == 0
    assert gen.main(["--check"]) == 0          # per-lane generated/INDEX.json carries this file's code_sha


# ── 2. breach detector deadlines (DST-safe) ───────────────────────────────────────────────────────────────


def _cron_lane(expr: str) -> dict:
    return {"lane_id": "x", "scheduler": {"kind": "cron", "expression": expr}, "expected_cadence_hours": 24}


def test_spring_forward_gap_fire_is_the_first_valid_instant_not_an_hour_late():
    # 2027-03-14: 02:30 EST does not exist; cron fires at 03:00 EDT = 07:00Z. Old naive math said 07:30Z, so an
    # output written at 07:10Z read as NO_OUTPUT.
    now = datetime(2027, 3, 14, 8, 0, tzinfo=timezone.utc)       # 04:00 EDT
    deadline, basis = sbd._expected_since(_cron_lane("30 2 * * *"), now)
    assert basis == "cron:30 2 * * *"
    assert deadline == datetime(2027, 3, 14, 7, 0, tzinfo=timezone.utc)


def test_fall_back_fold_fires_once_on_the_first_instant():
    # 2026-11-01 01:30 happens twice; the fire is fold 0 (01:30 EDT = 05:30Z), even when asked from the EST hour.
    now = datetime(2026, 11, 1, 6, 50, tzinfo=timezone.utc)      # 01:50 EST
    deadline, _ = sbd._expected_since(_cron_lane("30 1 * * *"), now)
    assert deadline == datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)


def test_names_and_aliases_keep_the_legacy_parser():
    now = datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc)      # Fri 12:00 EDT
    deadline, basis = sbd._expected_since(_cron_lane("0 9 * * mon-fri"), now)
    assert basis.startswith("cron:") and deadline == datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc)
    deadline, basis = sbd._expected_since(_cron_lane("@daily"), now)
    assert basis == "cron:@daily" and deadline == datetime(2026, 10, 9, 4, 0, tzinfo=timezone.utc)


def test_no_fire_inside_the_lookback_is_unknown_and_falls_to_the_cadence_rule(monkeypatch):
    monkeypatch.setattr(sbd, "CRON_LOOKBACK_DAYS", 1)
    now = datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc)
    deadline, basis = sbd._expected_since(_cron_lane("0 0 1 1 *"), now)
    assert basis == "cadence:24h×3"


# ── 3. fan-in DLQ + breakers ─────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)


def _dlq_ledger(tmp_path: Path) -> tuple[Path, LedgerRunStore]:
    path = tmp_path / "data/governance/n8n_coordination_ledger.sqlite"
    store = LedgerRunStore(CoordinationLedger(path))
    return path, store


def _dead(store, slot, lane="lane-a"):
    store.record_dead_letter(slot_key=slot, lane_id=lane, mode="live", slot_local=slot.rsplit(":", 1)[-1],
                             attempts=3, last_run_id="r1", last_state="RUN_FAILED", last_reason="exit 1",
                             verdict="terminal", now=NOW.timestamp() - 600)


def _dlq(found):
    return sorted(f["item"] for f in found if f["source"] == "dlq")


def test_fanin_p2_per_dead_letter_and_per_open_breaker_then_closes_on_release(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADEAI_N8N_COORDINATION_LEDGER", raising=False)
    monkeypatch.delenv("TRADEAI_FANIN_DLQ", raising=False)
    path, store = _dlq_ledger(tmp_path)
    _dead(store, "d:lane-a:live:20261009T1200")
    _dead(store, "d:lane-a:live:20261009T1300")
    store.open_breaker("lane-a", 3, NOW.timestamp() - 300)
    found = fanin._dlq_findings(tmp_path, NOW)
    assert _dlq(found) == ["breaker:lane-a", "dlq:d:lane-a:live:20261009T1200", "dlq:d:lane-a:live:20261009T1300"]
    assert {f["severity"] for f in found} == {"P2"}
    ev = fanin.build_event(found[0], day="2026-10-09", now=NOW, sha="abc")
    assert ev["artifact_ref"].endswith(fanin.LEDGER_REL)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE dead_letters SET released_at = '2026-10-09T18:30:00+00:00' WHERE slot_key LIKE '%1200'")
    conn.commit(); conn.close()
    store.release_breaker("lane-a", "operator", NOW.timestamp())
    assert _dlq(fanin._dlq_findings(tmp_path, NOW)) == ["dlq:d:lane-a:live:20261009T1300"]
    assert fanin.NOTES["dlq_source"].startswith("ledger:ok:dead=1:breakers=0")


def test_fanin_executor_status_adds_breakers_and_stands_in_without_a_ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADEAI_N8N_COORDINATION_LEDGER", raising=False)
    monkeypatch.delenv("TRADEAI_FANIN_DLQ", raising=False)
    st = tmp_path / fanin.EXECUTOR_LAST_REL
    st.parent.mkdir(parents=True)
    st.write_text(json.dumps({"schema": "ExecutorStatus@v1", "dlq_24h": 2, "breakers_open": ["lane-b"]}))
    found = fanin._dlq_findings(tmp_path, NOW)
    assert _dlq(found) == ["breaker:lane-b", "dlq:status_count"]
    assert all(f["artifact_rel"] == fanin.EXECUTOR_LAST_REL for f in found)
    # A v1 RunReceipt in the same file is not a status: nothing.
    st.write_text(json.dumps({"schema": "RunReceipt@v1", "dlq_24h": 5}))
    assert fanin._dlq_findings(tmp_path, NOW) == []
    monkeypatch.setenv("TRADEAI_FANIN_DLQ", "0")
    assert fanin._dlq_findings(tmp_path, NOW) == [] and "disabled" in fanin.NOTES["dlq_source"]


def test_fanin_pre_b54_ledger_without_tables_is_absent_not_a_crash(tmp_path, monkeypatch):
    p = tmp_path / "old.sqlite"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE runs(run_id TEXT)")
    conn.commit(); conn.close()
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(p))
    monkeypatch.delenv("TRADEAI_FANIN_DLQ", raising=False)
    assert fanin._dlq_findings(tmp_path, NOW) == []
    assert fanin.NOTES["dlq_source"].startswith("ledger:absent")
    before = p.read_bytes()
    fanin._dlq_findings(tmp_path, NOW)
    assert p.read_bytes() == before                                  # read-only: no migration


def test_fanin_collect_wires_the_dlq_source():
    import inspect

    assert "_dlq_findings(root, now)" in inspect.getsource(fanin.collect)


# ── 4. CI rails ─────────────────────────────────────────────────────────────────────────────────────────


def _row(lane, klass="monitor", policy="transient-2", cron=None, sched=None, dispatch=True):
    r = {"lane_id": lane, "scheduler": sched or {"kind": "cron", "expression": "*/5 * * * *", "match": f"run_{lane}.py"}}
    if dispatch:
        r["dispatch"] = {"mode": "off", "cron": cron if cron is not None else ["*/5 * * * *"], "class": klass,
                         "priority": 5, "retry_policy": policy, "wave": "W1"}
    return r


def test_dispatch_class_must_be_permitted_by_its_retry_policy():
    pols = load_policies()
    rows = [
        _row("ok-monitor"),
        _row("send-on-transient", klass="send"),           # transient-2 does not permit send
        _row("send-on-none", klass="send", policy="none"),
        _row("unknown-policy", policy="nope"),
        _row("unknown-class", klass="bogus"),
        _row("no-dispatch", dispatch=False),
        {"lane_id": "malformed", "dispatch": "off"},
    ]
    got = {(f["lane_id"], f["code"]) for f in DRC.class_policy_findings(rows, pols)}
    assert got == {
        ("send-on-transient", DRC.CODE_CLASS_NOT_PERMITTED),
        ("unknown-policy", DRC.CODE_UNKNOWN_POLICY),
        ("unknown-class", DRC.CODE_UNKNOWN_CLASS),
        ("malformed", DRC.CODE_MALFORMED),
    }


def test_dispatch_cron_must_equal_the_live_crontab_line_and_is_skipped_without_one():
    rows = [_row("a", cron=["*/5 * * * *"]), _row("b", cron=["0 9 * * 1-5"]), _row("c", cron=["0 1 * * *"]),
            _row("n8n", sched={"kind": "n8n", "expression": "wf"}, cron=["0 2 * * *"])]
    lines = ["*/5 * * * * cd $PROJ && $PY scripts/run_a.py >> logs/a.log 2>&1",
             "*/10 9-15 * * 1-5 cd $PROJ && $PY scripts/run_b.py",
             "0 2 * * * cd $PROJ && $PY scripts/run_n8n.py"]      # c has no live line: skipped; n8n row: skipped
    got = DRC.cron_mismatch_findings(rows, lines)
    assert [(f["lane_id"], f["code"]) for f in got] == [("b", DRC.CODE_CRON_MISMATCH)]
    assert DRC.cron_mismatch_findings(rows, None) == [] and DRC.cron_mismatch_findings(rows, []) == []


def test_check_lane_registry_wires_the_dispatch_rails():
    src = (ROOT / "scripts/check_lane_registry.py").read_text(encoding="utf-8")
    assert "class_policy_findings(rows, load_policies())" in src and "cron_mismatch_findings(" in src
    assert "if args.fail_on_new and dispatch_findings:" in src


def test_drift_check_covers_the_generic_workflow_set():
    git = D.git_reviewed_set()
    generic_ids = {gen.GENERIC_KINDS[k]["id"] for k in gen.GENERIC_KINDS}
    assert generic_ids <= set(git)
    placeholder = INV.load_generated_index()["relay_url_placeholder"]
    live = []
    for wid in sorted(generic_ids):
        doc = json.loads(json.dumps(git[wid][1]).replace("172.19.0.1", "10.0.0.7"))   # import-time host edit
        doc["active"] = True
        live.append(doc)
    rows = D.evaluate(live, git=git, placeholder=placeholder)
    assert {r["status"] for r in rows} == {D.OK} and len(rows) == 6
    edited = json.loads(json.dumps(live[0]))
    edited["settings"]["executionTimeout"] = 999
    assert D.evaluate([edited], git=git, placeholder=placeholder)[0]["status"] == D.DRIFT


def test_drift_check_refuses_an_id_in_both_sets(tmp_path):
    a, b = tmp_path / "gen", tmp_path / "generic"
    a.mkdir(); b.mkdir()
    doc = {"id": "dup", "nodes": []}
    (a / "x.json").write_text(json.dumps(doc)); (b / "y.json").write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="dup"):
        D.git_reviewed_set(a, b)
    assert set(D.git_reviewed_set(a, tmp_path / "absent")) == {"dup"}
