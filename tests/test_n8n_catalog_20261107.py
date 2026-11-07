"""LQ-20261107-150: GET /api/v2/ops/n8n-catalog — jobs + categories + relay live list + audit verdicts, joined."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import n8n_catalog as N  # noqa: E402
from scripts.lib import n8n_catalog_ops as OPS  # noqa: E402


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """Hermetic: no test reaches the real llm_consumption_log; an unreachable DB reads as None."""
    monkeypatch.setattr(OPS, "default_llm_query", lambda sql, params=None: None)

CATS = [{"key": "research", "label": "Research & intel", "blurb": "News and filings."},
        {"key": "ops", "label": "Ops, health & self-heal", "blurb": "Watchdogs."}]


def _row(lane, scheduler, *, cat="research", mode=None, state="ACTIVE", expr=("0 7 * * 1-5",)):
    return {"lane_id": lane, "title": lane.title(), "job": lane, "does": f"does {lane}", "category_key": cat,
            "scheduler": scheduler, "state": state, "status": "ok", "last_run": {"mode": mode} if mode else None,
            "cadence": {"expressions": list(expr), "timezone": "America/New_York"}}


ROWS = [
    _row("n8n-relay", "n8n"),                         # n8n + in relay -> live
    _row("n8n-ran-live", "n8n", mode="live"),          # n8n, not in relay, last run live -> live
    _row("n8n-dry", "n8n", mode="dry_run"),            # n8n, not in relay -> dry
    _row("cron-relay", "cron", cat="ops"),             # cron + in relay -> both
    _row("cron-only", "cron", cat="ops"),              # cron, not in relay -> none
    _row("systemd-relay", "systemd", cat="ops"),       # systemd is never n8n, even if listed -> none
    _row("retired-cron", "cron", state="RETIRED"),     # retired and not on n8n: not counted
    _row("fallback-cat", "n8n", cat="mystery"),        # unknown category still shows
]
RELAY = frozenset({"n8n-relay", "cron-relay", "systemd-relay", "fallback-cat"})
SNAP = {"rows": ROWS, "categories": CATS, "computed_at": "2026-11-07T16:00:00+00:00"}


def _verdicts(tmp_path: Path, rows) -> Path:
    p = tmp_path / N.VERDICTS_REL
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"schema": N.VERDICTS_SCHEMA, "written_at": "2026-11-07T16:15:00+00:00", "by": "test",
                             "rows": rows}), encoding="utf-8")
    return p


def _compute(tmp_path, relay=RELAY):
    import scripts.lib.n8n_catalog as mod

    orig = mod.read_relay
    mod.read_relay = lambda root, env: (relay, {"source": "test", "lanes": len(relay or ()), "paused": ["n8n-relay"],
                                                "note": None})
    try:
        return N.compute(environ={}, state=tmp_path, snapshot_fn=lambda: SNAP)
    finally:
        mod.read_relay = orig


# ── mode derivation ────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lane,expected", [
    ("n8n-relay", "live"), ("n8n-ran-live", "live"), ("n8n-dry", "dry"), ("cron-relay", "both"),
    ("cron-only", "none"), ("systemd-relay", "none"), ("fallback-cat", "live"),
])
def test_mode_derivation(lane, expected):
    row = next(r for r in ROWS if r["lane_id"] == lane)
    assert N.derive_mode(row, RELAY) == expected


def test_unreadable_relay_list_counts_no_lane_as_listed():
    assert N.derive_mode(_row("x", "cron"), None) == "none"
    assert N.derive_mode(_row("x", "n8n"), None) == "dry"
    assert N.derive_mode(_row("x", "n8n", mode="live"), None) == "live"


# ── missing / bad verdicts file ────────────────────────────────────────────────────────────────────────────────

def test_missing_verdicts_file_is_empty_rows_with_a_note(tmp_path):
    out = _compute(tmp_path)
    assert out["audit"]["state"] == "missing" and out["audit"]["rows"] == 0
    assert any("not audited" in n for n in out["notes"])
    assert out["stats"]["audit"] == {"pass": 0, "fail": 0, "not_provable": 0, "audited": 0}
    assert all(x["verdict"] is None and x["verdict_class"] == "not_audited" for x in out["lanes"].values())


@pytest.mark.parametrize("body", ["{not json", json.dumps({"schema": "other", "rows": []}), json.dumps([1, 2])])
def test_unreadable_or_wrong_schema_is_a_note_not_an_error(tmp_path, body):
    p = tmp_path / N.VERDICTS_REL
    p.parent.mkdir(parents=True)
    p.write_text(body, encoding="utf-8")
    out = _compute(tmp_path)
    assert out["audit"]["state"] in {"unreadable", "malformed"} and out["notes"]
    assert out["stats"]["audit"]["audited"] == 0


def test_snapshot_failure_is_empty_rows_not_a_raise(tmp_path):
    def boom():
        raise RuntimeError("ledger gone")
    out = N.compute(environ={}, state=tmp_path, snapshot_fn=boom)
    assert out["lanes"] == {} and out["categories"] == [] and out["notes"]


# ── the join ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_join_puts_verdict_defect_and_work_item_on_the_lane(tmp_path):
    _verdicts(tmp_path, [
        {"lane_id": "n8n-relay", "verdict": "PASS", "defect": "", "work_item": "", "audited_at": "t"},
        {"lane_id": "n8n-dry", "verdict": "FAIL_DATA", "defect": "stale values", "work_item": "LQ-20261107-160",
         "fix_suggestion": "re-key", "audited_at": "t"},
        {"lane_id": "cron-relay", "verdict": "UNVERIFIABLE", "defect": "no live run", "audited_at": "t"},
        {"lane_id": "ghost-lane", "verdict": "FAIL_RUN", "defect": "x"},
        {"lane_id": "", "verdict": "PASS"},             # malformed rows are skipped
    ])
    out = _compute(tmp_path)
    lanes = out["lanes"]
    assert lanes["n8n-relay"]["verdict"] == "PASS" and lanes["n8n-relay"]["verdict_class"] == "pass"
    assert lanes["n8n-relay"]["defect"] is None and lanes["n8n-relay"]["paused_on_n8n"] is True
    d = lanes["n8n-dry"]
    assert (d["verdict"], d["verdict_class"], d["defect"], d["work_item"], d["fix_suggestion"]) == \
        ("FAIL_DATA", "fail", "stale values", "LQ-20261107-160", "re-key")
    assert lanes["cron-relay"]["verdict_class"] == "not_provable"
    assert lanes["n8n-ran-live"]["verdict"] is None and lanes["n8n-ran-live"]["verdict_class"] == "not_audited"
    assert out["audited_not_in_registry"] == ["ghost-lane"] and any("ghost-lane" in n for n in out["notes"])
    assert out["stats"]["verdicts"] == {"PASS": 1, "FAIL_DATA": 1, "UNVERIFIABLE": 1, "FAIL_RUN": 1}
    assert out["stats"]["audit"] == {"pass": 1, "fail": 2, "not_provable": 1, "audited": 4}


def test_stats_and_categories(tmp_path):
    out = _compute(tmp_path)
    assert out["stats"]["modes"] == {"live": 3, "both": 1, "dry": 1, "none": 2}
    assert out["stats"]["retired_not_counted"] == 1
    cats = {c["key"]: c for c in out["categories"]}
    assert [c["key"] for c in out["categories"]] == ["research", "ops", "mystery"]
    assert cats["research"]["label"] == "Research & intel" and cats["research"]["blurb"] == "News and filings."
    assert cats["research"]["modes"] == {"live": 2, "both": 0, "dry": 1, "none": 0}
    assert cats["research"]["lanes"] == ["n8n-ran-live", "n8n-relay", "n8n-dry"]   # live first, then by title
    assert cats["ops"]["modes"] == {"live": 0, "both": 1, "dry": 0, "none": 2} and cats["ops"]["lanes"] == ["cron-relay"]
    assert cats["mystery"]["lanes"] == ["fallback-cat"]
    lane = out["lanes"]["n8n-relay"]
    assert lane["schedule"] == ["0 7 * * 1-5"] and lane["does"] == "does n8n-relay" and lane["in_relay"] is True
    assert "cron-only" not in out["lanes"]          # not-on-n8n rows are counted, not shipped (keeps the payload small)


@pytest.mark.parametrize("verdict,cls", [("PASS", "pass"), ("PASS_IDLE", "pass"), ("FAIL_CONSUMER", "fail"),
                                         ("HALLUCINATION", "fail"), ("UNVERIFIABLE", "not_provable"),
                                         (None, "not_audited"), ("", "not_audited")])
def test_only_pass_and_pass_idle_count_as_working(verdict, cls):
    assert N.verdict_class(verdict) == cls


def test_cache_serves_one_build_for_60_s(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(N, "compute", lambda **kw: calls.append(kw) or {"n": len(calls)})
    N._CACHE.clear()
    a = N.get_n8n_catalog(None, state=tmp_path)
    b = N.get_n8n_catalog(None, state=tmp_path)
    assert a is b and len(calls) == 1
    N.get_n8n_catalog(None, ttl=0, state=tmp_path)
    assert len(calls) == 2
    N._CACHE.clear()


def test_route_is_get_only_and_never_500():
    src = (ROOT / "scripts/api_v2.py").read_text(encoding="utf-8")
    i = src.index('if base_path == "/api/v2/ops/n8n-catalog":')
    block = src[i:i + 600]
    assert 'return 405, {"ok": False, "error": "read_only"}' in block
    assert "get_n8n_catalog" in block and "return 503" in block and "return 500" not in block


def test_live_verdicts_file_shape_if_present():
    """Against the host's audit file, when this runs on the host: the counts the operator was given."""
    p = N.state_root({}) / N.VERDICTS_REL
    if not p.exists():
        pytest.skip("no host verdicts file")
    v, meta = N.read_verdicts(p)
    assert meta["state"] == "ok" and meta["rows"] == len(v) > 0


