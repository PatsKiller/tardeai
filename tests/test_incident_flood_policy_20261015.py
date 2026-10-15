"""Incident-flood reduction rules (WS1-09, WS3-10, WS3-11, WS3-35; 2026-10-15).

scripts/lib/incident_flood_policy.py + its two callers: the fan-in (drop / auto-resolve / collapse / demote) and the
notifier (per-source P2 budget, P1 and recoveries off the P2 cap). The headline guarantee is pinned with the SPCX
stop-alert cases of 2026-10-14: no P0/P1 stop, broker or safety alert is ever dropped, collapsed, demoted,
auto-resolved, budgeted or capped, in report-only or enforce mode.

Every test uses a tmp state root, a stub sender and a tmp or missing ledger. Nothing reaches Telegram, the token
store, the live ledger or the live runtime state."""

from __future__ import annotations

import io
import json
import sqlite3
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import incident_notifier as N  # noqa: E402
from scripts import n8n_incident_fanin as F  # noqa: E402
from scripts.lib import incident_flood_policy as FP  # noqa: E402

T0 = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)  # 16:00 ET, outside quiet hours
ENV = {"TRADEAI_SERVED_SHA": "test-sha"}
ENFORCE = {**ENV, "TRADEAI_INCIDENT_FLOOD_POLICY_MODE": "enforce"}


def _policy(mode: str = "enforce") -> dict:
    return FP.load_policy({FP.ENV_MODE: mode})


def _diag(lane: str, key: str, reason: str, sev: str = "P2", event_type: str = "NO_OUTPUT", at: datetime = T0) -> dict:
    return {
        "source": "n8n_failure_diagnosis",
        "item": f"escalate:{lane}/{key}",
        "severity": sev,
        "detail": f"{reason}; conf=0.55; cause=x; siem=1",
        "detected_at": at.isoformat(),
        "artifact_rel": "data/runtime/n8n_failure_diagnosis_last.json",
        "store": "data/runtime",
        "lane": lane,
        "event_type": event_type,
        "reason": reason,
    }


def _flood(n: int = 700) -> list[dict]:
    """The 2026-10-14 shape: hundreds of diagnoser self-reports, mostly its own policy refusals."""
    reasons = ["deferred_offpeak", "lane_daily_call_cap", "process_daily_cap", "model_refused:governance_refused"]
    lanes = ["heartbeat-watch", "n8n-pilot-dispatch", "hermes-score-event-feeder", "document-mentions-backfill"]
    out = [_diag(lanes[i % 4], f"siem{i}-{i:012x}", reasons[i % 4]) for i in range(n)]
    out += [_diag("heartbeat-watch", f"siemL{i}", "low_confidence", "P1", "UNGOVERNED") for i in range(9)]
    out += [_diag("investment-costs", f"siemO{i}", "model_refused:provider_outage") for i in range(5)]
    return out


# The SPCX incident, 2026-10-14: stops filled at 14:36/14:38 ET while the near-trigger warnings were digested.
_REF = {"artifact_rel": "data/runtime/x.json", "store": "data/runtime"}
SPCX_CASES = [
    {**_REF, **c}
    for c in [
        {
            "source": "comms_intent",
            "item": "stops:NEAR_TRIGGER:SPCX",
            "severity": "P1",
            "detail": "SPCX (schwab_rollover_ira) price within 0.46% of stop $151.5 — about to fire",
            "detected_at": T0.isoformat(),
        },
        {
            "source": "comms_intent",
            "item": "stops:TRIGGERED:SPCX",
            "severity": "P0",
            "detail": "STOP HEALTH — TRIGGERED: SPCX (schwab_taxable) stop FILLED (#1008189857145)",
            "detected_at": T0.isoformat(),
        },
        {
            "source": "breach_detector",
            "item": "stop-health-check:FAILING",
            "severity": "P1",
            "detail": "{'cmd': 'python3 scripts/stop_health_check.py --alert'}",
            "detected_at": T0.isoformat(),
        },
        {
            "source": "expected_services",
            "item": "INACTIVE:tradeai-schwab-stream.service",
            "severity": "P1",
            "detail": "expected_services ran_at x",
            "detected_at": T0.isoformat(),
        },
        # A diagnoser P1 about a stop lane: low confidence, but it names the stop control -> never demoted or collapsed.
        {
            **_diag("stop-health-check", "siem9-aaaaaaaaaaaa", "low_confidence", "P1", "FAILING"),
            "detail": "low_confidence; conf=0.5; cause=STOP HEALTH NEAR_TRIGGER SPCX not delivered; siem=9",
        },
        # A diagnoser policy refusal on a broker lane: refusals are dropped, but not this one.
        _diag("schwab-stop-sync", "siem10-bbbbbbbbbbbb", "deferred_offpeak", "P2", "NO_OUTPUT"),
        # A broker-adjacent dead letter: auto-resolve must not touch it even after the lane succeeds.
        {
            "source": "dlq",
            "item": "dlq:d:schwab-positions-sync:live:20261009T1530",
            "severity": "P2",
            "detail": "schwab-positions-sync live RUN_FAILED exit_1 attempts 3",
            "detected_at": T0.isoformat(),
            "lane": "schwab-positions-sync",
            "mode": "live",
        },
    ]
]


