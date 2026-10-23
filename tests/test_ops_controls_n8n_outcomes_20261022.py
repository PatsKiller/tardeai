"""Ops -> Controls n8n lanes tab outcomes (ANCHOR OPS_CONTROLS_N8N_OUTCOMES_20261022).

Operator 2026-10-22: "I don't know if the last one was success or failure. This is not a real dashboard... When is
everything going live?" scripts/lib/ops_controls_n8n_outcomes.py joins the n8n coordination ledger (read-only, bounded
per-lane queries), the registry schedule and the documented promotion ladder.

Hermetic: a fixture sqlite ledger with the production schema subset and indexes, a tmp code root, a fake crontab.
Proves: outcome aggregation (counts by mode, failures 24h/7d, last / last success / last live success, pre-callback
history through the run-key prefixes); health verdicts OK / FAILING (last run, dead letter, breaker) / STALE /
NEVER_RAN / OFF; readiness READY_FOR_CANARY / READY_FOR_CUTOVER / NOT_READY / BLOCKED / CUT_OVER against
N8N_ONBOARDING_STANDARD.md and AGENTS.md §23.21; the summary strip; the ledger is opened read-only; no query does a
full-table scan of runs / run_outcomes / dead_letters; the 60 s cache; an unreadable ledger is UNAVAILABLE.
"""

from __future__ import annotations

import json
import sqlite3
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib import ops_controls_core as C
from scripts.lib import ops_controls_n8n_outcomes as NO

NOW = datetime(2026, 10, 22, 18, 0, tzinfo=timezone.utc)  # 14:00 ET, a Thursday
LOCK = "/tmp/tradeai_alpha.lock"

SCHEMA = """
CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT NOT NULL, mode TEXT NOT NULL, state TEXT NOT NULL,
  requested_by TEXT, caller_id TEXT, requested_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, exit_code INTEGER,
  duration_s REAL, receipt_json TEXT, slot_key TEXT, attempt INTEGER, parent_run_id TEXT, class TEXT,
  priority INTEGER, worker_id TEXT, pid INTEGER, heartbeat_at TEXT, verdict TEXT);
CREATE INDEX runs_state_requested_at ON runs (state, requested_at);
CREATE INDEX runs_slot_key ON runs (slot_key);
CREATE INDEX runs_lane_state ON runs (lane_id, state);
CREATE TABLE run_outcomes (run_id TEXT PRIMARY KEY, lane_id TEXT NOT NULL, mode TEXT, status TEXT NOT NULL,
  run_state TEXT NOT NULL, exit_code INTEGER, receipt_path TEXT, duration_s REAL, effect_key TEXT, reason TEXT,
  attempt INTEGER, finished_at TEXT, recorded_at TEXT NOT NULL);
CREATE INDEX run_outcomes_lane ON run_outcomes (lane_id, recorded_at);
CREATE TABLE dead_letters (slot_key TEXT PRIMARY KEY, lane_id TEXT NOT NULL, mode TEXT, slot_local TEXT,
  attempts INTEGER, last_run_id TEXT, last_state TEXT, last_reason TEXT, verdict TEXT, dead_at TEXT NOT NULL,
  released_at TEXT, released_by TEXT, release_note TEXT, class TEXT, max_attempts INTEGER, policy TEXT);
CREATE INDEX dead_letters_lane ON dead_letters (lane_id, dead_at);
CREATE TABLE breakers (lane_id TEXT PRIMARY KEY, opened_at TEXT, consecutive INTEGER, released_at TEXT,
  released_by TEXT);
"""
STATUS = {"RUN_DONE": "success", "RUN_FAILED": "failed", "RUN_TIMEOUT": "failed", "RUN_SKIPPED_LOCK": "skipped_lock"}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.c = sqlite3.connect(path)
        self.c.executescript(SCHEMA)
        self.n = 0

    def run(self, lane, mode, state, at, *, reason=None, outcome=True, advanced=True, prefix="d"):
        self.n += 1
        rid = f"{prefix}:{lane}:{mode}:{at.strftime('%Y%m%dT%H%M')}{'' if prefix == 'd' else f'x{self.n}'}"
        rec = {"output_signal_mtime_before": 100.0, "output_signal_mtime_after": 200.0 if advanced else 100.0}
        self.c.execute(
            "INSERT INTO runs (run_id, lane_id, mode, state, requested_at, finished_at, exit_code,"
            " receipt_json) VALUES (?,?,?,?,?,?,?,?)",
            (rid, lane, mode, state, iso(at), iso(at), 0 if state == "RUN_DONE" else 1, json.dumps(rec)),
        )
        if outcome:
            self.c.execute(
                "INSERT INTO run_outcomes (run_id, lane_id, mode, status, run_state, exit_code, reason,"
                " finished_at, recorded_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    rid,
                    lane,
                    mode,
                    STATUS[state],
                    state,
                    0 if state == "RUN_DONE" else 1,
                    reason,
                    iso(at),
                    iso(at + timedelta(seconds=1)),
                ),
            )
        self.c.commit()
        return rid