# ── LQ-20261107-180: per-category job health (same rule as GET /api/v2/jobs-catalog) + fix-item status ────────────

def test_status_mix_matches_the_jobs_catalog_rule(tmp_path):
    from scripts.lib import jobs_history as JH

    assert N.MIX_KEYS == ("failed", "missed", "late", "running", "ok", "ok_unverified", "not_measured", "inactive")
    for status, key in JH._MIX.items():
        assert N.STATUS_MIX[status] == key, status
    snap = {**SNAP, "rows": [dict(ROWS[0], status="failed"), dict(ROWS[1], status="paused"), ROWS[2],
                             dict(ROWS[6], status="retired"), dict(ROWS[7], status="something_new")]}
    out = N.build(snap, RELAY, {"paused": []}, {}, {})
    research = next(c for c in out["categories"] if c["key"] == "research")
    assert research["jobs"] == 4 and research["inactive"] == 2
    assert research["status_mix"] == {"failed": 1, "missed": 0, "late": 0, "running": 0, "ok": 1,
                                      "ok_unverified": 0, "not_measured": 0, "inactive": 2}
    mystery = next(c for c in out["categories"] if c["key"] == "mystery")
    assert mystery["status_mix"]["not_measured"] == 1  # an unknown status is never counted as ok


def _ledger(tmp_path, items, name="LEAD-WORK-LEDGER-20261107.json"):
    d = tmp_path / N.LEDGER_DIR_REL
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps({"items": items}), encoding="utf-8")


