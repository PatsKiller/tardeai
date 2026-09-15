"""2026-09-15: the watchlist bridge must not create proposals the enrichment loop expires on arrival."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _bridge():
    spec = importlib.util.spec_from_file_location("wl_bridge_t", ROOT / "scripts" / "watchlist_proposal_bridge.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_entry_far_from_live_would_expire():
    b = _bridge()
    assert b.entry_would_expire(6.55, 7.82) is True        # LNSR 09-14: +19.4 %
    assert b.entry_would_expire(195.5, 240.0) is True


def test_entry_close_to_live_is_kept():
    b = _bridge()
    assert b.entry_would_expire(22.3, 24.13) is False       # PMTS: +8.2 %
    assert b.entry_would_expire(100.0, 115.0) is False      # exactly 15 % is not past the line


def test_missing_live_price_is_not_evidence_of_drift():
    b = _bridge()
    assert b.entry_would_expire(10.0, None) is False
    assert b.entry_would_expire(None, 10.0) is False
    assert b.entry_would_expire("bad", 10.0) is False


def test_threshold_matches_enrichment_loop_expiry_rule():
    b = _bridge()
    loop_src = (ROOT / "scripts" / "proposal_enrichment_loop.py").read_text(encoding="utf-8")
    assert "abs(drift_pct) > 15" in loop_src
    assert b.ENRICHMENT_EXPIRY_DRIFT_PCT == 15.0


def test_sync_applies_guard_before_creating_or_refreshing():
    src = (ROOT / "scripts" / "watchlist_proposal_bridge.py").read_text(encoding="utf-8")
    i_guard = src.index("entry_would_expire(levels[0], live_px)")
    i_derive = src.index("levels = _derive_levels(c, quote_cache)")
    i_reject = src.index("if not levels:")
    assert i_derive < i_guard < i_reject
