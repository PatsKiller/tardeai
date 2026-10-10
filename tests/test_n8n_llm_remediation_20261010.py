"""LLM self-remediation for n8n lanes (REMEDIATION_PLAN §6, operator decisions 2026-10-09 23:38 ET).

Hermetic: a temp state root, a temp coordination ledger (real CoordinationLedger), an in-memory double of
system_health_events, and a fake governed call. No model, no network, no send, no live DB.

2026-10-10 (operator "Ok" ~00:35 ET): the diagnoser writes its own store (data/runtime/n8n_diagnoses/diagnoses.jsonl)
and never system_health_events — the SIEM bridge folds the diagnosis into its row (one writer, AGENTS.md §9.4);
reruns go through the gateway's coordination/run path and the executor's stage clamp (§23.11).
"""
from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import build_remediation_catalogue as builder
from scripts import n8n_failure_diagnosis as cli
from scripts import n8n_incident_fanin as fanin
from scripts import n8n_selftest_fail as selftest
from scripts.lib import n8n_failure_diagnosis as D
from scripts.lib import n8n_model_job as M
from scripts.lib import n8n_remediation_catalogue as C
from scripts.lib import lane_stage_clamp as S
from scripts.lib import n8n_coordination_gateway as G
from scripts.lib import n8n_siem_bridge as B
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 10, 6, 0, tzinfo=timezone.utc)
LOW_LANE = "n8n-selftest-fail"
HIGH_LANE = "generate-analyst-daily-digest"

SECRETS = ["sk-live-ABCDEFGHIJKLMNOPQRSTUV", "hunter2pass", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk"]
PORTFOLIO = ["12345678901", "$48,210.55", "XXXX-9876"]


# ---------------------------------------------------------------- doubles


class FakeDB:
    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.sql: list[str] = []
        self.readonly = False
        self.commits = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1
        self.readonly = False

    def rollback(self):
        self.readonly = False


class FakeCursor:
    def __init__(self, db):
        self.db, self.description, self._res = db, None, []

    def execute(self, sql, params=()):
        db = self.db
        db.sql.append(sql)
        if sql.strip().upper() == "SET TRANSACTION READ ONLY":
            db.readonly = True
            return
        head = sql.lstrip().split()[0].upper()
        if head in ("INSERT", "UPDATE", "DELETE"):
            raise AssertionError(f"the diagnoser must never write system_health_events: {sql[:60]}")
        if head == "SELECT":
            cols = ["id", "component", "event_type", "severity", "message", "action_taken", "lifecycle_state", "created_at"]
            self.description = [(c,) for c in cols]
            self._res = [tuple(r.get(c) for c in cols) for r in db.rows
                         if r["component"].startswith("n8n:") and r.get("lifecycle_state", "active") != "resolved"]
            return

    def fetchall(self):
        return self._res


def _siem_row(rid=7, lane=LOW_LANE, kind="RUN_FAILED", severity="WARN", error="exit=1 tail=SELFTEST_INDUCED_FAILURE"):
    f = {"lane_id": lane, "kind": kind, "component": f"n8n:{lane}", "event_type": kind, "severity": severity,
         "severity_basis": "registry:low", "priority": "P2", "source": "ledger", "detail": error,
         "detected_at": "2026-10-10T05:55:00+00:00", "workflow_id": "abc", "execution_id": "42",
         "run_id": "n8n-wf-abc-42", "remediation": "Read the RunReceipt stderr_tail", "remediation_source": "default"}
    return {"id": rid, "component": f"n8n:{lane}", "event_type": kind, "severity": severity,
            "message": B.message(f, "release:test@abc"), "action_taken": "n8n_siem_bridge: opened (ledger)",
            "lifecycle_state": "active", "created_at": "2026-10-10T05:55:01+00:00"}


def _ledger(tmp_path) -> Path:
    p = tmp_path / "state" / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    CoordinationLedger(p).close()
    return p


def _add_failed_run(ledger: Path, lane=LOW_LANE, stderr="boom"):
    led = CoordinationLedger(ledger)
    store = LedgerRunStore(led)
    store.request(run_id="n8n-wf-abc-42", lane_id=lane, mode="dry_run", requested_by="n8n:workflow:abc",
                  caller_id="n8n-relay", now=NOW.timestamp() - 400)
    store.claim_next(now=NOW.timestamp() - 390)
    store.finish("n8n-wf-abc-42", state="RUN_FAILED", now=NOW.timestamp() - 380,
                 receipt={"schema": "RunReceipt@v1", "exit_code": 1, "duration_s": 0.4, "reason": None,
                          "stderr_tail": stderr, "stdout_tail": "", "mode": "dry_run",
                          "finished_at": (NOW - timedelta(seconds=380)).isoformat()})
    led.close()


def _catalogue_file(tmp_path, *, lanes=None) -> Path:
    allow = dict(selftest.PROPOSED_ALLOWLIST_ENTRY)
    hi = {**allow, "lane_id": HIGH_LANE, "command": ["$PY", "scripts/generate_analyst_daily_digest.py"]}
    entries = [C.build_entry(LOW_LANE, [], allow=allow, registry_row=None, critical_ids={}),
               C.build_entry(HIGH_LANE, [{"inv_id": "cron:L569", "active": "yes", "business_function": "reporting"}],
                             allow=hi, registry_row=None, critical_ids={})]
    doc = {"schema": C.SCHEMA, "lanes": [e for e in entries if lanes is None or e["lane_id"] in lanes]}
    p = tmp_path / "catalogue.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _allowlist_file(tmp_path) -> Path:
    p = tmp_path / "allowlist.json"
    hi = {**selftest.PROPOSED_ALLOWLIST_ENTRY, "lane_id": HIGH_LANE}
    p.write_text(json.dumps({"lanes": [selftest.PROPOSED_ALLOWLIST_ENTRY, hi]}), encoding="utf-8")
    return p


def _registry_file(tmp_path, stage="shadow") -> Path:
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"lanes": [{"lane_id": LOW_LANE, "state": "ACTIVE",
                                         "scheduler": {"kind": "n8n", "expression": "dispatcher", "stage": stage,
                                                       "cadence": "*/15 * * * *"},
                                         "output_signal": {"kind": "file_mtime", "path": selftest.RECEIPT_REL}}]}),
                 encoding="utf-8")
    return p