def test_work_items_resolve_short_refs_in_the_newest_ledger(tmp_path):
    _ledger(tmp_path, [{"id": "LQ-20261106-57", "owner": "old", "status": "open"}], "LEAD-WORK-LEDGER-20261106.json")
    _ledger(tmp_path, [{"id": "LQ-20261107-57", "owner": "cc-x", "priority": "P1", "status": "in_progress", "title": "t"},
                       {"id": "INC-9", "owner": "cc-y", "status": "done"}])
    out, note = N.read_work_items(tmp_path, ["LQ-57", "INC-9", "LQ-404", None, ""])
    assert note is None
    assert out["LQ-57"] == {"id": "LQ-20261107-57", "owner": "cc-x", "priority": "P1", "status": "in_progress", "title": "t"}
    assert out["INC-9"]["status"] == "done"
    assert out["LQ-404"] == {"id": "LQ-404", "owner": None, "priority": None, "status": None, "title": None}
    assert set(out) == {"LQ-57", "INC-9", "LQ-404"}


def test_missing_or_broken_ledger_is_a_note_not_a_raise(tmp_path):
    out, note = N.read_work_items(tmp_path, ["LQ-1"])
    assert out["LQ-1"]["status"] is None and "No lead work ledger" in note
    d = tmp_path / N.LEDGER_DIR_REL
    d.mkdir(parents=True)
    (d / "LEAD-WORK-LEDGER-20261107.json").write_text("{not json", encoding="utf-8")
    out, note = N.read_work_items(tmp_path, ["LQ-1"])
    assert out["LQ-1"]["status"] is None and "could not be read" in note


def test_compute_carries_work_items_for_verdict_refs(tmp_path):
    _verdicts(tmp_path, [{"lane_id": "n8n-relay", "verdict": "FAIL_DATA", "defect": "d", "work_item": "LQ-57"}])
    _ledger(tmp_path, [{"id": "LQ-20261107-57", "owner": "cc-x", "status": "open"}])
    out = _compute(tmp_path)
    assert out["work_items"]["LQ-57"]["owner"] == "cc-x"


