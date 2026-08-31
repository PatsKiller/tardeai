#!/usr/bin/env python3
"""Catalyst Momentum Engine — continuous catalyst-driven momentum/scalp + swing research.

Orchestrates existing pieces (momentum candidate reader + SearXNG catalyst researcher +
scalp-critic gate) on 3 cadence bands, and feeds BOTH:
  (1) advisory/decision-support — stages catalyst findings into hermes_research_intelligence
      (research_type='momentum_catalyst'), which the live promote→cache/RAG path carries to the
      core agents (operator directive B).
  (2) gated proposals — for high-conviction catalyst-confirmed movers, invokes the EXISTING
      gated auto_proposal_generator.py --apply (11 safety gates + risk gate, paper only).
      NEVER bypasses gates; capped per run.

Bands: premarket_scalp (4–11 AM, fast), market_swing (9:30–4, multi-hour/day), overnight (24/7 baseline).
LLM classification on gemma3:4b. Kill-switch aware (data/runtime/HERMES_DISABLED). Default dry-run.
"""
import os
import sys
import json
import argparse
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
_env_path = ROOT / ".env"
if _env_path.is_file():
    for line in _env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [catalyst-momentum] %(message)s")
log = logging.getLogger("catalyst_momentum")
PY = str(ROOT / ".venv" / "bin" / "python")
# Kill switch: prefer served-state root, fall back to checkout (legacy).
# E5: resolution layer, not cron cwd — CURRENT/data/runtime is a symlink into
# persistent-state, so the served path is what operators and other pins see.


def _served_state_root() -> Path:
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root())
    except Exception:
        try:
            from lib.canonical_store_registry import production_state_root  # type: ignore
            return Path(production_state_root())
        except Exception:
            return Path.home() / "trade-ai-releases" / "persistent-state"


def _kill_paths() -> list[Path]:
    root = _served_state_root()
    return [
        root / "data" / "runtime" / "HERMES_DISABLED",
        ROOT / "data" / "runtime" / "HERMES_DISABLED",
    ]


LAST_RUN_RELATIVE = Path("data") / "cio" / "catalyst_momentum_last_run.json"
DB = dict(host=os.getenv("DB_HOST", "127.0.0.1"), port=int(os.getenv("DB_PORT", "5432")),
          dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
          password=os.getenv("DB_PASSWORD", ""))

# Cadence bands: candidate selectivity + caps + whether to auto-generate gated proposals
BANDS = {
    "premarket_scalp": {"min_rvol": 5.0, "min_score": 30, "max": 8, "gen_proposals": True, "prop_cap": 3, "kind": "scalp"},
    "market_swing":    {"min_rvol": 3.0, "min_score": 40, "max": 6, "gen_proposals": True, "prop_cap": 2, "kind": "swing"},
    "overnight":       {"min_rvol": 5.0, "min_score": 30, "max": 4, "gen_proposals": True, "prop_cap": 1, "kind": "swing"},
}


def kill_active():
    return any(p.exists() for p in _kill_paths())