class GovernedCall:
    """Fake bridge: records each call and returns the given answer under the live `_tradeai` envelope."""

    def __init__(self, answer, cost=0.0012, provider="grok", raise_on_call=False):
        self.answer, self.cost, self.provider, self.raise_on_call = answer, cost, provider, raise_on_call
        self.seen: list[dict] = []

    def __call__(self, messages, **kw):
        if self.raise_on_call:
            raise AssertionError("model must not be called")
        self.seen.append({"messages": messages, **kw})
        return {"choices": [{"message": {"content": json.dumps(self.answer)}}],
                "_tradeai": {"governance_pass": True, "process_id": kw.get("process_id"), "reservation_id": "res-1",
                             "model_id": "grok-fast", "provider": self.provider, "cost_estimate": self.cost,
                             "request_id": kw.get("request_id")}}


class FakeStore:
    def __init__(self):
        self.requests, self.finished = [], []

    def list(self, state=None, lane_id=None, limit=200):
        return []

    def list_running(self):
        return []

    def request(self, **kw):
        self.requests.append(kw)
        return {"run_id": kw["run_id"], "lane_id": kw["lane_id"], "mode": kw["mode"], "state": "REQUESTED",
                "requested_by": kw.get("requested_by"), "caller_id": kw.get("caller_id"), "requested_at": kw["now"]}, False

    def finish(self, run_id, **kw):
        self.finished.append((run_id, kw))


def _answer(action="rerun_dry_run", conf=0.9, cites=None):
    return {"cause": "the selftest lane exited 1 on purpose", "confidence": conf, "action_id": action,
            "rationale": "a dry rerun proves the lane recovers", "citations": cites if cites is not None else ["siem:7"],
            "recommendation": "NONE"}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.delenv("TRADEAI_N8N_COORDINATION_LEDGER", raising=False)
    monkeypatch.delenv("LLM_DEFER_OFFPEAK", raising=False)
    ledger = _ledger(tmp_path)
    _add_failed_run(ledger, stderr=("Traceback: SELFTEST_INDUCED_FAILURE\nDB_PASSWORD=" + SECRETS[1] + "\n"
                                    "Authorization: Bearer " + SECRETS[0] + "\njwt " + SECRETS[2] + "\n"
                                    "positions refreshed for account 12345678901 value $48,210.55\n"
                                    "acct XXXX-9876 synced\nconnection refused"))
    return {"state": state, "ledger": ledger, "catalogue": _catalogue_file(tmp_path),
            "allowlist": _allowlist_file(tmp_path), "registry": _registry_file(tmp_path)}


def _run(env, argv, *, db, call=None, store=None, deferral=None, now=NOW):
    return cli.main(argv, conn_factory=lambda: db, governed_call=call, now=now, catalogue_path=env["catalogue"],
                    registry_path=env["registry"], allowlist_path=env["allowlist"],
                    deferral=deferral or (lambda pid: type("Dec", (), {"defer": False, "reason": "DEFERRAL_DISABLED"})()),
                    store_factory=(lambda: store) if store is not None else None)


def _receipt(env) -> dict:
    return json.loads((env["state"] / cli.RECEIPT_REL).read_text())