def row(lane, *, stage="shadow", mode="dry_run", kind="cron", state="ACTIVE", cron="0 10 * * 1-5", **kw):
    r = {
        "lane_id": lane,
        "state": state,
        "scheduler": {
            "kind": kind,
            "stage": stage,
            "match": f"scripts/{lane}.py",
            "expression": cron,
            "command_text": f"cd $PROJ && flock -n /tmp/tradeai_{lane}.lock $PY scripts/{lane}.py",
        },
        "dispatch": {"mode": mode, "cron": [cron], "tz": "America/New_York", "class": "report"},
    }
    r.update(kw)
    return r


def entry(lane, *, lock=None, live=True):
    return {
        "lane_id": lane,
        "command": ["$PY", f"scripts/{lane}.py"],
        "lock": lock or f"/tmp/tradeai_{lane}.lock",
        "lock_kind": "flock",
        "dry_run_arg": ["--dry-run"],
        "live_arg": [] if live else None,
        "output_signal": f"data/runtime/{lane}_last.json",
    }


def contract(lane, status="REVIEWED"):
    return {"id": lane, "kind": "lane", "status": status, "stage": "shadow"}


def cronline(lane, flock=True):
    lk = f"flock -n /tmp/tradeai_{lane}.lock " if flock else "bash scripts/safe_flock.sh /tmp/x.lock "
    return f"0 10 * * 1-5 cd $PROJ && {lk}$PY scripts/{lane}.py >> logs/{lane}.log 2>&1"


@pytest.fixture()
def led(tmp_path):
    return Ledger(tmp_path / "ledger.sqlite")


def facts(led, lanes):
    return NO.read_ledger(led.path, lanes, NOW)


# ── aggregation ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_aggregation_counts_last_and_failures(led):
    led.run("a", "dry_run", "RUN_DONE", NOW - timedelta(days=3))
    led.run("a", "live", "RUN_DONE", NOW - timedelta(days=2))
    led.run("a", "live", "RUN_FAILED", NOW - timedelta(hours=30), reason="exit_1")
    led.run("a", "live", "RUN_TIMEOUT", NOW - timedelta(hours=5), reason="timeout_exit_124")
    led.run("a", "live", "RUN_SKIPPED_LOCK", NOW - timedelta(hours=2))
    led.run("a", "live", "RUN_DONE", NOW - timedelta(days=9))  # outside the 7-day window
    L = facts(led, ["a"])["a"]
    assert L.runs_7d == {"dry_run": 1, "live": 4}
    assert L.outcomes_7d == {"SUCCESS": 2, "FAILED": 1, "TIMEOUT": 1, "SKIPPED": 1}
    assert (L.failures_7d, L.failures_24h) == (2, 1)
    assert L.last["outcome"] == "SKIPPED"
    assert L.last_live["outcome"] == "SKIPPED"
    assert L.last_success["at"].startswith(iso(NOW - timedelta(days=2))[:16])
    assert L.last_live_success["mode"] == "live" and L.live_output_advanced is True
    assert L.last_dry["outcome"] == "SUCCESS"


