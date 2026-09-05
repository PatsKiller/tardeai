#!/usr/bin/env python3
"""watch_directives_service.py — wire operator Watch Directives into Trade AI + Hermes.

ADVISORY. For each ACTIVE directive: resolve to symbols (ticker→symbol; sector/trend→spec universe/seed),
record watch_directive_hits (surfaced_by='trade_ai') with current analyst divergence + GO/WAIT qualification,
and PROMOTE qualifying symbols into the watched universe (watchlist_items, origin_system='operator_directive',
directive_id, in_directive_watch) so Trade AI's news/analysis/scans cover them. Also DRAIN Hermes proposals
from hermes_directive_hits_staging → watch_directive_hits (surfaced_by='hermes') — the firewall: Hermes only
writes staging; this app-role service drains it. NEVER trades / changes GO-WAIT / scoring / stops.

  python3 scripts/watch_directives_service.py            # dry-run
  python3 scripts/watch_directives_service.py --apply
"""
import os, sys, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PILLS = ROOT / "data" / "runtime" / "pro_analyst_pills_latest.json"
for ln in (ROOT / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
import psycopg2
import psycopg2.extras
sys.path.insert(0, str(ROOT / "scripts"))
import directive_promotion as dp  # the real evaluation engine (governor → classify Bucket 2/3 → watchpool)
from research_critique_pipeline import is_removal_flagged, load_critique_snapshot


def _db():
    return psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                            password=os.getenv("DB_PASSWORD"), cursor_factory=psycopg2.extras.RealDictCursor)


def _pills():
    try:
        return {p["symbol"]: p for p in json.loads(PILLS.read_text()).get("pills", [])}
    except Exception:
        return {}


# Reused sector ETF map (continuous_runner.py:368 / market_context) — the single taxonomy, not a new one.
SECTOR_ETF = {"Technology": "XLK", "Financials": "XLF", "Energy": "XLE", "Healthcare": "XLV",
              "Consumer Cyclical": "XLY", "Consumer Disc.": "XLY", "Industrials": "XLI",
              "Consumer Defensive": "XLP", "Consumer Stapl.": "XLP", "Utilities": "XLU",
              "Real Estate": "XLRE", "Basic Materials": "XLB", "Materials": "XLB",
              "Communication Services": "XLC", "Comm. Services": "XLC"}
SECTOR_CONSTITUENT_CAP = 25  # bound staged hits per sector run; cap is LOGGED (no silent truncation)

COLD_CONFIRM_DAYS = 7
COLD_PAUSE_DAYS = 14


def _resolve(d, conn=None):
    """Directive → candidate symbols.
    ticker: explicit symbol.
    sector: operator universe + sector ETF + Finviz-sector constituents from incubator_universe (capped, logged).
    trend:  operator seed_symbols (Hermes-discovered symbols arrive via hermes_directive_hits_staging drain).
    """
    spec = d["spec"] if isinstance(d["spec"], dict) else json.loads(d["spec"])
    if d["kind"] == "ticker":
        s = spec.get("symbol")
        return [s.upper()] if s else []
    out = []
    for key in ("universe", "seed_symbols"):
        out += [str(x).upper() for x in (spec.get(key) or [])]
    if d["kind"] == "sector" and conn is not None:
        sec = spec.get("finviz_sector") or spec.get("gics_sector") or ""
        etf = spec.get("etf") or SECTOR_ETF.get(sec)
        if etf:
            out.append(etf.upper())
        if sec:
            cur = conn.cursor()
            # DISTINCT: incubator_universe has multiple rows per symbol; LIMIT must apply to distinct symbols.
            cur.execute("""SELECT DISTINCT symbol FROM incubator_universe WHERE sector=%s AND symbol IS NOT NULL
                           ORDER BY symbol LIMIT %s""", (sec, SECTOR_CONSTITUENT_CAP))
            out += [r["symbol"].upper() for r in cur.fetchall() if r.get("symbol")]
            cur.execute("SELECT count(DISTINCT symbol) AS n FROM incubator_universe WHERE sector=%s", (sec,))
            total = (cur.fetchone() or {}).get("n", 0)
            if total > SECTOR_CONSTITUENT_CAP:
                print(f"  [resolve] sector '{sec}': capped to {SECTOR_CONSTITUENT_CAP} of {total} constituents")
    return sorted(set(out))


