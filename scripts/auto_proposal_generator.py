#!/usr/bin/env python3
"""auto_proposal_generator.py — Stage 18f: Auto-create PENDING paper proposals from planned strategy signals.

Creates PENDING paper proposals from current-day planned strategy signals.
Does NOT approve trades or submit orders. Populates the review queue.

Usage:
    .venv/bin/python scripts/auto_proposal_generator.py --run-label 1000 --dry-run
    .venv/bin/python scripts/auto_proposal_generator.py --run-label 1000 --apply
    .venv/bin/python scripts/auto_proposal_generator.py --today --apply --limit 10
    .venv/bin/python scripts/auto_proposal_generator.py --symbol EVC --dry-run
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("auto_proposal")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

DEFAULT_MAX_DOLLAR_SIZE = 2000
DEFAULT_MAX_DOLLAR_RISK = 150
DEFAULT_RISK_PER_TRADE = 150
MAX_QUOTE_AGE_MINUTES = 15
TREND_LOOKBACK_DAYS = 2
# Consolidated 2026-06-11: 4-strategy trading core (gap_and_go->momentum_scalp, swing_trade->swing_breakout;
# others archived/parked/reclassified — see docs/project/SYSTEM_DEEP_REVIEW_20260611.md section F)
STRATEGY_PRIORITY = ["momentum_scalp", "swing_breakout", "fib_retracement_bounce", "earnings_post_momentum"]

BASE = str(PROJECT_ROOT)
PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python")


def _unified_edge_for_signal(signal: dict, sizing: dict | None = None) -> float:
    """Shared 0–100 edge composite for candidate ranking (see unified_edge_score.py)."""
    try:
        from unified_edge_score import edge_from_trade_context
    except ImportError:
        return float(signal.get("signal_score") or 0)
    entry = float(signal.get("entry_high") or 0)
    stop = float(signal.get("stop_loss") or 0)
    target = float(signal.get("target_1") or 0)
    rr = None
    if sizing:
        rr = sizing.get("rr")
    if rr is None and entry > stop > 0 and target > entry:
        rr = (target - entry) / (entry - stop)
    intel = signal.get("intel_readiness")
    catalyst_strength = 0.85 if signal.get("catalyst_verified") else 0.45
    if intel is not None:
        try:
            catalyst_strength = max(catalyst_strength, float(intel) / 100.0)
        except (TypeError, ValueError):
            pass
    score = float(signal.get("signal_score") or 0)
    return edge_from_trade_context({
        "risk_reward": rr or signal.get("rr") or 0.5,
        "catalyst_strength": catalyst_strength,
        "confidence": score / 100.0 if score else 0.5,
        "technical_score": signal.get("confluence_score") or score or 50,
        "regime_alignment": 50,
        "pop_pct": 55,
        "iv_rank": 25,
    })


def _enrich_proposal_async(proposal_id: int, symbol: str):
    """Kick off enrichment pipeline for a new proposal in a background thread.

    Sequence: queue agent reviews → warm Ollama → LLM analysis → quality review.
    Non-blocking — runs in a daemon thread so it doesn't delay proposal creation.
    """
    import threading

    def _run():
        import subprocess, time

        log.info(f"Starting async enrichment for proposal #{proposal_id} ({symbol})")

        # Step 1: Queue agent reviews
        try:
            r = subprocess.run(
                [PYTHON, f'{BASE}/scripts/queue_proposal_agent_reviews.py',
                 '--proposal-id', str(proposal_id), '--apply'],
                capture_output=True, text=True, timeout=60, cwd=BASE
            )
            log.info(f"Agent reviews queued for #{proposal_id}: "
                     f"{r.stdout.strip()[-100:] if r.stdout else 'done'}")
        except Exception as e:
            log.warning(f"Agent review queue failed for #{proposal_id}: {e}")

        # Brief pause to let agent processor pick up jobs
        time.sleep(10)

        # Step 2: Warm up Ollama
        try:
            # 2026-06-12: was hardcoded 'qwen3:14b' (DISABLED + uninstalled) — silently failed on
            # every proposal since qwen removal. Warm the CONFIGURED primary model instead.
            from local_llm_config import get_local_llm_model
            subprocess.run(
                ['ollama', 'run', get_local_llm_model(), 'ready'],
                capture_output=True, text=True, timeout=30, cwd=BASE
            )
        except Exception:
            pass  # non-fatal

        # Step 3: LLM analysis
        try:
            r = subprocess.run(
                [PYTHON, f'{BASE}/scripts/proposal_intelligence_analyzer.py',
                 '--proposal-id', str(proposal_id), '--apply'],
                capture_output=True, text=True, timeout=180, cwd=BASE
            )
            log.info(f"LLM analysis for #{proposal_id}: "
                     f"{'OK' if r.returncode == 0 else 'FAILED'}")
            if r.returncode != 0 and r.stderr:
                log.warning(f"Analyzer stderr: {r.stderr[-200:]}")
        except subprocess.TimeoutExpired:
            log.warning(f"LLM analysis timed out for #{proposal_id}")
        except Exception as e:
            log.warning(f"LLM analysis failed for #{proposal_id}: {e}")

        # Step 4: Quality review
        try:
            subprocess.run(
                [PYTHON, f'{BASE}/scripts/proposal_quality_reviewer.py',
                 '--proposal-id', str(proposal_id), '--apply'],
                capture_output=True, text=True, timeout=60, cwd=BASE
            )
            log.info(f"Quality review complete for #{proposal_id}")
        except Exception as e:
            log.warning(f"Quality review failed for #{proposal_id}: {e}")

        # Step 5: INLINE grok entry-zone validation (operator 2026-06-12: "not weekly — when a
        # proposal for a strategy [is created], have grok review inline"). Advisory-only: writes an
        # entry plan (zone/limit/urgency/WAIT-READY tag) into watchlist_entry_plans; the proposal
        # row itself is never modified. Lane falls back to local automatically if the grok proxy
        # is down (llm_lane.available inside the planner).
        try:
            r = subprocess.run(
                [PYTHON, f'{BASE}/scripts/watchlist_entry_planner.py',
                 '--scope', 'proposals', '--symbols', symbol, '--lane', 'grok'],
                capture_output=True, text=True, timeout=180, cwd=BASE
            )
            log.info(f"Grok entry validation for #{proposal_id}: "
                     f"{'OK' if r.returncode == 0 else 'FAILED'}")
        except Exception as e:
            log.warning(f"Grok entry validation failed for #{proposal_id}: {e}")

        log.info(f"Enrichment complete for proposal #{proposal_id} ({symbol})")

    t = threading.Thread(target=_run, daemon=True, name=f'enrich-{proposal_id}')
    t.start()
    return t


def _cloud_review_proposal(signal: dict, sizing: dict, proposal_id: int):
    """ADVISORY-ONLY: free-OAuth cloud lanes (ChatGPT+Grok) review the LOCAL model's proposal reasoning.

    Additive + advisory: the verdict is ONLY recorded (cloud_review persists each lane to
    llm_feedback_observations) + logged. It NEVER gates, blocks, or modifies the proposal — the row is
    already created and queued before this runs. Gated behind CLOUD_REVIEW=1 (default OFF) and called only
    for newly-generated proposals, capped per run by the caller. Wrapped + guarded so a down lane is a no-op.
    """
    try:
        import cloud_review
        if not cloud_review.available():
            return
        sym = signal.get("symbol")
        # local_output = the rationale/thesis text the local model produced for this proposal.
        rationale = (signal.get("setup_description") or signal.get("setup_type")
                     or signal.get("catalyst") or "").strip()
        if not rationale:
            return
        # context = SMALL dict of SAFE fields only. Deliberately NO dollar amounts, account ids, or
        # position sizes (per advisory-review safety policy) — just symbol/setup/entry-logic/signal scores.
        context = {
            "symbol": sym,
            "strategy": signal.get("strategy_id"),
            "setup": signal.get("setup_description"),
            "entry_logic": {
                "entry_high": signal.get("entry_high"),
                "entry_low": signal.get("entry_low"),
                "stop_loss": signal.get("stop_loss"),
                "target_1": signal.get("target_1"),
                "rr": sizing.get("rr") if sizing else None,
            },
            "signal_scores": {
                "signal_score": signal.get("signal_score"),
                "signal_grade": signal.get("signal_grade"),
                "rvol": signal.get("rvol"),
                "gap_pct": signal.get("gap_pct"),
                "catalyst_verified": signal.get("catalyst_verified"),
            },
        }
        r = cloud_review.review("paper_proposal_review", local_output=rationale, context=context,
                                symbol=sym, source="auto_proposal_generator")
        verdict = (r.get("consensus") or {}).get("verdict", "UNKNOWN")
        log.info(f"  {sym}: cloud review of local proposal reasoning (proposal #{proposal_id}) "
                 f"-> consensus={verdict} (lanes_ok={(r.get('consensus') or {}).get('lanes_ok', 0)}); "
                 f"advisory only, recorded to llm_feedback_observations")
    except Exception as _e:
        log.warning(f"  cloud review skipped for proposal #{proposal_id}: {_e}")


def _send_proposal_alert_async(proposal_id: int, symbol: str):
    """Send Telegram alert immediately after proposal creation. Non-blocking."""
    import threading

    def _run():
        try:
            import subprocess
            r = subprocess.run(
                [PYTHON, f'{BASE}/scripts/send_telegram_proposal_alert.py',
                 '--proposal-id', str(proposal_id), '--send'],
                capture_output=True, text=True, timeout=30, cwd=BASE,
                env={**os.environ},
            )
            if r.returncode == 0:
                log.info(f"Telegram alert sent for proposal #{proposal_id} ({symbol})")
            else:
                log.warning(f"Telegram alert failed for #{proposal_id}: {r.stderr[-200:] if r.stderr else r.stdout[-200:]}")
        except Exception as e:
            log.warning(f"Telegram alert error for #{proposal_id}: {e}")

    t = threading.Thread(target=_run, daemon=True, name=f'alert-{proposal_id}')
    t.start()


def _resolve_proposal_account(strategy_id: str = None) -> str:
    """Resolve target account from enabled ATM accounts. No hardcoded fallback."""
    try:
        from atm_config_manager import get_enabled_accounts
        enabled = get_enabled_accounts()
        if enabled:
            return enabled[0]  # first enabled account from config+DB
    except Exception:
        pass
    try:
        from broker_config import get_default_paper_account
        return get_default_paper_account()
    except Exception:
        return os.environ.get("DEFAULT_PAPER_ACCOUNT", "paper")


def get_conn():
    import psycopg2
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD missing from .env")
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=password,
    )


def _get_available_cols(conn, table: str) -> set:
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", [table])
    return {r[0] for r in cur.fetchall()}


def _load_strategy_config(strategy_id: str) -> dict:
    import yaml
    path = PROJECT_ROOT / "config" / "strategies" / f"{strategy_id}.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def _load_shared_risk_rules() -> dict:
    import yaml
    path = PROJECT_ROOT / "config" / "strategies" / "shared_risk_rules.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def _validate_against_strategy_criteria(strategy_id: str, signal: dict) -> tuple:
    """Hard-validate a signal against its strategy YAML criteria.
    Returns (passes: bool, fail_reason: str, fallback_strategy: str|None).
    """
    cfg = _load_strategy_config(strategy_id)
    if not cfg:
        return True, '', None

    # Deterministic machine evaluation of the FULL YAML criteria set (2026-06-11): the same evaluator the
    # signal simulator uses — repeatable, auditable, no LLM interpretation. Fails only on EVALUABLE criteria
    # (missing metrics are 'skipped', never auto-fail); evidence requirements handled by the legacy checks
    # below, which remain as a second layer.
    try:
        from strategy_criteria_evaluator import evaluate as _crit_eval
        _metrics = {k: signal.get(k) for k in ("rvol", "price", "float_m", "gap_pct", "change_pct",
                                               "catalyst_verified", "score") if signal.get(k) is not None}
        if not _metrics.get("price"):
            _metrics["price"] = signal.get("entry_high")
        _r = _crit_eval(strategy_id, _metrics, cfg=cfg)
        if _r.get("fail_ids"):
            return False, f"criteria_evaluator: {','.join(_r['fail_ids'][:4])}", None
    except Exception:
        pass  # evaluator is additive; legacy checks below still run

    filters = cfg.get('screen_filters', {})
    rvol = float(signal.get('rvol') or 0)
    price = float(signal.get('price') or signal.get('entry_high') or 0)
    float_m = float(signal.get('float_m') or 0)
    gap_pct = abs(float(signal.get('gap_pct') or 0))

    min_rvol = float(filters.get('min_rvol', 0))
    min_price = float(filters.get('min_price', 0))
    max_price = float(filters.get('max_price', 99999))
    max_float = float(filters.get('max_float_m', 99999))
    min_gap = float(filters.get('min_gap_pct', 0))

    # Hard safety floors (cannot be overridden by config)
    _MOMENTUM_STRATEGIES = {'momentum_scalp', 'gap_and_go', 'earnings_catalyst',
                            'screener', 'speculative_growth', 'earnings_post_momentum'}
    _hard_min_price = 3.0 if strategy_id in _MOMENTUM_STRATEGIES else 1.0
    if min_price < _hard_min_price:
        min_price = _hard_min_price

    reasons = []
    if min_rvol > 0 and rvol < min_rvol:
        reasons.append(f"RVOL {rvol:.1f}x < {min_rvol}x")
    if price < min_price or price > max_price:
        reasons.append(f"Price ${price:.2f} outside ${min_price}-${max_price}")
    if max_float < 99999 and float_m > 0 and float_m > max_float:
        reasons.append(f"Float {float_m:.0f}M > {max_float}M")
    if min_gap > 0 and gap_pct < min_gap:
        reasons.append(f"Gap {gap_pct:.1f}% < {min_gap}%")

    if reasons:
        # Suggest fallback based on strategy type
        fallback = None
        if strategy_id == 'momentum_scalp':
            fallback = 'swing_breakout'   # gap_and_go merged into momentum_scalp 2026-06-11
        return False, ' | '.join(reasons), fallback

    return True, '', None


# Only true intraday scalp/momentum setups need the strict generation-time liquidity gate. Swing,
# breakout, fib and earnings plans hold for hours-to-days, so an intraday spread/volume floor would
# wrongly reject a perfectly tradeable swing name — and the execution-readiness layer is still the
# tighter backstop at approval. (operator 2026-06-15: swing_breakout plans should generate proposals too.)
_LIQUIDITY_GATED_STRATEGIES = {"momentum_scalp", "gap_and_go", "earnings_catalyst"}


def _is_intraday_strategy(strategy_id: str) -> bool:
    """True for liquidity- and time-sensitive intraday strategies (momentum_scalp)."""
    if not strategy_id:
        return False
    try:
        import proposal_lifecycle as _pl
        return strategy_id in _pl.INTRADAY_STRATEGIES
    except Exception:
        return strategy_id in ("momentum_scalp", "gap_and_go")


def _liquidity_prescreen(symbol: str, rules: dict, strategy_id: str = None) -> tuple:
    """Structural liquidity gate at GENERATION time. Returns (ok: bool, reason: str).

    Stops untradeable microcaps (wide spread / no real volume) from becoming proposals.
    strategy_signals carries no absolute volume or spread, so we read a live quote.

    P0-4 — intraday is FAIL-CLOSED: momentum_scalp is liquidity- and time-sensitive, so a
    quote/provider error, a missing quote, or a stale quote must DEFER (no auto proposal),
    never fail open. Outside regular hours it may proceed ONLY with a fresh extended-hours
    quote (check_fresh_quote ok). Non-intraday gated strategies (e.g. earnings_catalyst)
    keep the prior fail-open behavior — the approval-time execution layer is their backstop.
    """
    if strategy_id and strategy_id not in _LIQUIDITY_GATED_STRATEGIES:
        return True, ""   # swing/breakout/fib — not intraday-liquidity-dependent
    liq = (rules or {}).get("liquidity_prescreen") or {}
    if not liq.get("enabled", True):
        return True, ""

    intraday = _is_intraday_strategy(strategy_id)

    if not intraday:
        # NON-INTRADAY gated: preserve fail-open (off-hours quotes untrustworthy; exec layer backstops).
        try:
            from market_session import current_market_session
            if current_market_session() != "regular":
                return True, ""
        except Exception:
            return True, ""
        try:
            from market_quote_provider import get_best_quote
            q = get_best_quote(symbol) or {}
        except Exception:
            return True, ""  # never block non-intraday on a data/provider error
    else:
        # INTRADAY (momentum_scalp): FAIL-CLOSED. Require a fresh quote (RTH or fresh extended-hours);
        # provider error / missing / stale quote → DEFER, no proposal.
        try:
            from market_quote_provider import check_fresh_quote
            fq = check_fresh_quote(symbol, strategy_id=strategy_id) or {}
        except Exception as e:
            return False, f"DEFER_LIQUIDITY_UNKNOWN: quote provider error ({e})"
        if not fq.get("ok"):
            return False, f"DEFER_LIQUIDITY_UNKNOWN: {fq.get('reason') or 'no fresh quote (stale/missing/off-hours)'}"
        try:
            from market_quote_provider import get_best_quote
            q = get_best_quote(symbol) or {}
        except Exception as e:
            return False, f"DEFER_LIQUIDITY_UNKNOWN: quote provider error ({e})"
        if not q:
            return False, "DEFER_LIQUIDITY_UNKNOWN: no quote liquidity detail"

    spread = q.get("spread_pct")
    last = q.get("last_price")
    dayvol = q.get("day_volume")

    max_spread = float(liq.get("max_spread_pct", 5.0))
    min_shares = float(liq.get("min_day_volume_shares", 25000))
    min_dollar_vol = float(liq.get("min_dollar_day_volume", 100000))

    if spread is not None:
        try:
            if float(spread) > max_spread:
                return False, f"spread {float(spread):.1f}% > {max_spread:.1f}% ceiling (illiquid)"
        except (TypeError, ValueError):
            pass

    # Volume floor: block only when BOTH the share AND dollar floors are breached,
    # so a low-share/high-price or high-share/low-price name is not falsely rejected.
    if last and dayvol:
        try:
            ddv = float(last) * float(dayvol)
            if float(dayvol) < min_shares and ddv < min_dollar_vol:
                return False, (f"day volume {float(dayvol):,.0f}sh / ${ddv:,.0f} below floor "
                               f"({min_shares:,.0f}sh & ${min_dollar_vol:,.0f})")
        except (TypeError, ValueError):
            pass

    return True, ""


def get_eligible_signals(conn, run_label=None, symbol=None, min_score=40) -> list:
    """Get current-day planned strategy signals eligible for auto-proposal."""
    cur = conn.cursor()
    sql = """
        SELECT id, symbol, strategy_id, setup_description, signal_grade, signal_score,
               price, rvol, float_m, gap_pct,
               catalyst, catalyst_verified, intel_readiness,
               entry_high, entry_low, stop_loss, target_1, target_2,
               shares, dollar_risk, risk_reward,
               sector, source_table, scan_run_label, discovery_source,
               discovery_trace_id,
               fired_at
        FROM strategy_signals
        WHERE fired_at::date = CURRENT_DATE
        AND entry_high IS NOT NULL AND stop_loss IS NOT NULL
        AND target_1 IS NOT NULL AND shares IS NOT NULL
        AND (signal_grade IN ('A','A+') OR signal_score >= %s)
        AND status IN ('active','ACTIVE')
    """
    params = [min_score]
    # Note: run_label filter removed in A-4 fix. Signals from any same-day
    # run are eligible — pre-market (0400) signals should be visible to
    # daytime (1200/1400/1600/1730) proposal runs. The fired_at::date = CURRENT_DATE
    # filter already scopes to today's signals only.
    if symbol:
        sql += " AND symbol = %s"
        params.append(symbol)
    sql += " ORDER BY signal_score DESC NULLS LAST"
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    # Phase 3 learning hook (opt-in, default OFF via REC_SOURCE_WEIGHTING=1): re-rank candidates by
    # signal_score x the LEARNED quality multiplier of their discovery_source, so sources with better
    # realized outcomes surface first. Advisory RANKING only — does not change risk gates, sizing, or
    # whether a proposal can execute; default-off means normal runs are unchanged.
    if os.getenv("REC_SOURCE_WEIGHTING") == "1":
        try:
            import recommendation_intelligence_engine as _rie
            for r in rows:
                m = _rie.get_source_quality(r.get("discovery_source") or "(direct/manual)")
                r["_rec_quality_multiplier"] = m
                r["_effective_score"] = (r.get("signal_score") or 0) * m
            rows.sort(key=lambda r: r.get("_effective_score", 0), reverse=True)
        except Exception:
            pass
    # Per-strategy allocation tilt (operator 2026-06-19, default ON; STRATEGY_TILT=0 disables): re-rank by
    # signal_score x the strategy's live-performance multiplier so WINNING strategies' candidates surface
    # first. Advisory ranking only (sizing tilt is applied separately in account_policy). momentum_scalp
    # is pinned to 1.0 (excluded). Composes with the source weighting above.
    try:
        import strategy_tilt as _stilt
        if _stilt.enabled():
            for r in rows:
                t = _stilt.get_tilt(r.get("strategy_id"))
                r["_strategy_tilt"] = t
                base = r.get("_effective_score", (r.get("signal_score") or 0))
                r["_effective_score"] = base * t
            rows.sort(key=lambda r: r.get("_effective_score", 0), reverse=True)
    except Exception:
        pass
    # Unified edge ranker (L10 maturity): final sort key blends tilt/source weighting with the
    # shared 0–100 composite so high-edge candidates surface first across strategies.
    try:
        for r in rows:
            edge = _unified_edge_for_signal(r)
            r["_unified_edge"] = edge
            base = float(r.get("_effective_score", r.get("signal_score") or 0))
            r["_effective_score"] = base + edge * 0.15
        rows.sort(
            key=lambda r: (r.get("_effective_score", 0), r.get("_unified_edge", 0)),
            reverse=True,
        )
    except Exception:
        pass
    return rows


def check_duplicate(conn, signal_id: int, symbol: str, strategy_id: str) -> dict | None:
    """Check for existing active proposal — SYMBOL-WIDE across ALL strategies (Gate 4.5).

    One screener hit must yield at most one live proposal per symbol. The old per-(symbol, strategy)
    check let the same hit spawn proposals under multiple strategies (BWEN x3 on 2026-06-04 across
    sector_rotation/speculative_growth/swing_breakout, all 0-min scratches). Window: 48h, any strategy."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, status, strategy_id FROM paper_trade_proposals
        WHERE (
            source_signal_id = %s
            OR (
                symbol = %s
                AND created_at > NOW() - INTERVAL '48 hours'
            )
        )
        AND status IN ('PENDING','APPROVED','MODIFIED','BROKER_SUBMITTED','APPROVED_FOR_PAPER_TEST')
        LIMIT 1
    """, [signal_id, symbol])
    row = cur.fetchone()
    if row:
        return {"id": row[0], "status": row[1], "existing_strategy": row[2]}

    # Re-proposal cooldown (2026-06-20): the active-status check above misses proposals that already
    # EXPIRED/were REJECTED — so a screener hit re-fired one EVERY 30 min (CAST x13/day), flooding the
    # queue + Lifecycle Journal. For NON-intraday strategies (swing/breakout/fib/etc.) block re-proposing
    # the same symbol within a cooldown window regardless of terminal status. INTRADAY scalp/momentum is
    # EXEMPT — re-proposing the same ticker through the day is by design (operator decision 2026-06-20;
    # respects the momentum_scalp rule).
    intraday = False
    try:
        from proposal_lifecycle import get_timeframe_class
        intraday = str(get_timeframe_class(strategy_id) or "").upper() == "INTRADAY"
    except Exception:
        intraday = "scalp" in (strategy_id or "").lower() or "gap" in (strategy_id or "").lower()
    if not intraday:
        import os as _os
        hrs = int(_os.getenv("PROPOSAL_RECOOLDOWN_HOURS", "12") or 12)
        cur.execute("""
            SELECT id, status, strategy_id FROM paper_trade_proposals
            WHERE symbol = %s AND created_at > NOW() - (%s || ' hours')::interval
            ORDER BY created_at DESC LIMIT 1
        """, [symbol, str(hrs)])
        r2 = cur.fetchone()
        if r2:
            return {"id": r2[0], "status": r2[1], "existing_strategy": r2[2], "cooldown": True}
    return None


def check_open_paper_trade(conn, symbol: str, strategy_id: str) -> dict | None:
    """Check for existing open paper trade — SYMBOL-WIDE (one symbol = one position, any strategy)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, status FROM paper_trades
        WHERE symbol = %s
        AND status IN ('open','pending','submitted')
        LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    return {"id": row[0], "status": row[1]} if row else None