def test_history_before_the_callback_comes_from_runs_by_key_prefix(led):
    # dispatcher slot + forced fire, recorded only in `runs` (pre-2026-10-15 history)
    led.run("old", "dry_run", "RUN_DONE", NOW - timedelta(days=12), outcome=False, prefix="f")
    led.run("old", "live", "RUN_DONE", NOW - timedelta(days=1), advanced=False)
    L = facts(led, ["old"])["old"]
    assert L.last_dry and L.last_dry["source"] == "runs" and L.last_dry["outcome"] == "SUCCESS"
    assert L.live_output_advanced is False


def test_dead_letters_and_breakers(led):
    led.run("b", "live", "RUN_DONE", NOW - timedelta(hours=3))
    led.c.execute(
        "INSERT INTO dead_letters (slot_key, lane_id, dead_at, last_state, last_reason) VALUES "
        "('s1','b',?, 'RUN_FAILED','exit_1')",
        (iso(NOW - timedelta(hours=1)),),
    )
    led.c.execute(
        "INSERT INTO dead_letters (slot_key, lane_id, dead_at, released_at) VALUES ('s0','b',?,?)",
        (iso(NOW - timedelta(days=2)), iso(NOW - timedelta(days=1))),
    )
    led.c.execute("INSERT INTO breakers (lane_id, opened_at, released_at) VALUES ('c', ?, NULL)", (iso(NOW),))
    led.c.commit()
    F = facts(led, ["b", "c"])
    assert F["b"].dead_letters_open == 1 and F["b"].dead_letter_last["reason"] == "exit_1"
    assert F["c"].breaker_open is True and F["b"].breaker_open is False


# ── health verdicts ─────────────────────────────────────────────────────────────────────────────────────────────


def test_health_verdicts(led):
    led.run("ok", "live", "RUN_DONE", NOW - timedelta(hours=3))  # today's 10:00 ET slot answered (11:00 ET)
    led.run("bad", "live", "RUN_FAILED", NOW - timedelta(hours=3), reason="output_unverifiable")
    led.run("stale", "live", "RUN_DONE", NOW - timedelta(days=3))  # missed today's slot
    led.run("dl", "live", "RUN_DONE", NOW - timedelta(hours=4))
    led.c.execute(
        "INSERT INTO dead_letters (slot_key, lane_id, dead_at, last_state) VALUES ('x','dl',?, 'RUN_TIMEOUT')",
        (iso(NOW - timedelta(hours=3)),),
    )
    led.c.commit()
    F = facts(led, ["ok", "bad", "stale", "dl", "never"])
    live = dict(stage="canary", mode="live")
    h = {k: NO.health(row(k, **live), F[k], "live", NOW) for k in F}
    assert h["ok"] == ("OK", None)
    assert h["bad"][0] == "FAILING" and "output_unverifiable" in h["bad"][1]
    assert h["stale"][0] == "STALE"
    assert h["dl"][0] == "FAILING" and "dead-lettered" in h["dl"][1]
    assert h["never"][0] == "NEVER_RAN"
    assert NO.health(row("x", state="RETIRED"), None, "off", NOW)[0] == "OFF"


def test_effective_mode_follows_stage_clamp_and_live_list():
    assert NO.effective_mode(row("s"), True) == "dry_run"  # shadow clamps to dry_run
    assert NO.effective_mode(row("c", stage="canary", mode="live"), True) == "live"
    assert NO.effective_mode(row("c", stage="canary", mode="live"), False) == "dry_run"  # not on the live list
    assert NO.effective_mode(row("c", stage="canary", mode="live"), None) == "unknown"
    assert NO.effective_mode(row("o", mode="off"), True) == "off"
    assert NO.effective_mode(row("n", state="NEVER_SCHEDULED"), True) == "off"