def _notify(msg):
    """Best-effort Telegram via chokepoint (advisory; never raises)."""
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="watch_directives_service", subject_key="ops:watch_directives",
                retention_class="operational", severity="info",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def pause_cold_trends(c, cur, dry, report):
    """Trend cold-detector (advisory, trend-only). 7-day confirm cadence:
      new credible hits since last_confirmed_at  -> reconfirm (last_confirmed_at=now, clear cold_since)
      none + cold_since NULL                      -> start the clock (cold_since=now)
      none + cold for >= 14 days                  -> status='paused' (NOT archived) + notify operator
    Operator-only un-pause. Hermes pauses and reports; never archives the mandate."""
    cur.execute("SELECT * FROM watch_directives WHERE status='active' AND kind='trend'")
    for d in cur.fetchall():
        did = d["id"]
        cur.execute("""SELECT count(*) AS n FROM watch_directive_hits
                       WHERE directive_id=%s
                         AND surfaced_at > COALESCE(%s, %s, now()-interval '7 days')""",
                    (did, d.get("last_confirmed_at"), d.get("created_at")))
        new_hits = cur.fetchone()["n"]
        if new_hits > 0:
            if not dry:
                cur.execute("UPDATE watch_directives SET last_confirmed_at=now(), cold_since=NULL, updated_at=now() WHERE id=%s", (did,))
            continue
        if d.get("cold_since") is None:
            if not dry:
                cur.execute("UPDATE watch_directives SET cold_since=now(), updated_at=now() WHERE id=%s", (did,))
            report.setdefault("cold_started", 0)
            report["cold_started"] += 1
            continue
        cur.execute("SELECT EXTRACT(EPOCH FROM (now()-cold_since))/86400.0 AS days FROM watch_directives WHERE id=%s", (did,))
        cold_days = (cur.fetchone() or {}).get("days") or 0
        if cold_days >= COLD_PAUSE_DAYS:
            if not dry:
                cur.execute("UPDATE watch_directives SET status='paused', updated_at=now() WHERE id=%s", (did,))
                _notify(f"⏸ Watch directive auto-PAUSED (cold): '{d['label']}' — no credible new hits in {int(cold_days)}d. "
                        f"Advisory only; the mandate is preserved. Operator un-pause when ready.")
            report.setdefault("paused_cold", 0)
            report["paused_cold"] += 1
            report["detail"].append({"directive": d["label"], "event": "auto_paused_cold", "cold_days": int(cold_days)})


def _drain_orphan_staging(cur, dry, report):
    """Staging rows for archived/paused directives never drain in the active loop — clear them."""
    cur.execute("""SELECT count(*) AS n FROM hermes_directive_hits_staging h
                   JOIN watch_directives d ON d.id=h.directive_id
                   WHERE h.drained=false AND d.status <> 'active'""")
    orphans = (cur.fetchone() or {}).get("n") or 0
    if orphans and not dry:
        cur.execute("""UPDATE hermes_directive_hits_staging h
                       SET drained=true, drained_at=now()
                       FROM watch_directives d
                       WHERE h.directive_id=d.id AND h.drained=false AND d.status <> 'active'""")
    report["orphan_staging_cleared"] = orphans


