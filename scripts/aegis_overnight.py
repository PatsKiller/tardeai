"""
aegis_overnight.py — Aegis Overnight Intelligence Orchestrator

Single entrypoint for the 20:00–04:00 overnight intelligence cycle.
Runs phases sequentially:
  Phase 1: Collection (nightly deltas, social sentiment, transcript/discovery)
  Phase 2: Synthesis (LLM briefs, covered-call candidates, rotation, escalation, evidence)
  Phase 3: Refinement (morning brief composition, handoff summary)

Safe to rerun manually. Uses file lock to prevent overlap.

Entry point: main()
"""
from __future__ import annotations
import json
import os
import sys
import fcntl
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
LOCK_FILE = PROJECT_ROOT / "logs" / ".aegis_overnight.lock"
LOG_FILE = PROJECT_ROOT / "logs" / "aegis-overnight.log"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Load .env
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v


def _log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# Reasons a phase legitimately did nothing. Not "ignore these" — they are still
# reported with their cause on the brief line; they just do not make the whole
# run read as faulted.
#
# `semantic_duplicate` is on this list with a caveat: on 2026-08-30 it fired
# because the brief hashed identically to 08-29's (MORNING:...:ec5a2e56de503f25
# both nights). Identical content two days running is correct to dedup and is
# ALSO a signal worth watching — if it persists, the question is why the product
# is not moving, not why delivery skipped.
BENIGN_NO_EFFECT = frozenset({"already_sent", "semantic_duplicate"})


def _phase_did_nothing(result: dict) -> bool:
    """True when a phase's own payload says the work did not happen.

    Deliberately conservative: only an EXPLICIT negative counts. A phase that
    reports nothing about delivery is not assumed to have failed, because
    treating silence as failure would make every phase without this key look
    broken. `delivered: False` is a statement; a missing key is not.
    """
    if not isinstance(result, dict):
        return False
    if result.get("error"):
        return True
    for key in ("delivered", "published", "sent"):
        if key in result and result[key] is False:
            return True
    return False


def _run_phase(name: str, func, *args, timeout_min: int = 30) -> dict:
    """Run a phase with timing, error handling, and hard timeout."""
    import signal

    _log(f"  PHASE START: {name}")
    start = time.time()
    result = {}

    def _timeout_handler(signum, frame):
        raise TimeoutError(f"Phase '{name}' exceeded {timeout_min}-minute limit")

    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout_min * 60)
    try:
        result = func(*args) or {}
        elapsed = time.time() - start
        # A phase reports COMPLETE only when it completed. Two shapes were
        # reporting COMPLETE while doing nothing, both observed on the live log:
        #
        #   2026-08-27/28  PHASE FAILED: morning_brief_delivery — No module
        #                  named 'scripts'   ...and the run still ended
        #                  "AEGIS OVERNIGHT COMPLETE" with a brief count.
        #   2026-08-30     PHASE COMPLETE: morning_brief_delivery —
        #                  {'delivered': False, 'reason': 'semantic_duplicate'}
        #
        # The second is the harder one: the phase did not raise, so nothing was
        # wrong from `try`'s point of view, yet its own payload says the work did
        # not happen. A success claim has to be conditional on the payload, not
        # merely on the absence of an exception.
        if _phase_did_nothing(result):
            result = {**result, "phase_status": "NO_EFFECT"}
            _log(f"  PHASE NO EFFECT: {name} — {elapsed:.1f}s — {result}")
        else:
            result = {**result, "phase_status": "COMPLETE"}
            _log(f"  PHASE COMPLETE: {name} — {elapsed:.1f}s — {result}")
    except TimeoutError as e:
        elapsed = time.time() - start
        _log(f"  PHASE TIMEOUT: {name} — {elapsed:.1f}s — {e}")
        result = {"error": str(e), "timeout": True, "phase_status": "TIMEOUT"}
    except Exception as e:
        elapsed = time.time() - start
        _log(f"  PHASE FAILED: {name} — {elapsed:.1f}s — {e}")
        result = {"error": str(e), "phase_status": "FAILED"}
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
    return result


