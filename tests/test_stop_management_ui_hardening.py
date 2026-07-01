from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "apps/command-center-v3/src/components/HoldingProtectionActions.tsx"
LEGACY_UI = ROOT / "apps/command-center-v3/src/components/PositionDecisionCard.tsx"
PORTFOLIO = ROOT / "apps/command-center-v3/src/pages/PortfolioHub.tsx"
OPEN_TRADES = ROOT / "apps/command-center-v3/src/components/OpenTradesIntelligence.tsx"
REVIEW_TS = ROOT / "apps/command-center-v3/src/lib/stopReviewTooltip.ts"
LOGIC = ROOT / "apps/command-center-v3/src/lib/stopManagement.ts"
API = ROOT / "scripts/api_v2.py"
OCO = ROOT / "scripts/schwab_oco_bracket.py"
APP = ROOT / "apps/command-center-v3/src/App.tsx"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_01_schwab_fractional_stop_blocked_and_whole_share_suggested():
    src = read(LOGIC) + read(API)
    assert "Schwab stop orders require whole shares" in src
    assert "Suggested: SELL" in src
    assert "residualQty" in src
    assert "whole_share_confirmed" in src
    assert "suggested_whole_qty" in src


def test_02_mutual_fund_money_market_controls_hidden():
    src = read(LOGIC) + read(UI) + read(API)
    assert "FCNTX" in src and "SPAXX" in src
    assert "money_market_fund" in src and "mutual_fund" in src
    assert "NOT APPLICABLE" in src
    assert "!logic.isFundLike" in src


def test_03_account_and_source_mismatch_blocks_execution():
    src = read(LOGIC) + read(API)
    assert "SOURCE MISMATCH" in src
    assert "source_broker" in src
    assert "source_mismatch" in src


def test_04_advisory_stop_is_not_rendered_as_live_and_live_stop_distinct():
    src = read(UI) + read(LOGIC)
    assert "ADVISORY ONLY — NOT PLACED" in src
    assert "LIVE BROKER STOP" in src
    assert "Broker live stop" in src
    assert "Advisor fixed stop" in src
    assert "liveStopDistancePct" in src


def test_05_active_approval_lock_owner_and_cancel_action():
    src = read(UI) + read(API) + read(ROOT / "scripts/brokers/approval_service.py")
    assert "Blocked by active approval" in src
    assert "active_approval_detail" in src
    assert "Cancel active approval" in src
    assert "protective-stop/reject-intent" in src


def test_06_stale_quote_and_missing_quote_block_live_request():
    src = read(LOGIC) + read(API)
    assert "stale_quote" in src
    assert "missing_quote" in src
    assert "Quote timestamp missing" in src
    assert "Missing current quote" in src


def test_07_trailing_start_price_mismatch_blocks_request():
    src = read(LOGIC) + read(API)
    assert "trail_start_mismatch" in src
    assert "Trailing start estimate" in src
    assert "0.35" in src


def test_08_oco_brackets_schwab_remains_off_and_ui_tests_do_not_write_brokers():
    oco = read(OCO)
    ui_test = read(Path(__file__))
    assert 'OCO_FLAG = "OCO_BRACKETS_SCHWAB"' in oco
    assert 'os.getenv(OCO_FLAG, "0")' in oco
    assert ("place_" + "order(") not in ui_test
    assert ("submit_" + "oco(") not in ui_test


def test_09_stop_action_decision_layer_and_hpe_keep_case():
    src = read(LOGIC) + read(UI)
    assert "StopActionDecision" in src
    assert "KEEP_EXISTING_STOP" in src
    assert "PLACE_NEW_STOP" in src
    assert "MODIFY_EXISTING_STOP" in src
    assert "BLOCKED_STALE_QUOTE" in src
    assert "stop_action_decision" in src
    assert "primary_operator_action" in src
    assert "secondary_operator_actions" in src
    assert "existing_stop_is_tighter_than_advisory" in src
    assert "advisory_stop_is_tighter_than_existing" in src
    assert "Keep existing $" in src
    assert "it is $" in src and "tighter than advisor stop" in src
    assert "Recommendation based on stale quote" in src


