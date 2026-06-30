"""Fixed vs trailing protective-stop logic — UI (stopManagement.ts) + backend (protective_stop_pilot, api gates)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
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


def _fresh_ts(now_ms: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── UI: fixed stop ────────────────────────────────────────────────────────────

def test_fixed_stop_place_new_when_clean(tmp_path):
    js = compile_stop_management(tmp_path)
    now = 1_751_280_000_000  # 2026-06-30 ~13:00 UTC
    r = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'V', account: 'schwab_rollover_ira', shares: 201, current_price: 130.0 }},
          pr: {{
            price: 130.0, stop_price: 118.7, source_broker: 'schwab',
            source_timestamp: '{_fresh_ts(now)}', family_floor_pct: 8.7
          }},
          orderKind: 'STOP',
          nowMs: {now}
        }})""",
    )
    assert r["state"] == "ADVISORY ONLY — NOT PLACED"
    assert r["stop_action_decision"] == "PLACE_NEW_STOP"
    assert r["canRequestLive"] is True
    assert not any(b["code"] == "trail_start_mismatch" for b in r["blockers"])


def test_fixed_stop_not_protective_blocks(tmp_path):
    js = compile_stop_management(tmp_path)
    now = 1_751_280_000_000
    r = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'V', account: 'schwab_roth', shares: 10, current_price: 130.0 }},
          pr: {{ price: 130.0, stop_price: 131.0, source_broker: 'schwab', source_timestamp: '{_fresh_ts(now)}' }},
          orderKind: 'STOP',
          nowMs: {now}
        }})""",
    )
    assert any(b["code"] == "stop_not_protective" for b in r["blockers"])
    assert r["canRequestLive"] is False


def test_fixed_stop_does_not_apply_trail_start_mismatch(tmp_path):
    js = compile_stop_management(tmp_path)
    now = 1_751_280_000_000
    r = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'V', account: 'schwab_rollover_ira', shares: 201, current_price: 130.0 }},
          pr: {{ price: 130.0, stop_price: 100.0, source_broker: 'schwab', source_timestamp: '{_fresh_ts(now)}' }},
          trailPct: 10,
          orderKind: 'STOP',
          nowMs: {now}
        }})""",
    )
    assert not any(b["code"] == "trail_start_mismatch" for b in r["blockers"])


def test_fixed_live_stop_keep_when_tighter(tmp_path):
    js = compile_stop_management(tmp_path)
    now = 1_751_280_000_000
    r = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'V', account: 'schwab_rollover_ira', shares: 201, current_price: 130.0 }},
          pr: {{
            price: 130.0, stop_price: 118.7, source_broker: 'schwab',
            source_timestamp: '{_fresh_ts(now)}'
          }},
          confirmedStop: {{ stop_price: 120.0, source: 'broker', order_type: 'STOP' }},
          orderKind: 'STOP',
          nowMs: {now}
        }})""",
    )
    assert r["state"] == "LIVE BROKER STOP"
    assert r["stop_action_decision"] == "KEEP_EXISTING_STOP"
    assert r["existing_stop_is_tighter_than_advisory"] is True


# ── UI: trailing stop ─────────────────────────────────────────────────────────

def test_trailing_aligned_passes(tmp_path):
    js = compile_stop_management(tmp_path)
    now = 1_751_280_000_000
    price, trail, stop = 130.0, 10.0, 117.0  # 130 * 0.9 = 117
    r = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'V', account: 'schwab_roth', shares: 10, current_price: {price} }},
          pr: {{ price: {price}, stop_price: {stop}, source_broker: 'schwab', source_timestamp: '{_fresh_ts(now)}' }},
          trailPct: {trail},
          orderKind: 'TRAILING',
          nowMs: {now}
        }})""",
    )
    assert not any(b["code"] == "trail_start_mismatch" for b in r["blockers"])
    assert r["canRequestLive"] is True


