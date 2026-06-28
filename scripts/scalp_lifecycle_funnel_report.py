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
    # NOTE (operator decision 2026-06-28): momentum_scalp validation testing does NOT require human paper
    # approval — deterministic gates replace the approval queue. "Proposals approved for paper" is no
    # longer a REQUIRED conversion stage; it is reported for context only (legacy ATM path).
    stage("proposals_approved_legacy", "Proposals approved for paper (legacy ATM — NOT required)",
          f"SELECT COUNT(*) FROM paper_trade_proposals WHERE created_at > {since} "
          f"AND strategy_id = 'momentum_scalp' AND status IN ('APPROVED_FOR_PAPER_TEST','BROKER_SUBMITTED')")

    # ── Deterministic VALIDATION FAST-PATH metrics (replace approval as the conversion stage, P0-3/P0-4) ──
    fast_path = {}
    legacy_aliases = {}
    try:
        import momentum_scalp_validation_fast_path as _fp
        fpr = _fp.run(dry_run=True)
        if fpr.get("ok"):
            _cands = fpr.get("candidates", [])
            def _rc(code):
                return sum(1 for c in _cands if code in (c.get("reason_codes") or []))
            fast_path = {
                "validation_fast_path_candidates": fpr.get("candidates_evaluated", 0),
                "validation_fast_path_gate_pass": fpr.get("would_submit_validation", 0),
                "validation_fast_path_submitted": len(fpr.get("validation_submitted_symbols") or []),
                "validation_fast_path_deferred": fpr.get("would_defer", 0),
                "validation_fast_path_rejected": fpr.get("would_reject", 0),
                "validation_fast_path_stale_quote_rejects": _rc("STALE_QUOTE"),
                "validation_fast_path_large_float_scout_rejects":
                    _rc("ROUTE_BLOCKED_LARGE_FLOAT_SOCIAL_SCOUT") + _rc("ROUTE_BLOCKED_MEME_SQUEEZE_MOMENTUM"),
                "validation_fast_path_social_only_rejects": _rc("SOCIAL_ONLY") + _rc("ROUTE_BLOCKED_WATCH_ONLY"),
            }
            legacy_aliases = {k.replace("validation_", "paper_", 1): k for k in fast_path}
            for k, v in fast_path.items():
                stages.append({"key": k, "label": k.replace("_", " "), "count": v, "available": True})
    except Exception as e:
        warnings.append(f"validation_fast_path: {str(e).splitlines()[0][:100]}")

    # ── Paper orders + closed outcomes (P0-1: conservative TRUE attribution) ──
    # Operator correction 2026-06-28: prior counts over-attributed momentum_scalp paper trades
    # (counted cancelled/dedup rows as "opened" and an unlinked direct-label row as confirmed).
    # We now count ONLY executed paper_trades with priority-1 strategy_id + lineage/fill evidence.
    try:
        import scalp_trade_attribution as _attr
        # All-time (days=None): the validation sample is CUMULATIVE; the --days window only scopes
        # the discovery/social stages above, not the momentum_scalp paper-trade validation count.
        attr = _attr.attribute(conn, days=None)
    except Exception as e:
        attr = {"ok": False, "note": str(e)[:120]}
        warnings.append(f"attribution: {str(e).splitlines()[0][:120]}")

    if attr.get("ok"):
        opened = attr["confirmed_opened"]
        closed = attr["confirmed_closed"]
        wins = attr["confirmed_winners"]
        win_rate = attr.get("confirmed_win_rate")
        profit_factor = attr.get("confirmed_profit_factor")
    else:
        opened = closed = wins = win_rate = profit_factor = None
        warnings.append("attribution unavailable — momentum_scalp trade counts UNKNOWN")

    stages.append({"key": "paper_opened", "label": "ACTUAL momentum_scalp paper trades opened (confirmed)",
                   "count": opened, "available": attr.get("ok", False)})
    stages.append({"key": "paper_closed", "label": "ACTUAL momentum_scalp paper trades closed (confirmed)",
                   "count": closed, "available": attr.get("ok", False)})
    stages.append({"key": "paper_wins", "label": "Confirmed closed winners (momentum_scalp)",
                   "count": wins, "available": attr.get("ok", False)})
    stages.append({"key": "unknown_strategy_paper_trades", "label": "Unknown-strategy paper trades (ambiguous + mismatched)",
                   "count": attr.get("unknown_strategy_paper_trades"), "available": attr.get("ok", False)})
    stages.append({"key": "ambiguous_attribution_rows", "label": "Ambiguous-attribution rows (direct-label, no lineage/fill)",
                   "count": attr.get("ambiguous_count"), "available": attr.get("ok", False)})
    stages.append({"key": "non_executed_rows", "label": "Non-executed momentum_scalp rows (cancelled/dedup — NOT trades)",
                   "count": attr.get("non_executed_count"), "available": attr.get("ok", False)})

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
        "proposal_to_fast_path_gate_pass": conv("validation_fast_path_gate_pass", "proposals_scalp"),
        "fast_path_gate_pass_to_opened": conv("paper_opened", "validation_fast_path_gate_pass"),
        "opened_to_closed": conv("paper_closed", "paper_opened"),
    }

    # ── Validation gate (uses CONFIRMED closed paper trades only) ──
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
        "operator_correction": "Operator correction 2026-06-28: no confirmed momentum_scalp paper "
                               "trades were expected; prior counts (e.g. 17 opened / 3 closed) were "
                               "over-attributed (non-executed rows + unlinked direct-label row). "
                               "Counts below reflect conservative TRUE attribution.",
        "stages": stages,
        "families": {
            "social_only": {"note": "watch_only/WAIT — advisory, not auto-tradeable"},
            "momentum_scalp": {"opened": opened, "closed": closed, "wins": wins,
                               "win_rate": win_rate, "profit_factor": profit_factor,
                               "confirmed_trade_ids": attr.get("confirmed_trade_ids"),
                               "ambiguous_trade_ids": attr.get("ambiguous_trade_ids"),
                               "attribution_chains": attr.get("attribution_chains")},
            "meme_squeeze_momentum": {"note": "manual-review route — no auto proposals"},
        },
        "conversions": conversions,
        "validation_fast_path": fast_path,
        "validation_fast_path_legacy_aliases": legacy_aliases,
        "confirmed_closed_validation_trades": closed,
        "validation_gate_met": gate_met,
        "validation_approval_required": False,
        "validation_approval_note": ("Momentum scalp validation execution does NOT require human approval — "
                                "deterministic gates replace validation approval for sample collection. The validation fast path "
                                "remains deterministic and sandbox-only; live trading is unchanged and "
                                "still requires operator confirmation + 2FA."),
        "reject_deferred_reasons": rej_rows,
        "validation_gate": {
            **GATE,
            "closed_paper_trades": closed,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "calendar_months_observed": months_observed,
            "gate_met": gate_met,
            "live_ready_claim": False,  # NEVER claim live-readiness from this report
            "status_note": ("Validation gate NOT met — momentum_scalp remains TESTING (sandbox-only); "
                            f"confirmed closed paper trades = {closed} of {GATE['min_closed_paper_trades']}."
                            if not gate_met else
                            "Trade-count/win/PF thresholds met on available data; 6-month calendar "
                            "span + human approval still required before any promotion."),
        },
        "attribution": {k: attr.get(k) for k in (
            "confirmed_opened", "confirmed_closed", "confirmed_winners", "ambiguous_count",
            "mismatched_count", "non_executed_count", "unknown_strategy_paper_trades",
            "confirmed_trade_ids", "ambiguous_trade_ids")} if attr.get("ok") else attr,
        "warnings": warnings,
        "note": "Read-only funnel report. No broker writes. LLMs advisory only.",
    }


def to_markdown(rep: dict) -> str:
    L = ["# Scalp Lifecycle Funnel", "",
         f"**Status: {rep['status']}**  ",
         f"_Generated: {rep['generated_at']} | window: {rep.get('window_days')}d_  ",
         "_Source: `python3 scripts/scalp_lifecycle_funnel_report.py --days N --json`_  ",
         "", "Read-only. No broker writes. Social-only signals are advisory (WATCH/WAIT) only.", ""]
    if rep.get("operator_correction"):
        L += [f"> **{rep['operator_correction']}**", ""]
    if rep.get("validation_approval_note"):
        L += [f"> **Validation approval:** {rep['validation_approval_note']}", ""]
    _ms = (rep.get("families", {}) or {}).get("momentum_scalp", {})
    if _ms.get("confirmed_trade_ids") is not None:
        L += [f"**Confirmed momentum_scalp paper trades:** {_ms.get('closed')} closed "
              f"(trade IDs {_ms.get('confirmed_trade_ids')}); "
              f"ambiguous/unlinked excluded (IDs {_ms.get('ambiguous_trade_ids')}).", ""]
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
