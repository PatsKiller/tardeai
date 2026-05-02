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


def _run_phase(name: str, func, *args) -> dict:
    """Run a phase with timing and error handling."""
    _log(f"  PHASE START: {name}")
    start = time.time()
    result = {}
    try:
        result = func(*args) or {}
        elapsed = time.time() - start
        _log(f"  PHASE COMPLETE: {name} — {elapsed:.1f}s — {result}")
    except Exception as e:
        elapsed = time.time() - start
        _log(f"  PHASE FAILED: {name} — {elapsed:.1f}s — {e}")
        result = {"error": str(e)}
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

    # ── PHASE 3: REFINEMENT ──────────────────────────────────────────────
    _log("PHASE 3: REFINEMENT")

    # 3a: Write handoff summary
    handoff = _write_handoff_summary(run_id, results)
    results["handoff"] = handoff

    # 3b: Deliver morning brief (Telegram + formal export)
    from aegis_morning_brief_delivery import deliver as brief_deliver
    results["brief_delivery"] = _run_phase("morning_brief_delivery", brief_deliver)

    # ── COMPLETE ─────────────────────────────────────────────────────────
    elapsed_total = time.time() - start_total
    _log(f"AEGIS OVERNIGHT COMPLETE — {run_id} — {elapsed_total:.0f}s total")
    _log(f"{'='*60}")

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