# ── LQ-180 commit 2: llm + fixes ───────────────────────────────────────────────────────────────────────────────
from datetime import datetime, timezone  # noqa: E402

NOW = datetime(2026, 11, 7, 17, 0, tzinfo=timezone.utc)


def _llm_rows():
    def r(pid, lane, calls, fails, cat, models=(), err=None, spend=0):
        return {"process_id": pid, "process_name": pid.title(), "category": cat, "model_lane": lane,
                "models": list(models), "calls": calls, "failures": fails,
                "last_at": datetime(2026, 11, 7, 16, 0, tzinfo=timezone.utc), "last_ok_at": None,
                "spend_usd": spend, "last_error": err}
    return [r("topic_curator", "chatgpt", 67, 67, "Research", err="401  unauthorized\n token"),
            r("topic_curator", "grok", 558, 145, "Research"),
            r("cio_plan_enrichment", "fast", 67, 0, "CIO", ("deepseek-flash", "grok-3-mini"), spend="0.067453"),
            r("incident_supervisor", "grok", 202, 2, "Operations"),
            r("n8n_lane_failure_diagnosis", "fast", 13, 0, "N8nCoordination", ("grok-3-mini",))]


def _query(rows, seen=None):
    calls = []

    def q(sql, params=None):
        calls.append((sql, params))
        if "INTERVAL '24 hours'" in sql:
            return rows
        return [{"process_id": k, "last_at": v} for k, v in (seen or {}).items()]
    q.calls = calls
    return q


def test_llm_splits_ops_and_content_and_flags_all_failed_lanes():
    q = _query(_llm_rows(), {"gap_resolver": datetime(2026, 11, 6, 21, 0, tzinfo=timezone.utc)})
    out = OPS.llm_section(q, fixer={"armed": False, "why": "no active git-push guard grant", "waiting": 6}, now=NOW)
    assert out["note"] is None and out["window"] == "24h" and out["as_of"] == NOW.isoformat()
    for sql, _ in q.calls:  # read-only
        assert sql.lstrip().upper().startswith("SELECT")
    g = {x["key"]: x for x in out["groups"]}
    ops = {i["process_id"]: i for i in g["ops"]["items"]}
    content = {i["process_id"]: i for i in g["content"]["items"]}
    assert set(OPS.OPS_ITEMS) <= set(ops) and "incident_supervisor" in ops and "topic_curator" in content
    tc = content["topic_curator"]
    assert tc["red"] and tc["status"] == "lane_all_failed" and (tc["calls"], tc["failures"]) == (625, 212)
    assert tc["lanes"][0]["lane"] == "chatgpt" and tc["lanes"][0]["all_failed"] is True
    assert tc["lanes"][0]["last_error"] == "401 unauthorized token"
    assert g["content"]["items"][0]["process_id"] == "topic_curator"  # red first
    cio = content["cio_plan_enrichment"]
    assert not cio["red"] and cio["models"] == ["deepseek-flash", "grok-3-mini"] and cio["spend_usd"] == 0.067453
    assert ops["gap_resolver"]["calls"] == 0 and ops["gap_resolver"]["status"] == "no_calls_24h"
    assert ops["gap_resolver"]["last_at"].startswith("2026-11-06T21:00")
    assert ops["prospectus_fact_check"]["last_at"] is None
    fx = ops["self_heal_fixer"]
    assert fx["status"] == "not_in_log" and fx["fixer"]["waiting"] == 6 and fx["label"] == "Code self-fix"
    assert g["ops"]["red"] == 0 and g["content"]["red"] == 1


def test_llm_all_calls_failed_is_red_and_unreadable_log_is_none_not_zero():
    rows = [{"process_id": "x", "model_lane": "chatgpt", "calls": 3, "failures": 3, "category": "Research"}]
    out = OPS.llm_section(_query(rows), now=NOW)
    x = next(i for g in out["groups"] for i in g["items"] if i["process_id"] == "x")
    assert x["status"] == "all_failed" and x["red"] and x["spend_usd"] is None
    out = OPS.llm_section(lambda sql, params=None: None, now=NOW)
    assert out["groups"] is None and "not zero" in out["note"]