def check_recently_closed(conn, symbol: str, strategy_id: str, cooldown_hours: int = 48) -> dict | None:
    """Block if any paper trade with this symbol closed within cooldown window, regardless of strategy."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, strategy_id, pnl, outcome_verdict,
               closed_at, exit_reason
        FROM paper_trades
        WHERE symbol = %s
          AND lifecycle_state = 'closed'
          AND closed_at > NOW() - make_interval(hours => %s)
        ORDER BY closed_at DESC LIMIT 1
    """, [symbol, cooldown_hours])
    row = cur.fetchone()
    if not row:
        return None
    prior_id, prior_strat, pnl, verdict, closed_at, exit_reason = row
    pnl_f = float(pnl) if pnl is not None else 0
    from datetime import datetime, timezone
    hours_since = (datetime.now(timezone.utc) - closed_at.astimezone(timezone.utc)).total_seconds() / 3600
    return {
        "reason": "SKIPPED_RECENTLY_CLOSED",
        "detail": (f"trade #{prior_id} ({symbol}/{prior_strat}) closed {closed_at} "
                   f"verdict={verdict} pnl=${pnl_f:.2f} via {exit_reason} — "
                   f"{hours_since:.1f}h ago, cooldown {cooldown_hours}h"),
        "prior_trade_id": prior_id,
        "prior_strategy": prior_strat,
        "prior_pnl": pnl_f,
        "prior_verdict": verdict,
        "hours_since_close": round(hours_since, 1),
    }


