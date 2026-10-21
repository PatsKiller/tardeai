"""Pipeline freshness SLO alert 2026-10-21 — two red checks, two causes.

1. hermes_score_snapshots_2h (REAL outage): watchlist_strategy_cards BHVN holds target_price/stop_loss = 'NaN'.
   psycopg2 returns Decimal('NaN'); `px <= stop` raised decimal.InvalidOperation and aborted every
   hermes_watchlist_scorer run from 2026-10-19 07:45 ET. _f_rr now treats a non-finite level as missing.
2. schwab_stream_book_2h (FALSE POSITIVE): the stream daemon's cron line is commented out
   ("# PAUSED 2026-10-14 schwab-app-deactivated") while config/schwab_access_mode.yaml is read_only, so the
   existing SCHWAB_PAUSED guard does not apply. The SLO now reports PRODUCER_UNSCHEDULED, not CRITICAL.

Hermetic: fake DB, fake crontab text, fake Schwab transport. No database, no broker, no Telegram.
"""
from __future__ import annotations

import sys
import types
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

COVERS: list[str] = []


# ── 1: scorer survives a NaN strategy card ──────────────────────────────────

@pytest.mark.parametrize("tgt,stop", [
    (Decimal("NaN"), Decimal("NaN")),
    (Decimal("12.0"), Decimal("NaN")),
    (Decimal("NaN"), Decimal("8.0")),
    (float("inf"), Decimal("8.0")),
])
def test_rr_factor_drops_non_finite_levels(tgt, stop):
    import hermes_watchlist_scorer as hws
    assert hws._f_rr({"price": Decimal("10.0"), "target_price": tgt, "stop_loss": stop}) == (None, None)


def test_rr_factor_still_scores_real_levels():
    import hermes_watchlist_scorer as hws
    s, det = hws._f_rr({"price": Decimal("10"), "target_price": Decimal("13"), "stop_loss": Decimal("9")})
    assert s == pytest.approx(99.0) and det == "R:R 3.0:1"


def test_score_symbol_survives_nan_card():
    import hermes_watchlist_scorer as hws
    wi = {"symbol": "BHVN", "price": Decimal("10.0"), "target_price": Decimal("NaN"),
          "stop_loss": Decimal("NaN"), "rsi": 55, "trend": "up", "score": 60}
    weights = {k: 0.1 for k in ("technical_momentum", "setup_quality", "analyst", "social_sentiment",
                                "sector_strength", "news_catalyst", "risk_reward", "hermes_research",
                                "options_edge", "thesis_outcome")}
    comp, components = hws.score_symbol(wi, None, None, {}, weights)   # raised InvalidOperation before
    assert "risk_reward" not in components


# ── 2: SLO honors an unscheduled stream producer ────────────────────────────

class _Cur:
    def __init__(self):
        self._q = ""

    def execute(self, q, *a):
        self._q = q

    def fetchone(self):
        return (0,) if "count(*)" in self._q else (1,)


def _run_slo(monkeypatch, crontab_text, kill_file=None):
    import pipeline_freshness_slo as pfs
    cur = _Cur()
    conn = types.SimpleNamespace(cursor=lambda *a, **k: cur)
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "read_only")      # reads allowed: SCHWAB_PAUSED n/a
    monkeypatch.setattr(pfs, "CHECKS", [])
    monkeypatch.setattr(pfs, "_market_state", lambda: pfs.MARKET_OPEN)
    monkeypatch.setattr(pfs, "_read_crontab_text", lambda: crontab_text)
    spec = dict(pfs.SCHEDULED_PRODUCERS["schwab_stream_book_2h"])
    spec["kill_file"] = kill_file or Path("/nonexistent/STREAM_DISABLED")
    monkeypatch.setitem(pfs.SCHEDULED_PRODUCERS, "schwab_stream_book_2h", spec)
    out = pfs.run(telegram=False)
    return out, {c["check"]: c["status"] for c in out["checks"]}


PAUSED_LINE = ('# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 31 9 * * 1-5 cd $PROJ && flock -n '
               '/tmp/schwab_stream.lock bash -c "set -a; . ./.env; set +a; $PY scripts/schwab_stream_daemon.py"')
ACTIVE_LINE = PAUSED_LINE.split("(incident SPCX) ", 1)[1]


def test_commented_stream_cron_is_expected_silence_not_critical(monkeypatch):
    out, st = _run_slo(monkeypatch, PAUSED_LINE + "\n")
    assert st["schwab_stream_book_2h"] == "PRODUCER_UNSCHEDULED"
    assert not any("schwab_stream_book_2h" in f for f in out["findings"])


def test_active_stream_cron_with_zero_rows_still_pages(monkeypatch):
    out, st = _run_slo(monkeypatch, ACTIVE_LINE + "\n")
    assert st["schwab_stream_book_2h"] == "CRITICAL"


def test_unreadable_crontab_is_conservative(monkeypatch):
    out, st = _run_slo(monkeypatch, None)
    assert st["schwab_stream_book_2h"] == "CRITICAL"


def test_kill_switch_is_expected_silence(monkeypatch, tmp_path):
    kf = tmp_path / "STREAM_DISABLED"
    kf.write_text("")
    out, st = _run_slo(monkeypatch, ACTIVE_LINE + "\n", kill_file=kf)
    assert st["schwab_stream_book_2h"] == "PRODUCER_KILL_SWITCH"
