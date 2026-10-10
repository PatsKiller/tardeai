"""Forbidden-token matcher moves to whole-word / path-segment matching — safety-rail tests.

Operator ruling 2026-10-10 ~00:20 ET (n8n-maturity REMEDIATION_PLAN §7 ruling 2): the forbidden-token matcher
behind `scripts/lib/lane_dispatch.dispatch_eligible` (and the §23.14 test mirror `dispatcher_eligible` in
tests/test_agents_policy_4_1_0_amendment.py) matched substrings of the separator-collapsed text, so `topic`
and `hermes_top20` tripped `stop`, `synthesizer` tripped `size`, `redeploy_cash` tripped `deploy`. It now
splits argv / paths / env assignments on every non-alphanumeric (incl. _ - / . = and space) and compares
words, with inflections (orders, stops, positions, sizing, promotion), multi-word tokens as contiguous words
or their joined form (two_factor / twofactor, place_order / placeorders), broker brand names and the
pipeline_manifest script names still matched as substrings of the collapsed text, and a small explicit
compound rule (liveorders, trailingstop, positionsync).

THIS IS A SAFETY RAIL (AGENTS.md §0 rails 1-2, §23.3, §23.14). The matrix below is the evidence that nothing
real got looser than the ruling intends:
  * every config/lane_registry.json row, every config/crontab_backup.txt command line, and every
    config/n8n_run_allowlist.json argv that the LEGACY substring matcher (copied verbatim below) blocks is
    still blocked by the new matcher — except the rows in REVIEWED_NOW_ALLOWED, each the ruling's named false
    positive, and each must carry only a reviewed false-positive token;
  * every allowlist `never` category and the broker/order/stop/secret names of the earlier review cases block;
  * mutations: a matcher that is too loose (exact words only; no brand substrings; no inflections) lets at
    least one real legacy-blocked lane through — so these tests have teeth;
  * env-var / flag tokens are inspected: L323's verbatim cron line (MOMENTUM_SCALP_VALIDATION_SUBMIT=1) makes
    the lane ineligible.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import n8n_coordination_gateway as GW  # noqa: E402
from scripts.pipelines import pipeline_manifest as PM  # noqa: E402

REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))["lanes"]
ALLOW = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
CRONTAB = (ROOT / "config" / "crontab_backup.txt").read_text(encoding="utf-8").splitlines()
L323_CRON_LINE = next(line for line in CRONTAB if "MOMENTUM_SCALP_VALIDATION_SUBMIT=1" in line
                      and "auto_proposal_generator.py" in line)


# ── the legacy matcher, verbatim (lane_dispatch.forbidden_hits before this change) ──────────────────

_LEGACY_EXTRA = (
    "secret", "stop", "position", "guard", "deploy", "sender", "sm-render", "sm_render", "smrender",
    "schwab", "alpaca", "snaptrade", "moomoo", "ibkr", "paper", "executor",
)
_LEGACY_SUBSTRINGS = tuple(PM.FORBIDDEN_COMMAND_TOKENS) + tuple(sorted(GW.SECRET_KEYS)) + _LEGACY_EXTRA


def _legacy_text_hits(text: str) -> set[str]:
    text = text.lower()
    hits: set[str] = set()
    squashed = re.sub(r"[^a-z0-9]+", "", text)
    for variant in (text, squashed):
        tok = GW.forbidden_route_token(variant)        # unchanged: the gateway's own (route) matcher
        if tok is not None:
            hits.add(tok)
    for sub in _LEGACY_SUBSTRINGS:
        s = sub.lower()
        if s in text or re.sub(r"[^a-z0-9]+", "", s) in squashed:
            hits.add(sub)
    return hits


def _legacy_row_hits(row: dict) -> set[str]:
    return {h for _f, text in LD._command_fields(row) for h in _legacy_text_hits(text)}


def _new_row_hits(row: dict) -> set[str]:
    return {tok for tok, _field in LD.forbidden_hits(row)}


# ── the corpus: every real registry row, crontab line and allowlist argv ─────────────────────────────

def _cron_rows() -> list[dict]:
    rows = []
    for n, line in enumerate(CRONTAB, 1):
        s = line.strip()
        if not s or s.startswith("#") or re.match(r"^[A-Z_]+=", s):
            continue
        rows.append({"lane_id": f"crontab-L{n}", "command": s})
    return rows


def _allowlist_rows() -> list[dict]:
    rows = []
    for e in ALLOW["lanes"]:
        argv = [*e.get("command", []), *(e.get("dry_run_arg") or []), *(e.get("live_arg") or [])]
        rows.append({"lane_id": f"allowlist:{e['lane_id']}", "command": " ".join(argv)})
    return rows


CORPUS = list(REGISTRY) + _cron_rows() + _allowlist_rows()

#: The ruling's named false positives, each reviewed. key = registry lane_id, or a script name for crontab rows.
#: Value = the only legacy tokens the row may carry (all of them substring artefacts) and why.
REVIEWED_NOW_ALLOWED: dict[str, tuple[frozenset[str], str]] = {
    "topic-curator-at-30-9-13": (frozenset({"stop"}), "'hermes_topic'/'.../topic' collapsed to 'stopic'"),
    "topic-curator-ensemble": (frozenset({"stop"}), "topic collapsed with a preceding s"),
    "hermes-topic-monitor-bridge": (frozenset({"stop"}), "hermes_topic -> hermestopic"),
    "hermes-top20-external-intel": (frozenset({"stop"}), "hermes_top20 -> hermestop20"),
    "topic-ingestion": (frozenset({"stop"}), "scripts/topic -> scriptstopic"),
    "topic-research-synthesizer-at-20-x": (frozenset({"stop", "size"}), "topic + synthesizer"),
    "topic-research-synthesizer-reground": (frozenset({"stop", "size"}), "topic + synthesizer"),
    "hermes-cross-source-synthesizer": (frozenset({"size"}), "synthesizer"),
    "defense-inverse-stoplights": (frozenset({"stop"}), "stoplights is a defense indicator, not a stop"),
    "active-trader-micro-recorder": (frozenset({"order"}), "recorder; script states 'no order path'"),
    "active-trader-micro-recorder-premarket": (frozenset({"order"}), "recorder; script states 'no order path'"),
    "n8n-incident-fanin": (frozenset({"2fa"}), "workflow id 722fac0e... collapsed"),
    # crontab_backup.txt lines, keyed by script
    "topic_curator.py": (frozenset({"stop"}), "topic"),
    "hermes_topic_monitor_bridge.py": (frozenset({"stop"}), "topic"),
    "hermes_top20_external_intel.py": (frozenset({"stop"}), "top20"),
    "topic_ingestion.py": (frozenset({"stop"}), "topic"),
    "topic_research_synthesizer.py": (frozenset({"stop", "size"}), "topic + synthesizer"),
    "defense_inverse_stoplights.py": (frozenset({"stop"}), "stoplights"),
}
REVIEWED_TOKENS = frozenset({"stop", "size", "order", "2fa"})
#: Legacy tokens that drop from a row that STAYS blocked by another token (asserted per row).
INCIDENTAL_TOKEN_DROPS = {
    "guard": "holdings_gain_guardian: 'guardian' is not the guard ledger; the script name still blocks",
    "sql": "'postgresql' inside a unit name; the postgres token still blocks",
    "size": "hermes_cross_source_synthesizer on a line still blocked by llm_priority_guard",
}


def _reviewed_key(row: dict) -> str | None:
    lane = row["lane_id"]
    if lane in REVIEWED_NOW_ALLOWED:
        return lane
    # An allowlist entry (CORPUS id "allowlist:<lane_id>") of a reviewed registry lane carries the same artefact.
    if lane.startswith("allowlist:") and lane.split(":", 1)[1] in REVIEWED_NOW_ALLOWED:
        return lane.split(":", 1)[1]
    if lane.startswith("crontab-L"):
        for key in REVIEWED_NOW_ALLOWED:
            if key.endswith(".py") and f"scripts/{key}" in row["command"]:
                return key
    return None


def _legacy_blocked() -> list[dict]:
    return [r for r in CORPUS if _legacy_row_hits(r)]


def test_reviewed_list_only_names_substring_artefact_tokens():
    for key, (toks, why) in REVIEWED_NOW_ALLOWED.items():
        assert toks and toks <= REVIEWED_TOKENS, (key, toks)
        assert why


def test_the_matrix_is_the_real_corpus_and_is_not_trivially_small():
    blocked = _legacy_blocked()
    assert len(REGISTRY) > 500 and len(ALLOW["lanes"]) >= 10
    assert len(blocked) >= 100, len(blocked)         # registry + crontab lines blocked by the legacy matcher
    assert any(r["lane_id"].startswith("crontab-L") for r in blocked)


@pytest.mark.parametrize("row", _legacy_blocked(), ids=lambda r: r["lane_id"])
def test_every_legacy_blocked_lane_is_still_blocked_unless_reviewed(row):
    legacy = _legacy_row_hits(row)
    new = _new_row_hits(row)
    key = _reviewed_key(row)
    dropped = legacy - new
    if key is None:
        assert new, f"{row['lane_id']}: legacy {sorted(legacy)} blocked it, the new matcher does not"
        # Per token, not just per row: a legacy token may drop only for a reviewed incidental reason.
        assert dropped <= set(INCIDENTAL_TOKEN_DROPS), (row["lane_id"], sorted(dropped))
        if row["lane_id"] in {r["lane_id"] for r in REGISTRY}:
            assert LD.dispatch_eligible(row, exceptions={})[0] is False, row["lane_id"]
    else:
        allowed, _why = REVIEWED_NOW_ALLOWED[key]
        assert dropped, (row["lane_id"], legacy)            # the ruling is implemented, not just tolerated
        assert dropped <= allowed, (row["lane_id"], sorted(dropped))  # only the reviewed artefact token drops


def test_every_reviewed_registry_row_exists():
    lanes = {r["lane_id"] for r in REGISTRY}
    for key in REVIEWED_NOW_ALLOWED:
        if not key.endswith(".py"):
            assert key in lanes, key


def test_no_real_row_is_newly_unblocked_outside_the_reviewed_list():
    newly = sorted(r["lane_id"] for r in CORPUS
                   if _legacy_row_hits(r) and not _new_row_hits(r) and _reviewed_key(r) is None)
    assert newly == []


# ── the never list and the earlier review cases ──────────────────────────────────────────────────────

NEVER_CASES = [
    # broker / positions / stops / orders / paper
    "scripts/schwab_position_sync.py --apply", "scripts/positions_sync.py", "scripts/snaptrade_sync.py",
    "scripts/alpaca_live_read_sync.py", "scripts/moomoo_bridge.py", "scripts/ibkr_gateway.py",
    "scripts/broker_stop_reconcile.py", "scripts/unified_stop_supervisor.py", "scripts/stop_drift_alert.py",
    "scripts/place_order_worker.py", "scripts/submit_orders.py", "scripts/order_router.py",
    "scripts/cancel_stops.py", "scripts/trailing-stop-manager.py", "scripts/position_sizer.py",
    "scripts/paper_trade_executor.py", "scripts/sync_basis_from_broker.py", "scripts/atm_position_reconciler.py",
    "scripts/holding_protection_advisor.py", "scripts/holdings_gain_guardian.py",
    "scripts/options_chain_snapshot.py", "scripts/schwab_econfirm_reconcile.py",
    "scripts/schwab_transaction_ingest.py", "scripts/snaptrade_activity_ingest.py",
    # every sender
    "scripts/send_telegram.py", "scripts/digest.py --send", "scripts/email_report.py", "scripts/alert_sender.py",
    # sm-render / secrets / 2fa
    "bash scripts/sm-render.sh", "scripts/sm_render.py", "scripts/secrets_refresh.sh", "scripts/token_refresh.py",
    "scripts/two_factor_prompt.py", "scripts/totp_seed.py", "API_KEY=x scripts/foo.py", "scripts/2fa.py",
    # guard / release deploy / promote / grants
    "scripts/guard_expire.py", "bash scripts/deploy_release.sh", "bash scripts/release_ctl.sh promote",
    "scripts/release_rollback.sh", "scripts/issue_grant.py", "scripts/approve_request.py",
    # dof / sql / payment
    "scripts/dof_bid.py", "scripts/payment_run.py", "scripts/run_sql.py", "scripts/postgres_vacuum.py",
    # earlier review (#1595 blocker 2) compound cases kept blocked
    "schwab-brokers-sync", "placeorders", "liveorders", "n8n-activation-grants", "trailingstop-manager",
    "positionsync", "schwab-token-refresh", "/two_factor", "brokerstop",
    # market-day gate (exemptible only for trade-ai-scalp-live)
    "bash scripts/market_day_gate.sh $PY scripts/report.py",
]


@pytest.mark.parametrize("text", NEVER_CASES)
def test_never_categories_still_block(text):
    assert LD.forbidden_text_hits(text), text
    row = {"lane_id": "x-report", "scheduler": {"kind": "cron", "expression": "0 7 * * 1-5",
                                                 "command_text": text}}
    ok, why = LD.dispatch_eligible(row, allowlist_argv={}, exceptions={})
    assert ok is False and why.startswith("forbidden_token:"), why


def test_every_source_list_token_still_blocks_itself():
    """Each entry of every source list blocks when it appears as its own path segment."""
    for tok in (*GW.FORBIDDEN_ROUTE_TOKENS, *GW.SECRET_KEYS, *PM.FORBIDDEN_COMMAND_TOKENS,
                *LD.EXTRA_FORBIDDEN_WORDS):
        for text in (tok, f"scripts/{tok}", f"$PY scripts/x.py --{tok}", f"{tok.upper()}=1 $PY scripts/x.py"):
            assert LD.forbidden_text_hits(text), (tok, text)


# ── the ruling's false positives, now allowed ────────────────────────────────────────────────────────

ALLOWED_CASES = [
    "$PY scripts/topic_curator.py --ensemble",
    "$PY scripts/hermes_topic_monitor_bridge.py --apply --max-rows 40",
    "$PY scripts/hermes_top20_external_intel.py --top 20 --lanes grok,chatgpt --apply",
    "$PY scripts/hermes_synthesizer.py --apply",
    "$PY scripts/topic_research_synthesizer.py --reground",
    "$PY scripts/cash_redeploy_planner.py --apply",
    "$PY scripts/redeploy_cash.py",
    "$PY scripts/defense_inverse_stoplights.py --apply",
    "$PY scripts/active_trader/microstructure_recorder.py --apply",
    "n8n workflow 722fac0e043ea5c4",
]


@pytest.mark.parametrize("text", ALLOWED_CASES)
def test_ruling_false_positives_are_allowed(text):
    assert LD.forbidden_text_hits(text) == [], (text, LD.forbidden_text_hits(text))
    assert _legacy_text_hits(text), f"{text}: not a false positive of the legacy matcher"


def test_named_lanes_are_token_clean():
    for lane in ("topic-curator-ensemble", "hermes-topic-monitor-bridge", "hermes-top20-external-intel",
                 "hermes-cross-source-synthesizer", "defense-inverse-stoplights"):
        row = next(r for r in REGISTRY if r["lane_id"] == lane)
        assert LD.forbidden_hits(row) == [], (lane, LD.forbidden_hits(row))


# ── env-var / flag tokens are inspected ──────────────────────────────────────────────────────────────

def test_l323_env_submit_flag_makes_the_lane_ineligible():
    row = dict(next(r for r in REGISTRY if r["lane_id"] == "auto-proposal-general"))
    assert row["rationalization"]["f_id"] == "L323"
    row["scheduler"] = {**row["scheduler"], "command_text": L323_CRON_LINE}
    ok, why = LD.dispatch_eligible(row, allowlist_argv={}, exceptions={})
    assert ok is False and why.startswith("forbidden_token:submit@"), why


@pytest.mark.parametrize("text", [
    "MOMENTUM_SCALP_VALIDATION_SUBMIT=1 $PY scripts/report.py",
    "env PLACE_ORDER=1 $PY scripts/report.py",
    "ALPACA_LIVE=1 $PY scripts/report.py",
    "$PY scripts/report.py --submit-validation",
    "$PY scripts/report.py --mode=live-orders",
    "TRADEAI_STOP_WRITE=1 $PY scripts/report.py",
    "$PY scripts/report.py --size 100",
    "bash -c 'set -a; . ./.env; $PY scripts/report.py --send'",
])
def test_env_assignments_and_flags_are_inspected(text):
    assert LD.forbidden_text_hits(text), text


def test_executor_allowlist_argv_is_inspected_too():
    row = {"lane_id": "plain-report", "scheduler": {"kind": "cron", "expression": "0 7 * * *"}}
    assert LD.dispatch_eligible(row, allowlist_argv={"plain-report": "$PY scripts/report.py"},
                                exceptions={})[0] is True
    ok, why = LD.dispatch_eligible(row, allowlist_argv={"plain-report": "$PY scripts/report.py --submit"},
                                   exceptions={})
    assert ok is False and why == "forbidden_token:submit@allowlist.argv", why


# ── mutations: a too-loose matcher fails the matrix ──────────────────────────────────────────────────

def _escapes(monkeypatch) -> list[str]:
    """Real legacy-blocked, non-reviewed lanes the (mutated) matcher lets through."""
    return sorted(r["lane_id"] for r in _legacy_blocked()
                  if _reviewed_key(r) is None and not _new_row_hits(r))


def test_unmutated_matcher_has_no_escapes(monkeypatch):
    assert _escapes(monkeypatch) == []


def test_mutation_exact_words_only_lets_real_lanes_through(monkeypatch):
    monkeypatch.setattr(LD, "_word_forms", lambda w: frozenset({w}))
    monkeypatch.setattr(LD, "DISTINCTIVE_SUBSTRINGS", ())
    monkeypatch.setattr(LD, "_SCRIPT_SUBSTRINGS", ())
    monkeypatch.setattr(LD, "COMPOUND_PARTNERS", frozenset())
    escaped = _escapes(monkeypatch)
    assert escaped, "an exact-word-only matcher should let at least one real broker/order lane through"


def test_mutation_without_brand_substrings_misses_glued_broker_names(monkeypatch):
    texts = ("schwabbrokers", "alpacasync", "brokerstop", "ibkrgateway", "moomoobridge")
    monkeypatch.setattr(LD, "DISTINCTIVE_SUBSTRINGS", ())
    assert [t for t in texts if not LD.forbidden_text_hits(t)], "brand substrings are load-bearing"
    monkeypatch.undo()
    assert all(LD.forbidden_text_hits(t) for t in texts)


def test_mutation_without_inflections_misses_plural_and_derived_forms(monkeypatch):
    texts = ("scripts/cancel_stops.py", "scripts/stopped_names.py", "scripts/holding_protection_check.py",
             "scripts/sizing_rules.py")
    monkeypatch.setattr(LD, "_word_forms", lambda w: frozenset({w}))
    for text in texts:
        assert not LD.forbidden_text_hits(text), (text, LD.forbidden_text_hits(text))
    monkeypatch.undo()
    for text in texts:
        assert LD.forbidden_text_hits(text), text


def test_mutation_without_compounds_misses_review_compounds(monkeypatch):
    monkeypatch.setattr(LD, "COMPOUND_PARTNERS", frozenset())
    assert not LD.forbidden_text_hits("liveorders")
    assert not LD.forbidden_text_hits("trailingstop-manager")
    monkeypatch.undo()
    assert LD.forbidden_text_hits("liveorders") and LD.forbidden_text_hits("trailingstop-manager")