def main():
    run_id = f"aegis-overnight-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    _log(f"{'='*60}")
    _log(f"AEGIS OVERNIGHT ORCHESTRATOR — {run_id}")
    _log(f"{'='*60}")
    start_total = time.time()

    # Acquire lock to prevent overlap
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        _log("ABORT: Another Aegis overnight run is already in progress")
        lock_fd.close()
        return {"error": "locked"}
    lock_fd.write(f"{run_id}\n{datetime.now().isoformat()}\n")
    lock_fd.flush()

    results = {}

    # ── PHASE 1: COLLECTION ──────────────────────────────────────────────
    _log("PHASE 1: COLLECTION")

    # 1a: Morning surveillance (stop/concentration/income/heat scan)
    from aegis_surveillance import main as surveillance_main
    results["surveillance"] = _run_phase("surveillance", surveillance_main)

    # 1b: Nightly delta ingestion (Finviz + Yahoo for tracked universe)
    from aegis_nightly_ingestion import main as ingestion_main
    results["ingestion"] = _run_phase("nightly_ingestion", ingestion_main)

    # 1c: Social sentiment (Reddit + Brave)
    from aegis_social_sentiment import main as social_main
    results["social"] = _run_phase("social_sentiment", social_main)

    # 1d: Transcript + discovery intelligence
    from aegis_transcript_discovery import main as transcript_main
    results["transcript"] = _run_phase("transcript_discovery", transcript_main)

    # ── PHASE 1.5: NEWS STRATEGY CLASSIFICATION ────────────────────────
    _log("PHASE 1.5: NEWS STRATEGY CLASSIFICATION")
    try:
        from _news_strategy_classifier import classify_recent_untagged
        tagged = classify_recent_untagged()
        results["news_strategy"] = {"classified": tagged}
        _log(f"  Classified {tagged} recent news articles")
    except Exception as e:
        _log(f"  News strategy classification failed: {e}")
        results["news_strategy"] = {"error": str(e)}

    # ── PHASE 2: SYNTHESIS ───────────────────────────────────────────────
    _log("PHASE 2: SYNTHESIS")

    # 2a: LLM synthesis (briefs + covered calls + rotation + escalation + evidence)
    from aegis_synthesis import main as synthesis_main
    results["synthesis"] = _run_phase("synthesis", synthesis_main)

    # ── PHASE 2b: DATA HEALTH ────────────────────────────────────────────
    _log("PHASE 2b: DATA HEALTH — watchlist quality check")
    try:
        import psycopg2, psycopg2.extras
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        hconn = psycopg2.connect(host='localhost', dbname='trade_ai', user='trade_ai', password=pw)
        hcur = hconn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Find LLM errors in synthesis for curated symbols
        hcur.execute("""
            SELECT DISTINCT wsm.symbol FROM watchlist_symbol_master wsm
            JOIN watchlist_final_synthesis wfs ON wsm.symbol = wfs.symbol
            WHERE (wsm.in_ai_watchlist = true OR wsm.in_personal_watchlist = true)
              AND (wfs.synthesis_narrative ILIKE '%%LLM error%%'
                   OR wfs.synthesis_narrative ILIKE '%%All providers failed%%')
        """)
        llm_broken = [r['symbol'] for r in hcur.fetchall()]

        # Find stale curated (no analysis in 48h)
        hcur.execute("""
            SELECT wsm.symbol FROM watchlist_symbol_master wsm
            WHERE (wsm.in_ai_watchlist = true OR wsm.in_personal_watchlist = true)
              AND wsm.updated_at < NOW() - INTERVAL '48 hours'
            LIMIT 10
        """)
        stale = [r['symbol'] for r in hcur.fetchall()]

        # Queue re-analysis
        health_queued = 0
        for sym in llm_broken:
            for agent in ['maria_research', 'steph_allocation', 'risk_agent']:
                hcur.execute("""
                    INSERT INTO watchlist_agent_jobs
                        (symbol, requested_agent, task_type, priority, status, submitted_from)
                    VALUES (%s, %s, 'health_requeue', 'high', 'pending', 'aegis_health')
                    ON CONFLICT DO NOTHING
                """, [sym, agent])
                health_queued += 1
        for sym in stale:
            hcur.execute("""
                INSERT INTO watchlist_agent_jobs
                    (symbol, requested_agent, task_type, priority, status, submitted_from)
                VALUES (%s, 'maria_research', 'stale_refresh', 'normal', 'pending', 'aegis_health')
                ON CONFLICT DO NOTHING
            """, [sym])
            health_queued += 1

        hconn.commit()
        hconn.close()

        results["data_health"] = {"llm_errors": len(llm_broken), "stale": len(stale), "queued": health_queued}
        _log(f"  LLM errors: {len(llm_broken)} | Stale: {len(stale)} | Queued: {health_queued} jobs")

        if llm_broken or stale:
            try:
                from telegram_alert import send_telegram
                send_telegram(
                    f"*Watchlist Health — {len(llm_broken) + len(stale)} issues*\n"
                    f"LLM errors: {len(llm_broken)} | Stale (48h+): {len(stale)}\n"
                    f"Auto-queued: {health_queued} jobs for re-analysis"
                )
            except Exception:
                pass
    except Exception as e:
        _log(f"  Data health check failed (non-fatal): {e}")
        results["data_health"] = {"error": str(e)}

    # ── PHASE 2c: RE-ENTRY SCAN ──────────────────────────────────────────
    _log("PHASE 2c: RE-ENTRY SCAN — previously traded watchlist")
    try:
        import subprocess
        subprocess.run([sys.executable, str(PROJECT_ROOT / 'scripts' / 'previously_traded_watchlist.py')],
                       capture_output=True, cwd=str(PROJECT_ROOT), timeout=120)

        # Alert on NEW IN_ZONE signals (not alerted within 7 days)
        hconn2 = psycopg2.connect(host='localhost', dbname='trade_ai', user='trade_ai', password=pw)
        hcur2 = hconn2.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        hcur2.execute("""
            SELECT symbol, current_price, reentry_zone_low, reentry_zone_high,
                   best_pnl_pct, last_exit_price, last_exit_date
            FROM previously_traded_watchlist
            WHERE reentry_signal = 'IN_ZONE' AND is_currently_held = false AND current_price IS NOT NULL
              AND (last_alerted_date IS NULL OR last_alerted_date < CURRENT_DATE - INTERVAL '7 days')
            ORDER BY best_pnl_pct DESC
        """)
        new_alerts = hcur2.fetchall()
        if new_alerts:
            from telegram_alert import send_telegram
            for s in new_alerts:
                send_telegram(
                    f"*Re-entry Signal: {s['symbol']}*\n"
                    f"Price: ${float(s['current_price']):.2f} (zone ${float(s['reentry_zone_low']):.2f}-${float(s['reentry_zone_high']):.2f})\n"
                    f"Last exit: ${float(s['last_exit_price']):.2f} on {s['last_exit_date']}\n"
                    f"Best trade: +{float(s['best_pnl_pct']):.0f}%"
                )
                hcur2.execute("UPDATE previously_traded_watchlist SET last_alerted_date=CURRENT_DATE WHERE symbol=%s", [s['symbol']])
            hconn2.commit()
            _log(f"  Alerted on {len(new_alerts)} re-entry signals")
        else:
            _log("  No new re-entry signals")
        hconn2.close()
        results["reentry_scan"] = {"alerted": len(new_alerts)}
    except Exception as e:
        _log(f"  Re-entry scan failed (non-fatal): {e}")
        results["reentry_scan"] = {"error": str(e)}

    # ── PHASE 3: REFINEMENT ──────────────────────────────────────────────
    _log("PHASE 3: REFINEMENT")

    # 3a: Write handoff summary
    handoff = _write_handoff_summary(run_id, results)
    results["handoff"] = handoff

    # 3b: Deliver morning brief (Telegram + formal export)
    from aegis_morning_brief_delivery import deliver as brief_deliver
    results["brief_delivery"] = _run_phase("morning_brief_delivery", brief_deliver)

    # ── COMPLETE — Send synthesis summary to Telegram ────────────────────
    elapsed_total = time.time() - start_total
    # The run is COMPLETE only if every phase was. Naming the failed phases in
    # the headline is the point: on 2026-08-27 and 08-28 this line read
    # "AEGIS OVERNIGHT COMPLETE" while morning_brief_delivery had failed with
    # "No module named 'scripts'", and nothing downstream disagreed.
    # INCOMPLETE is for faults, not for quiet days. A phase that did nothing
    # BECAUSE the work was already done is a legitimate no-op: shouting
    # INCOMPLETE at it every night is how a digest gets muted, and a muted
    # digest is worse than none because it still looks like coverage. The
    # no-effect reason is still reported on the brief line either way, so
    # "0 delivered" is never silent.
    _bad = {n: r for n, r in results.items()
            if isinstance(r, dict)
            and (r.get("phase_status") in ("FAILED", "TIMEOUT")
                 or (r.get("phase_status") == "NO_EFFECT"
                     and str(r.get("reason") or "") not in BENIGN_NO_EFFECT))}
    _headline = ("AEGIS OVERNIGHT COMPLETE" if not _bad
                 else f"AEGIS OVERNIGHT INCOMPLETE — {len(_bad)} phase(s): "
                      + ", ".join(f"{n}={r.get('phase_status')}" for n, r in _bad.items()))
    _log(f"{_headline} — {run_id} — {elapsed_total:.0f}s total")
    _log(f"{'='*60}")

    try:
        synth = results.get("synthesis", {})
        # `briefs` is the SYNTHESIS count — briefs generated. Reporting it under
        # a bare "Briefs:" label is what let the digest say "Briefs: 15" on a
        # night when delivery returned {'delivered': False}. The operator reads
        # that number as briefs received.
        _bd = results.get("brief_delivery") or {}
        _delivered = 1 if _bd.get("delivered") is True else 0
        _generated = synth.get("briefs", 0)
        _brief_line = (f"Briefs: {_delivered} delivered / {_generated} generated"
                       if _delivered or not _bd
                       else f"Briefs: 0 delivered / {_generated} generated — "
                            f"delivery {_bd.get('phase_status','?')}: "
                            f"{_bd.get('reason') or _bd.get('error') or 'no reason given'}")
        from telegram_alert import send_telegram
        send_telegram(
            f"{_headline.split(' — ')[0].title()} ({int(elapsed_total/60)}min)\n"
            f"{_brief_line} | Stops: {synth.get('stop_coverage',{}).get('total',0)}\n"
            f"Triggered: {synth.get('stop_coverage',{}).get('triggered',0)} | "
            f"Escalations: {synth.get('steph_escalations',0)}\n"
            f"Steph reviews: {synth.get('steph_reviews',0)} | "
            f"Evidence: {synth.get('evidence_entries',0)}\n"
            f"Check: /v3/trading"
        )
    except Exception:
        pass

    # Release lock
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    lock_fd.close()

    return {"run_id": run_id, "elapsed_seconds": round(elapsed_total, 1), "phases": results}


