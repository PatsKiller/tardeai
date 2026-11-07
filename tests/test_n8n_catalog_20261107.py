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
