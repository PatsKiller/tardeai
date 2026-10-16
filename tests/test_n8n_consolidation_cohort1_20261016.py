"""Process consolidation cohort 1 (operator 2026-10-16).

1. Verified-result triggers: a ``run_done`` trigger with ``require_verdict`` fires the downstream lane only on an
   upstream RUN_DONE whose receipt output_verdict is listed (scripts/lib/lane_dispatch.py, scripts/lib/n8n_due.py),
   and the research news chain (hermes-news-bridge -> news-to-catalyst -> research-insight-extractor) carries it.
2. scripts/report_n8n_capacity.py: per-lane dry/live queue wait, runtime, worker-seconds, executor concurrency.
3. scripts/lib/n8n_shadow_policy.py: accepted lanes get no continuous dry run; a regression canary is due only when
   the lane's config or entry script changed; shadow-cadence proposals are report-only.

Hermetic: tmp ledger, frozen clocks, injected readers. No socket, no live ledger, no DB, no send.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import report_n8n_capacity as CAP  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import n8n_due as D  # noqa: E402
from scripts.lib import n8n_retry_policy as RP  # noqa: E402
from scripts.lib import n8n_shadow_policy as SP  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")
NOW = datetime(2026, 10, 14, 14, 10, tzinfo=timezone.utc)  # Wed 10:10 ET
REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / "state"
    (root / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    return root


@pytest.fixture
def store(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield LedgerRunStore(ledger)
    ledger.close()


def _row(lane, triggers):
    d = {"mode": "dry_run", "cron": ["0 9 * * *"], "class": "monitor", "priority": 5, "retry_policy": "none",
         "wave": "W3", "triggers": triggers}
    return {"lane_id": lane, "scheduler": {"kind": "cron", "expression": "0 9 * * *", "stage": "shadow"},
            "dispatch": d}


def _allow(*lanes):
    return {lane: {"lane_id": lane, "command": ["/bin/true"], "dry_run_arg": ["--dry-run"], "live_arg": None,
                   "lock": f"/nonexistent/{lane}.lock", "lock_kind": "flock", "timeout_s": 30, "market_gate": False,
                   "env_names": ["PATH"], "output_signal": f"data/runtime/{lane}_last.json"} for lane in lanes}


def _done(store, run_id, lane, mode, verdict, finished):
    store.request(run_id=run_id, lane_id=lane, mode=mode, requested_by="t", caller_id="t",
                  now=(finished - timedelta(minutes=2)).timestamp())
    receipt = {"run_id": run_id, "state": "RUN_DONE"}
    if verdict is not None:
        receipt["output_verdict"] = {"verdict": verdict}
    store._l._conn.execute(
        "UPDATE runs SET state = 'RUN_DONE', started_at = ?, finished_at = ?, receipt_json = ? WHERE run_id = ?",
        ((finished - timedelta(seconds=5)).isoformat(), finished.isoformat(), json.dumps(receipt), run_id))
    store._l._conn.commit()


def _keys(rows, allow, store):
    return [i["idempotency_key"] for i in D.compute_due(rows, allow, POLICIES, store, NOW, source="event")["items"]]


VERIFIED = [{"source": "run_done", "lane_id": "up-lane", "require_verdict": ["produced"]}]


# ── 1. verified-result triggers ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("verdict", ["empty_allowed", "declared_not_enforced", "no_rule", "dry_run_exempt", None])
def test_unverified_upstream_result_fires_nothing(state, store, verdict):
    rows = [_row("up-lane", []), _row("down-lane", VERIFIED)]
    _done(store, "d:up-lane:live:20261014T1000", "up-lane", "live", verdict, NOW - timedelta(minutes=6))
    assert _keys(rows, _allow("up-lane", "down-lane"), store) == []


def test_produced_upstream_result_fires_the_downstream(state, store):
    rows = [_row("up-lane", []), _row("down-lane", VERIFIED)]
    _done(store, "d:up-lane:live:20261014T1000", "up-lane", "live", "produced", NOW - timedelta(minutes=6))
    assert _keys(rows, _allow("up-lane", "down-lane"), store) == ["e:down-lane:dry_run:20261014T1004"]


def test_newest_verified_run_sets_the_as_of_not_a_newer_empty_one(state, store):
    rows = [_row("up-lane", []), _row("down-lane", VERIFIED)]
    _done(store, "d:up-lane:live:20261014T0950", "up-lane", "live", "produced", NOW - timedelta(minutes=12))
    _done(store, "d:up-lane:live:20261014T1000", "up-lane", "live", "empty_allowed", NOW - timedelta(minutes=6))
    assert _keys(rows, _allow("up-lane", "down-lane"), store) == ["e:down-lane:dry_run:20261014T0958"]


def test_plain_run_done_trigger_unchanged(state, store):
    rows = [_row("up-lane", []), _row("down-lane", [{"source": "run_done", "lane_id": "up-lane"}])]
    _done(store, "d:up-lane:live:20261014T1000", "up-lane", "live", "empty_allowed", NOW - timedelta(minutes=6))
    assert _keys(rows, _allow("up-lane", "down-lane"), store) == ["e:down-lane:dry_run:20261014T1004"]


def test_run_output_verdict_reads_receipt_or_flat_row():
    assert D.run_output_verdict({"receipt": {"output_verdict": {"verdict": "produced"}}}) == "produced"
    assert D.run_output_verdict({"output_verdict": {"verdict": "empty_allowed"}}) == "empty_allowed"
    assert D.run_output_verdict({"receipt": None}) is None


@pytest.mark.parametrize("trig", [
    {"source": "broker_as_of", "domain": "catalyst_news", "require_verdict": ["produced"]},
    {"source": "run_done", "lane_id": "x", "require_verdict": []},
    {"source": "run_done", "lane_id": "x", "require_verdict": ["no_rule"]},
    {"source": "run_done", "lane_id": "x", "require_verdict": ["dry_run_exempt"]},
    {"source": "run_done", "lane_id": "x", "require_verdict": ["produced", "produced"]},
    {"source": "run_done", "lane_id": "x", "require_verdict": "produced"},
])
def test_require_verdict_is_closed(trig):
    with pytest.raises(LD.DispatchBlockError):
        LD.parse_dispatch_block(_row("down-lane", [trig]))


def test_require_verdict_parses_and_schema_matches():
    block = LD.parse_dispatch_block(_row("down-lane", VERIFIED))
    assert block.triggers[0].require_verdict == ("produced",)
    schema = json.loads((ROOT / "docs/implementation/n8n-maturity/schemas/registry-dispatch-block.schema.json")
                        .read_text(encoding="utf-8"))
    item = schema["properties"]["dispatch"]["properties"]["triggers"]["items"]
    assert set(item["properties"]) == set(LD._TRIGGER_KEYS)
    assert tuple(item["properties"]["require_verdict"]["items"]["enum"]) == LD.TRIGGER_VERIFIED_VERDICTS


def test_research_news_chain_triggers_on_verified_results():
    by_id = {r["lane_id"]: r for r in REGISTRY["lanes"]}
    n2c = LD.parse_dispatch_block(by_id["news-to-catalyst"])
    rie = LD.parse_dispatch_block(by_id["research-insight-extractor"])
    up = {t.lane_id: t.require_verdict for t in n2c.triggers if t.source == "run_done"}
    assert up == {"hermes-news-bridge": ("produced",)}
    assert [(t.lane_id, t.require_verdict) for t in rie.triggers] == [("news-to-catalyst", ("produced",))]
    # shadow first: the dry lane's event fires; the live lane's triggers stay inert until an operator event canary.
    assert n2c.mode == "dry_run" and rie.mode == "live" and D.EVENT_MODES == ("dry_run",)
    # the clock slots stay as the backstop sweep (no cron change in this PR)
    assert n2c.cron == ("45 6,12,18 * * *",) and rie.cron == ("50 6,12,18 * * *",)


# ── 2. capacity report ──────────────────────────────────────────────────────────────────────────────────────────


def _rec(lane, mode, start_s, dur, wait, worker, run_id=None, state="RUN_DONE"):
    t0 = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc) + timedelta(seconds=start_s)
    return {"lane_id": lane, "mode": mode, "state": state, "started_at": t0.isoformat(),
            "finished_at": (t0 + timedelta(seconds=dur)).isoformat(), "duration_s": dur, "queue_wait_s": wait,
            "worker_id": f"host:1:{worker}", "run_id": run_id or f"d:{lane}:{mode}:20261014T0800"}


def test_capacity_summary_separates_dry_and_live_and_measures_concurrency():
    recs = [CAP.normalize(r) for r in (
        _rec("a", "dry_run", 0, 10, 1.0, "w0"), _rec("a", "dry_run", 100, 20, 3.0, "w0"),
        _rec("a", "live", 5, 10, 40.0, "w1", run_id="e:a:live:20261014T0800"),
        _rec("b", "live", 8, 4, 0.5, "w1"),
    )]
    now = datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc)
    out = CAP.summarize(recs, now, 1.0, {"a": ("live", "cutover")}, queue_alarm_s=30)
    a = next(r for r in out["lanes"] if r["lane_id"] == "a")
    assert a["dry_run"]["runs"] == 2 and a["dry_run"]["worker_s"] == 30.0
    assert a["dry_run"]["duration_s"] == {"p50": 10.0, "p95": 20.0, "max": 20.0}
    assert a["live"]["queue_wait_over_alarm"] == 1 and a["live"]["triggers"] == {"event": 1}
    assert a["stage"] == "cutover"
    ex = out["executor"]
    assert ex["peak_concurrency"] == 3 and ex["observed_worker_slots"] == 2 and ex["saturated_s"] == 7.0
    assert out["totals"]["live"]["runs"] == 2 and out["totals"]["dry_run"]["runs"] == 2


def test_capacity_window_excludes_old_runs_and_skips_malformed():
    assert CAP.normalize({"lane_id": "a", "mode": "weird", "started_at": "2026-10-14T12:00:00Z"}) is None
    old = CAP.normalize(_rec("a", "live", -86400 * 9, 1, 0.1, "w0"))
    out = CAP.summarize([old], datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc), 7.0)
    assert out["runs"] == 0 and out["lanes"] == []


# ── 3. shadow policy ────────────────────────────────────────────────────────────────────────────────────────────


def test_repo_policy_is_report_only_and_valid():
    pol = SP.load_policy()
    assert pol["mode"] == "report"
    with pytest.raises(SP.ShadowPolicyError):
        SP.validate_policy({**pol, "mode": "enforce"})
    names = set(k for k in pol["shadow_cadence_proposals"] if not k.startswith("_"))
    assert names == {"momentum-cache-reconcile", "momentum-lifecycle-monitor", "hermes-score-event-feeder",
                     "scalp-hot-list", "finviz-enrichment-scalp-hot"}


def test_cadence_proposals_match_the_registry_and_never_raise_cadence():
    pol = SP.load_policy()
    by_id = {r["lane_id"]: r for r in REGISTRY["lanes"]}
    for row in SP.cadence_savings(pol)["lanes"]:
        reg = by_id[row["lane_id"]]
        # proposals only: the registry keeps the current cron and stays shadow / dry_run (operator §17 call)
        assert reg["dispatch"]["cron"] == row["current_cron"] and reg["dispatch"]["mode"] == "dry_run"
        assert reg["scheduler"]["stage"] == "shadow"
        assert 0 < row["fires_per_week"]["proposed"] < row["fires_per_week"]["current"]


def test_fires_per_week_counts():
    assert SP.fires_per_week(["*/5 * * * *"]) == 2016
    assert SP.fires_per_week(["*/15 6-16 * * 1-5"]) == 220
    assert SP.fires_per_week(["7 * * * *"]) == 168


def _live(lane, sha, verdict="produced", fin="2026-10-15T10:00:00+00:00"):
    return {"lane_id": lane, "mode": "live", "state": "RUN_DONE", "code_sha": sha, "finished_at": fin,
            "run_id": f"d:{lane}:live:20261015T0600", "output_verdict": {"verdict": verdict}}


def test_last_verified_live_skips_failing_verdicts_and_dry_runs():
    recs = [_live("a", "s1", fin="2026-10-15T10:00:00+00:00"),
            _live("a", "s2", verdict="empty_violation", fin="2026-10-15T11:00:00+00:00"),
            {**_live("a", "s3", fin="2026-10-15T12:00:00+00:00"), "mode": "dry_run"}]
    assert SP.last_verified_live(recs)["a"]["code_sha"] == "s1"


def test_canary_due_only_on_relevant_change():
    pol = SP.load_policy()
    last = {"same": _live("same", "A" * 40), "cfg": _live("cfg", "A" * 40), "code": _live("code", "A" * 40),
            "quiet": _live("quiet", "A" * 40), "unk": _live("unk", "A" * 40)}
    cur = "B" * 40
    digests = {("cfg", cur): "new"}

    def cdig(sha, lane):
        if lane == "unk":
            return None
        return digests.get((lane, sha), "old")

    plan = SP.plan_regression_canaries(
        sorted(last), {**last, "same": _live("same", cur)}, cur, pol, config_digest=cdig,
        entry_changed=lambda a, b, lane: lane == "code")
    by = {i["lane_id"]: i for i in plan["items"]}
    assert by["same"]["due"] is False and by["same"]["reasons"] == []           # no release change
    assert by["cfg"]["reasons"] == ["lane_config_changed"]
    assert by["code"]["reasons"] == ["entry_script_changed"]
    assert by["quiet"]["due"] is False                                          # new release, nothing relevant
    assert by["unk"]["due"] is False and by["unk"]["unknown"] == ["lane_config"]
    assert plan["continuous_dry_runs_planned"] == 0 and plan["due_lanes"] == ["cfg", "code"]


def test_accepted_lanes_need_live_dispatch_stage_and_a_live_run():
    reg = {"lanes": [
        {"lane_id": "a", "scheduler": {"stage": "cutover"}, "dispatch": {"mode": "live"}},
        {"lane_id": "b", "scheduler": {"stage": "shadow"}, "dispatch": {"mode": "dry_run"}},
        {"lane_id": "c", "scheduler": {"stage": "canary"}, "dispatch": {"mode": "live"}},
    ]}
    assert SP.accepted_lanes(reg, {"a": {}, "b": {}}, SP.load_policy()) == ["a"]


def test_entry_script_and_lane_config():
    entry = {"lane_id": "x", "command": ["$PY", "scripts/foo.py", "--x"]}
    assert SP.entry_script(entry) == "scripts/foo.py" and SP.entry_script(None) is None
    cfg = SP.lane_config({"lanes": [{"lane_id": "x"}]}, {"lanes": [entry]}, {"contracts": [{"id": "x"}]}, "x")
    assert cfg["registry_row"] == {"lane_id": "x"} and cfg["allowlist_entry"] is entry
    assert cfg["health_contract"] == {"id": "x"}
