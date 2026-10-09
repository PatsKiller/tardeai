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
from scripts.lib import n8n_coordination_gateway as GW  # noqa: E402
from scripts.lib.n8n_coordination_gateway import FORBIDDEN_ROUTE_TOKENS, SECRET_KEYS  # noqa: E402
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
    assert set(SECRET_KEYS) <= set(LD.FORBIDDEN_LANE_SUBSTRINGS)
    assert {"secret", "stop", "position", "guard", "deploy", "sender", "sm-render", "sm_render"} <= set(
        LD.FORBIDDEN_LANE_SUBSTRINGS)
    # The gateway's matcher is imported, not copied.
    assert LD._gateway_forbidden_token is GW.forbidden_route_token


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


# Blocker 2 (review of #1595): the gateway refuses substrings, so eligibility must too.
SUBSTRING_LANES = ["schwab-brokers-sync", "placeorders", "liveorders", "n8n-activation-grants",
                   "trailingstop-manager", "positionsync", "schwab-token-refresh", "reorder-watchlist"]


@pytest.mark.parametrize("lane_id", SUBSTRING_LANES)
def test_substrings_are_forbidden_like_the_gateway(lane_id):
    row = _row(lane_id=lane_id, expression="0 7 * * 1-5 $PY scripts/report.py", match="scripts/report.py")
    ok, why = LD.dispatch_eligible(row)
    assert ok is False and why.startswith("forbidden_token:"), why
    assert LD.dispatch_eligible(_row(expression=f"0 7 * * 1-5 $PY scripts/{lane_id}.py"))[0] is False


@pytest.mark.parametrize("route", ["/placeorders", "/n8n-activation-grants", "/liveorders", "/two_factor"])
def test_at_least_as_strict_as_gateway_route_matcher(route):
    assert GW.forbidden_route_token(route) is not None
    assert LD.dispatch_eligible(_row(lane_id=route.strip("/")))[0] is False


@pytest.mark.parametrize("word", sorted(SECRET_KEYS))
def test_gateway_secret_words_forbidden(word):
    assert LD.dispatch_eligible(_row(expression=f"0 6 * * * $PY scripts/refresh_{word}.py"))[0] is False


def test_bash_c_wrapper_and_string_scheduler_are_checked():
    wrapped = "0 9 * * 1-5 bash -c 'cd $PROJ && $PY scripts/schwab_trade_executor.py --apply'"
    assert LD.dispatch_eligible(_row(expression=wrapped))[0] is False
    string_sched = _row()
    string_sched["scheduler"] = wrapped                  # a plain-string scheduler is checked whole
    assert LD.dispatch_eligible(string_sched)[0] is False
    string_ok = _row()
    string_ok["scheduler"] = "0 7 * * 1-5 $PY scripts/daily_report.py"
    assert LD.dispatch_eligible(string_ok) == (True, "eligible")


def test_exec_start_and_service_checked():
    row = _row(lane_id="nightly-refresh", expression="nightly-refresh.timer", match=None,
               exec_start="/bin/bash ~/.config/mcporter/refresh_token.sh")
    assert LD.dispatch_eligible(row)[0] is False
    assert LD.dispatch_eligible(_row(service="tradeai-n8n-run-executor.service"))[0] is False


def test_allowlist_argv_checked():
    row = _row(lane_id="daily-report")
    assert LD.dispatch_eligible(row, allowlist_argv={}) == (True, "eligible")
    argv = {"daily-report": "$PY scripts/place_order_worker.py --live"}
    ok, why = LD.dispatch_eligible(row, allowlist_argv=argv)
    assert ok is False and why.endswith("@allowlist.argv")


def test_allowlist_loader_reads_real_argv(tmp_path):
    p = tmp_path / "allow.json"
    p.write_text(json.dumps({"lanes": [
        {"lane_id": "a", "command": ["$PY", "scripts/a.py"], "dry_run_arg": ["--dry-run"], "live_arg": [],
         "market_gate": True},
        {"lane_id": "b", "command": ["$PY", "scripts/b.py"], "dry_run_arg": None, "live_arg": ["--send"]},
        "junk"]}), encoding="utf-8")
    got = LD.load_run_allowlist_argv(p)
    assert got == {"a": "scripts/market_day_gate.sh $PY scripts/a.py --dry-run", "b": "$PY scripts/b.py --send"}
    assert LD.load_run_allowlist_argv(tmp_path / "missing.json") == {}
    real = LD.load_run_allowlist_argv()
    assert real, "config/n8n_run_allowlist.json must load"
    assert all(isinstance(v, str) and v for v in real.values())


