"""N8N Maturity B5.2 — registry dispatch/watch block loader + forbidden-token eligibility (design 02 §2).

Hermetic: synthetic rows. The live config/lane_registry.json is only READ, for two invariants: no row carries
a dispatch block yet (all parse to mode off), and every real row naming a broker/order/secret script is
dispatch-ineligible."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import lane_registry as LR  # noqa: E402
from scripts.lib.n8n_coordination_gateway import FORBIDDEN_ROUTE_TOKENS  # noqa: E402
from scripts.pipelines.pipeline_manifest import FORBIDDEN_COMMAND_TOKENS  # noqa: E402

SCHEMA_PATH = ROOT / "docs" / "implementation" / "n8n-maturity" / "schemas" / "registry-dispatch-block.schema.json"
DUE_SCHEMA_PATH = ROOT / "docs" / "implementation" / "n8n-maturity" / "schemas" / "due-response.schema.json"

GOOD_DISPATCH = {
    "mode": "live",
    "cron": ["30 7 * * 1-5"],
    "tz": "America/New_York",
    "wave": "W3",
    "class": "report",
    "priority": 5,
    "retry_policy": "transient-2",
    "catchup_min": 60,
    "after": [{"lane_id": "close-capture", "same_day": True, "deadline_min": 90}],
    "triggers": [{"source": "run_done", "lane_id": "material-change-detector"}],
    "sweep_cron": ["0 * * * *"],
    "min_interval_s": 120,
}
GOOD_WATCH = {"factor": 2.0, "severity": "P2", "max_run_s": 600}


def _row(lane_id="daily-report", expression="30 7 * * 1-5", match="scripts/daily_report.py", **extra):
    row = {"lane_id": lane_id, "owner": "platform",
           "scheduler": {"kind": "cron", "expression": expression, "match": match},
           "expected_cadence_hours": 24, "state": "ACTIVE", "output_signal": {"kind": "none"}}
    row.update(extra)
    return row


def _good_row(**extra):
    return _row(dispatch=copy.deepcopy(GOOD_DISPATCH), watch=dict(GOOD_WATCH), **extra)


KNOWN = {"daily-report", "close-capture", "material-change-detector"}


# ── constants ────────────────────────────────────────────────────────────────────────────────────

def test_constants_match_schema():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    d = schema["properties"]["dispatch"]["properties"]
    assert tuple(d["mode"]["enum"]) == LD.DISPATCH_MODES == ("off", "dry_run", "live")
    assert tuple(d["class"]["enum"]) == LD.DISPATCH_CLASSES and len(LD.DISPATCH_CLASSES) == 9
    assert tuple(d["wave"]["enum"]) == LD.DISPATCH_WAVES
    assert tuple(d["triggers"]["items"]["properties"]["source"]["enum"]) == LD.TRIGGER_SOURCES
    assert set(d) == set(LD._DISPATCH_KEYS)
    assert tuple(schema["properties"]["dispatch"]["required"]) == LD._DISPATCH_REQUIRED
    assert set(schema["properties"]["watch"]["properties"]) == set(LD._WATCH_KEYS)
    assert LD.RATIFICATION_GATED_CLASSES == {"llm", "ingest", "send", "learn"}
    assert LD.PERMITTED_CLASSES_PRE_R1 == {"monitor", "report", "hygiene", "pipeline", "heavy"}


def test_issue_codes_align_with_due_response_schema():
    due = json.loads(DUE_SCHEMA_PATH.read_text(encoding="utf-8"))
    codes = set(due["properties"]["errors"]["items"]["properties"]["code"]["enum"])
    for code in (LD.ISSUE_BAD_CRON, LD.ISSUE_UNKNOWN_RETRY_POLICY, LD.ISSUE_CLASS_NOT_PERMITTED,
                 LD.ISSUE_AFTER_UNKNOWN_LANE):
        assert code in codes


def test_forbidden_tokens_derive_from_sources_of_truth():
    assert set(FORBIDDEN_ROUTE_TOKENS) <= LD.FORBIDDEN_LANE_TOKENS
    assert set(FORBIDDEN_COMMAND_TOKENS) <= set(LD.FORBIDDEN_LANE_SUBSTRINGS)
    assert {"secret", "secrets", "stop", "positions", "guard", "deploy"} <= LD.FORBIDDEN_LANE_TOKENS
    assert {"sm-render", "sm_render"} <= set(LD.FORBIDDEN_LANE_SUBSTRINGS)


# ── parsing ──────────────────────────────────────────────────────────────────────────────────────

def test_absent_blocks_are_inert():
    row = _row()
    assert LD.parse_dispatch_block(row) is None
    assert LD.dispatch_mode(row) == "off"
    assert LD.parse_watch_block(row) == LD.WatchBlock(factor=2.0, severity=None, max_run_s=None,
                                                      stay_behind=False, restart_safe=False)
    assert LD.validate_dispatch_block(row, known_lane_ids=KNOWN, retry_policy_names={"transient-2"}) == []


def test_good_block_parses_to_frozen_dataclasses():
    block = LD.parse_dispatch_block(_good_row())
    assert block == LD.DispatchBlock(
        mode="live", cron=("30 7 * * 1-5",), tz="America/New_York", wave="W3", klass="report", priority=5,
        retry_policy="transient-2", catchup_min=60, min_interval_s=120,
        after=(LD.AfterEdge("close-capture", same_day=True, deadline_min=90, soft=False),),
        triggers=(LD.Trigger("run_done", lane_id="material-change-detector"),),
        sweep_cron=("0 * * * *",), digest_window=None, digest_role=None)
    with pytest.raises(Exception):
        block.mode = "off"  # type: ignore[misc]
    assert LD.parse_watch_block(_good_row()) == LD.WatchBlock(factor=2.0, severity="P2", max_run_s=600)
    assert LD.dispatch_mode(_good_row()) == "live"


def test_minimal_block_defaults():
    d = {k: GOOD_DISPATCH[k] for k in ("mode", "cron", "class", "priority", "retry_policy", "wave")}
    block = LD.parse_dispatch_block(_row(dispatch=dict(d, mode="dry_run", cron=[])))
    assert block.tz == "America/New_York" and block.catchup_min is None and block.min_interval_s == 0
    assert block.after == () and block.triggers == () and block.sweep_cron == () and block.cron == ()


def test_good_block_validates_against_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate({"dispatch": GOOD_DISPATCH, "watch": GOOD_WATCH}, schema)


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d.update(mode="on"), "bad_block"),
    (lambda d: d.pop("retry_policy"), "bad_block"),
    (lambda d: d.update(surprise=1), "bad_block"),
    (lambda d: d.update(tz="UTC"), "bad_block"),
    (lambda d: d.update(wave="W9"), "bad_block"),
    (lambda d: d.update(**{"class": "trading"}), "bad_block"),
    (lambda d: d.update(priority=10), "bad_block"),
    (lambda d: d.update(priority=True), "bad_block"),
    (lambda d: d.update(retry_policy="Bad Name"), "bad_block"),
    (lambda d: d.update(catchup_min=0), "bad_block"),
    (lambda d: d.update(after=[{"same_day": True}]), "bad_block"),
    (lambda d: d.update(after=[{"lane_id": "x", "deadline_min": 721}]), "bad_block"),
    (lambda d: d.update(triggers=[{"source": "webhook"}]), "bad_block"),
    (lambda d: d.update(triggers=[{"source": "receipt", "receipt_rel": "/etc/passwd"}]), "bad_block"),
    (lambda d: d.update(digest_role="owner"), "bad_block"),
    (lambda d: d.update(cron=["@daily"]), "bad_cron"),
    (lambda d: d.update(cron=["61 7 * * 1-5"]), "bad_cron"),
    (lambda d: d.update(cron=["30 7 * * MON"]), "bad_cron"),
    (lambda d: d.update(sweep_cron=["0 * * *"]), "bad_cron"),
])
def test_malformed_block_raises_typed_error_and_mode_off(mutate, code):
    d = copy.deepcopy(GOOD_DISPATCH)
    mutate(d)
    row = _row(dispatch=d)
    with pytest.raises(LD.DispatchBlockError) as exc:
        LD.parse_dispatch_block(row)
    assert exc.value.code == code
    assert LD.dispatch_mode(row) == "off"
    issues = LD.validate_dispatch_block(row)
    assert [i.code for i in issues] == [code]


@pytest.mark.parametrize("watch", [{"factor": 0.5}, {"factor": 7}, {"severity": "P0"}, {"max_run_s": 0},
                                   {"stay_behind": "yes"}, {"other": 1}, "P2"])
def test_malformed_watch(watch):
    row = _row(watch=watch)
    with pytest.raises(LD.DispatchBlockError):
        LD.parse_watch_block(row)
    assert [i.code for i in LD.validate_dispatch_block(row)] == ["bad_block"]
    assert LD.dispatch_eligible(row)[0] is False


# ── validation ───────────────────────────────────────────────────────────────────────────────────

def test_good_row_has_no_issues():
    assert LD.validate_dispatch_block(_good_row(), known_lane_ids=KNOWN, retry_policy_names={"transient-2"}) == []


def test_unknown_retry_policy():
    issues = LD.validate_dispatch_block(_good_row(), retry_policy_names={"none"})
    assert [i.code for i in issues] == ["unknown_retry_policy"]
    assert LD.validate_dispatch_block(_good_row(), retry_policy_names=None) == []


@pytest.mark.parametrize("klass", sorted(LD.RATIFICATION_GATED_CLASSES))
def test_ratification_gated_classes_refused_until_permitted(klass):
    row = _good_row()
    row["dispatch"]["class"] = klass
    assert [i.code for i in LD.validate_dispatch_block(row)] == ["class_not_permitted"]
    assert LD.validate_dispatch_block(row, permitted_classes=LD.DISPATCH_CLASSES) == []


def test_after_and_run_done_unknown_lane():
    row = _good_row()
    issues = LD.validate_dispatch_block(row, known_lane_ids={"daily-report"})
    assert [i.code for i in issues] == ["after_unknown_lane", "after_unknown_lane"]
    row["dispatch"]["after"] = [{"lane_id": "daily-report"}]       # self-edge
    row["dispatch"]["triggers"] = []
    assert [i.code for i in LD.validate_dispatch_block(row, known_lane_ids=KNOWN)] == ["after_unknown_lane"]


def test_issue_as_dict_shape():
    issue = LD.validate_dispatch_block(_good_row(), retry_policy_names=set())[0]
    assert issue.as_dict() == {"lane_id": "daily-report", "code": "unknown_retry_policy",
                               "detail": "retry_policy 'transient-2'"}


# ── forbidden-token rule ─────────────────────────────────────────────────────────────────────────

FORBIDDEN_ROWS = [
    ("broker-sync", "*/15 9-16 * * 1-5 $PY scripts/schwab_position_sync.py", "scripts/schwab_position_sync.py"),
    ("positions-sync", "0 * * * * $PY scripts/positions_sync.py --apply", "scripts/positions_sync.py"),
    ("place-order-runner", "*/5 9-15 * * 1-5 $PY scripts/place_order_worker.py", "place_order_worker.py"),
    ("stop-manager", "*/5 9-15 * * 1-5 $PY scripts/unified_stop_supervisor.py", "unified_stop_supervisor"),
    ("dynamic-stop-refresh", "0 8 * * 1-5 $PY scripts/refresh_levels.py", "scripts/refresh_levels.py"),
    ("secret-render", "0 6 * * * bash scripts/sm-render.sh", "scripts/sm-render.sh"),
    ("bws-refresh", "0 6 * * * bash scripts/secrets_refresh.sh", "scripts/secrets_refresh.sh"),
    ("grant-expiry", "*/10 * * * * $PY scripts/guard_expire.py", "scripts/guard_expire.py"),
    ("nightly-deploy", "0 2 * * * bash scripts/deploy_release.sh", "scripts/deploy_release.sh"),
    ("release-promote", "0 3 * * * bash scripts/release_ctl.sh promote", "scripts/release_ctl.sh promote"),
    ("digest-sender", "0 17 * * 1-5 $PY scripts/digest.py --send", "scripts/digest.py"),
    ("telegram-alerts", "*/5 * * * * $PY scripts/alerts.py", "scripts/alerts.py"),
    ("gated-report", "0 10 * * 1-5 bash scripts/market_day_gate.sh $PY scripts/report.py", "scripts/report.py"),
]


@pytest.mark.parametrize("lane_id,expression,match", FORBIDDEN_ROWS, ids=[r[0] for r in FORBIDDEN_ROWS])
def test_forbidden_lanes_never_eligible_even_live(lane_id, expression, match):
    row = _row(lane_id=lane_id, expression=expression, match=match, dispatch=copy.deepcopy(GOOD_DISPATCH))
    ok, why = LD.dispatch_eligible(row)
    assert ok is False and why.startswith("forbidden_token:")
    assert LD.dispatch_mode(row) == "live"            # the block says live ...
    codes = [i.code for i in LD.validate_dispatch_block(row)]
    assert "forbidden_lane" in codes                   # ... and validation refuses it


def test_forbidden_token_in_command_or_script_field():
    assert LD.dispatch_eligible(_row(command="$PY scripts/broker_stop_reconcile.py"))[0] is False
    assert LD.dispatch_eligible(_row(script="scripts/sync_basis_from_broker.py"))[0] is False


def test_token_boundary_not_substring():
    # "order" inside "reorder" and "stop" inside "nonstop" are not tokens.
    row = _row(lane_id="reorder-watchlist-nonstop", expression="0 7 * * 1-5 $PY scripts/reorder_watchlist.py",
               match="scripts/reorder_watchlist.py")
    assert LD.dispatch_eligible(row) == (True, "eligible")


def test_benign_report_lane_eligible_and_clean():
    row = _good_row()
    assert LD.dispatch_eligible(row) == (True, "eligible")
    assert LD.validate_dispatch_block(row, known_lane_ids=KNOWN, retry_policy_names={"transient-2"}) == []


def test_stay_behind_never_eligible():
    row = _good_row()
    row["watch"]["stay_behind"] = True
    assert LD.dispatch_eligible(row) == (False, "stay_behind")
    assert [i.code for i in LD.validate_dispatch_block(row)] == ["forbidden_lane"]


def test_mode_off_on_forbidden_lane_is_not_an_issue():
    d = dict(copy.deepcopy(GOOD_DISPATCH), mode="off")
    row = _row(lane_id="stop-manager", expression="*/5 * * * * x", match="unified_stop_supervisor", dispatch=d)
    assert LD.validate_dispatch_block(row) == []


# ── re-exports + gate hook ───────────────────────────────────────────────────────────────────────

def test_lane_registry_reexports():
    for name in ("dispatch_eligible", "dispatch_mode", "parse_dispatch_block", "parse_watch_block",
                 "validate_dispatch_block"):
        assert getattr(LR, name) is getattr(LD, name)


def test_registry_dispatch_errors_hook():
    bad = _good_row(lane_id="stop-manager", match="unified_stop_supervisor")
    reg = {"lanes": [_row(), _good_row(lane_id="close-capture"), _row(lane_id="material-change-detector"), bad]}
    errs = LD.registry_dispatch_errors(reg)
    assert any(e.startswith("stop-manager: dispatch forbidden_lane") for e in errs)
    # close-capture's after edge names itself: a self-edge is reported as after_unknown_lane.
    assert any(e.startswith("close-capture: dispatch after_unknown_lane") for e in errs)
    assert LD.registry_dispatch_errors({"lanes": [_row()]}) == []


# ── live registry (read-only) ────────────────────────────────────────────────────────────────────

def _live_rows():
    return json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))["lanes"]


def test_live_registry_rows_are_all_mode_off():
    rows = _live_rows()
    assert rows
    for row in rows:
        assert LD.dispatch_mode(row) == "off", row["lane_id"]
        assert LD.validate_dispatch_block(row, known_lane_ids={r["lane_id"] for r in rows}) == [], row["lane_id"]


def test_live_rows_naming_broker_order_secret_scripts_are_ineligible():
    named = 0
    for row in _live_rows():
        sched = row.get("scheduler") or {}
        blob = " ".join(str(v) for v in (row["lane_id"], sched.get("expression"), sched.get("match")) if v).lower()
        if any(t in blob for t in FORBIDDEN_COMMAND_TOKENS) or any(
                t in blob for t in ("broker", "place_order", "secret", "sm-render", "sm_render")):
            named += 1
            assert LD.dispatch_eligible(row)[0] is False, row["lane_id"]
    assert named > 0


def test_scalp_lane_trips_market_day_gate_token_and_is_not_carved_out():
    """AGENTS 4.0.0 §23.3: trade-ai-scalp-live is governed through the allowlist. Its registry cron line wraps
    market_day_gate.sh (a pipeline_manifest excluded token), so this rule marks it ineligible — reported, not
    silently carved out."""
    rows = {r["lane_id"]: r for r in _live_rows()}
    if "trade-ai-scalp-live" not in rows:
        pytest.skip("scalp row not present")
    ok, why = LD.dispatch_eligible(rows["trade-ai-scalp-live"])
    assert (ok, why) == (False, "forbidden_token:market_day_gate.sh@scheduler.expression")
