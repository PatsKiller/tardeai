"""SCHD — fixed stop uses floor-reconciled advisory; trailing uses suggested_trail_pct."""
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/command-center-v3"
LOGIC = APP / "src/lib/stopManagement.ts"
UI = APP / "src/components/HoldingProtectionActions.tsx"


def compile_stop_management(tmp_path: Path) -> Path:
    out = tmp_path / "compiled"
    subprocess.run(
        [str(APP / "node_modules/.bin/tsc"), str(LOGIC), "--target", "ES2020",
         "--module", "commonjs", "--outDir", str(out), "--skipLibCheck"],
        cwd=APP, check=True,
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


def test_schd_floor_reconciled_fixed_stop_matches_ui(tmp_path):
    """Raw API stop $31.12 widens to 4% income floor ≈ $31.09 at current $32.38."""
    js = compile_stop_management(tmp_path)
    result = run_logic(
        js,
        """m.buildStopLogic({
          h: { symbol: 'SCHD', account: 'schwab_rollover_ira', shares: 4155.2508,
               current_price: 32.38, instrument_type: 'equity',
               source_timestamp: '2026-07-12 13:30:08 ET' },
          pr: {
            price: 32.38,
            stop_price: 31.12,
            stop_distance_pct: 3.95,
            suggested_trail_pct: 4.0,
            trail_matches_stop: true,
            source_broker: 'schwab',
            family_floor_pct: 4.0,
            family_floor: 'income floor 4.0%',
            source_timestamp: '2026-07-08T13:02:00',
          },
          confirmedStop: { order_id: '1007030985719', pilot_placed: true, trail_offset: 5.8,
                           order_type: 'TRAILING_STOP', source: 'broker' },
          trailPct: 4,
          orderKind: 'STOP',
          wholeShareConfirmed: true,
          sourceTimestamp: '2026-07-12 13:30:08 ET',
          nowMs: Date.parse('2026-07-12T17:50:00-04:00'),
        })""",
    )
    assert result["advisoryStop"] in (31.08, 31.09)  # 4% income floor at $32.38
    assert result["stop_action_decision"] == "MODIFY_EXISTING_STOP"


def test_schd_trailing_uses_suggested_trail_pct(tmp_path):
    js = compile_stop_management(tmp_path)
    result = run_logic(
        js,
        """m.buildStopLogic({
          h: { symbol: 'SCHD', account: 'schwab_rollover_ira', shares: 4155.2508,
               current_price: 32.38, instrument_type: 'equity',
               source_timestamp: '2026-07-12 13:30:08 ET' },
          pr: {
            price: 32.38,
            stop_price: 31.12,
            stop_distance_pct: 3.95,
            suggested_trail_pct: 4.0,
            trail_matches_stop: true,
            source_broker: 'schwab',
            family_floor_pct: 4.0,
          },
          confirmedStop: { order_id: '1007030985719', pilot_placed: true, trail_offset: 5.8,
                           order_type: 'TRAILING_STOP', source: 'broker' },
          trailPct: 4,
          orderKind: 'TRAILING',
          wholeShareConfirmed: true,
          sourceTimestamp: '2026-07-12 13:30:08 ET',
          nowMs: Date.parse('2026-07-12T17:50:00-04:00'),
        })""",
    )
    assert result["advisoryStop"] in (31.08, 31.09)
    assert not any(b["code"] == "trail_start_mismatch" for b in result["blockers"])


def test_ui_submits_floor_reconciled_advisory_not_raw_stop():
    src = UI.read_text(encoding="utf-8")
    assert "advisedForKind" in src
    assert "advised.advisoryStop" in src
    assert "advised.trailPct" in src
    assert "orderPreviewLine('STOP')" in src
    assert "orderPreviewLine('TRAILING')" in src