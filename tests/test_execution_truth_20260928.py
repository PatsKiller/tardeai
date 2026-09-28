"""PR-6 (2026-09-28, root cause 6): truth-of-execution repairs.

- market cap: the enrichment cache's `market_cap_b` holds MILLIONS; a `market_cap_usd` is now
  published beside it and readers prefer it.
- broker queue: proposals past `expires_at` no longer count as blocked/pending; the count of such
  rows is reported as `expired_uncounted`.
- clocks: an `account_summaries.as_of` OLDER than the maintained position rows is a stale mirror
  (`summary_as_of_stale`), not an "observation divergence".
- quotes: a mutual fund's cached NAV (`price_cache_nav`) is its price, not a fallback → the header
  is no longer DEGRADED for one fund; `nav_marked_symbols` is reported.
- registry: `quote_price` declares an `extended_hours_provider` (proposed; operator ratifies).
- execution root: `run_continuous.sh` derives PROJECT_ROOT from its own location; the tracked unit
  points at CURRENT (host unit edit is operator-only).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import quote_selection_contract as qsc  # noqa: E402
from lib.finviz_csv import enrichment_market_cap_billions  # noqa: E402


# ---- market cap

def test_market_cap_usd_is_published_and_preferred():
    src = (ROOT / "scripts/finviz_enrichment.py").read_text()
    assert 'merged["market_cap_usd"] = round(float(_mc_m) * 1_000_000, 2)' in src
    assert enrichment_market_cap_billions({"market_cap_b": 4967858.67}) == 4967.85867
    assert round(enrichment_market_cap_billions({"market_cap_b": 4967858.67, "market_cap_usd": 4967858.67e6}), 3) == 4967.859


# ---- expired queue rows

def test_expired_rows_leave_the_active_queue():
    import broker_proposal_queue_ops as ops
    assert "expires_at IS NULL OR expires_at > NOW()" in ops._active_where()
    assert "expires_at <= NOW()" in ops._expired_uncounted_where()
    src = (ROOT / "scripts/broker_proposal_queue_ops.py").read_text()
    assert '"expired_uncounted": expired_uncounted' in src


# ---- clocks

def test_older_summary_is_stale_mirror_not_divergence():
    src = (ROOT / "scripts/lib/portfolio_aggregate_contract.py").read_text()
    assert '"summary_as_of_stale": summary_stale' in src
    assert "if _obs_key(summary_as_of) < _obs_key(obs):" in src
    from lib import portfolio_aggregate_contract as pac
    # the sortable key orders an older ISO date before a newer one
    assert pac._obs_key("2026-07-17") < pac._obs_key("2026-09-25T13:00:00+00:00")


def test_divergence_kept_when_summary_is_newer_than_positions():
    src = (ROOT / "scripts/lib/portfolio_aggregate_contract.py").read_text()
    assert 'divergence = f"positions say {obs} ({obs_source}); account_summaries.as_of says {summary_as_of}"' in src


# ---- quotes

def test_fund_nav_from_cache_is_not_degradation():
    out = qsc.project_quote_selection(reprice_source="finviz_afterhours", last_repriced="2026-09-28T07:30:00-04:00",
                                      source_counts={"finviz_elite": 9, "price_cache_nav": 1})
    assert out["fallback_used"] is False and out["status"] == qsc.STATUS_SELECTED and out["quality"] == "OK"
    assert out["nav_marked_symbols"] == 1 and out["fallback_reason"] is None


def test_real_fallbacks_still_degrade():
    out = qsc.project_quote_selection(reprice_source="finviz", last_repriced="2026-09-28T10:00:00-04:00",
                                      source_counts={"finviz_elite": 8, "yahoo_cache_fallback": 2})
    assert out["fallback_used"] is True and out["quality"] == "DEGRADED" and "yahoo_cache_fallback(2)" in out["fallback_reason"]
    out2 = qsc.project_quote_selection(reprice_source="finviz", last_repriced="x", source_counts={"finviz_elite": 8, "": 2})
    assert out2["quality"] == "DEGRADED"   # unpriced positions still degrade


# ---- registry

def test_registry_declares_extended_hours_provider_as_proposed():
    d = json.loads((ROOT / "config/data_source_authority.json").read_text())
    qp = next(x for x in d["domains"] if x["domain"] == "quote_price")
    assert qp["primary_provider"] == "alpaca"
    assert qp["extended_hours_provider"] == "finviz_elite"
    assert "PROPOSED" in qp["extended_hours_note"] and qp["approval"]["approved_on"] == "2026-09-13"


# ---- execution root

def test_launcher_derives_root_from_its_location(tmp_path):
    launcher = ROOT / "linux_launchers/run_continuous.sh"
    src = launcher.read_text()
    assert 'PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"' in src
    assert "/home/" + "johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild\"\n" not in src.split("VENV_DIR")[0]
    # a copy under another root resolves to that root
    fake = tmp_path / "release" / "linux_launchers"; fake.mkdir(parents=True)
    probe = fake / "probe.sh"
    probe.write_text('PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"\necho "$PROJECT_ROOT"\n')
    out = subprocess.run(["bash", str(probe)], capture_output=True, text=True, env={**os.environ, "PROJECT_ROOT": ""})
    assert out.stdout.strip() == str(tmp_path / "release")


def test_tracked_unit_points_at_current():
    unit = (ROOT / "config/systemd/tradeai-continuous.service").read_text()
    assert "WorkingDirectory=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT" in unit
    assert "CURRENT/linux_launchers/run_continuous.sh" in unit
    assert "persistent-state/logs/tradeai-continuous.log" in unit
    assert "trade-ai-v12-rebuild/trade-ai-v12-rebuild" not in unit