# ------------------------------------------------------------------------------------------------ policy loading


def test_default_mode_is_report_only_and_bad_or_missing_config_stays_report_only(tmp_path):
    assert FP.load_policy({})["mode"] == "report_only"
    assert json.loads((ROOT / "config" / "incident_flood_policy.json").read_text())["mode"] == "report_only"
    assert FP.load_policy({FP.ENV_MODE: "enforce"})["mode"] == "enforce"
    assert FP.load_policy({FP.ENV_MODE: "yolo"})["mode"] == "report_only"
    missing = FP.load_policy({FP.ENV_PATH: str(tmp_path / "nope.json")})
    assert missing["mode"] == "report_only" and missing["config_note"].startswith("unavailable")
    assert not FP.p1_counts_toward_cap(_policy()) and FP.p1_counts_toward_cap(_policy("report_only"))
    assert not FP.recoveries_count_toward_cap(_policy()) and FP.recoveries_count_toward_cap(_policy("report_only"))


def test_empty_policy_still_protects_p0_p1_and_stop_mentions():
    assert FP.is_protected({"source": "n8n_failure_diagnosis", "item": "x", "severity": "P1"}, {})
    assert FP.is_protected({"source": "x", "item": "y", "severity": "P0"}, {})
    assert FP.is_protected({"source": "x", "item": "stop-health-check:NO_OUTPUT", "severity": "P2"}, {})
    assert not FP.is_protected({"source": "x", "item": "document-mentions-backfill:NO_OUTPUT", "severity": "P2"}, {})


# ------------------------------------------------------------------------------------------------ SPCX guarantee


@pytest.mark.parametrize("mode", ["report_only", "enforce"])
def test_spcx_stop_broker_safety_findings_survive_every_fanin_rule(mode):
    policy = _policy(mode)
    for case in SPCX_CASES:
        assert FP.is_protected(case, policy), case["item"]
    # a lane success after every SPCX case: auto-resolve would close the dead letter if it were not protected
    succ = FP.successes_from_rows(
        [
            {"lane_id": c.get("lane") or "x", "mode": "live", "finished_at": (T0 + timedelta(hours=1)).isoformat()}
            for c in SPCX_CASES
        ]
    )
    res = FP.apply_fanin_policy(_flood() + SPCX_CASES, policy, successes=succ)
    for case in SPCX_CASES:
        assert case in res["findings"], f"suppressed: {case['item']}"
    touched = {r["item"] for k in ("dropped", "auto_resolved", "demoted") for r in res[k]}
    assert not touched & {c["item"] for c in SPCX_CASES}
    assert {c["item"] for c in SPCX_CASES} <= {p["item"] for p in res["protected"]}


def test_every_p0_p1_outside_the_diagnoser_passes_through_unchanged():
    rows = [
        {"source": s, "item": f"{s}:x", "severity": sev, "detail": "", "detected_at": T0.isoformat()}
        for s in ("expected_services", "cio_bridge_watchdog", "n8n_alert_path", "runs", "dlq", "heartbeat")
        for sev in ("P0", "P1")
    ]
    res = FP.apply_fanin_policy(rows + _flood(50), _policy())
    for r in rows:
        assert r in res["findings"]