def rank_proposals_for_symbol(conn, symbol: str, window_hours: int = 24):
    """Rank all proposals for a symbol created within the window.

    Rules (from design doc, operator decisions Q1/Q2):
    - Rank within screener-matched set only (don't invent new strategies)
    - Sort by signal_score DESC
    - Top score gets is_top_pick=True, rank=1
    - Anything within 5% of top AND confidence_score > 65 is tied (also top_pick)
    - Everything else gets is_top_pick=False
    - All get rank_among_peers and peer_group_id for audit

    Returns number of proposals ranked.
    """
    cur = conn.cursor()
    # Get all proposals for this symbol in the time window
    cur.execute("""
        SELECT id, strategy_id, signal_score, confidence_score,
               proposed_rr, catalyst_verified, intel_readiness, rvol
        FROM paper_trade_proposals
        WHERE symbol = %s
          AND created_at > NOW() - (%s || ' hours')::interval
          AND status NOT IN ('REJECTED', 'RISK_BLOCKED')
    """, [symbol, str(window_hours)])
    raw_rows = cur.fetchall()
    ranked_rows = []
    for pid, strat, score, conf, rr, cat_ver, intel, rvol in raw_rows:
        edge = _unified_edge_for_signal({
            "signal_score": score,
            "strategy_id": strat,
            "rr": rr,
            "catalyst_verified": cat_ver,
            "intel_readiness": intel,
            "rvol": rvol,
        })
        ranked_rows.append((edge, float(score or 0), float(conf or 0), pid, strat, score, conf))
    ranked_rows.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    rows = [(r[3], r[4], r[5], r[6]) for r in ranked_rows]
    rows = cur.fetchall()
    if len(rows) <= 1:
        # Single proposal or none — mark it as top pick if it exists
        if rows:
            cur.execute("""UPDATE paper_trade_proposals
                SET is_top_pick=TRUE, rank_among_peers=1, peer_group_id=%s
                WHERE id=%s""", [f"{symbol}_{rows[0][0]}", rows[0][0]])
            conn.commit()
        return len(rows)

    peer_group_id = f"{symbol}_{rows[0][0]}"
    top_score = float(rows[0][2] or 0)
    threshold_5pct = top_score * 0.95  # within 5% of top

    ranked = 0
    for rank_idx, (pid, strat, score, conf) in enumerate(rows):
        score_f = float(score or 0)
        conf_f = float(conf or 0)
        is_top = False
        if rank_idx == 0:
            is_top = True
        elif score_f >= threshold_5pct and conf_f >= 65:
            is_top = True  # tied — within 5% and high confidence
        cur.execute("""UPDATE paper_trade_proposals
            SET is_top_pick=%s, rank_among_peers=%s, peer_group_id=%s
            WHERE id=%s""", [is_top, rank_idx + 1, peer_group_id, pid])
        ranked += 1

    conn.commit()
    log.info(f"[ranker] {symbol}: ranked {ranked} proposals, "
             f"top_score={top_score}, threshold={threshold_5pct:.1f}")
    return ranked