def _write_last_run(payload: dict) -> Path | None:
    """Persist last-run marker on the served state root (not checkout)."""
    try:
        path = _served_state_root() / LAST_RUN_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        tmp.replace(path)
        return path
    except Exception as exc:
        log.warning("could not write served last-run marker: %s", exc)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--band", choices=list(BANDS), default="premarket_scalp")
    ap.add_argument("--apply", action="store_true", help="stage catalyst findings (feed #1)")
    ap.add_argument("--generate-proposals", action="store_true", help="also auto-create gated paper proposals (feed #2)")
    args = ap.parse_args()
    if kill_active():
        log.warning("kill switch active — engine halted"); return 0
    if os.environ.get("ALPACA_MODE", "") != "paper" and args.generate_proposals:
        log.error("ALPACA_MODE must be paper for proposal generation. Aborting."); return 1

    band = BANDS[args.band]
    log.info("Catalyst Momentum Engine — band=%s (apply=%s, gen_proposals=%s)", args.band, args.apply, args.generate_proposals and band["gen_proposals"])
    log.info("  served_state_root=%s", _served_state_root())

    from hermes_momentum_candidate_reader import get_momentum_candidates
    from hermes_momentum_catalyst_researcher import search_catalyst, classify_catalyst
    cands = get_momentum_candidates(max_tickers=band["max"], min_rvol=band["min_rvol"], min_score=band["min_score"])
    log.info("  %d candidates (RVOL≥%s, score≥%s)", len(cands), band["min_rvol"], band["min_score"])

    conn = psycopg2.connect(**DB); conn.autocommit = True
    cur = conn.cursor()
    staged, gated, proposals = 0, [], 0
    for c in cands:
        sym = c["symbol"] if isinstance(c, dict) else c
        try:
            sources = search_catalyst(sym, "premarket catalyst" if band["kind"] == "scalp" else "catalyst news swing")
        except Exception as e:
            log.warning("  %s: catalyst search failed: %s", sym, e); continue
        if not sources:
            continue  # ACCURACY GATE: no catalyst → skip (no fabricated signal)
        text = " ".join(s.get("title", "") + " " + s.get("content", "") for s in sources[:3])
        ctype = classify_catalyst(text)
        urls = [s.get("url") for s in sources if s.get("url")][:5]
        conf = round(min(0.9, 0.4 + 0.1 * len(sources)), 2)
        summary = f"{band['kind']} momentum catalyst ({ctype}) for {sym}: RVOL {c.get('rvol')}, gap {c.get('gap_pct')}%, {len(sources)} sources"
        # FEED #1 — advisory: stage into hermes_research_intelligence (→ promote→cache/RAG)
        if args.apply:
            cur.execute("""INSERT INTO hermes_research_intelligence
                           (research_type, symbol, topic, summary, confidence_score, status, source, source_urls_json, hermes_agent_name, model_used, freshness_date, created_at)
                           VALUES ('momentum_catalyst', %s, %s, %s, %s, 'staged', 'hermes', %s, 'catalyst_momentum_engine', 'gemma3:4b', CURRENT_DATE, NOW())""",
                        (sym, f"{ctype}: {sym}", summary, conf, json.dumps(urls)))
            staged += 1
        # collect catalyst-confirmed high-conviction for feed #2
        if conf >= 0.6 and float(c.get("rvol") or 0) >= band["min_rvol"]:
            gated.append((sym, conf, ctype))
        log.info("  %s: %s conf=%.2f (%d sources)%s", sym, ctype, conf, len(sources), " ✓gateable" if conf >= 0.6 else "")

    # FEED #2 — gated proposals via existing pipeline (paper, 11 gates + risk gate). Capped.
    if args.generate_proposals and band["gen_proposals"]:
        for sym, conf, ctype in sorted(gated, key=lambda x: -x[1])[:band["prop_cap"]]:
            try:
                r = subprocess.run([PY, "scripts/auto_proposal_generator.py", "--symbol", sym, "--apply", "--limit", "1"],
                                   cwd=str(ROOT), capture_output=True, text=True, timeout=300, env={**os.environ, "ALPACA_MODE": "paper"})
                ok = r.returncode == 0
                tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
                log.info("  proposal[%s]: %s — %s", sym, "ok" if ok else f"exit {r.returncode}", tail[0][:100])
                if ok:
                    proposals += 1
            except Exception as e:
                log.warning("  proposal[%s] failed: %s", sym, e)

    log.info("Done: %d staged (advisory), %d catalyst-confirmed, %d gated proposals attempted", staged, len(gated), proposals)
    marker = {
        "schema": "CatalystMomentumLastRun@v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "band": args.band,
        "apply": bool(args.apply),
        "candidates": len(cands),
        "staged": staged,
        "catalyst_confirmed": len(gated),
        "proposals_attempted": proposals,
        "served_state_root": str(_served_state_root()),
        "scheduled": True,
        "authority": "READ_ONLY_ADVISORY",
        "note": (
            "Engine is scheduled. hermes_momentum_catalyst_researcher still writes "
            "checkout-relative jsonl; consumers must resolve via production_state_root."
        ),
    }
    path = _write_last_run(marker)
    if path:
        log.info("  wrote served last-run marker %s", path)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