def test_next_run_is_the_next_cron_fire_in_et():
    nxt = NO.next_fire(["0 10 * * 1-5"], "America/New_York", NOW)  # Thu 14:00 ET -> Fri 10:00 ET
    assert nxt == datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
    assert NO.cron_exprs({"scheduler": {"expression": "dispatcher", "cadence": "*/5 * * * *"}}) == (
        ["*/5 * * * *"],
        "America/New_York",
    )


# ── promotion readiness ─────────────────────────────────────────────────────────────────────────────────────────


def ready(r, *, ent=..., con=..., live=False, L=None, tab="", policy=None, blocked=None):
    lane = r["lane_id"]
    return NO.readiness(
        r,
        entry=entry(lane) if ent is ... else ent,
        contract=contract(lane) if con is ... else con,
        on_live_list=live,
        L=L,
        crontab=tab,
        policy=policy or {},
        blocked_reasons=blocked or {},
    )


def test_shadow_to_canary(led):
    led.run("s1", "dry_run", "RUN_FAILED", NOW - timedelta(days=2))
    led.run("s1", "dry_run", "RUN_DONE", NOW - timedelta(days=1))  # a clean fire after the failure
    led.run("s2", "dry_run", "RUN_FAILED", NOW - timedelta(days=1))
    led.run("s3", "dry_run", "RUN_DONE", NOW - timedelta(days=1))
    F = facts(led, ["s1", "s2", "s3", "s4"])
    tab = "\n".join([cronline("s1"), cronline("s2"), cronline("s3", flock=False), cronline("s4")])
    r1 = ready(row("s1"), L=F["s1"], tab=tab)
    assert r1["verdict"] == "READY_FOR_CANARY" and r1["target"] == "canary", r1
    assert any("flock lock" in e for e in r1["evidence"])
    r2 = ready(row("s2"), L=F["s2"], tab=tab)
    assert r2["verdict"] == "NOT_READY" and any("latest dry_run fire is FAILED" in m for m in r2["missing"])
    r3 = ready(row("s3"), L=F["s3"], tab=tab)
    assert r3["verdict"] == "NOT_READY" and any("flock" in m for m in r3["missing"])
    r4 = ready(row("s4"), L=F["s4"], tab=tab)
    assert r4["verdict"] == "NOT_READY" and any("no n8n dry_run fire" in m for m in r4["missing"])
    r5 = ready(row("s1"), ent=entry("s1", lock="/tmp/other.lock"), L=F["s1"], tab=tab)
    assert r5["verdict"] == "NOT_READY" and any("is not the cron line's lock" in m for m in r5["missing"])


def test_blocked_reasons(led):
    led.run("b", "dry_run", "RUN_DONE", NOW - timedelta(days=1))
    L, tab = facts(led, ["b"])["b"], cronline("b")
    assert "REVIEWED" in " ".join(ready(row("b"), con=contract("b", "DRAFT"), L=L, tab=tab)["blocked_by"])
    assert ready(row("b"), con=None, L=L, tab=tab)["verdict"] == "BLOCKED"
    assert ready(row("b"), ent=None, L=L, tab=tab)["verdict"] == "BLOCKED"
    assert ready(row("b", state="NEVER_SCHEDULED"), L=L, tab=tab)["verdict"] == "BLOCKED"
    held = ready(row("b"), L=L, tab=tab, policy={"holds": {"b": "operator_hold_20261016: SPCX"}})
    assert held["verdict"] == "BLOCKED" and "operator hold" in held["blocked_by"][0]
    assert ready(row("b"), L=L, tab=tab, blocked={"b": "grant token"})["verdict"] == "BLOCKED"
    broker = row("b")
    broker["scheduler"]["match"] = "scripts/brokers/place_order.py"
    assert ready(broker, L=L, tab=tab)["verdict"] == "BLOCKED"  # never-list via lane_dispatch.dispatch_eligible