@pytest.mark.parametrize("marker", [
    {"stay_on_cron": {"class": "secret", "token": "token"}},
    {"stay_on_cron": True},
    {"recommendation": "KEEP_ON_CRON"},
    {"rationalization": {"recommendation": "KEEP_ON_CRON"}},
])
def test_stay_on_cron_and_keep_on_cron_are_hard_ineligible(marker):
    row = _good_row(**marker)
    ok, why = LD.dispatch_eligible(row)
    assert ok is False and why in ("stay_on_cron", "keep_on_cron")
    assert LD.dispatchable(row) is False
    assert "forbidden_lane" in [i.code for i in LD.validate_dispatch_block(row)]


def test_dispatchable_requires_mode_and_eligibility():
    assert LD.dispatchable(_good_row(), allowlist_argv={}) is True
    assert LD.dispatchable(_row(), allowlist_argv={}) is False                     # no block: mode off
    off = _good_row()
    off["dispatch"]["mode"] = "off"
    assert LD.dispatchable(off, allowlist_argv={}) is False
    bad = _good_row()
    bad["dispatch"]["mode"] = "sometimes"                                           # malformed: fail closed
    assert LD.dispatchable(bad, allowlist_argv={}) is False
    assert LD.dispatchable(_good_row(lane_id="trailingstop-manager"), allowlist_argv={}) is False
    assert LR.dispatchable is LD.dispatchable


# ── PR #1597 reconcile rows (fixture extract) ────────────────────────────────────────────────────

FIXTURE_1597 = ROOT / "tests" / "fixtures" / "lane_registry_1597_keep_on_cron_extract.json"
NAMED_IN_REVIEW = ["paper-execution-sweep", "atm-auto-approver", "at-observation-01",
                   "at-observation-01-closeout", "mcporter-token-refresh", "tradeai-n8n-run-executor-service",
                   "alpaca-paper-adapter", "options-lifecycle-run", "options-tick"]


def test_1597_stay_on_cron_and_keep_on_cron_rows_never_eligible():
    rows = json.loads(FIXTURE_1597.read_text(encoding="utf-8"))["lanes"]
    by_id = {r["lane_id"]: r for r in rows}
    stay = [r for r in rows if r.get("stay_on_cron")]
    keep = [r for r in rows if r.get("recommendation") == "KEEP_ON_CRON"
            or (r.get("rationalization") or {}).get("recommendation") == "KEEP_ON_CRON"]
    assert len(stay) >= 60 and len(keep) >= 120
    for row in rows:
        live = dict(row, dispatch=copy.deepcopy(GOOD_DISPATCH))
        assert LD.dispatch_eligible(live, exceptions={})[0] is False, row["lane_id"]
        if row["lane_id"] in LD.load_policy_exceptions():
            continue                       # AGENTS 4.0.0 §23.3 exception; pinned in the scalp tests below
        assert LD.dispatch_eligible(live)[0] is False, row["lane_id"]
        assert LD.dispatchable(live) is False, row["lane_id"]
    for lane in NAMED_IN_REVIEW:
        assert lane in by_id, lane
        assert LD.dispatch_eligible(by_id[lane])[0] is False, lane


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
            assert LD.dispatch_eligible(row, exceptions={})[0] is False, row["lane_id"]
            if row["lane_id"] not in LD.load_policy_exceptions():
                assert LD.dispatch_eligible(row)[0] is False, row["lane_id"]
    assert named > 0


