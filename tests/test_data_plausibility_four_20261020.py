"""Four data_plausibility_monitor BLOCKs of 2026-10-20: the writer defects still live after the 2026-10-18 fixes.

Measured 2026-10-20 (read-only SQL, last 30 days):
  trade_ai_scans.catalyst_confidence single_scale -- 195 rows > 1, every one exactly 1.1 or 1.2 (never 85-style),
      newest RTX 2026-10-20 11:09 ET, i.e. AFTER the scoring.py clamp was served (release 720fce06c, 08:56 ET).
      The second producer is scalp_critic_agent.validate_catalyst: ticker 0.6 + company up to 0.6 = 1.2, unclamped.
  symbol_profiles.ytd_return_pct finite -- 11 NaN rows, all perf_updated_at 2026-08-29 07:15 (one run, before the
      2026-09-13 central finite check). They persist because etf_performance_enrich takes the first SYMBOL_CAP=300 of
      434 targets ORDER BY symbol, so the L..N tail (NBIZ, NVD, NLR, ...) is never revisited.
  indicator_confluence_cache.stop_price min -- the engine floor (2026-10-18) is right, but the batch API upsert's
      conflict branch never refreshed stop_price, so a stale negative stop survives a recompute.

Hermetic: no database, network, broker or model; sqlite and source text only.

COVERS = ["scripts/scalp_critic_agent.py", "scripts/etf_performance_enrich.py", "scripts/api_v2.py"]
"""
from __future__ import annotations

import ast
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# -- 1. trade_ai_scans.catalyst_confidence: the scalp critic producer -------------------------------------------

def test_scalp_critic_catalyst_confidence_never_exceeds_one():
    import scalp_critic_agent as sca

    # Production row EXYN 2026-10-19 17:38 stored 1.2: ticker 0.6 + company "exyn","technologies" 0.6.
    ok, conf, reason = sca.validate_catalyst(
        "EXYN", "Exyn Technologies Inc",
        "Exyn Technologies Interim CEO Ben Williams to Appear Today on FOX Business Network")
    assert ok and conf == 1.0, (conf, reason)
    # 0.6 + 0.3 = 0.9 is untouched; the relevance threshold is unchanged.
    ok, conf, _ = sca.validate_catalyst("KVYO", "Klaviyo Inc", "KVYO slides as Klaviyo guides lower")
    assert ok and conf == 0.9
    ok, conf, _ = sca.validate_catalyst("ABCD", "Nothing Matches Corp", "Markets rally on Fed")
    assert not ok and conf == 0.0


# -- 2. symbol_profiles.ytd_return_pct: the capped lane must reach the stale tail ---------------------------------

def _profiles_db(rows):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE symbol_profiles (symbol TEXT, instrument_type TEXT, perf_updated_at TEXT)")
    con.executemany("INSERT INTO symbol_profiles VALUES (?,?,?)", rows)
    return con


def test_etf_performance_targets_are_stalest_first():
    import etf_performance_enrich as epe

    rows = [("AAA", "etf", "2026-10-17"), ("BBB", "fund", "2026-10-17"),
            ("NVD", "etf", "2026-08-29"),            # NaN since 2026-08-29, alphabetically past the cap
            ("ZZZ", "inverse_etf", None),            # never enriched
            ("STK", "stock", None)]                  # not a target
    got = [r[0] for r in _profiles_db(rows).execute(epe._TARGET_SQL).fetchall()]
    assert got == ["ZZZ", "NVD", "AAA", "BBB"]


def test_the_cap_reaches_the_alphabetical_tail():
    import etf_performance_enrich as epe

    fresh = [(f"A{i:04d}", "etf", "2026-10-17") for i in range(epe.SYMBOL_CAP)]
    got = [r[0] for r in _profiles_db(fresh + [("NBIZ", "etf", "2026-08-29")]).execute(epe._TARGET_SQL).fetchall()]
    assert "NBIZ" in got[: epe.SYMBOL_CAP]


# -- 3. indicator_confluence_cache.stop_price: every upsert must refresh the stop -------------------------------

_SCALARS = ("confluence_score", "confluence_tier", "signals_bullish", "signals_bearish", "signals_neutral",
            "strategy_badges", "bearish_badges", "key_levels", "stop_price", "target_price", "atr", "adx_regime",
            "entry_quality", "full_result")


def _confluence_upserts():
    tree = ast.parse((ROOT / "scripts" / "api_v2.py").read_text())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and "INSERT INTO indicator_confluence_cache" in node.value:
            out.append(node.value)
    return out


def test_every_api_confluence_upsert_refreshes_the_stop_on_conflict():
    sqls = _confluence_upserts()
    assert len(sqls) >= 2
    for sql in sqls:
        set_clause = sql.split("DO UPDATE SET", 1)[1]
        updated = set(re.findall(r"(\w+)\s*=\s*EXCLUDED\.\1", set_clause))
        missing = [c for c in _SCALARS if c not in updated]
        assert not missing, missing


def test_the_universe_lane_upsert_is_the_reference_shape():
    from scripts.lib import indicator_universe_lane as L

    updated = set(re.findall(r"(\w+)=EXCLUDED\.\1", L.UPSERT_SQL.split("DO UPDATE SET", 1)[1]))
    assert set(_SCALARS) <= updated
