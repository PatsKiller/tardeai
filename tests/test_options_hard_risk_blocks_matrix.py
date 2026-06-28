#!/usr/bin/env python3
"""Options hard-risk block fixture matrix (P1-3).

Each fixture case drives evaluate_hard_risk_blocks(mode="live") and asserts a STABLE
machine code plus severity/source/function and required snapshot keys. The block codes
are an external contract — changing one requires updating tests/fixtures. Also exports
the live matrix to docs/diligence/current/OPTIONS_RISK_BLOCK_MATRIX.md.

Runs under pytest and standalone.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
FIXTURES = ROOT / "tests" / "fixtures" / "options_risk_blocks" / "_fixtures.json"

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")
    assert cond, f"{name} {detail}"


def _load_cases():
    return json.loads(FIXTURES.read_text())["cases"]


def _run_case(case):
    import options_desk_enterprise as ent
    inp = case["input"]
    return ent.evaluate_hard_risk_blocks(
        inp["proposal"], mode="live",
        holdings=inp.get("holdings"), positions=inp.get("positions"),
    )


def test_all_fixture_cases_block_with_stable_code():
    cases = _load_cases()
    for case in cases:
        blocks = _run_case(case)
        exp = case["expect"]
        match = next((b for b in blocks if b.get("code") == exp["code"]), None)
        check(f"{case['name']}: code {exp['code']} present", match is not None,
              f"got codes={[b.get('code') for b in blocks]}")
        if match is None:
            continue
        check(f"{case['name']}: severity", match.get("severity") == exp.get("severity", "hard"))
        check(f"{case['name']}: source", match.get("source") == exp.get("source"))
        check(f"{case['name']}: function", match.get("function") == exp.get("function"))
        if exp.get("reason_contains"):
            check(f"{case['name']}: reason mentions {exp['reason_contains']}",
                  exp["reason_contains"].lower() in str(match.get("reason", "")).lower())
        for k in exp.get("snapshot_keys", []):
            check(f"{case['name']}: snapshot has {k}", k in (match.get("snapshot") or {}))


def test_matrix_covers_required_codes():
    required = {
        "earnings_blackout", "ex_dividend_cc_risk", "bs_estimate_only", "no_resolved_occ",
        "oi_below_threshold", "volume_below_threshold", "spread_too_wide", "quote_stale",
        "option_chain_stale", "market_closed", "max_contracts_per_order", "max_per_strategy_notional",
        "assignment_exercise_risk", "max_net_delta_pct", "max_symbol_notional_pct",
        "min_buying_power",
    }
    covered = {c["expect"]["code"] for c in _load_cases()}
    missing = required - covered
    check("all required hard-risk codes have a fixture", not missing, f"missing={missing}")


def test_advisory_mode_emits_no_blocks():
    import options_desk_enterprise as ent
    p = {"symbol": "TST", "strategy": "covered_call", "data_source": "bs_estimate"}
    check("advisory mode empty", len(ent.evaluate_hard_risk_blocks(p, mode="advisory")) == 0)


def _export_matrix():
    """Write the diligence matrix doc from the live fixtures + results."""
    import datetime as dt
    cases = _load_cases()
    lines = [
        "# Options Hard-Risk Block Matrix",
        "",
        f"_Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}_  ",
        "_Source: `python3 tests/test_options_hard_risk_blocks_matrix.py` over "
        "`tests/fixtures/options_risk_blocks/_fixtures.json`_",
        "",
        "Each row is a hard block enforced on the live options path by "
        "`options_desk_enterprise.evaluate_hard_risk_blocks`. Codes are a stable contract.",
        "",
        "| Block code | Severity | Source | Verified reason (sample) | Snapshot keys |",
        "|------------|----------|--------|--------------------------|---------------|",
    ]
    for case in cases:
        try:
            blocks = _run_case(case)
        except Exception:
            blocks = []
        exp = case["expect"]
        match = next((b for b in blocks if b.get("code") == exp["code"]), None)
        reason = (match or {}).get("reason", "—")
        snap_keys = ", ".join((match or {}).get("snapshot", {}).keys()) or "—"
        lines.append(f"| `{exp['code']}` | {exp.get('severity','hard')} | {exp.get('source')} | "
                     f"{str(reason)[:60]} | {snap_keys} |")
    out = ROOT / "docs" / "diligence" / "current" / "OPTIONS_RISK_BLOCK_MATRIX.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def test_export_matrix_doc():
    out = _export_matrix()
    check("matrix doc exported", out.exists() and out.stat().st_size > 200)


ALL = [
    test_all_fixture_cases_block_with_stable_code,
    test_matrix_covers_required_codes,
    test_advisory_mode_emits_no_blocks,
    test_export_matrix_doc,
]


if __name__ == "__main__":
    print("\n— options hard-risk block matrix —")
    for t in ALL:
        try:
            t()
        except AssertionError:
            pass
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)