def check_rejection_cooldown(conn, symbol: str, force: bool = False) -> dict | None:
    """Check if symbol was recently rejected (24h cooldown). Returns skip reason or None."""
    if force:
        return None
    cur = conn.cursor()
    # Recent rejection or risk-gate rejection in last 24h
    cur.execute("""
        SELECT id, status, rejection_reason, risk_gate_result, rejected_at
        FROM paper_trade_proposals
        WHERE symbol = %s
        AND (
            (status = 'REJECTED' AND rejected_at > NOW() - INTERVAL '24 hours')
            OR (risk_gate_result ILIKE '%%BLOCK%%' AND created_at > NOW() - INTERVAL '24 hours')
        )
        ORDER BY created_at DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if row:
        return {
            "reason": "SKIPPED_RECENTLY_REJECTED",
            "detail": f"proposal #{row[0]} {row[1]} — {row[2] or row[3] or 'unknown reason'}",
            "cooldown_until": str(row[4] + timedelta(hours=24)) if row[4] else None,
        }
    return None


def _cap_sizing_risk(sizing: dict, max_risk: float) -> dict:
    """Clamp proposal dollar risk to a ceiling (trend-bridge guardrail)."""
    if not sizing or not sizing.get("valid") or max_risk is None:
        return sizing
    risk = float(sizing.get("adjusted_dollar_risk") or 0)
    if risk <= max_risk:
        return sizing
    entry = float(sizing.get("adjusted_dollar_size") or 0) / max(int(sizing.get("adjusted_shares") or 1), 1)
    shares = int(sizing.get("adjusted_shares") or 0)
    if shares <= 0 or entry <= 0:
        return sizing
    stop_pct = float(sizing.get("stop_pct") or 0)
    if stop_pct <= 0:
        return sizing
    risk_per_share = entry * stop_pct / 100.0
    if risk_per_share <= 0:
        return sizing
    max_shares = max(1, int(max_risk / risk_per_share))
    if max_shares >= shares:
        return sizing
    out = dict(sizing)
    out["adjusted_shares"] = max_shares
    out["adjusted_dollar_size"] = round(max_shares * entry, 2)
    out["adjusted_dollar_risk"] = round(max_shares * risk_per_share, 2)
    out["sizing_adjusted"] = True
    out["sizing_reason"] = (f"trend_risk_cap ${max_risk:.0f}: {shares}→{max_shares} shares")
    return out


def check_scan_decision(conn, symbol: str, *, trend_qualified: bool = False,
                        lookback_days: int = TREND_LOOKBACK_DAYS) -> dict | None:
    """Check if scan decision blocks proposal. Returns skip reason or None.

    trend_qualified: use best GO/A+ hit in lookback (trend bridge) instead of today's row only,
    so a name that qualified on a trend screen isn't blocked because a later full-universe pass
    marked it AVOID."""
    cur = conn.cursor()
    if trend_qualified:
        cur.execute("""
            SELECT decision, score, grade, critic_verdict
            FROM trade_ai_scans
            WHERE symbol = %s AND decision IN ('GO', 'A+')
              AND scanned_at > NOW() - (%s || ' days')::interval
              AND COALESCE(score, 0) >= 40
            ORDER BY score DESC NULLS LAST, scanned_at DESC LIMIT 1
        """, [symbol, str(lookback_days)])
    else:
        cur.execute("""
            SELECT decision, score, grade, critic_verdict
            FROM trade_ai_scans
            WHERE symbol = %s AND scanned_at::date = CURRENT_DATE
            ORDER BY scanned_at DESC LIMIT 1
        """, [symbol])
    row = cur.fetchone()
    if not row:
        return None  # no qualifying scan, let other checks handle

    decision, score, grade, critic = row

    if decision in ('WAIT', 'NO_GO', 'AVOID'):
        return {"reason": "SKIPPED_NOT_GO", "detail": f"scan decision={decision}"}

    if grade not in ('A', 'A+') and (score is None or score < 40):
        return {"reason": "SKIPPED_LOW_SCORE", "detail": f"grade={grade} score={score}"}

    if critic == 'DOWNGRADE':
        return {"reason": "SKIPPED_CRITIC_DOWNGRADE", "detail": f"critic={critic}"}

    if critic == 'BLOCK':
        return {"reason": "SKIPPED_CRITIC_BLOCK", "detail": f"critic={critic}"}

    return None


def normalize_size(signal: dict, strategy_cfg: dict, shared_rules: dict,
                   *, account_key: str = "tradeai_automated", equity: float | None = None,
                   policy: dict | None = None) -> dict:
    """Normalize proposal sizing via the percent-of-equity engine (operator 2026-06-19).

    Sizing is owned by account_policy.compute_sizing (the ONE implementation, shared with risk_gate):
    shares = min(position-cap, risk-cap) where caps = account_equity * pct/100 from the account's
    admin-editable automation policy. Falls back to the legacy fixed-dollar caps only when policy/equity
    is unavailable or the account is explicitly on the 'fixed_dollar' engine. Returns the legacy keys
    (back-compat) plus `sizing_basis` for the proposal row / audit."""
    import account_policy as _ap
    entry = float(signal.get("entry_high") or signal.get("price") or 0)
    stop = float(signal.get("stop_loss") or 0)
    original_shares = int(signal.get("shares") or 0)
    if entry <= 0 or stop <= 0:
        return {"valid": False, "reason": "MISSING_PLAN_DATA"}

    if policy is None:
        policy = _ap.load_policy(account_key)
    eq_src = "provided"
    if equity is None:
        equity, eq_src = _ap.equity_for_account(account_key)

    # On the legacy fixed_dollar engine, honour the per-strategy caps as absolute ceilings (back-compat).
    if (policy or {}).get("sizing_engine") != "percent_equity":
        live_rules = strategy_cfg.get("live_trade_rules", {})
        policy = dict(policy or {})
        policy.setdefault("max_notional_per_trade", float(live_rules.get("max_position_size", _ap.FALLBACK_SIZE_DOLLARS)))
        policy.setdefault("max_risk_dollars_per_trade",
                          min(float(live_rules.get("max_dollar_risk", _ap.FALLBACK_RISK_DOLLARS)),
                              float(shared_rules.get("risk_limits", {}).get("default_risk_per_trade", _ap.FALLBACK_RISK_DOLLARS))))

    # Per-strategy allocation tilt (operator 2026-06-19): winning strategies risk more (capped at the
    # position cap; momentum_scalp excluded). Default ON; STRATEGY_TILT=0 disables.
    _tilt = 1.0
    try:
        import strategy_tilt as _stilt
        if _stilt.enabled():
            _tilt = _stilt.get_tilt(signal.get("strategy_id"))
    except Exception:
        pass
    # Volatility-aware risk down-shift (operator-approved 2026-07-03, mirrors the card's wide-stop
    # note): a wide stop means the same $ risk buys outsized exposure to noise — scale the RISK
    # budget down via tilt (position cap untouched). >7% stop → ×0.75, >10% → ×0.5.
    _vol_factor = 1.0
    _stop_pct = abs(entry - stop) / entry * 100 if entry > 0 else 0
    if _stop_pct > 10:
        _vol_factor = 0.5
    elif _stop_pct > 7:
        _vol_factor = 0.75
    s = _ap.compute_sizing(policy, equity, entry, stop, desired_shares=None, tilt=_tilt * _vol_factor)
    if not s.get("valid"):
        return {"valid": False, "reason": s.get("reason", "SIZE_TOO_SMALL"),
                "original_shares": original_shares,
                "max_shares_by_size": s.get("max_shares_by_size"),
                "max_shares_by_risk": s.get("max_shares_by_risk")}

    adjusted_shares = s["shares"]
    risk_per_share = s["risk_per_share"]
    sizing_adjusted = adjusted_shares != original_shares
    sizing_reason = None
    if sizing_adjusted:
        sizing_reason = (f"{s['engine']}: {s['binding']} "
                         f"(eq=${s['equity']:,.0f} risk%={s['risk_pct']} pos%={s['pos_pct']})")
    rr = round((float(signal.get("target_1") or 0) - entry) / risk_per_share, 2) if risk_per_share > 0 else 0

    return {
        "valid": True,
        "original_shares": original_shares,
        "adjusted_shares": adjusted_shares,
        "original_dollar_size": round(original_shares * entry, 2),
        "adjusted_dollar_size": s["dollar_size"],
        "original_dollar_risk": round(original_shares * risk_per_share, 2),
        "adjusted_dollar_risk": s["dollar_risk"],
        "sizing_adjusted": sizing_adjusted,
        "sizing_reason": sizing_reason,
        "stop_pct": s["stop_pct"],
        "rr": rr,
        "sizing_basis": {
            "engine": s["engine"], "equity": s["equity"], "equity_source": eq_src,
            "risk_pct": s["risk_pct"], "pos_pct": s["pos_pct"],
            "max_dollar_risk": s["max_dollar_risk"], "max_dollar_size": s["max_dollar_size"],
            "binding": s["binding"], "tilt": s.get("tilt", 1.0), "account_key": account_key,
            "vol_factor": _vol_factor, "vol_stop_pct": round(_stop_pct, 1),
        },
    }


def check_risk_gate(conn, symbol: str, strategy_id: str, plan: dict) -> dict:
    """Run risk gate precheck. Returns {approved, result, codes}."""
    try:
        from risk_gate import RiskGate
        gate = RiskGate(conn)
        decision = gate.check(
            symbol=symbol,
            strategy_id=strategy_id,
            trade_plan=plan,
            account=_resolve_proposal_account(),
            mode="paper",
            action_context="paper_proposal",
        )
        return {
            "approved": decision.approved,
            "result": decision.result,
            "codes": decision.reason_codes,
        }
    except Exception as e:
        log.warning(f"  {symbol}: risk gate error — {e}")
        return {"approved": False, "result": "RISK_GATE_ERROR", "codes": [str(e)]}


def check_quality(signal: dict, sizing: dict) -> tuple:
    """Quality filter. Returns (pass, reason_codes)."""
    reasons = []
    score = int(signal.get("signal_score") or 0)
    rr = sizing.get("rr", 0)
    entry = float(signal.get("entry_high") or 0)
    stop = float(signal.get("stop_loss") or 0)
    target = float(signal.get("target_1") or 0)

    if score < 40:
        reasons.append("LOW_SCORE")
    if rr < 1.2:
        reasons.append("BAD_RR")
    if entry <= 0 or stop <= 0 or target <= 0:
        reasons.append("NO_PLAN")
    if stop >= entry:
        reasons.append("PRICE_ORDER_INVALID")
    if target <= entry:
        reasons.append("TARGET_BELOW_ENTRY")

    # Source cap: reject social-only or youtube-only
    source = (signal.get("discovery_source") or "").lower()
    if source in ("social", "stocktwits", "reddit") and not signal.get("catalyst_verified"):
        reasons.append("SOURCE_CAP_SOCIAL_ONLY")

    return len(reasons) == 0, reasons


def _proposal_instrument_type(conn, symbol):
    """Stamp the proposal with the symbol's instrument_type (stock/etf/fund/inverse_etf) so the pipeline is
    instrument-aware. Defaults to 'stock' if unknown."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT instrument_type FROM symbol_profiles WHERE upper(symbol)=%s", ((symbol or "").upper(),))
        r = cur.fetchone()
        return (r[0] if r and r[0] else "stock")
    except Exception:
        return "stock"