def _drain_curation_sources(c, cur, dry, report, evaluate, resolve_fn):
    """Drain CIO/advisory/defense/rotation/reentry curation feedback (two-way loop, forward edge).

    Each source stages feedback via lib.two_way_curation.emit_feedback(); this app-role
    service drains it through the SAME governor path as Hermes (promote_directive_lead).
    Self-thinking: a feedback record that carries directive_kind/spec mints its own
    watch_directives row (deduped by kind+label) — no operator hand-creation required.

    auto_apply_gate is AND-ed with the governor: gate False forces stage; gate True
    still lets promote_directive_lead decide (never force auto=True).
    """
    from lib.two_way_curation import (
        BOOTSTRAP_ASSUMPTION,
        DEFAULT_DRAIN_LIMIT,
        DESK_PROMOTION_TIER,
        auto_apply_gate,
        drain_curation_sources,
    )
    import os

    try:
        limit = max(1, int(os.environ.get("CURATION_DRAIN_LIMIT", DEFAULT_DRAIN_LIMIT)))
    except ValueError:
        limit = DEFAULT_DRAIN_LIMIT

    def _auto_apply(source, symbol, did):
        # Hit-rate floor starts open (None) until calibration exists; gate then
        # requires trusted tier + non-divergent. Divergence is read inside promote.
        tier = DESK_PROMOTION_TIER.get(source, "candidate")
        # Prefer live divergence when available
        try:
            import directive_promotion as dp
            div = dp.get_divergence_status(symbol, c) or "unavailable"
        except Exception:
            div = "unavailable"
        # No calibrated hit-rate yet → pass None so hit_rate_ok is False unless
        # CURATION_HIT_RATE_DEFAULT (MEASURED_HIT_RATE) is set.
        hr_raw = os.environ.get("CURATION_HIT_RATE_DEFAULT", "").strip()
        try:
            hr = float(hr_raw) if hr_raw else None
        except ValueError:
            hr = None
        # During bootstrap (no measured hit-rate), substitute BOOTSTRAP_ASSUMPTION to meet
        # the floor only when CURATION_AUTO_APPLY=1; default is stage-for-review (safer).
        if hr is None and os.environ.get("CURATION_AUTO_APPLY", "0").strip() in ("1", "true", "yes"):
            hr = BOOTSTRAP_ASSUMPTION
        return auto_apply_gate(tier, div, hr)

    drain_curation_sources(
        cur, dry, report, evaluate, resolve_fn,
        drain_limit=limit,
        auto_apply=_auto_apply if os.environ.get("CURATION_AUTO_APPLY_GATE", "1").strip()
        not in ("0", "false", "no") else None,
    )


def _max_hermes_drain():
    for i, a in enumerate(sys.argv):
        if a == "--max-hermes-drain" and i + 1 < len(sys.argv):
            try:
                return max(1, int(sys.argv[i + 1]))
            except ValueError:
                pass
    return 50


