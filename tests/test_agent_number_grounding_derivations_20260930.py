"""Grounding checker derivations (2026-09-30).

Measured on the served release 7cfa0ea85: the 7-day soft-unsupported share was 0.185 (251/1,358),
and every one of 20 sampled flagged tokens was either arithmetic the agent derived from the prompt
or a checker extraction bug; none was invented. These fixtures are shaped on those rows (APA, MCK,
SNDK, BE, the tax/steph `$45,600/yr` and the momentum-scalp `float_m < 0.5`). The guard tests
prove an invented figure is still flagged and the demotion bar is unchanged."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import agent_number_grounding as ang  # noqa: E402

RISK_PROMPT = """Symbol: SNDK
Position: NOT CURRENTLY HELD (0 shares in any account).
RSI: 71.2, Beta: 1.9, Sector: Technology, Industry: Computer Hardware
PE: 41.2, Forward PE: 22.0, ATR: 108.17
Allowed ATR multiples: ATR×1=108.2, ATR×2=216.3, ATR×0.85=91.94, ATR×0.95=102.8 (precomputed for stop distance checks).
Strategy: breakout, Support: $1361.92, Resistance: $1810.00
Stop: $1361.92, Target: $2100.00, R:R: 1.9
Recent prices: $1702.11, $1688.40, $1650.00, $1611.20, $1590.75
SCAN INTEL: momentum leader; current price $1740.23 on volume 2.1x average.
RISK RULES:
- Stop placement: new position = entry - (2 × ATR). Min 5%, max 15% distance.
"""


def _verdict(answer: str, prompt: str = RISK_PROMPT) -> dict:
    return ang.check_grounding([answer], prompt)


def test_rate_units_after_a_slash_are_read_whole():
    vals = [n["value"] for n in ang.extract_numbers("SSDI income: $45,600/yr and $1.20/sh dividend")]
    assert 45600.0 in vals and 1.2 in vals
    # a fraction or a date is still not a quantity
    assert not [n for n in ang.extract_numbers("split 1/2 on 9/30") if n["value"] in (1.0, 9.0)]


def test_tax_and_income_constants_quoted_by_the_agent_are_supported():
    prompt = ("- SSDI income: $45,600/yr — counts toward MAGI\n"
              "- IRMAA threshold (MFS): $103,000 — NEVER breach\n"
              "- 22% bracket ceiling: $94,300 (MFS)\n"
              "- Portfolio income target: $55,000/yr from investments\n")
    r = _verdict("SSDI of $45,600 plus the $55,000 target; headroom to IRMAA is $8,700 above the $94,300 ceiling.", prompt)
    assert r["verdict"] == "grounded", r


def test_unit_named_prompt_constants_in_the_agents_unit():
    r = _verdict("Float is under 0.5M, well inside the 1.0M ceiling.", "filters: float_m < 0.5; relaxed float_m < 1.0\n")
    assert r["verdict"] == "grounded", r


def test_labelled_current_price_derivations_are_supported():
    # 1740.23 − 2×108.17 = 1523.89; 216.34/1740.23 = 12.4%; (1740.23 − 1361.92)/1740.23 = 21.7%
    r = _verdict("Stop at $1523.89 (2×ATR, a 12.4% distance); the card stop $1361.92 is 21.7% below $1740.23.")
    assert r["verdict"] == "grounded", r


def test_stop_rule_percent_levels_and_atr_units():
    prompt = ("Symbol: MCK\nATR: 1.52\nStop: $39.63, Target: $48.00\nRecent prices: $41.90, $41.10\n"
              "Quote: current price $42.73\n- Stop placement: Min 5%, max 15% distance.\n")
    # 0.95 × 42.73 = 40.59 (5% minimum stop); (42.73 − 39.63)/1.52 = 2.04 ATR
    r = _verdict("The 5% minimum stop is $40.59; the card stop sits 2.04 ATR below price.", prompt)
    assert r["verdict"] == "grounded", r


def test_an_invented_figure_is_still_flagged():
    r = _verdict("Stop at $1523.89, but fair value is $2,977.45 and VaR is 3.71%.")
    assert "$2,977.45" in r["unsupported"] and "3.71%" in r["unsupported"], r
    assert r["verdict"] in ("soft_unsupported", "ungrounded")


def test_the_demotion_bar_is_unchanged():
    r = _verdict("Fair value $2,977.45, VaR 3.71%, beta-adjusted size $18,114.")
    assert r["verdict"] == "ungrounded" and r["thresholds"] == {"min_unsupported": 2, "max_share": 0.2}, r


def test_labelled_anchors_are_capped():
    prompt = "".join(f"current price ${100 + i}.00\n" for i in range(10)) + "Stop: $90.00\n"
    direct, _derived = ang.supplied_values(prompt)
    # the first two labelled prices are anchors (their distance to the stop is derivable); the rest are only direct values
    assert ang._within(_derived, 11.0, 1e-6) and not ang._within(_derived, 19.0, 1e-6)


# ── offline re-check: the supplied text is stored with the verdict ──────────────────────────

def test_supplied_text_round_trips_and_rescore_counts_before_after(monkeypatch):
    import json
    sys.path.insert(0, str(ROOT / "scripts"))
    import report_agent_number_grounding as rep
    parsed = {"summary": "Stop at $1523.89 (2×ATR, a 12.4% distance).", "full_narrative": "", "next_action": "", "evidence": []}
    _out, report = ang.apply_number_grounding(parsed, RISK_PROMPT, mode_override="record")
    assert ang.supplied_text_from_record(report) == RISK_PROMPT and len(report["supplied_sha256"]) == 64
    stale = dict(report, verdict="soft_unsupported")      # as the old checker would have stored it
    legacy = {"verdict": "soft_unsupported", "unsupported": ["$1523.89"]}   # pre-2026-09-30 row, hash only
    rows = [("risk_agent", json.dumps({**parsed, "number_grounding": stale})),
            ("risk_agent", json.dumps({**parsed, "number_grounding": legacy}))]
    out = rep.rescore(rows)
    assert out["rescored"] == 1 and out["not_rescorable"] == 1
    assert out["agents"]["risk_agent"] == {"before": {"soft_unsupported": 1}, "after": {"grounded": 1}}


def test_store_cap_zero_keeps_only_the_hash(monkeypatch):
    monkeypatch.setenv(ang.SUPPLIED_STORE_MAX_CHARS_ENV, "0")
    rec = ang.supplied_record(RISK_PROMPT)
    assert "supplied_z" not in rec and len(rec["supplied_sha256"]) == 64