def _records(env) -> list[dict]:
    p = env["state"] / cli.DIAGNOSES_REL
    return [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []


# ---------------------------------------------------------------- 1. catalogue generation


def _inventory(tmp_path) -> Path:
    inv = tmp_path / "inv"
    (inv / "analysis").mkdir(parents=True)
    base_cols = ["inv_id", "job_name", "source", "active", "known_issues", "custom_work_required", "migration_risk",
                 "business_function", "classification", "must_remain_outside_n8n"]
    rows = [
        ["n8n:aaa", "lane-low", "n8n", "yes", "flaky dns", "add retry", "Low", "monitoring", "Ready", "no"],
        ["n8n:bbb", "lane-cut", "n8n", "yes", "", "", "Low", "maintenance", "Ready", "no"],
        ["cron:L1", "lane-report", "crontab", "yes", "", "", "Low", "reporting", "R", "no"],
        ["cron:L2", "lane-wave", "crontab", "yes", "no lock", "wrap in flock", "Medium", "research", "R", "no"],
        ["cron:L3", "lane-cp1", "crontab", "yes", "", "", "Low", "monitoring", "R", "no"],
        ["cron:L4", "lane-broker", "crontab", "yes", "", "", "Low", "monitoring", "R", "no"],
        ["cron:L5", "lane-long", "crontab", "yes", "", "", "Low", "monitoring", "R", "no"],
        ["cron:L6", "lane-low", "crontab", "no", "", "", "High", "alerts-ops", "Retire", "n/a"],   # retired twin
    ]
    with (inv / "inventory_base.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(base_cols)
        w.writerows(rows)
    (inv / "enrich_S1.csv").write_text("inv_id,known_issues\ncron:L2,no lock (enriched)\n")
    (inv / "refactor_wave1.json").write_text(json.dumps({"W1": {"inv_ids": ["cron:L2"]}}))
    (inv / "analysis" / "critical_paths.csv").write_text("path,inv_id\nCP1 premarket,cron:L3\n")
    return inv


def _allow(lane, timeout=60, live=True, cmd=None):
    return {"lane_id": lane, "command": cmd or ["$PY", f"scripts/{lane.replace('-', '_')}.py"],
            "dry_run_arg": ["--dry-run"], "live_arg": ["--write"] if live else None, "lock": f"/tmp/{lane}.lock",
            "timeout_s": timeout, "output_signal": f"data/runtime/{lane}_last.json"}


def test_catalogue_generation_from_inventory(tmp_path):
    inv = _inventory(tmp_path)
    allowlist = {"lanes": [_allow("lane-low"), _allow("lane-cut"), _allow("lane-n8n"), _allow("lane-report"),
                           _allow("lane-cp1"),
                           _allow("lane-broker", cmd=["$PY", "scripts/broker_stop_reconcile.py"]),
                           _allow("lane-long", timeout=16200), _allow("trade-ai-scalp-live")]}
    registry = {"lanes": [{"lane_id": "lane-cut", "state": "ACTIVE",
                           "scheduler": {"kind": "n8n", "expression": "dispatcher", "stage": "cutover"}},
                          {"lane_id": "lane-n8n", "state": "ACTIVE", "scheduler": {"kind": "n8n", "expression": "x"}}]}
    doc = C.build_catalogue(inventory_dir=inv, registry=registry, allowlist=allowlist, as_of="2026-10-10",
                            selftest_entry=selftest.PROPOSED_ALLOWLIST_ENTRY)
    assert C.validate_catalogue(doc) == []
    lanes = {e["lane_id"]: e for e in doc["lanes"]}
    ids = lambda lane: {a["action_id"]: a["auto"] for a in lanes[lane]["actions"]}  # noqa: E731
    # severity: active rows only (the retired alerts-ops/High twin does not raise lane-low)
    assert lanes["lane-low"]["severity"] == "Low" and ids("lane-low") == {"rerun_dry_run": True, "reap_orphan_run": True}
    assert lanes["lane-low"]["known_issues"][0]["known_issues"] == "flaky dns"
    # registry stage cutover -> dry then live is offered; an n8n lane with no stage never gets a live rerun
    assert ids("lane-cut") == {"rerun_dry_run": True, "rerun_dry_then_live": True, "reap_orphan_run": True}
    assert lanes["lane-cut"]["actions"][1]["argv"]["live"][-1] == "--write"
    assert "rerun_dry_then_live" not in ids("lane-n8n")
    bad = json.loads(json.dumps(doc))
    next(e for e in bad["lanes"] if e["lane_id"] == "lane-cut")["registry"]["stage"] = "shadow"
    assert any("needs registry stage cutover" in e for e in C.validate_catalogue(bad))
    # reporting = High -> listed but human approval; CP1 -> Critical
    assert lanes["lane-report"]["severity"] == "High" and ids("lane-report")["rerun_dry_run"] is False
    assert lanes["lane-cp1"]["severity"] == "Critical"
    # wave-1 lane without an allowlist entry, broker argv, never-list lane: suggest_only
    assert lanes["lane-wave"]["actions"] == [] and "allowlist" in lanes["lane-wave"]["suggest_only_reason"]
    assert lanes["lane-wave"]["known_issues"][0]["known_issues"] == "no lock (enriched)"
    assert lanes["lane-broker"]["actions"] == [] and "FORBIDDEN" in lanes["lane-broker"]["suggest_only_reason"]
    assert "trade-ai-scalp-live" not in lanes   # excluded from LLM diagnosis (DIAGNOSIS_EXCLUDED_LANES, 2026-10-10 optional)
    # a long lane would hold the single executor worker -> approval
    assert ids("lane-long")["rerun_dry_run"] is False
    # the self-test lane is in scope from its proposed entry, and says so
    assert lanes[LOW_LANE]["allowlisted"] is False and "PROPOSED" in lanes[LOW_LANE]["allowlist_source"]
    assert ids(LOW_LANE)["rerun_dry_run"] is True
    assert doc["summary"]["lanes"] == len(lanes) and doc["summary"]["lanes_suggest_only"] >= 3


def test_catalogue_never_offers_unsafe_actions_and_validator_catches_them(tmp_path):
    doc = json.loads((ROOT / "config" / "n8n_remediation_catalogue.json").read_text())
    assert C.validate_catalogue(doc) == []
    text = json.dumps([e["actions"] for e in doc["lanes"]]).lower()   # known_issues prose may name anything
    for bad in ("systemctl", "crontab -e", "rm -", "send_telegram", "place_order", "restart_unit", "release_dlq"):
        assert bad not in text, bad
    assert {a["handler"] for e in doc["lanes"] for a in e["actions"]} <= C.HANDLERS
    tampered = json.loads(json.dumps(doc))
    tampered["lanes"][0]["actions"] = [{"action_id": "restart_unit", "handler": "shell", "argv": {"live": ["systemctl"]}}]
    errs = C.validate_catalogue(tampered)
    assert any("restart_unit" in e for e in errs) and any("handler" in e for e in errs)


def test_committed_catalogue_matches_a_rebuild_when_the_inventory_is_present():
    if not (builder.DEFAULT_INVENTORY / "inventory_base.csv").is_file():
        pytest.skip("cron inventory not on this host (CI): the committed file is validated by the test above")
    assert builder.main(["--check"]) == 0


# ---------------------------------------------------------------- 2. §2A: no portfolio data in the prompt


def test_prompt_contains_no_portfolio_data_or_secrets(env, capsys):
    db = FakeDB([_siem_row()])
    call = GovernedCall(_answer())
    assert _run(env, ["--apply"], db=db, call=call, store=FakeStore()) == 0
    assert len(call.seen) == 1
    prompt = json.dumps(call.seen[0]["messages"])
    for s in SECRETS + PORTFOLIO:
        assert s not in prompt, s
    assert "SELFTEST_INDUCED_FAILURE" in prompt and "connection refused" in prompt   # error text and logs do go
    assert D.WITHHELD_LINE in prompt
    for key in ("\"positions\"", "\"holdings\"", "\"accounts\"", "\"account_number\"", "\"shares\""):
        assert key not in prompt
    assert call.seen[0]["process_id"] == D.PROCESS_ID and call.seen[0]["task_type"] == "lane_failure_diagnosis"


def test_scrub_and_egress_check():
    raw = {"lane": "x", "positions": [{"symbol": "AAPL", "qty": 10}], "holdings": 3, "account_number": "123",
           "note": "API_KEY=abcd1234 balance $9,999.00 for account 99887766554", "nested": {"cost_basis": 1.0}}
    assert D.egress_violations(raw)
    clean = D.scrub_obj(raw)
    assert D.egress_violations(clean) == []
    assert set(clean) == {"lane", "note", "nested"} and clean["nested"] == {}
    assert D.scrub_text("token=abc\nok line") == "token=[REDACTED]\nok line"


def test_egress_refusal_blocks_the_call(env, monkeypatch):
    monkeypatch.setattr(D, "scrub_obj", lambda v: {**v, "positions": [1]})   # a scrubber regression
    call = GovernedCall(_answer(), raise_on_call=True)
    assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=call, store=FakeStore()) == 0
    res = _receipt(env)["results"][0]
    assert res["reason"] == "egress_refused" and res["decision"]["priority"] == "P1" and not res.get("model_called")


# ---------------------------------------------------------------- 3. bounded remediation


def test_action_not_in_catalogue_is_refused_and_escalated(env):
    store = FakeStore()
    db = FakeDB([_siem_row()])
    call = GovernedCall(_answer(action="restart_unit:executor"))
    assert _run(env, ["--apply"], db=db, call=call, store=store) == 0
    assert store.requests == [] and store.finished == []
    rec = _receipt(env)
    res = rec["results"][0]
    assert res["decision"] == {"kind": "escalate", "priority": "P1", "reason": "action_not_in_catalogue_refused",
                               "action_id": "suggest_only"}
    assert res["verdict"]["refused_action_id"] == "restart_unit:executor"
    assert rec["escalations"][0]["priority"] == "P1"


def test_model_text_never_executes(env):
    """Even a catalogue-shaped answer carrying shell text only selects a handler; argv comes from the catalogue."""
    store = FakeStore()
    ans = {**_answer(), "rationale": "run `rm -rf /` then systemctl restart"}
    assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=GovernedCall(ans), store=store) == 0
    assert len(store.requests) == 1
    req = store.requests[0]
    assert req["lane_id"] == LOW_LANE and req["mode"] == "dry_run" and req["caller_id"] == cli.CALLER_ID
    assert set(req) == {"run_id", "lane_id", "mode", "requested_by", "caller_id", "now"}