def test_scalp_lane_eligible_only_through_the_policy_exception():
    """AGENTS 4.0.0 §23.3 + operator 2026-10-09 ~18:05 ET: trade-ai-scalp-live wraps market_day_gate.sh (a
    pipeline_manifest excluded token). The config exception lifts exactly that token; without it the lane is
    ineligible for exactly that reason. Mode stays off, so it is still not dispatchable."""
    rows = {r["lane_id"]: r for r in _live_rows()}
    if "trade-ai-scalp-live" not in rows:
        pytest.skip("scalp row not present")
    row = rows["trade-ai-scalp-live"]
    assert LD.dispatch_eligible(row) == (True, "eligible:policy_exception:market_day_gate.sh")
    # Post-#1597 the reconciler stamps stay_on_cron (gate token) + KEEP_ON_CRON, which short-circuit first.
    assert row.get("stay_on_cron", {}).get("token") == "market_day_gate.sh"
    assert LD.dispatch_eligible(row, exceptions={}) == (False, "stay_on_cron")
    # With the markers stripped, the forbidden-token rule still trips on its own without the exception.
    bare = {k: v for k, v in row.items() if k not in ("stay_on_cron", "recommendation", "rationalization")}
    assert LD.dispatch_eligible(bare, exceptions={}) == (
        False, "forbidden_token:market_day_gate.sh@scheduler.expression")
    assert LD.dispatch_eligible(bare) == (True, "eligible:policy_exception:market_day_gate.sh")
    assert LD.dispatch_mode(row) == "off" and LD.dispatchable(row) is False


def test_only_the_excepted_lane_changes_eligibility_in_the_live_registry():
    flipped = [r["lane_id"] for r in _live_rows()
               if LD.dispatch_eligible(r)[0] != LD.dispatch_eligible(r, exceptions={})[0]]
    assert flipped in ([], ["trade-ai-scalp-live"])


# ── policy exceptions (config/lane_dispatch_policy_exceptions.json) ─────────────────────────────

SCALP_EXPR = ("*/5 9-15 * * 1-5 cd $PROJ && flock -n /tmp/tradeai_scalp_live.lock timeout 295 bash "
              "scripts/market_day_gate.sh $PY scripts/run_trade_ai_scalp_live.py >> logs/trade_ai_scalp_live.log 2>&1")
SCALP_EXC = {"trade-ai-scalp-live": frozenset({"market_day_gate.sh"})}
SCALP_ARGV = {"trade-ai-scalp-live": "scripts/market_day_gate.sh scripts/run_trade_ai_scalp_live.py --dry-run"}
GATE_MARK = {"class": "pipeline_excluded_gate", "token": "market_day_gate.sh",
             "source": "pipeline_manifest.FORBIDDEN_COMMAND_TOKENS"}


def _scalp(**extra):
    return _row(lane_id="trade-ai-scalp-live", expression=SCALP_EXPR, match="scripts/run_trade_ai_scalp_live.py",
                **extra)


def test_policy_exception_config_lists_only_scalp_live_market_day_gate():
    doc = json.loads(LD.DEFAULT_POLICY_EXCEPTIONS.read_text(encoding="utf-8"))
    assert [e["lane_id"] for e in doc["exceptions"]] == ["trade-ai-scalp-live"]
    assert doc["exceptions"][0]["exempt_tokens"] == ["market_day_gate.sh"]
    assert "4.0.0" in doc["exceptions"][0]["authority"] and "2026-10-09" in doc["exceptions"][0]["approval"]
    assert LD.load_policy_exceptions() == SCALP_EXC
    assert LD.EXEMPTIBLE_TOKENS == frozenset({"market_day_gate.sh"})
    assert LD.EXEMPTIBLE_LANES == frozenset({"trade-ai-scalp-live"})
    assert "market_day_gate.sh" in FORBIDDEN_COMMAND_TOKENS


def test_scalp_live_eligible_with_exception_including_allowlist_argv():
    row = _scalp()
    assert LD.dispatch_eligible(row, allowlist_argv=SCALP_ARGV, exceptions=SCALP_EXC) == (
        True, "eligible:policy_exception:market_day_gate.sh")
    assert LD.dispatch_eligible(row, allowlist_argv=SCALP_ARGV, exceptions={})[0] is False
    live = _scalp(dispatch=copy.deepcopy(GOOD_DISPATCH))
    assert LD.dispatchable(live, allowlist_argv=SCALP_ARGV, exceptions=SCALP_EXC) is True
    off = _scalp(dispatch=dict(copy.deepcopy(GOOD_DISPATCH), mode="off"))
    assert LD.dispatchable(off, allowlist_argv=SCALP_ARGV, exceptions=SCALP_EXC) is False
    assert LD.dispatchable(_scalp(), allowlist_argv=SCALP_ARGV, exceptions=SCALP_EXC) is False   # no block = off


