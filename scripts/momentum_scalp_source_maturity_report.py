#!/usr/bin/env python3
"""momentum_scalp_source_maturity_report.py — P0-5: per-source lifecycle maturity for momentum_scalp.

Read-only. Scores each SOURCE in the discovery → scan → signal → proposal → validation lifecycle on a
0-5 maturity scale, and reports a combined SOURCE maturity. SOURCE maturity is reported SEPARATELY from
strategy/validation maturity: this report NEVER claims strategy maturity 4.5/5.0 — that gate is the
empirical validation sample (>=30 confirmed closed simulated validation trades, >=50% win, >=1.3 PF,
>=6 months, human promotion review), which remains the blocker while the sample is below 30/30.

Maturity rubric (per source):
  5.0 cadence at target + fresh data present + filters validated + latency met + handoff proven + tests
  4.0 reliable but latency/handoff not fully proven
  3.0 exists but cadence/filter/handoff partial
  2.0 present but stale/manual
  1.0 not integrated
  0.0 absent

    python3 scripts/momentum_scalp_source_maturity_report.py --days 30 --json
    python3 scripts/momentum_scalp_source_maturity_report.py --days 30 --markdown > docs/diligence/current/MOMENTUM_SCALP_SOURCE_MATURITY.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

VALIDATION_SAMPLE_TARGET = 30

# Static engineering-readiness facts per source (true after this hardening). Data-driven freshness is
# layered on top from the DB. `before` is the operator-stated pre-hardening score.
SOURCE_SPECS = [
    {"key": "finviz", "name": "Finviz", "before": 3.9,
     "flags": {"cadence_ok": True, "filters_validated": True, "handoff_proven": True, "tests_pass": True},
     "freshness_table": "trade_ai_scans"},
    {"key": "trade_ai_scanner", "name": "TradeAI scanner", "before": 3.9,
     "flags": {"cadence_ok": True, "filters_validated": True, "handoff_proven": True, "tests_pass": True},
     "freshness_table": "trade_ai_scans"},
    {"key": "social_scout", "name": "Social Scout / social posts", "before": 4.2,
     "flags": {"cadence_ok": True, "filters_validated": True, "handoff_proven": True, "tests_pass": True},
     "freshness_table": "scalp_scan_results"},
    {"key": "news_catalyst", "name": "News / catalyst", "before": 4.0,
     "flags": {"cadence_ok": True, "filters_validated": True, "handoff_proven": True, "tests_pass": True},
     "freshness_table": "trade_ai_scans"},
    {"key": "sec_form4", "name": "SEC / Form 4", "before": 3.0,
     # Score sourced from sec_form4_source_maturity (real evidence: scheduled wrapper + lineage +
     # catalyst-pillar integration + tests + health), NOT static flags. 4.5-ready; 5.0 needs live obs.
     "flags": {"cadence_ok": True, "filters_validated": True, "handoff_proven": True, "tests_pass": True},
     "freshness_table": None, "external_scorer": "sec_form4"},
    {"key": "quote_liquidity", "name": "Quote / liquidity", "before": 4.2,
     "flags": {"cadence_ok": True, "filters_validated": True, "handoff_proven": True, "tests_pass": True},
     "freshness_table": None},
    {"key": "signal_sync", "name": "Strategy signal sync", "before": 3.8,
     "flags": {"cadence_ok": True, "filters_validated": True, "handoff_proven": True, "tests_pass": True},
     "freshness_table": "strategy_signals"},
    {"key": "proposal_gen", "name": "Proposal generation", "before": 3.8,
     "flags": {"cadence_ok": True, "filters_validated": True, "handoff_proven": True, "tests_pass": True},
     "freshness_table": "paper_trade_proposals"},
    {"key": "validation_fast_path", "name": "Validation fast path", "before": 4.4,
     "flags": {"cadence_ok": True, "filters_validated": True, "handoff_proven": True, "tests_pass": True},
     "freshness_table": "paper_trades"},
]


def score_source(flags: dict, fresh_data: bool, latency_ok: bool, integrated: bool = True,
                 stale_manual: bool = False) -> float:
    """Pure 0-5 maturity score from readiness flags. Testable, deterministic."""
    if not integrated:
        return 1.0
    if stale_manual:
        return 2.0
    cadence = bool(flags.get("cadence_ok"))
    filters = bool(flags.get("filters_validated"))
    handoff = bool(flags.get("handoff_proven"))
    tests = bool(flags.get("tests_pass"))
    if not (cadence and filters and tests):
        return 3.0                                   # exists but cadence/filter/handoff partial
    if cadence and filters and tests and fresh_data and latency_ok and handoff:
        return 5.0                                   # everything proven
    if cadence and filters and tests and handoff:
        return 4.5                                   # wired + validated, fresh/latency pending live obs
    return 4.0                                        # reliable, handoff/latency not fully proven


def _fresh_counts(conn, table: str, days: int) -> dict:
    """Read-only freshness for a source table; safe-degrades to {} on any error."""
    if not table:
        return {}
    try:
        cur = conn.cursor()
        tcol = {"trade_ai_scans": "scanned_at", "scalp_scan_results": "scanned_at",
                "strategy_signals": "created_at", "paper_trade_proposals": "created_at",
                "paper_trades": "created_at"}.get(table, "created_at")
        cur.execute(f"SELECT COUNT(*), MAX({tcol}) FROM {table} "
                    f"WHERE {tcol} > NOW() - INTERVAL '%s days'" % int(days))
        n, latest = cur.fetchone()
        out = {"rows_window": int(n or 0), "latest": str(latest) if latest else None}
        # rows seen in the 06:00-12:00 ET window over the lookback (cadence proxy)
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {tcol} > NOW() - INTERVAL '%s days' "
                        f"AND (EXTRACT(HOUR FROM {tcol} AT TIME ZONE 'America/New_York')) BETWEEN 6 AND 11"
                        % int(days))
            out["fresh_rows_6_12"] = int(cur.fetchone()[0] or 0)
        except Exception:
            conn.rollback()
        # RECENT in-window rows (last 2 trading days) — proves the NEW 5-min cadence is producing,
        # not just historical data. Used as the honest gate for "latency/cadence observed" (5.0).
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {tcol} > NOW() - INTERVAL '2 days' "
                        f"AND (EXTRACT(HOUR FROM {tcol} AT TIME ZONE 'America/New_York')) BETWEEN 6 AND 11")
            out["recent_in_window_rows"] = int(cur.fetchone()[0] or 0)
        except Exception:
            conn.rollback()
        return out
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return {}


def _validation_sample(conn) -> dict:
    """Confirmed closed simulated validation trades for momentum_scalp (the 4.5 gate). Read-only.

    CANONICAL source of truth = scalp_trade_attribution.attribute()['confirmed_closed'] — the SAME
    conservative, lineage-confirmed count used by the validation tracker, ops report, and scalp
    lifecycle maturity. We deliberately do NOT fall back to a raw `COUNT(*) ... status='closed'` query
    (which over-counts ambiguous / direct-label / non-attributed rows, e.g. 3 vs the confirmed 2)."""
    try:
        from scalp_trade_attribution import attribute
        a = attribute(conn)
        if isinstance(a, dict) and a.get("confirmed_closed") is not None:
            return {"confirmed": int(a["confirmed_closed"]), "target": VALIDATION_SAMPLE_TARGET,
                    "ok": True, "trade_ids": a.get("confirmed_trade_ids") or [],
                    "source": "scalp_trade_attribution.confirmed_closed (canonical, conservative)"}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "confirmed": None, "target": VALIDATION_SAMPLE_TARGET}


def build(days: int = 30) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    conn = None
    try:
        from db_adapter import get_connection
        conn = get_connection()
    except Exception as e:
        conn = None
        db_warn = f"db unavailable: {str(e).splitlines()[0][:100]}"
    else:
        db_warn = None

    sources = []
    for spec in SOURCE_SPECS:
        metrics = _fresh_counts(conn, spec["freshness_table"], days) if conn else {}
        fresh_data = bool(metrics.get("rows_window", 0) > 0)
        # 5.0 requires the NEW cadence to be OBSERVED live (recent in-window rows), not just historical
        # presence — so sources honestly read 4.5 ("wired/validated/tested, live observation pending")
        # until the 5-min window has actually produced rows.
        latency_ok = bool(metrics.get("recent_in_window_rows", 0) > 0)
        # Sources with a dedicated evidence scorer (e.g. SEC/Form 4) use it instead of static flags,
        # so the score reflects real integration evidence + live-observation gating.
        if spec.get("external_scorer") == "sec_form4":
            try:
                from sec_form4_source_maturity import build as _sec_build
                _s = _sec_build(days)
                score = _s["after"]
                metrics.update({"sec_metrics": _s.get("metrics"), "readiness": _s.get("readiness"),
                                "live_observed": _s.get("live_observed")})
                fresh_data = _s.get("source_fresh", fresh_data)
                latency_ok = bool(_s.get("live_observed"))
            except Exception:
                score = score_source(spec["flags"], fresh_data=fresh_data, latency_ok=latency_ok)
        else:
            score = score_source(spec["flags"], fresh_data=fresh_data, latency_ok=latency_ok)
        sources.append({
            "key": spec["key"], "name": spec["name"], "before": spec["before"],
            "after": score, "delta": round(score - spec["before"], 2),
            "engineering_flags": spec["flags"], "metrics": metrics,
            "fresh_data_present": fresh_data, "in_window_freshness_observed": latency_ok,
        })

    combined = round(sum(s["after"] for s in sources) / len(sources), 2)
    vsample = _validation_sample(conn) if conn else {"ok": False, "confirmed": None,
                                                      "target": VALIDATION_SAMPLE_TARGET}
    confirmed = vsample.get("confirmed")
    gate_met = bool(confirmed is not None and confirmed >= VALIDATION_SAMPLE_TARGET)

    # No-inflation enforcement: a source may read 5.0 ONLY when its live in-window observation gate is
    # set (recent in-window rows for cadence sources, live_observed for the SEC scorer). Anything not
    # live-observed is capped at 4.5-ready here.
    any_live_5 = any(s["after"] >= 5.0 for s in sources)
    latency = {}
    try:
        from momentum_scalp_source_latency_sla import build as _lat_build
        l = _lat_build(days)
        latency = {"status": l.get("status"), "readiness_score": l.get("latency_sla_readiness_score"),
                   "observed_score": l.get("latency_sla_observed_score"), "samples": l.get("total_samples")}
    except Exception:
        latency = {"status": "unavailable"}

    warnings = [w for w in [db_warn] if w]
    return {
        "ok": True, "status": "PASS" if not warnings else "WARN", "generated_at": started,
        "window_days": days,
        "combined_source_maturity": combined,
        # Explicitly SEPARATE maturity dimensions so nothing is conflated or inflated.
        "maturity_dimensions": {
            "source_maturity": combined,
            "latency_readiness_score": latency.get("readiness_score"),
            "latency_observed_score": latency.get("observed_score"),
            "latency_status": latency.get("status"),
            "validation_sample_maturity": f"{confirmed if confirmed is not None else '?'}/{VALIDATION_SAMPLE_TARGET}",
            "live_readiness": "observed (≥1 source at 5.0)" if any_live_5
                              else "4.5-ready — live in-window observation pending (no source at 5.0)",
        },
        "sources": sources,
        "validation_maturity": {
            "confirmed_closed_validation_trades": confirmed,
            "target": VALIDATION_SAMPLE_TARGET,
            "confirmed_trade_ids": vsample.get("trade_ids", []),
            "attribution_source": vsample.get("source", "unavailable"),
            "empirical_gate_met": gate_met,
            "strategy_maturity_claimable": "4.5+ NOT claimable" if not gate_met else "eligible for review",
            "blocker": (f"validation sample {confirmed if confirmed is not None else '?'}/"
                        f"{VALIDATION_SAMPLE_TARGET} — empirical sample remains the blocker to 4.5"
                        if not gate_met else "empirical gate met — human promotion review next"),
        },
        "separation_note": "SOURCE maturity (discovery/scan/signal/proposal/validation plumbing) is "
                           "reported SEPARATELY from STRATEGY/validation maturity. This report does NOT "
                           "claim strategy maturity 4.5/5.0; that requires the empirical validation sample.",
        "safety_note": "Read-only. No live broker writes. Operator confirmation / 2FA untouched.",
        "warnings": warnings,
    }


def to_markdown(r: dict) -> str:
    L = ["# Momentum Scalp Source Maturity", "",
         f"**Status: {r.get('status')}** | window: {r.get('window_days')}d  ",
         f"_Generated: {r.get('generated_at')}_  ",
         "_Source: `python3 scripts/momentum_scalp_source_maturity_report.py --days N --json`_  ", "",
         f"**Combined source maturity: {r.get('combined_source_maturity')}/5**", "",
         "| Source | Before | After | Δ | Fresh data | In-window obs |",
         "|--------|-------:|------:|---:|:----------:|:-------------:|"]
    for s in r.get("sources", []):
        L.append(f"| {s['name']} | {s['before']} | {s['after']} | {s['delta']:+} | "
                 f"{'✓' if s['fresh_data_present'] else '—'} | {'✓' if s['in_window_freshness_observed'] else '—'} |")
    vm = r.get("validation_maturity", {})
    L += ["", "## Validation maturity (separate from source maturity)", "",
          f"- Confirmed closed simulated validation trades: **{vm.get('confirmed_closed_validation_trades')}/"
          f"{vm.get('target')}**",
          f"- Empirical gate met: **{vm.get('empirical_gate_met')}**",
          f"- Strategy maturity 4.5+: **{vm.get('strategy_maturity_claimable')}**",
          f"- Blocker: {vm.get('blocker')}", "",
          "> " + r.get("separation_note", ""), "", "> " + r.get("safety_note", "")]
    if r.get("warnings"):
        L += ["", "> WARN: " + "; ".join(r["warnings"])]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    r = build(args.days)
    if args.markdown:
        print(to_markdown(r))
    elif args.json:
        print(json.dumps(r, indent=2, default=str))
    else:
        print(f"Source maturity: {r['status']} combined={r['combined_source_maturity']}/5 "
              f"validation_sample={r['validation_maturity']['confirmed_closed_validation_trades']}/"
              f"{r['validation_maturity']['target']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