def test_approval_required_for_high_severity_lane(env, tmp_path):
    store = FakeStore()
    row = _siem_row(rid=9, lane=HIGH_LANE)
    call = GovernedCall(_answer(cites=["siem:9"]))
    assert _run(env, ["--apply"], db=FakeDB([row]), call=call, store=store) == 0
    res = _receipt(env)["results"][0]
    assert store.requests == [] and res["decision"]["priority"] == "P2"
    assert res["decision"]["reason"].startswith("approval_required")


# ---------------------------------------------------------------- 4. dry run


def test_dry_run_makes_no_model_call_and_writes_nothing(env, capsys):
    db = FakeDB([_siem_row()])
    def snapshot():
        files = sorted(str(p.relative_to(env["state"])) for p in env["state"].rglob("*")
                       if not str(p).endswith(("-wal", "-shm")))
        led = CoordinationLedger(env["ledger"])
        runs = [dict(r) for r in led._conn.execute("SELECT * FROM runs ORDER BY run_id").fetchall()]
        led.close()
        return files, runs

    before = snapshot()
    call = GovernedCall(_answer(), raise_on_call=True)
    store = FakeStore()
    assert _run(env, ["--dry-run"], db=db, call=call, store=store) == 0
    assert snapshot() == before
    assert not any(s.lstrip().upper().startswith("UPDATE") for s in db.sql) and db.commits == 0
    assert store.requests == [] and call.seen == []
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["mode"] == "dry-run" and out["model_calls"] == 0
    would = out["would"][0]
    assert would["lane"] == LOW_LANE and would["prompt_bytes"] > 0 and would["provider"] == "fixture"
    assert would["decision"]["priority"] == "P1"   # the default fixture is confidence 0 -> would escalate


def test_dry_run_with_fixture_reports_the_action_it_would_take(env, tmp_path, capsys):
    fx = tmp_path / "fx.json"
    fx.write_text(json.dumps(_answer()))
    assert _run(env, ["--dry-run", "--fixture", str(fx)], db=FakeDB([_siem_row()]), store=FakeStore()) == 0
    would = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["would"][0]
    assert would["decision"]["kind"] == "execute" and would["decision"]["action_id"] == "rerun_dry_run"