def test_unlisted_lane_with_market_day_gate_stays_ineligible():
    row = _row(lane_id="gated-report", expression="0 10 * * 1-5 bash scripts/market_day_gate.sh $PY scripts/report.py",
               match="scripts/report.py", dispatch=copy.deepcopy(GOOD_DISPATCH))
    assert LD.dispatch_eligible(row, exceptions=SCALP_EXC) == (
        False, "forbidden_token:market_day_gate.sh@scheduler.expression")
    assert LD.dispatch_eligible(row) == (False, "forbidden_token:market_day_gate.sh@scheduler.expression")


@pytest.mark.parametrize("extra", [
    " && $PY scripts/broker_stop_reconcile.py",
    " && $PY scripts/place_order_worker.py",
    " && $PY scripts/positions_sync.py",
    " && $PY scripts/digest.py --send",
    " && bash scripts/sm-render.sh",
])
def test_scalp_live_with_any_other_forbidden_token_stays_ineligible(extra):
    row = _row(lane_id="trade-ai-scalp-live", expression=SCALP_EXPR + extra,
               match="scripts/run_trade_ai_scalp_live.py", dispatch=copy.deepcopy(GOOD_DISPATCH))
    ok, why = LD.dispatch_eligible(row, exceptions=SCALP_EXC)
    assert ok is False and why.startswith("forbidden_token:") and "market_day_gate" not in why
    assert LD.dispatchable(row, exceptions=SCALP_EXC) is False


def test_scalp_live_command_field_broker_token_stays_ineligible():
    ok, why = LD.dispatch_eligible(_scalp(command="$PY scripts/sync_basis_from_broker.py"), exceptions=SCALP_EXC)
    assert ok is False and why.startswith("forbidden_token:")


def test_exception_lifts_only_the_b1_gate_marker():
    row = _scalp(stay_on_cron=dict(GATE_MARK), recommendation="KEEP_ON_CRON")
    assert LD.dispatch_eligible(row, exceptions=SCALP_EXC) == (True, "eligible:policy_exception:market_day_gate.sh")
    assert LD.dispatch_eligible(row, exceptions={}) == (False, "stay_on_cron")
    for mark in ({"class": "broker_order", "token": "market_day_gate.sh"},
                 {"class": "pipeline_excluded_gate", "token": "other_gate.sh"},
                 {"class": "secret", "token": "token"}, True):
        assert LD.dispatch_eligible(_scalp(stay_on_cron=mark), exceptions=SCALP_EXC) == (False, "stay_on_cron")
    # KEEP_ON_CRON without the gate marker is some other reason: still blocks
    assert LD.dispatch_eligible(_scalp(recommendation="KEEP_ON_CRON"), exceptions=SCALP_EXC) == (
        False, "keep_on_cron")
    # an unlisted lane carrying the gate marker stays blocked
    other = _row(lane_id="gated-report", stay_on_cron=dict(GATE_MARK))
    assert LD.dispatch_eligible(other, exceptions=SCALP_EXC) == (False, "stay_on_cron")


def test_1597_scalp_row_eligible_only_through_the_exception():
    rows = {r["lane_id"]: r for r in json.loads(FIXTURE_1597.read_text(encoding="utf-8"))["lanes"]}
    row = rows["trade-ai-scalp-live"]
    assert row["stay_on_cron"]["class"] == LD.GATE_STAY_CLASS and row["recommendation"] == "KEEP_ON_CRON"
    assert LD.dispatch_eligible(row) == (True, "eligible:policy_exception:market_day_gate.sh")
    assert LD.dispatch_eligible(row, exceptions={}) == (False, "stay_on_cron")


def test_stay_behind_still_blocks_excepted_lane():
    row = _scalp(watch={"factor": 2.0, "severity": "P2", "stay_behind": True})
    assert LD.dispatch_eligible(row, exceptions=SCALP_EXC) == (False, "stay_behind")


