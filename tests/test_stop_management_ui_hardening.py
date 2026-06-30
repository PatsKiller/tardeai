from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "apps/command-center-v3/src/components/HoldingProtectionActions.tsx"
LOGIC = ROOT / "apps/command-center-v3/src/lib/stopManagement.ts"
API = ROOT / "scripts/api_v2.py"
OCO = ROOT / "scripts/schwab_oco_bracket.py"


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
    assert "Suggested fixed stop" in src
    assert "Broker live stop</span><br /><b" in src


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