def test_spcx_p0_p1_reach_the_operator_through_a_full_flood_with_every_budget_and_the_cap_spent(tmp_path):
    rows = [_row(c["source"], c["item"], c["severity"], c["detail"]) for c in SPCX_CASES]
    rows += [_row("n8n_failure_diagnosis", f"collapse:lane{i}/NO_OUTPUT", "P2") for i in range(300)]
    _fanin(tmp_path, rows)
    spent = {
        s: 10_000 for s in ("comms_intent", "breach_detector", "dlq", "n8n_failure_diagnosis", "expected_services")
    }
    for env in (ENV, ENFORCE):
        _write_state(tmp_path, sends=10_000, triggers=spent)
        cap = Capture()
        rec = _run(tmp_path, sender=cap, env=env)
        p1 = [m for m in rec["messages"] if m["kind"] == "p1"]
        assert p1 and p1[0]["status"] == "SENT", env
        for c in SPCX_CASES:
            if c["severity"] in ("P0", "P1"):
                assert c["item"] in cap.calls[0]["text"], (env, c["item"])  # the P0 pages as P1, never skipped


# ------------------------------------------------------------------------------------------------ fan-in rules


def test_policy_refusals_and_lock_skips_are_not_incidents():
    rows = [
        _diag("a", "k1", "deferred_offpeak"),
        _diag("a", "k2", "lane_daily_call_cap"),
        _diag("a", "k3", "remediation_failed:RUN_SKIPPED_LOCK", "P1", "RUN_FAILED"),
        _diag("a", "k4", "remediation_failed:RUN_REFUSED", "P1", "RUN_FAILED"),
        _diag("b", "k5", "model_refused:provider_outage"),
    ]
    res = FP.apply_fanin_policy(rows, _policy())
    assert {d["item"] for d in res["dropped"]} == {"escalate:a/k1", "escalate:a/k2", "escalate:a/k3", "escalate:a/k4"}
    assert [f["item"] for f in res["findings"]] == ["collapse:b/NO_OUTPUT"]  # an outage is kept, collapsed


def test_diagnoser_self_reports_collapse_per_lane_and_failure_class():
    rows = [_diag("lane1", f"k{i}", "model_refused:provider_outage") for i in range(40)]
    rows += [_diag("lane1", f"u{i}", "suggest_only", event_type="UNGOVERNED") for i in range(7)]
    rows += [_diag("lane2", f"v{i}", "suggest_only") for i in range(3)]
    res = FP.apply_fanin_policy(rows, _policy())
    got = {f["item"]: f for f in res["findings"]}
    assert set(got) == {"collapse:lane1/NO_OUTPUT", "collapse:lane1/UNGOVERNED", "collapse:lane2/NO_OUTPUT"}
    assert got["collapse:lane1/NO_OUTPUT"]["count"] == 40 and got["collapse:lane1/NO_OUTPUT"]["severity"] == "P2"
    assert res["before"]["open"] == 50 and res["after"]["open"] == 3


def test_low_confidence_p1_is_demoted_but_a_failed_remediation_p1_is_not():
    low = [_diag("l", f"k{i}", "low_confidence", "P1") for i in range(3)]
    mixed = [
        _diag("m", "a", "low_confidence", "P1", "RUN_FAILED"),
        _diag("m", "b", "remediation_stuck", "P1", "RUN_FAILED"),
    ]
    res = FP.apply_fanin_policy(low + mixed, _policy())
    got = {f["item"]: f["severity"] for f in res["findings"]}
    assert got == {"collapse:l/NO_OUTPUT": "P2", "collapse:m/RUN_FAILED": "P1"}


def test_auto_resolve_needs_a_later_success_in_the_same_mode():
    dead = {
        "source": "dlq",
        "item": "dlq:d:signal-fusion-active:dry_run:20261009T1500",
        "severity": "P2",
        "detail": "",
        "detected_at": T0.isoformat(),
        "lane": "signal-fusion-active",
        "mode": "dry_run",
    }
    brk = {
        "source": "dlq",
        "item": "breaker:signal-fusion-active",
        "severity": "P2",
        "detail": "",
        "detected_at": T0.isoformat(),
    }
    later, earlier = (T0 + timedelta(minutes=30)).isoformat(), (T0 - timedelta(minutes=30)).isoformat()
    p = _policy()
    live_only = FP.successes_from_rows([{"lane_id": "signal-fusion-active", "mode": "live", "finished_at": later}])
    assert dead in FP.apply_fanin_policy([dead], p, successes=live_only)["findings"]
    before = FP.successes_from_rows([{"lane_id": "signal-fusion-active", "mode": "dry_run", "finished_at": earlier}])
    assert dead in FP.apply_fanin_policy([dead], p, successes=before)["findings"]
    ok = FP.successes_from_rows([{"lane_id": "signal-fusion-active", "mode": "dry_run", "finished_at": later}])
    res = FP.apply_fanin_policy([dead, brk], p, successes=ok)
    assert res["findings"] == [brk]  # an open breaker is never auto-resolved
    assert res["auto_resolved"][0]["rule"].startswith("lane_succeeded:signal-fusion-active:dry_run@")