def _proposal_cio_view(conn, symbol):
    """Stamp the latest CIO holistic verdict (watchlist_final_synthesis.recommendation) so a momentum proposal
    for a name the CIO says AVOID is VISIBLE at review — advisory, never blocks (proposals are PENDING +
    operator-approved). Returns the recommendation string or None."""
    try:
        cur = conn.cursor()
        cur.execute("""SELECT recommendation FROM watchlist_final_synthesis WHERE upper(symbol)=%s
                       ORDER BY created_at DESC LIMIT 1""", ((symbol or "").upper(),))
        r = cur.fetchone()
        return (r[0] if r and r[0] else None)
    except Exception:
        return None


def create_auto_proposal(conn, signal: dict, sizing: dict, risk_gate: dict,
                         auto_run_id: int, available_cols: set,
                         auto_context: dict = None) -> int | None:
    """Insert a PENDING paper proposal. Returns proposal_id."""
    # PROMOTE-1: Pre-promotion readiness gate
    try:
        from pre_promotion_readiness_policy import evaluate_pre_promotion_readiness
        # Compute scan age from fired_at — screener signals have fresh price data from Finviz
        _scan_age = 0.5  # Default: assume recent
        _fired = signal.get("fired_at")
        if _fired and hasattr(_fired, 'timestamp'):
            try:
                _now = datetime.now(timezone.utc)
                _fa = _fired if _fired.tzinfo else _fired.replace(tzinfo=timezone.utc)
                _scan_age = max(0.01, (_now - _fa).total_seconds() / 3600)
            except Exception:
                pass

        _quote_age_h = None
        _quote_price = None
        try:
            from market_quote_provider import check_fresh_quote
            _fq = check_fresh_quote(signal.get("symbol"), strategy_id=signal.get("strategy_id"))
            if _fq.get("age_minutes") is not None:
                _quote_age_h = float(_fq["age_minutes"]) / 60.0
            _quote_price = _fq.get("last_price")
        except Exception:
            pass

        _pre = evaluate_pre_promotion_readiness({
            "symbol": signal.get("symbol"), "strategy_id": signal.get("strategy_id"),
            "proposed_entry": signal.get("entry_high"), "proposed_stop": signal.get("stop_loss"),
            "proposed_target1": signal.get("target_1"), "proposed_rr": signal.get("rr"),
            "catalyst": signal.get("catalyst"), "catalyst_verified": signal.get("catalyst_verified"),
            "discovery_source": "screener",
            "scan_age_hours": _scan_age,
            "quote_age_hours": _quote_age_h,
            "quote_price": _quote_price,
        })
        if _pre["blockers"]:
            log.warning(f"[auto_gen] BLOCKED by pre-promotion gate: {signal.get('symbol')} — {_pre['blockers']}")
            return None
    except Exception as _e:
        log.warning(f"[auto_gen] Pre-promotion check failed: {_e}")

    entry = float(signal.get("entry_high") or 0)
    stop = float(signal.get("stop_loss") or 0)
    target = float(signal.get("target_1") or 0)
    target2 = float(signal.get("target_2") or 0) if signal.get("target_2") else None
    shares = sizing["adjusted_shares"]
    # Session 24A: Strategy-aware expiry + strategy type stamp
    _strat = signal.get("strategy_id", "momentum_scalp")
    try:
        from proposal_lifecycle import (get_expiry_datetime, get_max_expiry_datetime,
                                        get_timeframe_class, get_strategy_metadata, is_overnight)
        _strat_meta = get_strategy_metadata(_strat)
        _now = datetime.now(timezone.utc)
        expires = get_expiry_datetime(_strat, _now)
        _max_expires = get_max_expiry_datetime(_strat, _now)
        _base_expires = expires
        _timeframe_class = _strat_meta.get("timeframe_class") or get_timeframe_class(_strat)
        _overnight = is_overnight(_strat)
    except Exception:
        _strat_meta = {}
        expires = datetime.now(timezone.utc) + timedelta(hours=4)
        _max_expires = expires
        _base_expires = expires
        _timeframe_class = "intraday"
        _overnight = False

    data = {
        "symbol": signal["symbol"],
        "strategy_id": signal.get("strategy_id", "momentum_scalp"),
        "setup_type": signal.get("setup_description"),
        "signal_score": signal.get("signal_score"),
        "signal_grade": signal.get("signal_grade"),
        "signal_decision": "GO",
        "source_signal_id": signal["id"],
        "rvol": signal.get("rvol"),
        "float_m": signal.get("float_m"),
        "gap_pct": signal.get("gap_pct"),
        "catalyst": (signal.get("catalyst") or "")[:200],
        "catalyst_verified": signal.get("catalyst_verified", False),
        "intel_readiness": signal.get("intel_readiness"),
        "proposed_entry": entry,
        "proposed_stop": stop,
        "proposed_target1": target,
        "proposed_target2": target2,
        "proposed_shares": shares,
        "proposed_dollar_size": sizing["adjusted_dollar_size"],
        "proposed_dollar_risk": sizing["adjusted_dollar_risk"],
        "proposed_stop_pct": sizing.get("stop_pct", 0),
        "proposed_rr": sizing.get("rr", 0),
        "risk_gate_result": risk_gate.get("result", "UNKNOWN"),
        "risk_gate_codes": json.dumps(risk_gate.get("codes", [])),
        "proposed_by": "auto_proposal_generator",
        "status": "PENDING",
        "instrument_type": _proposal_instrument_type(conn, signal.get("symbol")),
        "side": "long",  # screener momentum signals are long; ETF/short proposals come via the rotation path
        "cio_view": _proposal_cio_view(conn, signal.get("symbol")),  # advisory visibility of the CIO verdict
        "expires_at": expires,
        "base_expires_at": _base_expires,
        "max_expires_at": _max_expires,
        "lifecycle_status": "ACTIVE",
        "proposal_timeframe_class": _timeframe_class,
        "strategy_type": _strat_meta.get("strategy_type"),
        "overnight_monitoring_enabled": _overnight,
        "auto_created": True,
        "auto_proposal_run_id": auto_run_id,
        "sizing_adjusted": sizing.get("sizing_adjusted", False),
        "original_shares": sizing.get("original_shares"),
        "adjusted_shares": sizing.get("adjusted_shares"),
        "sizing_reason": sizing.get("sizing_reason"),
        "sector": signal.get("sector"),
        "discovery_source": signal.get("discovery_source"),
        "discovery_trace_id": signal.get("discovery_trace_id"),  # P0-6: end-to-end lineage
        "setup_description": signal.get("setup_description"),
        "source_run_label": signal.get("scan_run_label"),
        "auto_execution_label": auto_context.get("execution_label", "manual") if auto_context else "manual",
        # Unified queue — broker-agnostic at creation; routing set at promote/approve
        "origin": "auto",
        "routing_state": "unassigned",
        "equity_at_proposal": (sizing.get("sizing_basis") or {}).get("equity"),
        "sizing_basis": json.dumps({
            **(sizing.get("sizing_basis") or {}),
            "unified_edge": _unified_edge_for_signal(signal, sizing),
        }),
    }

    # Filter to existing columns
    insert_data = {k: v for k, v in data.items() if k in available_cols and v is not None}
    cols_str = ", ".join(insert_data.keys())
    placeholders = ", ".join(["%s"] * len(insert_data))

    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO paper_trade_proposals ({cols_str}) VALUES ({placeholders}) RETURNING id",
        list(insert_data.values())
    )
    proposal_id = cur.fetchone()[0]

    # SP-2C: Generate route audit evidence
    try:
        from proposal_route_audit_integration import ensure_route_audit_for_proposal
        ensure_route_audit_for_proposal(
            conn, proposal_id, signal["symbol"],
            signal.get("strategy_id", ""),
            signal, source="auto_proposal_generator"
        )
    except Exception as _e:
        log.warning(f"[route_audit] Failed for proposal #{proposal_id}: {_e}")

    return proposal_id