def _fixer_files(tmp_path, armed=False):
    rt = tmp_path / "data/runtime"
    rt.mkdir(parents=True, exist_ok=True)
    jobs = {"a": {"job_id": "a", "lane": "lane-a", "state": "fix_requested", "created_at": "2026-11-01T00:00:00+00:00",
                  "history": [{"at": "2026-11-01T00:00:00+00:00", "state": "fix_requested"}]},
            "b": {"job_id": "b", "lane": "lane-b", "state": "fix_requested", "created_at": "2026-11-07T16:30:00+00:00"},
            "c": {"job_id": "c", "lane": "lane-c", "state": "fix_failed", "created_at": "2026-11-05T00:00:00+00:00"},
            "d": {"job_id": "d", "lane": "lane-d", "state": "fixed", "created_at": "2026-11-05T00:00:00+00:00"}}
    (rt / "self_heal_fixer_state.json").write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    (rt / "self_heal_fixer_last.json").write_text(json.dumps(
        {"finished_at": "2026-11-07T16:50:00+00:00",
         "arming": {"armed": armed, "why": "no active git-push guard grant"}}), encoding="utf-8")
    (rt / "n8n_failure_diagnosis_state.json").write_text(json.dumps({"escalations": {
        "k1": {"lane": "lane-e", "reason": "p1_floor:P1;suggest_only", "priority": "P1", "at": "2026-11-07T10:00:00+00:00",
               "detail": "x cause=the feed returned 0 rows"}}}), encoding="utf-8")


def test_fixes_lists_what_self_heal_could_not_fix_with_disabled_rerun(tmp_path):
    _fixer_files(tmp_path)
    _ledger(tmp_path, [
        {"id": "LQ-20261107-57", "owner": "cc-x", "priority": "P1", "status": "ASSIGNED", "title": "fix the feed"},
        {"id": "LQ-20261107-60", "owner": "cc-y", "priority": "P0", "status": "QUEUED", "title": "n8n cutover wave"},
        {"id": "LQ-20261107-61", "owner": "cc-z", "priority": "P2", "status": "ASSIGNED", "title": "lane-a output gap"},
        {"id": "LQ-20261107-62", "owner": "cc-z", "priority": "P0", "status": "DONE_LIVE", "title": "n8n done"},
        {"id": "LQ-20261107-63", "owner": "cc-z", "priority": "P0", "status": "QUEUED", "title": "broker docs"}])
    lanes = {"lane-a": {"work_item": None}, "n8n-relay": {"work_item": "LQ-57"}}
    refs = {"LQ-57": {"id": "LQ-20261107-57"}}
    fixes, summary = OPS.fixes_section(tmp_path, lanes, refs, now=NOW)
    assert fixes["notes"] == [] and fixes["ledger"] == "LEAD-WORK-LEDGER-20261107.json"
    assert [w["id"] for w in fixes["work"]] == ["LQ-20261107-60", "LQ-20261107-57", "LQ-20261107-61"]
    w = {x["id"]: x for x in fixes["work"]}
    assert w["LQ-20261107-57"]["audit_fix"] and w["LQ-20261107-57"]["lanes"] == ["n8n-relay"]
    assert w["LQ-20261107-61"]["lanes"] == ["lane-a"]
    sh = {x["key"]: x for x in fixes["self_heal"]}
    assert set(sh) == {"a", "c", "k1"}  # b is < 24 h old, d is fixed
    assert sh["a"]["grant_href"] == OPS.GRANTS_HREF and "not armed" in sh["a"]["plain"]
    assert sh["c"]["grant_href"] is None and "failed" in sh["c"]["plain"]
    assert sh["k1"]["cause"] == "the feed returned 0 rows" and sh["k1"]["plain"].startswith("Severity P1")
    assert all(x["rerun"] == {"enabled": False, "why": "needs operator grant"} for x in fixes["self_heal"])
    assert summary["waiting"] == 2 and summary["armed"] is False


def test_fixes_missing_stores_are_notes_and_none_not_empty(tmp_path):
    fixes, summary = OPS.fixes_section(tmp_path, {}, {}, now=NOW)
    assert fixes["work"] is None and summary["waiting"] is None
    assert len(fixes["notes"]) == 3


def test_compute_carries_llm_and_fixes(tmp_path):
    _fixer_files(tmp_path)
    out = _compute(tmp_path)
    assert out["llm"]["groups"] is None and "not zero" in out["llm"]["note"]  # hermetic: DB unreachable
    assert {x["key"] for x in out["fixes"]["self_heal"]} == {"a", "c", "k1"}