def test_latest_successes_reads_the_ledger_read_only(tmp_path):
    db = tmp_path / "ledger.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE runs (run_id TEXT, lane_id TEXT, mode TEXT, state TEXT, exit_code INT, finished_at TEXT)")
    con.executemany(
        "INSERT INTO runs VALUES (?,?,?,?,?,?)",
        [
            ("1", "a", "dry_run", "RUN_DONE", 0, "2026-10-09T19:00:00+00:00"),
            ("2", "a", "dry_run", "RUN_FAILED", 1, "2026-10-09T21:00:00+00:00"),
            ("3", "a", "live", "RUN_DONE", 0, "2026-10-09T20:30:00+00:00"),
        ],
    )
    con.commit()
    con.close()
    got = FP.latest_successes(db)
    assert got[("a", "dry_run")] == "2026-10-09T19:00:00+00:00" and got[("a", "*")] == "2026-10-09T20:30:00+00:00"
    assert FP.latest_successes(tmp_path / "absent.sqlite") == {}


def test_fanin_report_only_publishes_the_original_findings(monkeypatch, tmp_path):
    rows = _flood(40) + SPCX_CASES
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(tmp_path / "no_ledger.sqlite"))
    monkeypatch.delenv(FP.ENV_MODE, raising=False)
    monkeypatch.setattr(F, "collect", lambda root, now, prev=None: [dict(r) for r in rows])
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert F.main(["--dry-run"]) == 0
    out = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert out["open"] == len(rows)  # unchanged
    assert out["flood_policy"]["mode"] == "report_only"
    assert out["flood_policy"]["after"] < out["flood_policy"]["before"]


def test_fanin_enforce_publishes_the_reduced_list_and_keeps_spcx(monkeypatch, tmp_path):
    rows = _flood(40) + SPCX_CASES
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(tmp_path / "no_ledger.sqlite"))
    monkeypatch.setenv(FP.ENV_MODE, "enforce")
    monkeypatch.setattr(F, "collect", lambda root, now, prev=None: [dict(r) for r in rows])
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert F.main(["--dry-run"]) == 0
    out = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert out["open"] == out["flood_policy"]["after"] < len(rows)
    flood = F._flood_policy(tmp_path, [dict(r) for r in rows])
    kept = flood["_findings"]
    for c in SPCX_CASES:
        assert c in kept


def test_a_broken_policy_never_stops_the_fanin(monkeypatch, tmp_path):
    monkeypatch.setattr(FP, "apply_fanin_policy", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = F._flood_policy(tmp_path, [{"source": "x", "item": "y", "severity": "P2"}])
    assert out["applied"] is False and out["mode"] == "error"


# ------------------------------------------------------------------------------------------------ notifier side


def _row(source: str, item: str, sev: str, detail: str = "d") -> dict:
    return {
        "source": source,
        "item": item,
        "severity": sev,
        "detail": detail,
        "detected_at": T0.isoformat(),
        "idempotency_key": "inc-x",
        "event_id": f"evt-{source}-{item}",
        "state": "ARTIFACT_WRITTEN",
    }


def _fanin(root: Path, rows: list[dict]) -> None:
    p = root / N.FANIN_RECEIPT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    by: dict[str, int] = {}
    for r in rows:
        by[r["severity"]] = by.get(r["severity"], 0) + 1
    p.write_text(
        json.dumps(
            {
                "schema": "N8nIncidentFanin@v1",
                "mode": "apply",
                "as_of": T0.isoformat(),
                "open": len(rows),
                "by_severity": by,
                "incidents": rows,
            }
        ),
        encoding="utf-8",
    )


def _write_state(root: Path, *, sends: int = 0, triggers: dict | None = None) -> None:
    p = root / N.STATE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "schema": N.STATE_SCHEMA,
                "notified": {},
                "sends_by_day": {"2026-10-09": sends},
                "source_triggers_by_day": {"2026-10-09": triggers or {}},
            }
        ),
        encoding="utf-8",
    )


class Capture:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, text, **kw):
        self.calls.append({"text": text, **kw})
        return {"ok": True, "message_id": len(self.calls)}


def _run(root: Path, *, sender, env, now: datetime = T0):
    return N.run(
        live=True, root=root, now=now, env=env, sender=sender, previewer=None, ledger_path=root / "no_ledger.sqlite"
    )