def test_dry_run_branch_returns_before_any_write_is_reachable():
    src = (ROOT / "scripts" / "n8n_failure_diagnosis.py").read_text()
    body = src[src.index("def main("):]
    assert body.index("if args.dry_run:") < body.index("apply_results(") < body.index("_atomic(root / STATE_REL")
    dry = body[body.index("if args.dry_run:"):body.index("# ---- apply")]
    for forbidden in ("apply_results", "_atomic", "execute_action", "_bridge_call", "apply=True"):
        assert forbidden not in dry, forbidden
    with pytest.raises(SystemExit):
        cli.main(["--apply", "--fixture", "x.json"])


# ---------------------------------------------------------------- 5. SIEM row write-back


def _bridge_plan(rows, diagnoses):
    """What the SIEM bridge would do with the same finding (it rebuilds the base message from the ledger)."""
    f = {"lane_id": LOW_LANE, "kind": "RUN_FAILED", "component": f"n8n:{LOW_LANE}", "event_type": "RUN_FAILED",
         "severity": "WARN", "severity_basis": "registry:low", "priority": "P2", "source": "ledger",
         "detail": "exit=1 tail=SELFTEST_INDUCED_FAILURE", "detected_at": "2026-10-10T05:55:00+00:00",
         "workflow_id": "abc", "execution_id": "42", "run_id": "n8n-wf-abc-42",
         "remediation": "Read the RunReceipt stderr_tail", "remediation_source": "default"}
    return B.plan({(f["component"], f["event_type"]): f}, rows, env="release:test@abc", good_lanes=set(),
                  ledger_ok=True, fanin_ok=True, diagnoses=diagnoses)


def test_diagnoser_never_touches_system_health_events(env):
    """Change 1 (§9.4): read-only SELECT inside a READ ONLY transaction, never INSERT/UPDATE/DELETE, never commit."""
    row = _siem_row()
    db = FakeDB([row])
    store = FakeStore()
    assert _run(env, ["--apply"], db=db, call=GovernedCall(_answer()), store=store) == 0
    assert [q.strip().split()[0].upper() for q in db.sql] == ["SET", "SELECT"] and db.commits == 0
    assert db.rows == [row]                                       # byte-for-byte untouched
    src = (ROOT / "scripts" / "n8n_failure_diagnosis.py").read_text()
    assert not re.search(r"(?i)\b(update|insert\s+into|delete\s+from)\s+system_health_events", src)
    rec = _receipt(env)
    assert rec["ok"] and rec["counts"]["execute"] == 1 and rec["applied"]["diagnoses_appended"] == 1
    assert "siem_updated" not in rec["applied"]


def test_successful_diagnosis_goes_to_its_own_store_and_the_bridge_folds_it(env):
    row = _siem_row()
    db = FakeDB([row])
    store = FakeStore()
    assert _run(env, ["--apply"], db=db, call=GovernedCall(_answer()), store=store) == 0
    (d,) = _records(env)
    assert d["schema"] == B.DIAGNOSIS_SCHEMA and d["kind"] == "diagnosis" and d["siem_id"] == 7
    assert d["incident_key"] == D.incident_key(row) and d["component"] == f"n8n:{LOW_LANE}"
    assert d["incident_refs"]["run"] == "n8n-wf-abc-42" and d["incident_refs"]["execution"] == "42"
    assert d["cause"] == "the selftest lane exited 1 on purpose" and d["confidence"] == 0.9
    assert d["action_id"] == "rerun_dry_run" and d["outcome"].startswith("requested:dry_run:rem-")
    assert (d["provider"], d["model_id"], d["cost_usd"]) == ("grok", "grok-fast", 0.0012)
    assert d["citations"] == ["siem:7"] and d["latency_ms"] is not None
    rec = _receipt(env)
    assert rec["results"][0]["evidence_artifact"]["store"] == "data/runtime"
    assert (env["state"] / "data" / "runtime" / rec["results"][0]["evidence_artifact"]["ref"]).is_file()
    # the bridge (the row's one writer) folds it into exactly that row
    diags, note = B.read_diagnoses(env["state"] / cli.DIAGNOSES_REL)
    assert note == "diagnoses:ok:1"
    p = _bridge_plan([row], diags)
    (up,) = p["update"]
    assert up["id"] == 7 and up["diagnosis_folded"] == d["incident_key"]
    assert B.DIAG_MARKER in up["message"] and "action=rerun_dry_run" in up["message"]
    assert "model=grok/grok-fast" in up["message"] and "cost_usd=0.0012" in up["message"]
    assert up["action_note"].startswith("n8n_siem_bridge: diagnosis folded (n8n_failure_diagnosis: rerun_dry_run ->")
    # the folded row keeps the same incident key: the diagnoser does not diagnose it again
    folded = {**row, "message": up["message"]}
    assert D.incident_key(folded) == D.incident_key(row)
    assert _bridge_plan([folded], diags)["skip"][0]["id"] == 7          # idempotent: second pass is a skip
    call2 = GovernedCall(_answer(), raise_on_call=True)
    assert _run(env, ["--apply"], db=FakeDB([folded]), call=call2, store=store) == 0
    assert len(store.requests) == 1 and _receipt(env)["skipped_reasons"] == {"already_diagnosed": 1}
    assert [r["kind"] for r in _records(env)].count("diagnosis") == 1     # (FakeStore: the rerun row is "missing")


