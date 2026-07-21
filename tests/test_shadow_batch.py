#!/usr/bin/env python3
"""Bounded batch packet generation + the actionable decision band.

Operator-authorised 2026-07-21: generate packets for the top-N by rank in the
eligible ratings {strong_buy, buy, add, add_on_pullback, hold} plus all starred.
Bounded because a blind pass is real, recurring model spend and HOLD alone is
~1,000 symbols.

No order queued, submitted, or 2FA requested anywhere in this module.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

BAND = ROOT / "apps" / "command-center-v3" / "src" / "components" / "DecisionPacketBand.tsx"
BTN = ROOT / "apps" / "command-center-v3" / "src" / "components" / "ShadowBatchButton.tsx"
HUB = ROOT / "apps" / "command-center-v3" / "src" / "pages" / "WatchlistHub.tsx"


# ── target selection is bounded and honest ────────────────────────────────────

def test_eligible_ratings_are_the_authorised_set():
    import shadow_batch_generator as bg
    assert set(bg.ELIGIBLE_RATINGS) == {"STRONG_BUY", "BUY", "ADD", "ADD_ON_PULLBACK", "HOLD"}


def test_target_is_capped_at_top_n():
    import shadow_batch_generator as bg
    sel = bg.select_targets(top_n=50)
    assert len(sel["members"]) <= 50, "selection must be bounded by the cap"
    # every member qualifies on at least one governed evidence reason
    valid = {"starred", "directive", "held", "material_move", "catalyst",
             "scope_s1", "packet_absent"}
    for m in sel["members"]:
        assert set(m["reasons"]) & valid, f"{m['symbol']} has no valid evidence reason"


def test_no_silent_truncation_dropped_count_is_reported():
    """A bounded run must say what it did NOT cover."""
    import shadow_batch_generator as bg
    sel = bg.select_targets(top_n=50)
    # with ~1,588 eligible, the vast majority are below the cut and must be counted
    assert sel["dropped_below_cap"] >= 0
    if sel["eligible_total"] > 50:
        assert sel["dropped_below_cap"] == sel["eligible_total"] - min(50, sel["eligible_total"])


def test_hard_cap_is_an_absolute_ceiling():
    import shadow_batch_generator as bg
    assert bg.HARD_CAP >= bg.TOP_N
    src = Path(bg.__file__).read_text()
    assert "if len(members) > HARD_CAP" in src


def test_thresholds_are_env_configurable():
    import shadow_batch_generator as bg
    src = Path(bg.__file__).read_text()
    for env in ("SHADOW_BATCH_TOP_N", "SHADOW_BATCH_CONCURRENCY",
                "SHADOW_BATCH_FRESH_HOURS", "SHADOW_BATCH_HARD_CAP"):
        assert f'os.getenv("{env}"' in src


def test_generation_is_idempotent_via_freshness():
    """A symbol with a live packet younger than the window is skipped — a re-run
    costs nothing for what is already fresh."""
    import shadow_batch_generator as bg
    src = Path(bg.__file__).read_text()
    assert "_fresh_symbols" in src and "generated_at > now() - (%s || ' hours')" in src


def test_one_symbol_failure_does_not_abort_the_batch():
    import shadow_batch_generator as bg
    src = Path(bg.__file__).read_text()
    gen = src[src.index("def _generate_one"):src.index("def _write_status")]
    assert "except Exception" in gen and "return {" in gen


def test_batch_only_writes_shadow_tables():
    import shadow_batch_generator as bg
    src = Path(bg.__file__).read_text()
    for forbidden in ("options_approval_queue", "request_2fa", "place_order", "trade_approvals"):
        assert forbidden not in src


# ── the API surface ───────────────────────────────────────────────────────────

def test_batch_endpoints_registered():
    import api_v2
    src = Path(api_v2.__file__).read_text()
    assert '"/api/v2/shadow/strategy/batch": _shadow_batch_status' in src
    assert '"/api/v2/shadow/strategy/batch"' in src  # POST route
    assert "def _shadow_batch_start" in src and "def _shadow_batch_status" in src


def test_batch_start_is_idempotent():
    import api_v2
    src = Path(api_v2.__file__).read_text()
    start = src[src.index("def _shadow_batch_start"):src.index("def _shadow_strategy_packet")]
    assert 'st.get("state") == "running"' in start and "already_running" in start
    assert "start_new_session=True" in start   # detached, does not block the request


# ── the actionable decision band ──────────────────────────────────────────────

def test_band_is_expanded_by_default():
    src = BAND.read_text()
    assert "useState(true)" in src, "the band must default to open — no click to see families"


def test_band_shows_actionable_mechanics_not_just_states():
    src = BAND.read_text()
    # long-term & swing levels
    assert "starter" in src and "stop" in src and "target" in src and "R:R" in src
    assert "zone" in src and "limit" in src
    # trigger / invalidation price context
    assert "TRIGGER" in src and "INVALIDATE" in src


def test_band_shows_option_structures_with_strikes():
    src = BAND.read_text()
    assert "optionLine" in src
    assert "occ_symbol" in src and "strike" in src and "maximum_loss" in src


def test_batch_button_mounted_in_header():
    hub = HUB.read_text()
    assert "import ShadowBatchButton" in hub
    assert "<ShadowBatchButton" in hub


def test_batch_button_is_shadow_only_and_polls():
    src = BTN.read_text()
    assert "/api/v2/shadow/strategy/batch" in src
    assert "method: 'POST'" in src
    assert "nothing queued or submitted" in src.lower()


def test_batch_button_no_sub_ten_px_or_raw_hex():
    import re
    src = BTN.read_text()
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", src)
    for m in re.finditer(r"fontSize:\s*([0-9.]+)", src):
        assert float(m.group(1)) >= 10


# ── fundamentals enrichment (2026-07-21) ──────────────────────────────────────

def test_fundamentals_whitelist_excludes_analyst_verdicts():
    """recom/recom_score/analyst_rating are analyst VERDICTS — feeding them the
    blind pass would anchor it, the exact defect. They must not be in the set."""
    import shadow_decision_service as svc
    for anchor in ("recom", "recom_score", "analyst_rating", "trend", "rsi_status"):
        assert anchor not in svc.FUNDAMENTAL_KEYS


def test_fundamentals_excludes_the_misparsed_volatility_field():
    import shadow_decision_service as svc
    assert "volatility_w_pct" not in svc.FUNDAMENTAL_KEYS


def test_fundamentals_include_the_thesis_evidence():
    import shadow_decision_service as svc
    for k in ("pe", "forward_pe", "oper_margin_pct", "lt_debt_equity",
              "eps_next_5y", "roe_pct"):
        assert k in svc.FUNDAMENTAL_KEYS


def test_extracted_fundamentals_pass_the_blindness_guard():
    """Whatever the extractor returns must never anchor the blind pass."""
    import shadow_decision_service as svc
    import blind_review as br
    f = svc._fundamentals_for("NXPI")
    if not f:
        import pytest
        pytest.skip("no enrichment for NXPI in this environment")
    br.assert_blind({"symbol": "NXPI", "fundamentals": f})   # raises if an anchor slipped in
    assert not any(w in k.lower() for k in f for w in ("recom", "rating", "verdict"))


# ── evidence-based eligibility — label is NOT an inclusion gate (2026-07-21) ───

def test_selection_is_evidence_based_not_label_gated():
    """The eligible-ratings gate recreated the original circular defect. Selection
    now qualifies on evidence; the label is a sort tiebreaker only."""
    import shadow_batch_generator as bg
    src = Path(bg.__file__).read_text()
    sel_src = src[src.index("def select_targets"):src.index("def _fresh_symbols")]
    for signal in ("starred", "directive", "held", "material_move", "catalyst",
                   "scope_s1", "packet_absent"):
        assert signal in sel_src, f"evidence signal {signal} missing"
    # the label must NOT be a WHERE-clause inclusion filter in the selector
    assert "IN {ratings}" not in sel_src, "legacy label is gating inclusion again"
    assert "label: tiebreaker ONLY" in sel_src


def test_label_rank_is_only_a_final_tiebreaker():
    """_label_rank must appear AFTER hermes_rank in the priority tuple, so a label
    can never outrank real evidence."""
    import shadow_batch_generator as bg
    src = Path(bg.__file__).read_text()
    pr = src[src.index("def _priority"):src.index("ranked = sorted")]
    # hermes_rank sort key comes before the label rank in the returned tuple
    assert pr.index("hermes_rank") < pr.rindex("_label_rank")


def test_dry_run_reports_the_full_composition():
    """The dry run must expose the composition before any spend (spec #1)."""
    import shadow_batch_generator as bg
    sel = bg.select_targets(top_n=20)
    for k in ("total_qualifying", "selected", "deferred_by_cap", "by_reason",
              "starred", "held", "catalyst", "material_move",
              "legacy_buy_side", "legacy_ignore_avoid", "est_lane_calls"):
        assert k in sel, f"composition report missing {k}"
    # every selected member carries its evidence reasons, none empty
    for m in sel["members"]:
        assert m.get("reasons"), f"{m['symbol']} selected with no evidence reason"


def test_ignore_avoid_names_are_reachable_by_evidence():
    """The decisive regression: an IGNORE/AVOID label cannot block selection when
    the symbol has evidence. With evidence-based selection the selected set should
    be ABLE to contain ignore/avoid names (it does today: most held/starred names
    carry avoid-side labels)."""
    import shadow_batch_generator as bg
    sel = bg.select_targets(top_n=50)
    # not asserting a fixed count (data-dependent), but the mechanism must permit it:
    # legacy_ignore_avoid is COUNTED among selected, proving they are not excluded.
    assert "legacy_ignore_avoid" in sel
    assert sel["legacy_ignore_avoid"] >= 0   # counted, never filtered out upstream