def test_report_only_notifier_behaves_exactly_as_before_but_reports_the_budget(tmp_path):
    rows = [_row("breach_detector", "a:NO_OUTPUT", "P2"), _row("expected_services", "MISSING:x", "P1")]
    _fanin(tmp_path, rows)
    rec = _run(tmp_path, sender=Capture(), env={**ENV, "TRADEAI_INCIDENT_NOTIFIER_DAILY_CAP": "1"})
    # today's rule: the P1 spent the only slot, so the P2 batch is capped
    assert [(m["kind"], m["status"]) for m in rec["messages"]] == [("p1", "SENT"), ("p2_batch", "CAPPED")]
    assert rec["flood_policy"]["mode"] == "report_only"
    assert rec["flood_policy"]["source_budget"]["triggering"] == 1
    assert rec["flood_policy"]["cap_basis"] == "all_messages"


def test_enforce_p1_does_not_spend_the_p2_cap(tmp_path):
    rows = [_row("breach_detector", "a:NO_OUTPUT", "P2"), _row("expected_services", "MISSING:x", "P1")]
    _fanin(tmp_path, rows)
    rec = _run(tmp_path, sender=Capture(), env={**ENFORCE, "TRADEAI_INCIDENT_NOTIFIER_DAILY_CAP": "1"})
    assert [(m["kind"], m["status"]) for m in rec["messages"]] == [("p1", "SENT"), ("p2_batch", "SENT")]
    assert rec["cap"]["used"] == 1 and rec["flood_policy"]["p1_used"] == 1
    st = json.loads((tmp_path / N.STATE_REL).read_text())
    assert st["p1_sends_by_day"]["2026-10-09"] == 1 and st["sends_by_day"]["2026-10-09"] == 1
    assert st["source_triggers_by_day"]["2026-10-09"] == {"breach_detector": 1}


def test_enforce_p1_is_never_capped_or_budgeted(tmp_path):
    rows = [_row("expected_services", "MISSING:x", "P1"), _row("n8n_failure_diagnosis", "collapse:l/X", "P1")]
    _fanin(tmp_path, rows)
    _write_state(tmp_path, sends=10_000, triggers={"expected_services": 10_000, "n8n_failure_diagnosis": 10_000})
    cap = Capture()
    rec = _run(tmp_path, sender=cap, env=ENFORCE)
    assert [(m["kind"], m["status"]) for m in rec["messages"]] == [("p1", "SENT")]
    assert "MISSING:x" in cap.calls[0]["text"] and "collapse:l/X" in cap.calls[0]["text"]


def test_enforce_noisy_source_over_budget_cannot_trigger_a_batch(tmp_path):
    rows = [_row("n8n_failure_diagnosis", f"collapse:l{i}/NO_OUTPUT", "P2") for i in range(30)]
    _fanin(tmp_path, rows)
    _write_state(tmp_path, triggers={"n8n_failure_diagnosis": 2})  # its budget (config) is 2
    cap = Capture()
    rec = _run(tmp_path, sender=cap, env=ENFORCE)
    assert rec["messages"] == [] and cap.calls == []
    assert rec["p2_batch"]["held"] == "source_budget"
    assert rec["p2_batch"]["source_budget"]["exhausted"] == ["n8n_failure_diagnosis"]
    # nothing was marked notified: the incidents wait for a batch another source triggers, or tomorrow
    assert json.loads((tmp_path / N.STATE_REL).read_text())["notified"] == {}


def test_enforce_over_budget_lines_ride_along_and_protected_lines_lead(tmp_path):
    rows = [_row("n8n_failure_diagnosis", f"collapse:l{i:02d}/NO_OUTPUT", "P2") for i in range(30)]
    rows += [
        _row("breach_detector", "maturity-remeasure:NO_OUTPUT", "P2"),
        _row("breach_detector", "schwab-stop-sync:NO_OUTPUT", "P2"),
    ]
    _fanin(tmp_path, rows)
    _write_state(tmp_path, triggers={"n8n_failure_diagnosis": 2})
    cap = Capture()
    rec = _run(tmp_path, sender=cap, env=ENFORCE)
    batch = [m for m in rec["messages"] if m["kind"] == "p2_batch"][0]
    assert batch["status"] == "SENT"
    lines = cap.calls[0]["text"].splitlines()
    assert "schwab-stop-sync:NO_OUTPUT" in lines[1]  # protected first
    assert sum("n8n_failure_diagnosis" in ln for ln in lines) <= 15  # round-robin: one source cannot fill it
    assert any("maturity-remeasure" in ln for ln in lines[:6])
    st = json.loads((tmp_path / N.STATE_REL).read_text())
    assert st["source_triggers_by_day"]["2026-10-09"] == {"n8n_failure_diagnosis": 2, "breach_detector": 1}
    assert len(st["notified"]) == 32  # riding lines were delivered and are recorded