def test_rerun_goes_through_the_gateway_run_path(env, monkeypatch):
    """Change 2: the catalogue rerun is coordination/run's own validation + row, not a direct ledger insert."""
    seen = []
    real = G.host_run_request
    monkeypatch.setattr(G, "host_run_request", lambda **kw: seen.append(kw) or real(**kw))
    store = FakeStore()
    assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=GovernedCall(_answer()), store=store) == 0
    (kw,) = seen
    assert kw["lane_id"] == LOW_LANE and kw["mode"] == "dry_run" and kw["caller_id"] == cli.CALLER_ID
    assert LOW_LANE in kw["run_allowlist"] and len(store.requests) == 1
    # the gateway's validation applies: a lane outside the allowlist or a dispatcher slot key is refused
    assert G.host_run_request(lane_id="not-allowlisted", mode="dry_run", run_id="rem-abcdefghijkl-dry_run",
                              requested_by="x", caller_id="y", run_store=store, run_allowlist=frozenset({LOW_LANE}),
                              now=1.0)["reason"] == "run_lane_not_allowlisted"
    assert G.host_run_request(lane_id=LOW_LANE, mode="dry_run", run_id="d:x:dry_run:20261010T0600",
                              requested_by="x", caller_id="y", run_store=store, run_allowlist=frozenset({LOW_LANE}),
                              now=1.0)["reason"] == "run_slot_not_due"
    assert len(store.requests) == 1


def test_live_rerun_only_for_a_lane_at_stage_cutover(tmp_path):
    allow = {LOW_LANE: selftest.PROPOSED_ALLOWLIST_ENTRY}
    for stage in ("shadow", "canary", None):
        rows = [{"lane_id": LOW_LANE, "scheduler": {"kind": "n8n", "expression": "dispatcher",
                                                     **({"stage": stage} if stage else {})}}]
        store = FakeStore()
        got = cli.handle_request_run(store, lane=LOW_LANE, mode="live", run_id="rem-siem7-abcdef-live", allowlist=allow,
                                     now=1.0, registry_rows=rows)
        assert not got["ok"] and got["outcome"].startswith("precondition_unmet:live_rerun_needs_stage_cutover")
        assert store.requests == []
        assert cli.rerun_phases({"mode_sequence": ["dry_run", "live"]}, LOW_LANE, rows)[0] == ["dry_run"]
    assert not cli.handle_request_run(FakeStore(), lane=LOW_LANE, mode="live", run_id="rem-siem7-abcdef-live",
                                      allowlist=allow, now=1.0, registry_rows=None)["ok"]      # registry unreadable
    cut = [{"lane_id": LOW_LANE, "scheduler": {"kind": "n8n", "expression": "dispatcher", "stage": "cutover"}}]
    store = FakeStore()
    assert cli.handle_request_run(store, lane=LOW_LANE, mode="live", run_id="rem-siem7-abcdef-live", allowlist=allow,
                                  now=1.0, registry_rows=cut)["ok"]
    assert store.requests[0]["mode"] == "live"
    assert cli.rerun_phases({"mode_sequence": ["dry_run", "live"]}, LOW_LANE, cut) == (["dry_run", "live"], None)


def test_shadow_lane_rerun_requested_live_still_runs_dry_in_the_executor(tmp_path):
    """Defence in depth: even a live row in the ledger for a shadow lane executes dry_run (executor stage clamp)."""
    from scripts import n8n_run_executor as X

    entry = {**selftest.PROPOSED_ALLOWLIST_ENTRY, "command": ["/bin/true"], "lock": str(tmp_path / "l.lock")}
    ran = []

    def runner(argv, **kw):
        ran.append(argv)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    rows = [{"lane_id": LOW_LANE, "scheduler": {"kind": "n8n", "expression": "dispatcher", "stage": "shadow"}}]
    rec = X.execute({"run_id": "rem-siem7-abcdef-live", "lane_id": LOW_LANE, "mode": "live"}, entry, env={},
                    state_root=tmp_path, code_root=tmp_path, runner=runner, stage_rows=rows)
    assert rec["mode"] == "dry_run" and rec["requested_mode"] == "live" and rec["stage_clamp"]["reason"] == "stage_shadow"
    assert ran[0][-1].endswith("n8n_runs/shadow/n8n_selftest_fail_last.json")     # the dry_run_arg ran
    assert S.clamp_mode(LOW_LANE, "live", rows)["effective_mode"] == "dry_run"


def test_pending_rerun_advances_then_failure_escalates_p1(env, tmp_path):
    store = LedgerRunStore(CoordinationLedger(env["ledger"]))
    db = FakeDB([_siem_row()])
    assert _run(env, ["--apply"], db=db, call=GovernedCall(_answer()), store=store) == 0
    st = json.loads((env["state"] / cli.STATE_REL).read_text())
    (key, pend), = st["pending"].items()
    assert store.get(pend["run_id"])["state"] == "REQUESTED"
    store.claim_next(now=NOW.timestamp() + 10)
    store.finish(pend["run_id"], state="RUN_FAILED", receipt={"exit_code": 1}, now=NOW.timestamp() + 20)
    assert _run(env, ["--apply"], db=db, call=GovernedCall(_answer(), raise_on_call=True), store=store,
                now=NOW + timedelta(minutes=5)) == 0
    rec = _receipt(env)
    assert rec["pending"][0]["outcome"] == "remediation_failed:RUN_FAILED"
    assert any(e["priority"] == "P1" and "remediation_failed" in e["reason"] for e in rec["escalations"])
    rem = [r for r in _records(env) if r["kind"] == "remediation"]
    assert [r["outcome"] for r in rem] == ["remediation_failed:RUN_FAILED"] and rem[0]["escalation"] == "P1"
    diags, _ = B.read_diagnoses(env["state"] / cli.DIAGNOSES_REL)
    up = _bridge_plan(db.rows, diags)["update"][0]
    assert "remediation=remediation_failed:RUN_FAILED" in up["message"] and "remediation_escalated=P1" in up["message"]