def record_decision(conn, run_label: str, signal: dict, decision: str,
                     reason_codes: list, proposal_id: int | None,
                     sizing: dict | None, risk_gate: dict | None):
    """Record auto-proposal decision for diagnostics."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO auto_proposal_decisions
            (run_label, source_signal_id, symbol, strategy_id, decision, reason_codes,
             proposal_id, original_shares, adjusted_shares,
             original_dollar_size, adjusted_dollar_size,
             original_dollar_risk, adjusted_dollar_risk,
             risk_gate_result, risk_gate_codes, quality_pass, source_cap_pass)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, [
        run_label, signal.get("id"), signal["symbol"], signal.get("strategy_id"),
        decision, json.dumps(reason_codes),
        proposal_id,
        sizing.get("original_shares") if sizing else None,
        sizing.get("adjusted_shares") if sizing else None,
        sizing.get("original_dollar_size") if sizing else None,
        sizing.get("adjusted_dollar_size") if sizing else None,
        sizing.get("original_dollar_risk") if sizing else None,
        sizing.get("adjusted_dollar_risk") if sizing else None,
        risk_gate.get("result") if risk_gate else None,
        json.dumps(risk_gate.get("codes", [])) if risk_gate else None,
        "SOURCE_CAP" not in " ".join(reason_codes) if reason_codes else True,
        "SOURCE_CAP" not in " ".join(reason_codes) if reason_codes else True,
    ])


def run_auto_proposals(conn, run_label: str = None, symbol: str = None,
                       min_score: int = 40, limit: int = 20,
                       dry_run: bool = True,
                       execution_label: str = "manual",
                       force: bool = False,
                       max_risk_dollars: float | None = None,
                       trend_lookback_days: int = TREND_LOOKBACK_DAYS) -> dict:
    """Main auto-proposal generation. Returns audit summary."""
    shared_rules = _load_shared_risk_rules()
    proposal_cols = _get_available_cols(conn, "paper_trade_proposals")
    cur = conn.cursor()

    # Percent-of-equity sizing (operator 2026-06-19): resolve the account policy + live equity ONCE per
    # run (avoid per-signal broker calls), passed into normalize_size. Single source of truth = account_policy.
    import account_policy as _ap
    _size_account = _resolve_proposal_account()
    _size_policy = _ap.load_policy(_size_account)
    _size_equity, _size_equity_src = _ap.equity_for_account(_size_account)
    log.info(f"sizing engine={_size_policy.get('sizing_engine')} account={_size_account} "
             f"equity=${_size_equity:,.0f} ({_size_equity_src}) "
             f"risk%={_size_policy.get('risk_per_trade_pct')} pos%={_size_policy.get('max_position_allocation_pct')}")

    # Record run start
    auto_run_id = None
    if not dry_run:
        cur.execute("""
            INSERT INTO auto_proposal_runs (run_label, run_date, status, started_at,
                                            execution_label, source_run_label)
            VALUES (%s, CURRENT_DATE, 'RUNNING', NOW(), %s, %s) RETURNING id
        """, [run_label or "manual", execution_label, run_label])
        auto_run_id = cur.fetchone()[0]
        conn.commit()

    # ADVISORY cloud-review gate (default OFF — normal runs unchanged). When CLOUD_REVIEW=1, the first few
    # NEWLY-created proposals this run get an additive ChatGPT+Grok second-opinion on the local model's
    # reasoning (recorded only, never gates). Capped to bound latency (~10-30s/lane/call).
    _cloud_review_on = os.environ.get("CLOUD_REVIEW") == "1"
    _cloud_review_cap = 5
    _cloud_reviewed = 0

    signals = get_eligible_signals(conn, run_label=run_label, symbol=symbol, min_score=min_score)
    log.info(f"Found {len(signals)} eligible signals for auto-proposal")

    # Deduplicate: ONE signal per symbol. TILT-AWARE TIE-BREAK (operator 2026-06-19): when several
    # strategies flag the SAME symbol, award it to the highest TILT-WEIGHTED score (signal_score x the
    # strategy's live-performance multiplier) so winning strategies (e.g. fib_retracement_bounce at 1.5x)
    # win their overlapping symbols instead of always losing to fixed strategy priority. Strategy priority
    # is only the final tiebreak. momentum_scalp stays 1.0 (excluded from the tilt). Still walks past a
    # strategy whose liquidity gate rejects the symbol (operator 2026-06-15).
    _tilt_map = {}
    try:
        import strategy_tilt as _stilt
        if _stilt.enabled():
            for _sid in {s.get("strategy_id", "") for s in signals}:
                _tilt_map[_sid] = _stilt.get_tilt(_sid)
    except Exception:
        pass

    def _prio(s):
        sid = s.get("strategy_id", "")
        try:
            score = float(s.get("signal_score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        tilt = float(_tilt_map.get(sid, 1.0))
        prio = STRATEGY_PRIORITY.index(sid) if sid in STRATEGY_PRIORITY else 99
        edge = _unified_edge_for_signal(s)
        return (-(score * tilt + edge * 0.15), prio)   # tilt-weighted score + unified edge; priority breaks ties
    by_symbol = {}
    for sig in signals:
        by_symbol.setdefault(sig["symbol"], []).append(sig)
    deduped = []
    for sym, lst in by_symbol.items():
        lst.sort(key=_prio)
        chosen = lst[0]                       # default: top-priority strategy
        if not force:
            for cand in lst:                  # walk priority order; take first that clears liquidity
                ok, _r = _liquidity_prescreen(sym, shared_rules, cand.get("strategy_id"))
                if ok:
                    chosen = cand
                    break
        deduped.append(chosen)
    deduped.sort(key=lambda s: -(_unified_edge_for_signal(s) * 0.15 + float(s.get("signal_score") or 0)))
    if limit:
        deduped = deduped[:limit]

    stats = {
        "signals_checked": len(deduped),
        "proposals_created": 0,
        "proposals_skipped": 0,
        "duplicates_skipped": 0,
        "risk_rejected": 0,
        "liquidity_rejected": 0,
        "quality_rejected": 0,
        "source_cap_rejected": 0,
        "edge_floor_rejected": 0,
        "daily_cap_rejected": 0,
        "sizing_adjusted": 0,
        "errors": 0,
        "details": [],
    }

    min_edge = float(os.getenv("PROPOSAL_MIN_UNIFIED_EDGE", "0") or 0)
    daily_cap = int(os.getenv("PROPOSAL_DAILY_CAP_PER_STRATEGY", "0") or 0)
    strategy_today: dict[str, int] = {}
    if daily_cap > 0 and not dry_run:
        try:
            cur.execute(
                """SELECT strategy_id, COUNT(*) FROM paper_trade_proposals
                   WHERE created_at >= CURRENT_DATE AND origin = 'auto'
                   GROUP BY strategy_id"""
            )
            for sid_row, n in cur.fetchall():
                strategy_today[str(sid_row or "")] = int(n or 0)
        except Exception:
            pass

    for sig in deduped:
        sym = sig["symbol"]
        sid = sig.get("strategy_id", "momentum_scalp")
        sig_id = sig["id"]

        try:
            # 0. Fresh quote gate — Schwab/Alpaca/Polygon; swing relaxes to 24h outside RTH.
            _fresh_quote = None
            if not force:
                try:
                    from market_quote_provider import check_fresh_quote
                    _fresh_quote = check_fresh_quote(sym, strategy_id=sid)
                    if not _fresh_quote.get("ok"):
                        stats["proposals_skipped"] += 1
                        reason = f"SKIPPED_STALE_QUOTE ({_fresh_quote.get('reason')})"
                        log.info(f"  {sym}: {reason}")
                        if not dry_run:
                            record_decision(conn, run_label, sig, "SKIPPED_STALE_QUOTE",
                                            [_fresh_quote.get("reason", "")], None, None, None)
                        stats["details"].append({"symbol": sym, "decision": "SKIPPED_STALE_QUOTE", "reason": reason})
                        continue
                except Exception as exc:
                    stats["proposals_skipped"] += 1
                    reason = f"SKIPPED_QUOTE_ERROR ({exc})"
                    log.info(f"  {sym}: {reason}")
                    if not dry_run:
                        record_decision(conn, run_label, sig, "SKIPPED_QUOTE_ERROR", [str(exc)], None, None, None)
                    stats["details"].append({"symbol": sym, "decision": "SKIPPED_QUOTE_ERROR", "reason": reason})
                    continue

            # 0a. Regular-hours gate for intraday — bypass when fresh extended-hours quote exists.
            if not force and not (_fresh_quote and _fresh_quote.get("ok")):
                try:
                    from proposal_lifecycle import get_timeframe_class as _gtc
                    _is_intraday = _gtc(sid) == "intraday"
                except Exception:
                    _is_intraday = sid in ("momentum_scalp", "gap_and_go")
                if _is_intraday:
                    from market_session import current_market_session
                    _sess = current_market_session()
                    if _sess != "regular":
                        stats["proposals_skipped"] += 1
                        reason = f"SKIPPED_OUTSIDE_RTH ({sid}: market {_sess}, no fresh quote)"
                        log.info(f"  {sym}: {reason}")
                        if not dry_run:
                            record_decision(conn, run_label, sig, "SKIPPED_OUTSIDE_RTH", [reason], None, None, None)
                        stats["details"].append({"symbol": sym, "decision": "SKIPPED_OUTSIDE_RTH", "reason": reason})
                        continue

            # 0b. Strategy performance gate (operator 2026-06-19, Task 4): a strategy with a real losing
            # record (>=10 closed paper trades at <25% WR) stops generating proposals until its edge
            # recovers; <5 closed = always eligible. Read-only, fail-open, DORMANT today (no strategy qualifies).
            try:
                import strategy_utils as _su
                _gok, _greason = _su.is_strategy_promotable(sid, conn)
                if not _gok:
                    stats["proposals_skipped"] += 1
                    reason = f"SKIPPED_STRATEGY_GATE ({_greason})"
                    log.info(f"  {sym}: {reason}")
                    _su.log_suppression(conn, sym, sid, _greason)
                    if not dry_run:
                        record_decision(conn, run_label, sig, "SKIPPED_STRATEGY_GATE", [_greason], None, None, None)
                    stats["details"].append({"symbol": sym, "decision": "SKIPPED_STRATEGY_GATE", "reason": reason})
                    continue
            except Exception:
                pass

            # 1. Duplicate check
            dup = check_duplicate(conn, sig_id, sym, sid)
            if dup:
                stats["duplicates_skipped"] += 1
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_DUPLICATE (proposal #{dup['id']} {dup['status']})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_DUPLICATE", [reason], None, None, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_DUPLICATE", "reason": reason})
                continue

            # 2. Open trade check
            open_trade = check_open_paper_trade(conn, sym, sid)
            if open_trade:
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_OPEN_TRADE (trade #{open_trade['id']} {open_trade['status']})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_OPEN_TRADE", [reason], None, None, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_OPEN_TRADE", "reason": reason})
                continue

            # 2a. Recently closed trade cooldown (48h, any strategy)
            closed_block = check_recently_closed(conn, sym, sid, cooldown_hours=48)
            if closed_block:
                stats["proposals_skipped"] += 1
                reason = f"{closed_block['reason']} ({closed_block['detail']})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, closed_block["reason"], [closed_block["detail"]], None, None, None)
                stats["details"].append({"symbol": sym, "decision": closed_block["reason"], "reason": reason})
                continue

            # 2b. Rejection cooldown check (24h)
            cooldown = check_rejection_cooldown(conn, sym, force=force)
            if cooldown:
                stats["proposals_skipped"] += 1
                reason = f"{cooldown['reason']} ({cooldown['detail']})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, cooldown["reason"], [cooldown["detail"]], None, None, None)
                stats["details"].append({"symbol": sym, "decision": cooldown["reason"], "reason": reason})
                continue

            # 2c. Scan decision gate (trend bridge uses lookback GO/A+, not today's AVOID rerate)
            _trend_q = "rotation" in (execution_label or "") or "trend" in (execution_label or "")
            scan_block = check_scan_decision(
                conn, sym, trend_qualified=_trend_q,
                lookback_days=trend_lookback_days if _trend_q else 7,
            )
            if scan_block:
                stats["proposals_skipped"] += 1
                reason = f"{scan_block['reason']} ({scan_block['detail']})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, scan_block["reason"], [scan_block["detail"]], None, None, None)
                stats["details"].append({"symbol": sym, "decision": scan_block["reason"], "reason": reason})
                continue

            # 2d. Strategy criteria hard validation
            passes, fail_reason, fallback_sid = _validate_against_strategy_criteria(sid, sig)
            if not passes:
                if fallback_sid:
                    passes2, _, _ = _validate_against_strategy_criteria(fallback_sid, sig)
                    if passes2:
                        log.info(f"  {sym}: {sid} fails ({fail_reason}), reassigned to {fallback_sid}")
                        sid = fallback_sid
                        sig['strategy_id'] = fallback_sid
                    else:
                        stats["proposals_skipped"] += 1
                        reason = f"SKIPPED_STRATEGY_CRITERIA ({sid}: {fail_reason})"
                        log.info(f"  {sym}: {reason}")
                        if not dry_run:
                            record_decision(conn, run_label, sig, "SKIPPED_STRATEGY_CRITERIA", [fail_reason], None, None, None)
                        stats["details"].append({"symbol": sym, "decision": "SKIPPED_STRATEGY_CRITERIA", "reason": reason})
                        continue
                else:
                    stats["proposals_skipped"] += 1
                    reason = f"SKIPPED_STRATEGY_CRITERIA ({sid}: {fail_reason})"
                    log.info(f"  {sym}: {reason}")
                    if not dry_run:
                        record_decision(conn, run_label, sig, "SKIPPED_STRATEGY_CRITERIA", [fail_reason], None, None, None)
                    stats["details"].append({"symbol": sym, "decision": "SKIPPED_STRATEGY_CRITERIA", "reason": reason})
                    continue

            # 2e. Liquidity pre-screen. P0-4: INTRADAY (momentum_scalp) is FAIL-CLOSED — unknown
            # liquidity DEFERS (no proposal) rather than failing open. force bypasses only in
            # dry-run / manual / operator mode, and is ALWAYS logged (never a silent proceed).
            if force:
                _intraday = _is_intraday_strategy(sid)
                if _intraday and not (dry_run or execution_label in ("manual", "operator")):
                    log.warning(f"  {sym}: FORCE_BYPASS_LIQUIDITY (intraday {sid}, "
                                f"execution_label={execution_label}) — operator-explicit liquidity bypass")
                elif _intraday:
                    log.info(f"  {sym}: liquidity prescreen bypassed via force "
                             f"({sid}, dry_run={dry_run}, execution_label={execution_label})")
            else:
                liq_ok, liq_reason = _liquidity_prescreen(sym, shared_rules, sid)
                if not liq_ok:
                    _defer = liq_reason.startswith("DEFER_LIQUIDITY_UNKNOWN")
                    _dcode = "DEFER_LIQUIDITY_UNKNOWN" if _defer else "SKIPPED_LIQUIDITY"
                    stats["liquidity_rejected"] += 1
                    stats["proposals_skipped"] += 1
                    reason = f"{_dcode} ({sym}: {liq_reason})"
                    log.info(f"  {sym}: {reason}")
                    if not dry_run:
                        record_decision(conn, run_label, sig, _dcode, [liq_reason], None, None, None)
                    stats["details"].append({"symbol": sym, "decision": _dcode, "reason": reason})
                    continue

            # 2f. Analyst gate — equities need rating + price target (ETFs exempt).
            if not force:
                try:
                    from analyst_coverage import check_analyst_gate
                    _an_ok, _an_reason, _an_snap = check_analyst_gate(conn, sym, fetch_if_missing=True)
                    if not _an_ok:
                        stats["proposals_skipped"] += 1
                        reason = f"SKIPPED_NO_ANALYST ({_an_reason})"
                        log.info(f"  {sym}: {reason}")
                        if not dry_run:
                            record_decision(conn, run_label, sig, "SKIPPED_NO_ANALYST", [_an_reason], None, None, None)
                        stats["details"].append({"symbol": sym, "decision": "SKIPPED_NO_ANALYST", "reason": reason})
                        continue
                    if _an_snap:
                        sig["_analyst_snapshot"] = _an_snap
                except Exception as exc:
                    stats["proposals_skipped"] += 1
                    reason = f"SKIPPED_ANALYST_ERROR ({exc})"
                    log.info(f"  {sym}: {reason}")
                    if not dry_run:
                        record_decision(conn, run_label, sig, "SKIPPED_ANALYST_ERROR", [str(exc)], None, None, None)
                    stats["details"].append({"symbol": sym, "decision": "SKIPPED_ANALYST_ERROR", "reason": reason})
                    continue

            # 3. Normalize sizing (percent-of-equity; run-level policy + equity)
            strategy_cfg = _load_strategy_config(sid)
            sizing = normalize_size(sig, strategy_cfg, shared_rules,
                                    account_key=_size_account, equity=_size_equity, policy=_size_policy)
            if max_risk_dollars:
                sizing = _cap_sizing_risk(sizing, float(max_risk_dollars))
            if not sizing.get("valid"):
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_SIZE ({sizing.get('reason')})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_SIZE", [sizing.get("reason", "")], None, sizing, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_SIZE", "reason": reason})
                continue

            if sizing.get("sizing_adjusted"):
                stats["sizing_adjusted"] += 1
                log.info(f"  {sym}: sizing adjusted {sizing['original_shares']}→{sizing['adjusted_shares']} shares ({sizing.get('sizing_reason')})")

            # 3b. Unified edge floor + per-strategy daily cap (noise filter)
            edge_score = _unified_edge_for_signal(sig, sizing)
            if min_edge > 0 and edge_score < min_edge and not force:
                stats["edge_floor_rejected"] += 1
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_EDGE_FLOOR ({edge_score:.1f} < {min_edge:.1f})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_EDGE_FLOOR",
                                    [f"unified_edge {edge_score:.1f} < {min_edge:.1f}"], None, sizing, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_EDGE_FLOOR", "reason": reason})
                continue
            if daily_cap > 0 and strategy_today.get(sid, 0) >= daily_cap and not force:
                stats["daily_cap_rejected"] += 1
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_DAILY_CAP ({sid}: {strategy_today.get(sid, 0)}/{daily_cap})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_DAILY_CAP",
                                    [f"{sid} daily cap {daily_cap}"], None, sizing, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_DAILY_CAP", "reason": reason})
                continue

            # 4. Quality check
            q_pass, q_reasons = check_quality(sig, sizing)
            if not q_pass:
                source_cap = any("SOURCE_CAP" in r for r in q_reasons)
                if source_cap:
                    stats["source_cap_rejected"] += 1
                else:
                    stats["quality_rejected"] += 1
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_QUALITY ({', '.join(q_reasons)})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_QUALITY", q_reasons, None, sizing, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_QUALITY", "reason": reason})
                continue

            # 5. Risk gate precheck
            plan_for_gate = {
                "stop_loss": float(sig.get("stop_loss") or 0),
                "dollar_size": sizing["adjusted_dollar_size"],
                "dollar_risk": sizing["adjusted_dollar_risk"],
            }
            rg = check_risk_gate(conn, sym, sid, plan_for_gate)
            if not rg["approved"]:
                stats["risk_rejected"] += 1
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_RISK_GATE ({rg['result']}: {', '.join(rg.get('codes', []))})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_RISK_GATE", rg.get("codes", []), None, sizing, rg)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_RISK_GATE", "reason": reason})
                continue

            # 6. Create proposal
            if dry_run:
                log.info(f"  {sym}: WOULD CREATE proposal — {sid} score={sig.get('signal_score')} "
                         f"entry=${float(sig.get('entry_high') or 0):.2f} stop=${float(sig.get('stop_loss') or 0):.2f} "
                         f"shares={sizing['adjusted_shares']} risk=${sizing['adjusted_dollar_risk']:.0f} rr={sizing['rr']:.1f}")
                stats["proposals_created"] += 1
                stats["details"].append({"symbol": sym, "decision": "WOULD_CREATE", "strategy_id": sid,
                                         "shares": sizing["adjusted_shares"], "dollar_risk": sizing["adjusted_dollar_risk"]})
            else:
                proposal_id = create_auto_proposal(conn, sig, sizing, rg, auto_run_id, proposal_cols,
                                                   auto_context={"execution_label": execution_label})
                conn.commit()
                if not proposal_id:
                    # create_auto_proposal returns None when the pre-promotion gate blocks the insert
                    # (e.g. rr_below_minimum: 1.99 < 2.0). It was NOT created — count it as skipped, log
                    # honestly, and do NOT enrich/alert a null id. (bugfix 2026-06-15: QMCO #None)
                    stats["proposals_skipped"] += 1
                    log.info(f"  {sym}: SKIPPED_PREPROMOTION — gate blocked the insert (no proposal created)")
                    record_decision(conn, run_label, sig, "SKIPPED_PREPROMOTION",
                                    ["pre-promotion gate blocked"], None, sizing, rg)
                    conn.commit()
                    stats["details"].append({"symbol": sym, "decision": "SKIPPED_PREPROMOTION", "strategy_id": sid})
                    continue
                record_decision(conn, run_label, sig, "CREATED", [], proposal_id, sizing, rg)
                conn.commit()
                stats["proposals_created"] += 1
                strategy_today[sid] = strategy_today.get(sid, 0) + 1
                log.info(f"  {sym}: CREATED proposal #{proposal_id} — {sid} score={sig.get('signal_score')} "
                         f"shares={sizing['adjusted_shares']} risk=${sizing['adjusted_dollar_risk']:.0f}")
                stats["details"].append({"symbol": sym, "decision": "CREATED", "proposal_id": proposal_id,
                                         "strategy_id": sid, "shares": sizing["adjusted_shares"]})

                # Session 23: kick off enrichment pipeline in background
                _enrich_proposal_async(proposal_id, sym)

                # Real-time Telegram alert — fire immediately, non-blocking
                _send_proposal_alert_async(proposal_id, sym)

                # ADVISORY cloud review of the LOCAL model's proposal reasoning (additive, recorded only).
                # Gated by CLOUD_REVIEW=1, capped per run, newly-created proposals only. Never gates/blocks.
                if _cloud_review_on and _cloud_reviewed < _cloud_review_cap:
                    _cloud_reviewed += 1
                    _cloud_review_proposal(sig, sizing, proposal_id)

        except Exception as e:
            stats["errors"] += 1
            stats["proposals_skipped"] += 1
            log.error(f"  {sym}: ERROR — {e}")
            stats["details"].append({"symbol": sym, "decision": "ERROR", "error": str(e)})
            if not dry_run:
                try:
                    record_decision(conn, run_label, sig, "ERROR", [str(e)], None, None, None)
                    conn.commit()
                except Exception:
                    conn.rollback()

    # Post-run: rank proposals per symbol (Phase 6)
    if not dry_run:
        created_symbols = set(d["symbol"] for d in stats["details"] if d.get("decision") == "CREATED")
        for sym in created_symbols:
            try:
                rank_proposals_for_symbol(conn, sym, window_hours=24)
            except Exception as e:
                log.warning(f"[ranker] Failed to rank {sym}: {e}")

    # Finalize run record
    if not dry_run and auto_run_id:
        reason_summary = {}
        for d in stats["details"]:
            dec = d.get("decision", "UNKNOWN")
            reason_summary[dec] = reason_summary.get(dec, 0) + 1
        cur.execute("""
            UPDATE auto_proposal_runs
            SET status = 'COMPLETED',
                signals_checked = %s, proposals_created = %s, proposals_skipped = %s,
                duplicates_skipped = %s, risk_rejected = %s, quality_rejected = %s,
                source_cap_rejected = %s, sizing_adjusted = %s,
                reason_summary = %s, finished_at = NOW()
            WHERE id = %s
        """, [
            stats["signals_checked"], stats["proposals_created"], stats["proposals_skipped"],
            stats["duplicates_skipped"], stats["risk_rejected"], stats["quality_rejected"],
            stats["source_cap_rejected"], stats["sizing_adjusted"],
            json.dumps(reason_summary), auto_run_id,
        ])
        conn.commit()

    log.info(f"\nAuto-proposal summary: checked={stats['signals_checked']} "
             f"created={stats['proposals_created']} skipped={stats['proposals_skipped']} "
             f"(dup={stats['duplicates_skipped']} risk={stats['risk_rejected']} "
             f"quality={stats['quality_rejected']} source_cap={stats['source_cap_rejected']} "
             f"sizing_adj={stats['sizing_adjusted']})")

    # MONITOR (operator 2026-06-15): surface "0 proposals on a trading day despite eligible signals" so
    # an empty proposal queue never goes unnoticed — fires a warning → SIEM/Telegram with the filter
    # breakdown (why each candidate was dropped). Only on weekdays; quiet when there were no candidates.
    try:
        import datetime as _dt
        if (not dry_run and stats.get("proposals_created", 0) == 0
                and stats.get("signals_checked", 0) > 0 and _dt.datetime.now().weekday() < 5):
            bd = {k: stats.get(k, 0) for k in ("liquidity_rejected", "risk_rejected", "quality_rejected",
                                               "source_cap_rejected", "duplicates_skipped") if stats.get(k, 0)}
            msg = (f"[auto-proposals] 0 proposals from {stats['signals_checked']} eligible signal(s) "
                   f"(run {run_label}) — all filtered: {bd or 'pre-promotion/sizing/strategy-criteria'}")
            from alert_event_writer import save_alert_event
            save_alert_event(alert_type="strategic_alert", severity="warning",
                             source_script="auto_proposal_generator.py", symbol=None, raw_text=msg,
                             parsed_payload={"kind": "zero_proposals", "run_label": run_label,
                                             "signals_checked": stats["signals_checked"], "breakdown": bd})
            log.info(f"  [monitor] {msg}")
    except Exception:
        pass

    # P0-5: optional momentum_scalp paper fast-path after generation (default OFF; env-gated,
    # paper-only, idempotent). No-op unless MOMENTUM_SCALP_PAPER_FAST_PATH=1. Never touches live.
    try:
        from momentum_scalp_paper_fast_path import maybe_run_after_generation
        _fp = maybe_run_after_generation(dry_run=dry_run)
        if _fp:
            stats["momentum_scalp_paper_fast_path"] = {
                "mode": _fp.get("mode"), "would_submit_paper": _fp.get("would_submit_paper"),
                "paper_submitted_symbols": _fp.get("paper_submitted_symbols")}
            log.info(f"  [fast-path] momentum_scalp paper fast-path: {_fp.get('mode')} "
                     f"submit={_fp.get('would_submit_paper')}")
    except Exception as _e:
        log.debug(f"momentum_scalp fast-path hook skipped: {_e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Auto-generate PENDING paper proposals from strategy signals")
    parser.add_argument("--run-label", type=str, help="Filter by run label")
    parser.add_argument("--today", action="store_true", help="Process all today's signals")
    parser.add_argument("--symbol", type=str, help="Process single symbol")
    parser.add_argument("--apply", action="store_true", help="Actually create proposals (default is dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    parser.add_argument("--limit", type=int, default=20, help="Max proposals to create")
    parser.add_argument("--min-score", type=int, default=40, help="Minimum signal score")
    parser.add_argument("--force", action="store_true", help="Override rejection cooldown")
    args = parser.parse_args()

    if not args.run_label and not args.today and not args.symbol:
        print("Usage: --run-label 1000 or --today or --symbol MNKD")
        print("       Add --apply to actually create proposals")
        sys.exit(1)

    dry_run = not args.apply
    conn = get_conn()
    try:
        result = run_auto_proposals(
            conn,
            run_label=args.run_label,
            symbol=args.symbol,
            min_score=args.min_score,
            limit=args.limit,
            dry_run=dry_run,
            force=args.force,
        )
        print(json.dumps({k: v for k, v in result.items() if k != "details"}, indent=2, default=str))
        if result.get("details"):
            print("\nDetails:")
            for d in result["details"]:
                print(f"  {d.get('symbol','?')}: {d.get('decision','?')} {d.get('reason','')}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