def test_enforce_protected_p2_triggers_even_when_its_source_is_over_budget(tmp_path):
    rows = [_row("breach_detector", "schwab-positions-sync:NO_OUTPUT", "P2")]
    _fanin(tmp_path, rows)
    _write_state(tmp_path, triggers={"breach_detector": 999})
    rec = _run(tmp_path, sender=Capture(), env=ENFORCE)
    assert [(m["kind"], m["status"]) for m in rec["messages"]] == [("p2_batch", "SENT")]


def test_enforce_recovery_does_not_spend_the_p2_cap(tmp_path):
    _fanin(tmp_path, [_row("breach_detector", "a:NO_OUTPUT", "P2")])
    cap = Capture()
    _run(tmp_path, sender=cap, env={**ENFORCE, "TRADEAI_INCIDENT_NOTIFIER_DAILY_CAP": "1"})
    _fanin(tmp_path, [_row("breach_detector", "b:NO_OUTPUT", "P2")])  # a cleared, b new
    later = T0 + timedelta(minutes=35)
    p = tmp_path / N.FANIN_RECEIPT_REL
    doc = json.loads(p.read_text())
    doc["as_of"] = later.isoformat()
    p.write_text(json.dumps(doc))
    rec = _run(tmp_path, sender=cap, env={**ENFORCE, "TRADEAI_INCIDENT_NOTIFIER_DAILY_CAP": "1"}, now=later)
    kinds = [(m["kind"], m["status"]) for m in rec["messages"]]
    assert ("recovery", "SENT") in kinds and ("p2_batch", "CAPPED") in kinds  # the cap binds P2 only


def test_order_lines_is_protected_first_then_round_robin():
    p = _policy()
    incs = [{"source": "a", "item": f"a{i}", "severity": "P2"} for i in range(10)]
    incs += [
        {"source": "b", "item": "b0", "severity": "P2"},
        {"source": "c", "item": "stop-watch:NO_OUTPUT", "severity": "P2"},
    ]
    out = [i["item"] for i in FP.order_lines(incs, p)]
    assert out[0] == "stop-watch:NO_OUTPUT"
    assert out.index("b0") < out.index("a5")
    assert sorted(out) == sorted(i["item"] for i in incs)  # nothing dropped


# ------------------------------------------------------------------------------------------------ replay tool


def test_replay_runs_read_only_on_a_tmp_root(tmp_path):
    from scripts import replay_incident_flood as RP

    rt = tmp_path / "data" / "runtime"
    rt.mkdir(parents=True)
    end = T0
    esc = [
        {
            "key": f"s{i}",
            "lane": "hb",
            "event_type": "NO_OUTPUT",
            "priority": "P2",
            "reason": "deferred_offpeak",
            "detail": "deferred_offpeak",
            "at": (end - timedelta(hours=10, minutes=i)).isoformat(),
        }
        for i in range(60)
    ]
    (rt / "n8n_failure_diagnosis_last.json").write_text(json.dumps({"as_of": end.isoformat(), "escalations": esc}))
    (rt / "n8n_incident_fanin_last.json").write_text(
        json.dumps(
            {
                "as_of": end.isoformat(),
                "incidents": [
                    {
                        "source": "expected_services",
                        "item": "INACTIVE:x",
                        "severity": "P1",
                        "detail": "",
                        "detected_at": None,
                    }
                ],
            }
        )
    )
    (rt / "supervisor_breaches.jsonl").write_text(
        json.dumps(
            {
                "state": "OPEN",
                "lane_id": "lane-a",
                "kind": "NO_OUTPUT",
                "detected_at": (end - timedelta(hours=5)).isoformat(),
            }
        )
        + "\n"
    )
    before = sorted(p.name for p in rt.iterdir())
    r = RP.replay(tmp_path, hours=24, warmup_hours=1)
    assert sorted(p.name for p in rt.iterdir()) == before  # wrote nothing
    assert r["distinct_incidents"]["before"] == 62 and r["distinct_incidents"]["after"] == 2
    assert r["protected_p1_at_end"] == {"n": 1, "all_kept": True}