def test_canary_to_cutover(led):
    for lane in ("c1", "c2", "c3", "c4"):
        led.run(lane, "dry_run", "RUN_DONE", NOW - timedelta(days=4))
    led.run("c1", "live", "RUN_DONE", NOW - timedelta(hours=8))
    led.run("c2", "live", "RUN_SKIPPED_LOCK", NOW - timedelta(hours=8))  # not a live proof (§23.12)
    led.run("c3", "live", "RUN_DONE", NOW - timedelta(hours=8), advanced=False)  # output_signal did not move
    led.run("c4", "live", "RUN_DONE", NOW - timedelta(days=2))
    led.run("c4", "live", "RUN_FAILED", NOW - timedelta(hours=8), reason="exit_1")
    F = facts(led, ["c1", "c2", "c3", "c4"])
    tab = "\n".join(cronline(x) for x in ("c1", "c2", "c3", "c4"))
    canary = dict(stage="canary", mode="live")
    r1 = ready(row("c1", **canary), L=F["c1"], live=True, tab=tab)
    assert r1["verdict"] == "READY_FOR_CUTOVER" and r1["target"] == "cutover", r1
    assert any("regression tests" in o for o in r1["owed"])  # §23.21 (3) is owed in the PR, never assumed
    assert ready(row("c1", **canary), L=F["c1"], live=False, tab=tab)["verdict"] == "NOT_READY"
    r2 = ready(row("c2", **canary), L=F["c2"], live=True, tab=tab)
    assert r2["verdict"] == "NOT_READY" and any("RUN_SKIPPED_LOCK does not count" in m for m in r2["missing"])
    r3 = ready(row("c3", **canary), L=F["c3"], live=True, tab=tab)
    assert any("did not advance its output_signal" in m for m in r3["missing"])
    r4 = ready(row("c4", **canary), L=F["c4"], live=True, tab=tab)
    assert any("latest live run FAILED" in m for m in r4["missing"])
    gone = ready(row("c1", **canary), L=F["c1"], live=True, tab="")
    assert any("§23.21 (4) needs the live run with the cron line present" in m for m in gone["missing"])
    cut = ready(row("x", stage="cutover", mode="live", kind="n8n"), L=None)
    assert cut["verdict"] == "CUT_OVER"


def test_summary_strip():
    def r(eff, h, v):
        return {"outcome": {"effective_mode": eff, "health": h}, "readiness": {"verdict": v}}

    s = NO.summarize(
        [
            r("live", "OK", "CUT_OVER"),
            r("live", "FAILING", "NOT_READY"),
            r("live", "STALE", "N_A"),
            r("dry_run", "OK", "READY_FOR_CANARY"),
            r("dry_run", "NEVER_RAN", "NOT_READY"),
            r("off", "OFF", "BLOCKED"),
            r("live", "OK", "READY_FOR_CUTOVER"),
        ]
    )
    assert s == {
        "live_healthy": 2,
        "live_failing": 2,
        "rehearsing": 2,
        "ready_to_promote": 2,
        "never_ran": 1,
        "off": 1,
        "cut_over": 1,
    }


# ── read-only, bounded, cached ──────────────────────────────────────────────────────────────────────────────────


def test_ledger_is_read_only(led):
    c = NO.connect_ro(led.path)
    with pytest.raises(sqlite3.OperationalError):
        c.execute("INSERT INTO breakers (lane_id) VALUES ('x')")
    c.close()
    with pytest.raises(FileNotFoundError):
        NO.connect_ro(led.path.parent / "absent.sqlite")