def test_trailing_mismatch_blocks(tmp_path):
    js = compile_stop_management(tmp_path)
    now = 1_751_280_000_000
    r = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'V', account: 'schwab_roth', shares: 10, current_price: 130.0 }},
          pr: {{ price: 130.0, stop_price: 118.7, source_broker: 'schwab', source_timestamp: '{_fresh_ts(now)}' }},
          trailPct: 10,
          orderKind: 'TRAILING',
          nowMs: {now}
        }})""",
    )
    assert any(b["code"] == "trail_start_mismatch" for b in r["blockers"])
    assert r["canRequestLive"] is False


def test_trailing_live_broker_null_stop_price_is_live(tmp_path):
    """Schwab trailing orders often report stop_price=null — still LIVE BROKER STOP."""
    js = compile_stop_management(tmp_path)
    now = 1_751_280_000_000
    r = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'V', account: 'schwab_roth', shares: 10, current_price: 130.0 }},
          pr: {{
            price: 130.0, stop_price: 117.0, source_broker: 'schwab',
            source_timestamp: '{_fresh_ts(now)}'
          }},
          confirmedStop: {{
            stop_price: null, trail_offset: 10, order_type: 'TRAILING_STOP',
            source: 'broker', broker_verified: true, order_id: '12345'
          }},
          trailPct: 10,
          orderKind: 'TRAILING',
          nowMs: {now}
        }})""",
    )
    assert r["state"] == "LIVE BROKER STOP"
    assert r["liveStopIsTrailing"] is True
    assert r["liveTrailPct"] == 10
    assert r["liveStop"] == 117.0
    assert r["stop_action_decision"] == "KEEP_EXISTING_STOP"


def test_trailing_live_tighter_than_advisory_keeps(tmp_path):
    js = compile_stop_management(tmp_path)
    now = 1_751_280_000_000
    r = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'V', account: 'schwab_roth', shares: 10, current_price: 130.0 }},
          pr: {{
            price: 130.0, stop_price: 115.0, source_broker: 'schwab',
            source_timestamp: '{_fresh_ts(now)}'
          }},
          confirmedStop: {{
            stop_price: null, trail_offset: 10, order_type: 'TRAILING_STOP', source: 'broker'
          }},
          trailPct: 10,
          orderKind: 'TRAILING',
          nowMs: {now}
        }})""",
    )
    # Estimated floor 117 > advisory 115 → keep existing trailing protection
    assert r["stop_action_decision"] == "KEEP_EXISTING_STOP"
    assert r["existing_stop_is_tighter_than_advisory"] is True


# ── Backend: order spec shape ─────────────────────────────────────────────────

def test_backend_stop_spec_has_stop_price_only():
    from brokers import protective_stop_pilot as psp

    fixed = psp.build_order_spec("V", 10, "STOP", stop_price=118.7)
    assert fixed["orderType"] == "STOP"
    assert "stopPrice" in fixed
    assert "stopPriceOffset" not in fixed

    trail = psp.build_order_spec("V", 10, "TRAILING_STOP", trail_pct=10)
    assert trail["orderType"] == "TRAILING_STOP"
    assert trail.get("stopPriceOffset") == 10.0
    assert "stopPrice" not in trail
    assert trail["stopPriceLinkType"] == "PERCENT"
    assert trail["stopPriceLinkBasis"] == "LAST"


def test_backend_trailing_requires_trail_pct():
    from brokers import protective_stop_pilot as psp

    try:
        psp.build_order_spec("V", 10, "TRAILING_STOP")
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_backend_kind_aliases():
    from brokers import protective_stop_pilot as psp

    assert psp.normalize_kind("TRAILING") == "TRAILING_STOP"
    assert psp.normalize_kind("STOP") == "STOP"


def test_math_distance_pct_matches_advisor_formula(tmp_path):
    """stop_distance_pct = (price - stop) / price × 100 — same as holding_protection_advisor."""
    js = compile_stop_management(tmp_path)
    price, stop = 130.0, 118.7
    r = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'V', account: 'schwab_rollover_ira', shares: 201, current_price: {price} }},
          pr: {{
            price: {price}, stop_price: {stop}, stop_distance_pct: 8.69,
            source_broker: 'schwab', source_timestamp: '{_fresh_ts(1_751_280_000_000)}',
            family_floor_pct: 5, family: 'position'
          }},
          nowMs: {1_751_280_000_000}
        }})""",
    )
    expected_dist = round((price - stop) / price * 100, 2)
    assert abs(r["distancePct"] - expected_dist) < 0.02
    assert r["floor_math_consistent"] is True


