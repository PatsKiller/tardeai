import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/command-center-v3"
LOGIC = APP / "src/lib/stopManagement.ts"


def compile_stop_management(tmp_path: Path) -> Path:
    out = tmp_path / "compiled"
    subprocess.run(
        [
            str(APP / "node_modules/.bin/tsc"),
            str(LOGIC),
            "--target",
            "ES2020",
            "--module",
            "commonjs",
            "--outDir",
            str(out),
            "--skipLibCheck",
        ],
        cwd=APP,
        check=True,
    )
    return out / "stopManagement.js"


def run_logic(js_path: Path, expression: str) -> dict:
    script = f"""
      const m = require({json.dumps(str(js_path))});
      const result = {expression};
      console.log(JSON.stringify(result));
    """
    p = subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)
    return json.loads(p.stdout)


def test_hpe_like_existing_stop_tighter_keeps_current_stop_and_flags_floor_mismatch(tmp_path):
    js = compile_stop_management(tmp_path)
    result = run_logic(
        js,
        """m.buildStopLogic({
          h: { symbol: 'HPE', account: 'fidelity_rollover_ira', shares: 100, current_price: 43.93, instrument_type: 'equity' },
          pr: {
            price: 43.93,
            stop_price: 42.19,
            source_broker: 'fidelity',
            source_timestamp: '2026-06-30T13:00:00Z',
            family_floor: 'position/core floor 5%',
            family_floor_pct: 5,
            anchor: '20d swing low'
          },
          confirmedStop: { stop_price: 42.59, source: 'manual' },
          trailPct: 4,
          nowMs: Date.parse('2026-06-30T15:30:00Z')
        })""",
    )
    assert result["state"] == "FIDELITY STOP RECORDED — MANUAL"
    assert result["stop_action_decision"] == "KEEP_EXISTING_STOP"
    assert result["existing_stop_is_tighter_than_advisory"] is True
    assert result["advisory_stop_is_tighter_than_existing"] is False
    assert result["stop_delta_amount"] == 0.86  # live 42.59 vs floor-reconciled advisory 41.73
    assert result["primary_operator_action"].startswith("Recommendation based on stale quote")  # 2.5h > any freshness window
    assert "Keep existing $42.59 stop" in result["primary_operator_action"]
    assert result["floor_math_consistent"] is True  # advisory widened to 5% floor at current price
    assert not any(b["code"] == "floor_mismatch" for b in result["blockers"])
    assert any(b["code"] == "stale_quote" for b in result["blockers"])
    assert result["canRequestLive"] is False


def test_advisor_tighter_than_existing_modifies_existing_stop(tmp_path):
    js = compile_stop_management(tmp_path)
    result = run_logic(
        js,
        """m.buildStopLogic({
          h: { symbol: 'HPE', account: 'fidelity_rollover_ira', shares: 100, current_price: 43.93, instrument_type: 'equity' },
          pr: {
            price: 43.93,
            stop_price: 42.75,
            source_broker: 'fidelity',
            source_timestamp: '2026-06-30T13:29:00Z',
            family_floor: 'position/core floor 2%',
            family_floor_pct: 2
          },
          confirmedStop: { stop_price: 42.25, source: 'manual' },
          nowMs: Date.parse('2026-06-30T13:30:00Z')
        })""",
    )
    assert result["stop_action_decision"] == "MODIFY_EXISTING_STOP"
    assert result["advisory_stop_is_tighter_than_existing"] is True
    assert result["primary_operator_action"] == "Advisor suggests tightening stop from $42.25 to $42.75."
    assert "Create modify ticket" in result["secondary_operator_actions"]


def test_fresh_price_timestamp_not_blocked_by_old_advisory_timestamp(tmp_path):
    js = compile_stop_management(tmp_path)
    result = run_logic(
        js,
        """m.buildStopLogic({
          h: {
            symbol: 'SCHG',
            account: 'fidelity_rollover_ira',
            shares: 2000,
            current_price: 33.54,
            instrument_type: 'equity',
            price_as_of: '2026-06-30 09:50:54 ET'
          },
          pr: {
            price: 33.54,
            stop_price: 31.79,
            source_broker: 'fidelity',
            source_timestamp: '2026-06-29T21:42:47',
            family_floor: 'position',
            family_floor_pct: 5
          },
          trailPct: 5.2,
          sourceTimestamp: '2026-06-30 09:50:54 ET',
          nowMs: Date.parse('2026-06-30T13:55:00Z')
        })""",
    )
    assert all(b["code"] != "stale_quote" for b in result["blockers"])
    assert result["canRequestLive"] is True
    assert result["stop_action_decision"] == "PLACE_NEW_STOP"