def _write_handoff_summary(run_id: str, results: dict) -> dict:
    """Write a handoff file summarizing the overnight run for morning review."""
    summary_lines = [
        f"# Aegis Overnight Handoff — {run_id}",
        f"Completed: {datetime.now().isoformat()}",
        "",
    ]

    # Collect key counts
    surv = results.get("surveillance", {})
    ingest = results.get("ingestion", {})
    social = results.get("social", {})
    transcript = results.get("transcript", {})
    synth = results.get("synthesis", {})

    summary_lines.append(f"## Collection")
    summary_lines.append(f"- Surveillance: {surv.get('findings', '?')} findings")
    summary_lines.append(f"- Ingestion: {ingest.get('written', '?')}/{ingest.get('universe', '?')} symbols")
    summary_lines.append(f"- Social: {social.get('written', '?')} sentiment records")
    summary_lines.append(f"- Transcripts: {transcript.get('transcripts', '?')} + {transcript.get('discovery', '?')} discovery")
    summary_lines.append("")
    summary_lines.append(f"## Synthesis")
    summary_lines.append(f"- Briefs: {synth.get('briefs', '?')}")
    summary_lines.append(f"- Covered calls: {synth.get('covered_calls', '?')}")
    summary_lines.append(f"- Rotations: {synth.get('rotations', '?')}")
    summary_lines.append(f"- Steph escalations: {synth.get('steph_escalations', '?')}")
    summary_lines.append(f"- Evidence entries: {synth.get('evidence_entries', '?')}")

    handoff_path = PROJECT_ROOT / "logs" / f"aegis-overnight-handoff-{datetime.now().strftime('%Y%m%d')}.md"
    handoff_path.write_text("\n".join(summary_lines))
    _log(f"  Handoff written: {handoff_path.name}")

    return {"handoff_file": str(handoff_path), "lines": len(summary_lines)}


if __name__ == "__main__":
    main()
