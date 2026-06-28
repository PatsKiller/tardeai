#!/usr/bin/env python3
"""P1-1: Social / Momentum Scalp lifecycle funnel report.

Proves the discovery → scan → proposal → paper order → closed outcome funnel with real
counts and conversion rates, separated by family (social-only vs momentum_scalp vs
meme_squeeze_momentum). Read-only — NO broker writes. Missing tables/columns degrade to
WARN with the missing source named, never a crash.

    python3 scripts/scalp_lifecycle_funnel_report.py --days 30 --json
    python3 scripts/scalp_lifecycle_funnel_report.py --days 30 --markdown > docs/diligence/current/SCALP_LIFECYCLE_FUNNEL.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Validation gate (kept in sync with momentum_scalp.yaml validation_gate).
GATE = {"min_closed_paper_trades": 30, "min_win_rate": 0.50,
        "min_profit_factor": 1.30, "min_calendar_months": 6}


def _conn():
    from db_adapter import get_connection
    return get_connection()


def _scalar(cur, sql, params=None):
    """Run a scalar query; return (value, None) or (None, error_str) on missing table/column."""
    try:
        cur.execute(sql, params or [])
        row = cur.fetchone()
        return (row[0] if row else 0), None
    except Exception as e:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        return None, str(e).splitlines()[0][:120]


def build_funnel(days: int = 30) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []
    stages: list[dict] = []
    try:
        conn = _conn()
        cur = conn.cursor()
    except Exception as e:
        return {"ok": False, "status": "WARN", "generated_at": started,
                "warnings": [f"no database: {e}"], "stages": [],
                "note": "Read-only funnel report. No broker writes."}

    since = f"NOW() - INTERVAL '{int(days)} days'"

    def stage(key, label, sql, params=None):
        val, err = _scalar(cur, sql, params)
        if err:
            warnings.append(f"{key}: {err}")
        stages.append({"key": key, "label": label, "count": val, "available": err is None})
        return val

    # ── Discovery → scan ──
    stage("social_posts", "Social posts ingested",
          f"SELECT COUNT(*) FROM social_posts WHERE ingested_at > {since}")
    stage("unique_tickers", "Unique tickers mentioned",
          f"SELECT COUNT(DISTINCT sym) FROM (SELECT jsonb_array_elements_text(symbols_mentioned) AS sym "
          f"FROM social_posts WHERE ingested_at > {since} AND jsonb_typeof(symbols_mentioned)='array') t")
    stage("scalp_scans", "Social scalp scan rows",
          f"SELECT COUNT(*) FROM scalp_scan_results WHERE scanned_at > {since}")
    stage("scalp_alerted", "Scalp scans alerted (final GO)",
          f"SELECT COUNT(*) FROM scalp_scan_results WHERE scanned_at > {since} AND alerted IS TRUE")
    stage("scalp_traced", "Scalp scans with discovery_trace_id",
          f"SELECT COUNT(*) FROM scalp_scan_results WHERE scanned_at > {since} AND discovery_trace_id IS NOT NULL")

    # ── Final-decision distribution (capped decisions) ──
    for dec in ("GO", "WAIT", "AVOID"):
        stage(f"decision_{dec.lower()}", f"Scalp final decision = {dec}",
              f"SELECT COUNT(*) FROM scalp_scan_results WHERE scanned_at > {since} AND decision = %s", [dec])

    # ── Scan → signals → proposals (momentum_scalp family) ──
    stage("trade_ai_scans", "trade_ai_scans rows (scalp-eligible)",
          f"SELECT COUNT(*) FROM trade_ai_scans WHERE scanned_at > {since}")
    stage("signals_scalp", "strategy_signals (momentum_scalp)",
          f"SELECT COUNT(*) FROM strategy_signals WHERE fired_at > {since} AND strategy_id = 'momentum_scalp'")
    stage("proposals_scalp", "Proposals (momentum_scalp)",
          f"SELECT COUNT(*) FROM paper_trade_proposals WHERE created_at > {since} AND strategy_id = 'momentum_scalp'")
    stage("proposals_expired_intraday", "Proposals expired on intraday TTL",
          f"SELECT COUNT(*) FROM paper_trade_proposals WHERE created_at > {since} "
          f"AND strategy_id = 'momentum_scalp' AND lifecycle_status = 'EXPIRED_INTRADAY'")
    stage("proposals_approved", "Proposals approved for paper",
          f"SELECT COUNT(*) FROM paper_trade_proposals WHERE created_at > {since} "
          f"AND strategy_id = 'momentum_scalp' AND status IN ('APPROVED_FOR_PAPER_TEST','BROKER_SUBMITTED')")

    # ── Paper orders + closed outcomes ──
    opened = stage("paper_opened", "Paper trades opened (momentum_scalp)",
                   f"SELECT COUNT(*) FROM paper_trades WHERE entry_time > {since} AND strategy_id = 'momentum_scalp'")
    closed = stage("paper_closed", "Paper trades closed (momentum_scalp)",
                   f"SELECT COUNT(*) FROM paper_trades WHERE entry_time > {since} "
                   f"AND strategy_id = 'momentum_scalp' AND status = 'closed'")
    wins = stage("paper_wins", "Closed winners (momentum_scalp)",
                 f"SELECT COUNT(*) FROM paper_trades WHERE entry_time > {since} "
                 f"AND strategy_id = 'momentum_scalp' AND status = 'closed' AND pnl > 0")

    # Profit factor (gross win / gross loss)
    gw, _ = _scalar(cur, f"SELECT COALESCE(SUM(pnl),0) FROM paper_trades WHERE entry_time > {since} "
                         f"AND strategy_id='momentum_scalp' AND status='closed' AND pnl > 0")
    gl, _ = _scalar(cur, f"SELECT COALESCE(SUM(pnl),0) FROM paper_trades WHERE entry_time > {since} "
                         f"AND strategy_id='momentum_scalp' AND status='closed' AND pnl < 0")
    win_rate = (wins / closed) if (closed and wins is not None) else None
    profit_factor = (float(gw) / abs(float(gl))) if (gl not in (None, 0) and gw is not None) else None

    # ── Rejected / deferred reason breakdown ──
    rej_rows, rej_err = [], None
    try:
        cur.execute(f"SELECT decision, COUNT(*) FROM auto_proposal_decisions "
                    f"WHERE created_at > {since} AND strategy_id = 'momentum_scalp' "
                    f"GROUP BY decision ORDER BY COUNT(*) DESC")
        rej_rows = [{"decision": r[0], "count": r[1]} for r in cur.fetchall()]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        rej_err = str(e).splitlines()[0][:120]
        warnings.append(f"reject_reasons: {rej_err}")

    # ── Conversion rates between adjacent meaningful stages ──
    def conv(numer_key, denom_key):
        n = next((s["count"] for s in stages if s["key"] == numer_key), None)
        d = next((s["count"] for s in stages if s["key"] == denom_key), None)
        if n is None or not d:
            return None
        return round(n / d, 4)

    conversions = {
        "scan_to_signal": conv("signals_scalp", "scalp_scans"),
        "signal_to_proposal": conv("proposals_scalp", "signals_scalp"),
        "proposal_to_approved": conv("proposals_approved", "proposals_scalp"),
        "approved_to_opened": conv("paper_opened", "proposals_approved"),
        "opened_to_closed": conv("paper_closed", "paper_opened"),
    }

    # ── Validation gate ──
    gate_met = bool(
        closed is not None and closed >= GATE["min_closed_paper_trades"]
        and win_rate is not None and win_rate >= GATE["min_win_rate"]
        and profit_factor is not None and profit_factor >= GATE["min_profit_factor"]
    )
    months_observed = None  # requires a span query; reported as unknown until 6mo of data exists

    status = "PASS" if not warnings else "WARN"
    return {
        "ok": True,
        "status": status,
        "generated_at": started,
        "window_days": days,
        "stages": stages,
        "families": {
            "social_only": {"note": "watch_only/WAIT — advisory, not auto-tradeable"},
            "momentum_scalp": {"opened": opened, "closed": closed, "wins": wins,
                               "win_rate": win_rate, "profit_factor": profit_factor},
            "meme_squeeze_momentum": {"note": "manual-review route — no auto proposals"},
        },
        "conversions": conversions,
        "reject_deferred_reasons": rej_rows,
        "validation_gate": {
            **GATE,
            "closed_paper_trades": closed,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "calendar_months_observed": months_observed,
            "gate_met": gate_met,
            "live_ready_claim": False,  # NEVER claim live-readiness from this report
            "status_note": ("Validation gate NOT met — momentum_scalp remains TESTING (paper only)."
                            if not gate_met else
                            "Trade-count/win/PF thresholds met on available data; 6-month calendar "
                            "span + human approval still required before any promotion."),
        },
        "warnings": warnings,
        "note": "Read-only funnel report. No broker writes. LLMs advisory only.",
    }


def to_markdown(rep: dict) -> str:
    L = ["# Scalp Lifecycle Funnel", "",
         f"**Status: {rep['status']}**  ",
         f"_Generated: {rep['generated_at']} | window: {rep.get('window_days')}d_  ",
         "_Source: `python3 scripts/scalp_lifecycle_funnel_report.py --days N --json`_  ",
         "", "Read-only. No broker writes. Social-only signals are advisory (WATCH/WAIT) only.", ""]
    if not rep.get("stages"):
        L += ["", "> WARN: " + "; ".join(rep.get("warnings", ["no data"]))]
        return "\n".join(L)
    L += ["## Funnel stages", "", "| Stage | Count | Source |", "|-------|-------|--------|"]
    for s in rep["stages"]:
        cnt = s["count"] if s["count"] is not None else "—"
        L.append(f"| {s['label']} | {cnt} | {'ok' if s['available'] else 'MISSING'} |")
    L += ["", "## Conversion rates", "", "| Transition | Rate |", "|-----------|------|"]
    for k, v in rep["conversions"].items():
        L.append(f"| {k} | {('%.1f%%' % (v*100)) if v is not None else '—'} |")
    g = rep["validation_gate"]
    L += ["", "## Validation gate (momentum_scalp)", "",
          f"- Closed paper trades: **{g['closed_paper_trades']}** (need ≥ {g['min_closed_paper_trades']})",
          f"- Win rate: **{('%.1f%%' % (g['win_rate']*100)) if g['win_rate'] is not None else '—'}** "
          f"(need ≥ {int(g['min_win_rate']*100)}%)",
          f"- Profit factor: **{('%.2f' % g['profit_factor']) if g['profit_factor'] is not None else '—'}** "
          f"(need ≥ {g['min_profit_factor']})",
          f"- Calendar months observed: **{g['calendar_months_observed'] or 'unknown'}** "
          f"(need ≥ {g['min_calendar_months']})",
          f"- **Gate met: {g['gate_met']}** — {g['status_note']}",
          f"- Live-ready claim: **{g['live_ready_claim']}** (momentum_scalp is TESTING)"]
    if rep.get("reject_deferred_reasons"):
        L += ["", "## Rejected / deferred reasons", "", "| Decision | Count |", "|----------|-------|"]
        for r in rep["reject_deferred_reasons"]:
            L.append(f"| {r['decision']} | {r['count']} |")
    if rep.get("warnings"):
        L += ["", "## Warnings (missing sources)", ""] + [f"- {w}" for w in rep["warnings"]]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--out", default="data/runtime/scalp_lifecycle_funnel_latest.json")
    args = ap.parse_args()

    rep = build_funnel(args.days)
    try:
        out = ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=2, default=str))
    except Exception:
        pass

    if args.markdown:
        print(to_markdown(rep))
    elif args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(f"Scalp funnel: {rep['status']} ({len(rep.get('stages', []))} stages, "
              f"{len(rep.get('warnings', []))} warnings)")
        print(f"  gate_met={rep.get('validation_gate', {}).get('gate_met')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