def main():
    dry = "--apply" not in sys.argv
    max_hermes_drain = _max_hermes_drain()
    pills = _pills()
    c = _db(); cur = c.cursor()
    critique_snap = load_critique_snapshot()
    critique_index = critique_snap.get("index") or {}
    stale_ids = set(critique_index.get("stale_directive_ids") or [])
    report = {"directives": 0, "ta_hits": 0, "hermes_drained": 0,
              "promoted": 0, "staged": 0, "skipped_stale": 0, "stale_staging_discarded": 0,
              "critique_snapshot_at": critique_snap.get("updated_at"), "detail": []}
    _drain_orphan_staging(cur, dry, report)
    cur.execute("SELECT * FROM watch_directives WHERE status='active'")
    directives = cur.fetchall()
    report["directives"] = len(directives)

    def recent_hit(did, sym, by):
        cur.execute("""SELECT 1 FROM watch_directive_hits WHERE directive_id=%s AND symbol=%s AND surfaced_by=%s
                       AND surfaced_at > now()-interval '12 hours' LIMIT 1""", (did, sym, by))
        return cur.fetchone() is not None

    def evaluate(sym, did, reason, source_system, auto):
        # RECONCILED: route through the REAL evaluation engine instead of a flat watchlist add.
        # promote_directive_lead = governor (tier+divergence) → register provenance → enrich-on-demand
        # → classify (Bucket 2/3 ONLY; momentum_scalp/gap_and_go/SAME_DAY excluded) → watchpool. It
        # records the watch_directive_hit itself and runs under its own app-role connection.
        try:
            return dp.promote_directive_lead(sym, did, reason, source_system, auto=auto)
        except Exception as e:
            return {"status": "ERROR", "error": str(e)[:140]}

    for d in directives:
        did = d["id"]
        spec = d["spec"] if isinstance(d["spec"], dict) else json.loads(d["spec"] or "{}")
        if did in stale_ids or is_removal_flagged(spec):
            report["skipped_stale"] += 1
            report["detail"].append({"directive": d["label"], "event": "skipped_stale_flag",
                                     "id": did, "reasons": spec.get("stale_reasons")})
            continue
        # ── Trade AI side: resolve the directive's own symbols ──
        if d["trade_ai_enabled"]:
            # ticker = operator named the exact symbol → auto (real eval; scalp firewall still applies).
            # sector/trend surfaced symbols → governor decides (typically STAGE for one-tap).
            is_ticker = d["kind"] == "ticker"
            src = "operator" if is_ticker else "trade_ai"  # surfaced_by my engine will record
            for sym in _resolve(d, conn=c):
                if recent_hit(did, sym, src):   # dedup on the same surfaced_by (was 'trade_ai' only — bug)
                    continue
                if not dry:
                    res = evaluate(sym, did, f"directive:{d['label']}", src,
                                   True if is_ticker else None)
                    st = res.get("status")
                    report["promoted"] += 1 if st == "PROMOTED" else 0
                    report["staged"] += 1 if st == "STAGED_FOR_REVIEW" else 0
                    report["detail"].append({"directive": d["label"], "symbol": sym,
                                             "surfaced_by": "trade_ai", "status": st})
                else:
                    report["detail"].append({"directive": d["label"], "symbol": sym, "surfaced_by": "trade_ai"})
                report["ta_hits"] += 1
        # ── Hermes drain (firewall: app drains staging, then evaluates under app role) ──
        if d["hermes_enabled"]:
            cur.execute("""SELECT * FROM hermes_directive_hits_staging WHERE drained=false AND directive_id=%s LIMIT %s""",
                        (did, max_hermes_drain))
            for h in cur.fetchall():
                sym = (h["symbol"] or "").upper()
                if not sym:
                    continue
                hit_detail = h.get("source_detail") if isinstance(h.get("source_detail"), dict) else json.loads(h.get("source_detail") or "{}")
                if is_removal_flagged(hit_detail):
                    if not dry:
                        cur.execute("UPDATE hermes_directive_hits_staging SET drained=true, drained_at=now() WHERE id=%s", (h["id"],))
                    report["stale_staging_discarded"] += 1
                    report["detail"].append({"directive": d["label"], "symbol": sym,
                                             "event": "discarded_stale_staging"})
                    continue
                if not dry:
                    res = evaluate(sym, did, f"hermes:{(h.get('thesis') or '')[:60]}", "hermes", None)
                    st = res.get("status")
                    report["promoted"] += 1 if st == "PROMOTED" else 0
                    report["staged"] += 1 if st == "STAGED_FOR_REVIEW" else 0
                    cur.execute("UPDATE hermes_directive_hits_staging SET drained=true, drained_at=now() WHERE id=%s", (h["id"],))
                    report["detail"].append({"directive": d["label"], "symbol": sym,
                                             "surfaced_by": "hermes", "status": st})
                else:
                    report["detail"].append({"directive": d["label"], "symbol": sym, "surfaced_by": "hermes"})
                report["hermes_drained"] += 1
        if not dry:
            cur.execute("UPDATE watch_directives SET last_serviced_at=now(), updated_at=now() WHERE id=%s", (did,))
    # ── Two-way curation drain (CIO/advisory/defense → watchlist, forward edge) ──
    _drain_curation_sources(c, cur, dry, report, evaluate, _resolve)
    # Trend cold-detector (advisory): reconfirm / start-clock / auto-pause-on-cold
    pause_cold_trends(c, cur, dry, report)
    if not dry:
        c.commit()
    c.close()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