def test_reap_orphan_handler_uses_the_reaper_receipt(tmp_path):
    ledger = _ledger(tmp_path)
    store = LedgerRunStore(CoordinationLedger(ledger))
    t0 = NOW.timestamp() - 3600
    store.request(run_id="n8n-wf-xyz-1552", lane_id=LOW_LANE, mode="live", requested_by="n8n", caller_id="n8n-relay", now=t0)
    store.claim_next(now=t0 + 1)
    allow = {LOW_LANE: selftest.PROPOSED_ALLOWLIST_ENTRY}
    got = cli.handle_reap_orphan(store, lane=LOW_LANE, allowlist=allow, now=NOW.timestamp())
    assert got["ok"] and store.get("n8n-wf-xyz-1552")["state"] == "RUN_TIMEOUT"
    rec = store.get("n8n-wf-xyz-1552")["receipt"]
    assert rec["reason"] == "executor_lost" and rec["reaped_by"] == "n8n_failure_diagnosis"
    assert cli.handle_reap_orphan(store, lane=LOW_LANE, allowlist=allow, now=NOW.timestamp())["outcome"] == \
        "precondition_unmet:no_orphan_running_row"


# ---------------------------------------------------------------- 6. escalation


def test_low_confidence_escalates_p1_through_the_fanin(env, monkeypatch):
    store = FakeStore()
    assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=GovernedCall(_answer(conf=0.4)), store=store) == 0
    rec = _receipt(env)
    assert store.requests == []
    assert rec["escalations"][0]["priority"] == "P1" and rec["escalations"][0]["reason"] == "low_confidence"
    monkeypatch.setattr(fanin, "_governance_lane", lambda lane: None)
    found = fanin._diagnosis_findings(env["state"], NOW + timedelta(minutes=1))
    assert [(f["source"], f["severity"]) for f in found] == [("n8n_failure_diagnosis", "P1")]
    assert found[0]["item"].startswith(f"escalate:{LOW_LANE}/") and "low_confidence" in found[0]["detail"]
    # the SIEM bridge maps the escalation to its own component (never onto the lane's row)
    lane, kind = B.lane_kind(found[0]["source"], found[0]["item"])
    assert lane.startswith("n8n_failure_diagnosis/") and kind == "ESCALATE"


def test_ungrounded_citations_count_as_low_confidence(env):
    assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=GovernedCall(_answer(cites=["run:made-up"])),
                store=FakeStore()) == 0
    assert _receipt(env)["results"][0]["decision"]["reason"] == "low_confidence_ungrounded"


def test_diagnoser_liveness_is_a_p1_once_scheduled(env, monkeypatch):
    monkeypatch.setattr(fanin, "_governance_lane", lambda lane: {"state": "ACTIVE", "expected_cadence_hours": 5 / 60,
                                                                 "scheduler": {"kind": "n8n", "stage": "shadow"}})
    assert fanin._diagnosis_findings(env["state"], NOW) == []          # shadow = --dry-run = no receipt by design
    monkeypatch.setattr(fanin, "_governance_lane", lambda lane: {"state": "ACTIVE", "scheduler": {"kind": "n8n"},
                                                                 "expected_cadence_hours": 5 / 60})
    assert [f["item"] for f in fanin._diagnosis_findings(env["state"], NOW)] == ["diagnoser:receipt_missing"]
    (env["state"] / cli.RECEIPT_REL).parent.mkdir(parents=True, exist_ok=True)
    (env["state"] / cli.RECEIPT_REL).write_text(json.dumps({"as_of": (NOW - timedelta(hours=2)).isoformat(),
                                                             "ok": False, "consecutive_blind": 2}))
    items = sorted(f["item"] for f in fanin._diagnosis_findings(env["state"], NOW))
    assert items == ["diagnoser:blind", "diagnoser:cycle_not_ok", "diagnoser:receipt_stale"]
    assert {f["severity"] for f in fanin._diagnosis_findings(env["state"], NOW)} == {"P1"}


# ---------------------------------------------------------------- 7. cost cap


def test_cost_caps_are_registered():
    reg = {p["id"]: p for p in json.loads((ROOT / "config" / "llm_process_registry.json").read_text())["processes"]}
    row = reg[D.PROCESS_ID]
    assert row["daily_cost_cap_usd"] == D.DAILY_CAP_USD and row["output_schema_id"] == D.OUTPUT_SCHEMA_ID
    assert row["tools_allowed"] is False and row["advisory_only"] is True and row["free_text_allowed"] is False
    route = json.loads((ROOT / "config" / "llm_routing_policy.json").read_text())["policies"]["default"]["processes"][D.PROCESS_ID]
    assert route["cost_ceiling_usd"] == D.PER_CALL_CAP_USD == 0.05
    assert [route[k]["provider"] for k in ("primary", "secondary", "fallback")] == ["grok", "chatgpt", "deepseek"]


def test_projected_cost_over_the_per_call_cap_makes_no_call(env, monkeypatch):
    monkeypatch.setattr(D, "PER_CALL_CAP_USD", 0.000001)
    call = GovernedCall(_answer(), raise_on_call=True)
    assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=call, store=FakeStore()) == 0
    assert _receipt(env)["results"][0]["reason"] == "per_call_cost_cap"