@pytest.mark.parametrize("content", [
    None, "", "not json", "[]", '{"exceptions": "x"}', '{"exceptions": [1, null]}',
    '{"exceptions": [{"lane_id": "trade-ai-scalp-live"}]}',
    '{"exceptions": [{"lane_id": "trade-ai-scalp-live", "exempt_tokens": []}]}',
    '{"exceptions": [{"lane_id": "trade-ai-scalp-live", "exempt_tokens": "market_day_gate.sh"}]}',
    '{"exceptions": [{"lane_id": "trade-ai-scalp-live", "exempt_tokens": ["market_day_gate.sh", "broker"]}]}',
    '{"exceptions": [{"lane_id": "trade-ai-scalp-live", "exempt_tokens": ["sender"]}]}',
    '{"exceptions": [{"lane_id": "trade-ai-scalp-live", "exempt_tokens": ["market_day_gate.sh"]},'
    ' {"lane_id": "trade-ai-scalp-live", "exempt_tokens": ["market_day_gate.sh"]}]}',
], ids=lambda c: "missing" if c is None else (c[:40] or "empty"))
def test_missing_or_malformed_exception_config_fails_closed(tmp_path, content):
    p = tmp_path / "exc.json"
    if content is not None:
        p.write_text(content, encoding="utf-8")
    table = LD.load_policy_exceptions(p)
    assert table == {}
    assert LD.dispatch_eligible(_scalp(), allowlist_argv=SCALP_ARGV, exceptions=table)[0] is False


def test_exception_table_cannot_widen_beyond_exemptible_tokens():
    widened = {"trade-ai-scalp-live": frozenset({"market_day_gate.sh", "broker", "place_order"})}
    row = _row(lane_id="trade-ai-scalp-live", expression=SCALP_EXPR + " && $PY scripts/place_order_worker.py",
               match="x")
    assert LD.dispatch_eligible(row, exceptions=widened)[0] is False


def test_sender_lane_listed_in_exceptions_stays_ineligible():
    exc = {"digest-sender": frozenset({"market_day_gate.sh"})}
    row = _row(lane_id="digest-sender", expression="0 17 * * 1-5 bash scripts/market_day_gate.sh $PY scripts/digest.py --send",
               match="scripts/digest.py")
    ok, why = LD.dispatch_eligible(row, exceptions=exc)
    assert ok is False and why.startswith("forbidden_token:") and "market_day_gate" not in why


def test_exception_entry_for_other_lane_is_ignored(tmp_path):
    p = tmp_path / "exc.json"
    p.write_text(json.dumps({"exceptions": [
        {"lane_id": "trade-ai-scalp-live", "exempt_tokens": ["market_day_gate.sh"]},
        {"lane_id": "other-report", "exempt_tokens": ["market_day_gate.sh"]}]}), encoding="utf-8")
    table = LD.load_policy_exceptions(p)
    assert table == SCALP_EXC
    row = _row(lane_id="other-report", expression="0 10 * * 1-5 bash scripts/market_day_gate.sh $PY scripts/report.py",
               match="scripts/report.py")
    assert LD.dispatch_eligible(row, exceptions=table) == (
        False, "forbidden_token:market_day_gate.sh@scheduler.expression")
    # even a hand-built table naming the lane is intersected with the code ceiling
    forced = {"other-report": frozenset({"market_day_gate.sh"})}
    assert LD.dispatch_eligible(row, exceptions=forced) == (
        False, "forbidden_token:market_day_gate.sh@scheduler.expression")
    assert LD.dispatch_eligible(dict(row, stay_on_cron=dict(GATE_MARK)), exceptions=forced) == (False, "stay_on_cron")


def test_exception_lifts_only_top_level_keep_on_cron_not_rationalization():
    lifted = _scalp(stay_on_cron=dict(GATE_MARK), recommendation="KEEP_ON_CRON",
                    rationalization={"recommendation": "PIPELINE:P02"})
    assert LD.dispatch_eligible(lifted, exceptions=SCALP_EXC) == (True, "eligible:policy_exception:market_day_gate.sh")
    rat_keep = _scalp(stay_on_cron=dict(GATE_MARK), recommendation="KEEP_ON_CRON",
                      rationalization={"recommendation": "KEEP_ON_CRON"})
    assert LD.dispatch_eligible(rat_keep, exceptions=SCALP_EXC) == (False, "keep_on_cron")
    rat_only = _scalp(stay_on_cron=dict(GATE_MARK), rationalization={"recommendation": "KEEP_ON_CRON"})
    assert LD.dispatch_eligible(rat_only, exceptions=SCALP_EXC) == (False, "keep_on_cron")