def test_10_existing_stop_not_primary_place_ticket_and_fidelity_manual_wording():
    src = read(LOGIC) + read(UI)
    assert "FIDELITY STOP RECORDED — MANUAL" in src
    assert "FIDELITY STOP VERIFIED" in src
    assert "Review Fidelity stop" in src
    assert "Create modify ticket" in src
    assert "Trade AI does not submit to Fidelity" in src
    assert "logic.liveStop != null" in src
    assert "'Review Fidelity stop'" in src and "'Create Fidelity manual ticket'" in src
    assert "liveStop != null && advisoryStop != null" in src


def test_11_stale_quote_disables_modify_place_and_floor_mismatch_flagged():
    src = read(LOGIC) + read(UI)
    assert "stale_quote" in src
    assert "liveBlocked" in src
    assert "disabled={busy || validating || liveBlocked" in src
    assert "Floor mismatch: displayed stop is inside the" in src
    assert "floor_math_consistent" in src
    assert "familyFloorPct" in src
    assert "43.93" not in src  # HPE is represented by logic, not a hardcoded symbol-specific special case.


def test_12_operator_decision_area_replaces_dense_rationale():
    src = read(UI) + read(LOGIC)
    assert "Recommendation" in src
    assert "Anchor" in src
    assert "Policy" in src
    assert "Mode" in src
    assert "Reason to act" in src
    assert "Analyst note:" in src


def test_13_internal_guard_copy_not_schwab_rejected_and_no_sample_code():
    src = read(UI) + read(LEGACY_UI)
    assert "Trade AI blocked submit before Schwab: missing evidence-bound approval. No broker order was sent." in src
    assert "approved, but Schwab rejected" not in src
    assert "placeholder=\"6-digit code\"" in src
    assert "placeholder=\"000000\"" not in src


def test_14_operator_buttons_use_2fa_and_manual_ticket_copy():
    src = read(UI) + read(LEGACY_UI) + read(LOGIC)
    assert "Request Schwab stop via 2FA" in src
    assert "Request Schwab fixed stop via 2FA" in src
    assert "Request Schwab trailing stop via 2FA" in src
    assert "Create Fidelity manual ticket" in src
    assert "Execute @ Schwab" not in src
    assert "Execute @ Fidelity" not in src


def test_15_build_marker_visible_for_deployment_verification():
    src = read(APP)
    assert "BUILD_MARKER" in src
    assert "cc-v3 stop-audit-sync 2026-07-01" in src


def test_17_click_preflight_validates_before_2fa_and_manual():
    src = read(UI)
    assert "runClickPreflight" in src
    assert "preflightAndRequest" in src
    assert "preflightAndConfirm" in src
    assert "protective-stop/refresh-quote" in src
    assert "holdings/live-stops" in src
    assert "portfolio/llm-coverage" in src
    assert "preflight-changed" in src
    assert "preflight-diff" in src
    assert "onPreflightUpdate" in src
    assert "buildPreflightDiff" in src
    assert "Validating" in src


def test_18_portfolio_hub_merges_preflight_holding_patches():
    src = read(PORTFOLIO)
    assert "holdingPatches" in src
    assert "protectionPatches" in src
    assert "mergeHolding" in src
    assert "onPreflightUpdate" in src


def test_16_live_stops_endpoint_and_review_tooltips():
    src = read(API) + read(PORTFOLIO) + read(UI) + read(LEGACY_UI) + read(OPEN_TRADES) + read(REVIEW_TS)
    assert "/api/v2/holdings/live-stops" in src
    assert "stopReviewTooltip" in src
    assert "last reviewed" in src
    assert "broker_stops_fetched_at" in src
    assert "fetched_at" in src