def test_no_full_table_scan(led, monkeypatch):
    for i in range(30):
        led.run("p", "live", "RUN_DONE", NOW - timedelta(hours=i))
    led.run("q", "dry_run", "RUN_DONE", NOW - timedelta(days=20), outcome=False)
    seen: list[tuple[str, tuple]] = []
    real = NO.connect_ro

    def spy(path):
        c = real(path)
        return types.SimpleNamespace(
            execute=lambda q, a=(): (seen.append((q, tuple(a))), c.execute(q, a))[1], close=c.close
        )

    monkeypatch.setattr(NO, "connect_ro", spy)
    NO.read_ledger(led.path, ["p", "q", "r"], NOW)
    assert seen
    c = sqlite3.connect(led.path)
    for q, a in seen:
        plan = " | ".join(r[-1] for r in c.execute("EXPLAIN QUERY PLAN " + q, a))
        for t in ("runs", "run_outcomes", "dead_letters"):
            assert not any(p.strip() == f"SCAN {t}" for p in plan.split("|")), (q, plan)


def test_cache_reuses_within_ttl():
    calls = []
    t = [0.0]
    f = lambda: calls.append(1) or len(calls)  # noqa: E731
    key = ("test-cache", id(calls))
    assert NO.cached(key, f, clock=lambda: t[0]) == 1
    t[0] = 59.0
    assert NO.cached(key, f, clock=lambda: t[0]) == 1
    t[0] = 61.0
    assert NO.cached(key, f, clock=lambda: t[0]) == 2


def test_enrich_end_to_end_and_unavailable_ledger(led, tmp_path):
    led.run("s1", "dry_run", "RUN_DONE", NOW - timedelta(days=1))
    led.run("c1", "dry_run", "RUN_DONE", NOW - timedelta(days=3))
    led.run("c1", "live", "RUN_DONE", NOW - timedelta(hours=3))
    code = tmp_path / "code"
    (code / "config").mkdir(parents=True)
    (code / "config" / "n8n_run_allowlist.json").write_text(json.dumps({"lanes": [entry("s1"), entry("c1")]}))
    (code / "config" / "n8n_health_contracts.json").write_text(
        json.dumps({"contracts": [contract("s1"), contract("c1")]})
    )
    reg = {"s1": row("s1"), "c1": row("c1", stage="canary", mode="live")}
    rows = [{"lane_id": "s1", "on_live_list": False}, {"lane_id": "c1", "on_live_list": True}]
    tab = cronline("s1") + "\n" + cronline("c1")
    extra = NO.enrich(rows, reg, code_root=code, ledger_path=led.path, crontab=lambda: tab, now=NOW)
    assert extra["outcomes_state"] == "OK" and extra["crontab_read"] is True
    v = {r["lane_id"]: r for r in rows}
    assert v["s1"]["readiness"]["verdict"] == "READY_FOR_CANARY"
    assert v["c1"]["readiness"]["verdict"] == "READY_FOR_CUTOVER"
    assert (
        v["c1"]["outcome"]["last_outcome"] == "SUCCESS" and v["c1"]["outcome"]["next_run_at"] == "2026-10-23T14:00:00Z"
    )
    assert extra["summary"]["live_healthy"] == 1 and extra["summary"]["rehearsing"] == 1
    assert extra["summary"]["ready_to_promote"] == 2
    rows2 = [{"lane_id": "c1", "on_live_list": True}]

    def boom():
        raise C.OpsError("CRONTAB_UNREADABLE", "x", 503)

    extra2 = NO.enrich(rows2, reg, code_root=code, ledger_path=tmp_path / "absent.sqlite", crontab=boom, now=NOW)
    assert extra2["outcomes_state"] == "UNAVAILABLE" and extra2["crontab_read"] is False
    assert rows2[0]["outcome"]["health"] == "UNKNOWN"
    assert rows2[0]["readiness"]["verdict"] == "NOT_READY"
    assert "ledger unreadable" in rows2[0]["readiness"]["missing"][0]