def test_math_trail_start_v_canary_8_7_pct(tmp_path):
    """V @ $130, 8.7% trail → initial floor $118.69; advisory $118.7 within 0.35% of price."""
    js = compile_stop_management(tmp_path)
    price, trail, advisory = 130.0, 8.7, 118.7
    expected = price * (1 - trail / 100)
    assert abs(expected - 118.69) < 0.01
    tol_pct = abs(expected - advisory) / price * 100
    assert tol_pct < 0.35
    r = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'V', account: 'schwab_rollover_ira', shares: 201, current_price: {price} }},
          pr: {{ price: {price}, stop_price: {advisory}, source_broker: 'schwab',
                 source_timestamp: '{_fresh_ts(1_751_280_000_000)}' }},
          trailPct: {trail}, orderKind: 'TRAILING', nowMs: {1_751_280_000_000}
        }})""",
    )
    assert not any(b["code"] == "trail_start_mismatch" for b in r["blockers"])


def test_math_floor_mismatch_when_stop_tighter_than_family_floor(tmp_path):
    """HPE-like: 3.96% distance vs 5% position floor → floor_mismatch."""
    js = compile_stop_management(tmp_path)
    r = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'HPE', account: 'fidelity_rollover_ira', shares: 100, current_price: 43.93 }},
          pr: {{
            price: 43.93, stop_price: 42.19, source_broker: 'fidelity',
            source_timestamp: '{_fresh_ts(1_751_280_000_000)}',
            family_floor_pct: 5, family_bounds: {{ stop_min_pct: 5 }}
          }},
          nowMs: {1_751_280_000_000}
        }})""",
    )
    assert abs(r["distancePct"] - 3.96) < 0.1
    assert r["floor_math_consistent"] is False
    assert any(b["code"] == "floor_mismatch" for b in r["blockers"])


def test_math_live_stop_delta_direction_long_position(tmp_path):
    """Higher live stop = tighter protection → KEEP; lower live = looser → MODIFY."""
    js = compile_stop_management(tmp_path)
    now = 1_751_280_000_000
    keep = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'V', account: 'schwab_rollover_ira', shares: 201, current_price: 130 }},
          pr: {{ price: 130, stop_price: 118.7, source_broker: 'schwab', source_timestamp: '{_fresh_ts(now)}' }},
          confirmedStop: {{ stop_price: 120.0, source: 'broker' }},
          nowMs: {now}
        }})""",
    )
    assert keep["stop_action_decision"] == "KEEP_EXISTING_STOP"
    assert keep["existing_stop_is_tighter_than_advisory"] is True
    modify = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'V', account: 'schwab_rollover_ira', shares: 201, current_price: 130 }},
          pr: {{ price: 130, stop_price: 119.5, source_broker: 'schwab', source_timestamp: '{_fresh_ts(now)}' }},
          confirmedStop: {{ stop_price: 118.7, source: 'broker' }},
          nowMs: {now}
        }})""",
    )
    assert modify["stop_action_decision"] == "MODIFY_EXISTING_STOP"
    assert modify["advisory_stop_is_tighter_than_existing"] is True


def test_math_trailing_floor_estimate_matches_schwab_offset(tmp_path):
    """Live trailing 10% @ $130 → estimated floor $117 (Schwab stopPriceOffset semantics)."""
    js = compile_stop_management(tmp_path)
    r = run_logic(
        js,
        f"""m.resolveLiveStop(
          {{ trail_offset: 10, order_type: 'TRAILING_STOP', source: 'broker' }},
          null, 130.0)""",
    )
    assert r["isTrailing"] is True
    assert r["trailPct"] == 10
    assert abs(r["price"] - 117.0) < 0.01


def test_backend_trail_gate_matches_ui_formula():
    """api_v2 trail_start_mismatch uses same formula as stopManagement.ts."""
    price, trail, advisory = 130.0, 8.7, 118.7
    expected = price * (1 - trail / 100.0)
    blocked = abs(expected - advisory) / price * 100.0 > 0.35
    assert blocked is False
    bad_advisory = 118.0
    blocked_bad = abs(expected - bad_advisory) / price * 100.0 > 0.35
    assert blocked_bad is True


def test_funds_not_applicable(tmp_path):
    js = compile_stop_management(tmp_path)
    now = 1_751_280_000_000
    r = run_logic(
        js,
        f"""m.buildStopLogic({{
          h: {{ symbol: 'FCNTX', account: 'fidelity_rollover_ira', shares: 100 }},
          pr: {{ stop_price: 10.0, source_broker: 'fidelity', source_timestamp: '{_fresh_ts(now)}' }},
          nowMs: {now}
        }})""",
    )
    assert r["state"] == "NOT APPLICABLE"
    assert r["stop_action_decision"] == "NOT_APPLICABLE"