def test_daily_cap_reached_makes_no_call(env):
    st = cli.empty_state()
    cli.day_bucket(st, NOW)["spend_usd"] = D.DAILY_CAP_USD
    (env["state"] / cli.STATE_REL).parent.mkdir(parents=True, exist_ok=True)
    (env["state"] / cli.STATE_REL).write_text(json.dumps(st))
    call = GovernedCall(_answer(), raise_on_call=True)
    assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=call, store=FakeStore()) == 0
    res = _receipt(env)["results"][0]
    assert res["reason"] == "process_daily_cap" and res["decision"]["priority"] == "P2"
    assert res["incident_key"] not in json.loads((env["state"] / cli.STATE_REL).read_text())["diagnosed"]   # retried


def test_measured_cost_over_the_cap_stops_the_cycle_and_escalates(env):
    rows = [_siem_row(rid=7), _siem_row(rid=8, kind="RUN_TIMEOUT")]
    call = GovernedCall(_answer(cites=["siem:7"]), cost=0.08)
    store = FakeStore()
    assert _run(env, ["--apply"], db=FakeDB(rows), call=call, store=store) == 0
    rec = _receipt(env)
    assert len(call.seen) == 1 and store.requests == []
    first = [r for r in rec["results"] if r.get("model_called")][0]
    assert first["decision"]["reason"] == "per_call_cost_cap_breached" and first["decision"]["priority"] == "P1"
    assert [r for r in rec["results"] if not r.get("model_called")][0]["outcome"] == "not_this_cycle"


def test_deferral_is_respected(env):
    call = GovernedCall(_answer(), raise_on_call=True)
    dec = lambda pid: type("Dec", (), {"defer": True, "reason": "OUTSIDE_OFFPEAK_WINDOW"})()  # noqa: E731
    assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=call, store=FakeStore(), deferral=dec) == 0
    res = _receipt(env)["results"][0]
    assert res["reason"] == "deferred_offpeak" and res["decision"]["priority"] == "P2"
    # a deferred incident is retried next cycle (not recorded as diagnosed)
    assert not json.loads((env["state"] / cli.STATE_REL).read_text())["diagnosed"]


# ---------------------------------------------------------------- 8. registration


def test_capability_is_registered_end_to_end():
    from scripts.lib import cio_governed_model_bridge as bridge

    assert M.task_type_for(D.PROCESS_ID) == "lane_failure_diagnosis"
    assert bridge.CALLER_TASK_PROCESS_MAP["n8n_model_job"]["lane_failure_diagnosis"] == D.PROCESS_ID
    tpls = M.load_templates()
    assert D.TEMPLATE_ID in tpls and "_invalid" not in tpls
    assert tpls[D.TEMPLATE_ID]["process_id"] == D.PROCESS_ID
    schema = M.load_schemas()[D.OUTPUT_SCHEMA_ID]
    assert M.validate(_answer(), schema) == []
    assert M.validate({**_answer(), "argv": ["rm"]}, schema)


# ---------------------------------------------------------------- 9. selftest lane classes


@pytest.mark.parametrize("cls,code,writes", [("ok", 0, True), ("exit1", 1, False), ("timeout", 124, False),
                                             ("no_receipt", 0, False)])
def test_selftest_classes(tmp_path, monkeypatch, cls, code, writes):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    slept = []
    assert selftest.main(["--mode", cls], now=NOW, sleeper=slept.append) == code
    assert (tmp_path / selftest.RECEIPT_REL).is_file() is writes
    assert slept == ([600.0] if cls == "timeout" else [])


def test_selftest_stale_output_pins_the_mtime(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert selftest.main(["--mode", "ok"], now=NOW) == 0
    p = tmp_path / selftest.RECEIPT_REL
    os.utime(p, (1_000_000, 1_000_000))
    assert selftest.main(["--mode", "stale_output"], now=NOW) == 0
    assert p.stat().st_mtime == 1_000_000 and json.loads(p.read_text())["class"] == "stale_output"


def test_selftest_dry_run_writes_nothing_and_arm_is_consumed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    for argv in (["--mode", "exit1", "--dry-run"], ["--arm", "exit1", "--dry-run"], ["--dry-run"]):
        assert selftest.main(argv, now=NOW) == 0
    assert list(tmp_path.rglob("*")) == []
    assert selftest.main(["--arm", "exit1", "--count", "1"], now=NOW) == 0
    assert selftest.main([], now=NOW) == 1                      # armed: fails once (S6b/S1)
    assert selftest.main([], now=NOW) == 0                      # consumed: ok again (S6a)
    assert selftest.main(["--arm", "timeout", "--ttl-min", "1"], now=NOW) == 0
    assert selftest.resolve_class(None, tmp_path, NOW + timedelta(minutes=2))[0] == "ok"   # expired


def test_no_sends_no_shell_no_broker_in_the_new_code():
    for rel in ("scripts/n8n_failure_diagnosis.py", "scripts/lib/n8n_failure_diagnosis.py",
                "scripts/lib/n8n_remediation_catalogue.py", "scripts/n8n_selftest_fail.py",
                "scripts/build_remediation_catalogue.py"):
        src = (ROOT / rel).read_text()
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        for bad in ("send_telegram(", "send_system(", "subprocess", "os.system", "shell=True", "Popen", "schwab",
                    "place_order", "os.remove", "unlink(", "rmtree"):
            assert bad not in code, (rel, bad)
