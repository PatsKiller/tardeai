#!/usr/bin/env python3
"""claude_challenger_curator.py — weekly Claude-curated CHALLENGER cohort (pure A/B vs the screener).

Once a week, Claude (the metered high-level API) curates ~100 US-listed candidates across diverse
themes / trends / sectors — INDEPENDENTLY of the Finviz screener — so the recommendation-intelligence
engine can compare `claude_challenger`-origin returns head-to-head against `scan`/`screener`-origin.

What it does (advisory only, paper-tracked):
  1. Prompts Claude for a diversified 100-name thematic challenger list (JSON).
  2. Upserts each into incubator_universe with source='claude_challenger' (roll-on/roll-off tracked).
  3. Records rec_ticker_attribution(source_type='claude_challenger') so return-by-origin is measurable.
  4. Logs an incubator_events roll-on row.

The research_scheduler then picks the cohort up as a tier and fans gemma/Grok/ChatGPT research over it.
Dry-run by default; --apply writes. Claude stays metered-curation-only (one call/week), never in sweeps.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

TARGET_N = int(os.getenv("CHALLENGER_TARGET_N", "100"))
BATCH_N = int(os.getenv("CHALLENGER_BATCH_N", "25"))    # per-call size (small enough to fit token budget + HTTP timeout)
MODEL = os.getenv("CHALLENGER_MODEL", "claude-sonnet-4-6")
SOURCE_TAG = "claude_challenger"

PROMPT = """You are a senior buy-side portfolio manager building a CHALLENGER watchlist that will be \
A/B-tested against a mechanical Finviz screener. Curate exactly {n} US-listed equities (common stocks \
or liquid ETFs) that you believe have favorable risk/reward over the next 1-3 months, chosen by \
top-down reasoning about THEMES, TRENDS, and SECTOR rotations — the kind of edge a mechanical \
RVOL/gap/value screener cannot see.

Requirements:
- Diversify across many GICS sectors and distinct themes/trends.
- Mix time-horizons: some momentum/catalyst names, some structural/secular compounders, some \
contrarian/mean-reversion.
- Avoid obvious mega-cap consensus names unless your thesis is genuinely differentiated.
- US-listed, real tickers only. No OTC/pink sheets.{avoid}

Return ONLY valid JSON — a JSON array of exactly {n} objects, each with keys:
  "symbol"      (uppercase ticker),
  "company"     (short name),
  "sector"      (GICS sector),
  "theme"       (the macro/thematic/trend driver, e.g. "AI datacenter power", "defense supercycle"),
  "conviction"  ("high" | "medium" | "low"),
  "thesis"      (one sentence — why now),
  "catalyst"    (near-term catalyst if any, else "").
No prose before or after the JSON."""


def _is_symbol(s: str) -> bool:
    s = (s or "").upper().strip()
    return bool(s) and bool(re.fullmatch(r"[A-Z]{1,5}", s))


def _one_batch(n: int, avoid: list[str]) -> list[dict]:
    """One metered Claude call for n names, avoiding already-chosen symbols."""
    from hermes_external_researcher import call_external
    avoid_txt = ""
    if avoid:
        avoid_txt = ("\n- Do NOT repeat any of these already-chosen tickers: " + ", ".join(sorted(avoid)) + ".")
    prompt = PROMPT.format(n=n, avoid=avoid_txt)
    raw = call_external("claude", MODEL, prompt, max_tokens=6000)
    return _parse_json_array(raw)


def _parse_json_array(raw: str) -> list[dict]:
    """Robust array parse: strip ``` fences, then salvage complete {...} objects even if truncated."""
    if not raw or not raw.strip():
        return []
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    start = text.find("[")
    if start >= 0:
        text = text[start:]
    try:
        return json.loads(text)
    except Exception:
        pass
    # truncated/dirty — salvage every complete top-level object
    objs, depth, buf, in_obj = [], 0, "", False
    for ch in text:
        if ch == "{":
            depth += 1; in_obj = True
        if in_obj:
            buf += ch
        if ch == "}":
            depth -= 1
            if depth == 0 and in_obj:
                try:
                    objs.append(json.loads(buf))
                except Exception:
                    pass
                buf, in_obj = "", False
    return objs


def curate() -> list[dict]:
    """Batched Claude curation (each call < HTTP timeout) → parsed, validated, de-duped list."""
    out, seen = [], set()
    remaining = TARGET_N
    batch = 0
    while remaining > 0 and batch < 6:
        batch += 1
        ask = min(BATCH_N, remaining)
        items = _one_batch(ask, list(seen))
        before = len(out)
        for it in items:
            if not isinstance(it, dict):
                continue
            sym = str(it.get("symbol") or "").upper().strip()
            if not _is_symbol(sym) or sym in seen:
                continue
            seen.add(sym)
            out.append({
                "symbol": sym,
                "company": str(it.get("company") or "")[:120],
                "sector": str(it.get("sector") or "")[:60],
                "theme": str(it.get("theme") or "")[:120],
                "conviction": str(it.get("conviction") or "medium").lower()[:10],
                "thesis": str(it.get("thesis") or "")[:400],
                "catalyst": str(it.get("catalyst") or "")[:300],
            })
        gained = len(out) - before
        print(f"[challenger] batch {batch}: +{gained} new (total {len(out)}/{TARGET_N})")
        remaining = TARGET_N - len(out)
        if gained == 0:
            break   # Claude exhausted fresh ideas
    return out


def infuse(cands: list[dict], apply: bool) -> dict:
    """Idempotent upsert keyed on (symbol, strategy_id='claude_challenger') — NEVER touches other
    strategies' incubator rows. Each pick → incubator_universe + incubator_events + rec attribution."""
    from db_adapter import _execute
    now = datetime.now(timezone.utc)
    run_label = now.strftime("CHAL-%Y%m%d")
    STRAT = "claude_challenger"
    written = 0
    for c in cands:
        sym = c["symbol"]
        payload = json.dumps({k: c[k] for k in ("company", "sector", "theme", "conviction", "catalyst")})
        if not apply:
            continue
        # only ever the challenger's OWN row per symbol (unique on symbol, strategy_id)
        _execute("""INSERT INTO incubator_universe
                    (symbol, strategy_id, first_seen_at, last_seen_at, status, lifecycle_state,
                     source_first_seen, source_latest, source_run_label, sector, catalyst,
                     notes, evidence_payload, created_at, updated_at)
                    VALUES (%s,%s,NOW(),NOW(),'active','incubating',%s,%s,%s,%s,%s,%s,%s::jsonb,NOW(),NOW())
                    ON CONFLICT (symbol, strategy_id) DO UPDATE SET
                      last_seen_at=NOW(), status='active', source_latest=EXCLUDED.source_latest,
                      source_run_label=EXCLUDED.source_run_label,
                      sector=COALESCE(NULLIF(EXCLUDED.sector,''), incubator_universe.sector),
                      catalyst=EXCLUDED.catalyst, notes=EXCLUDED.notes,
                      evidence_payload=EXCLUDED.evidence_payload, updated_at=NOW()""",
                 (sym, STRAT, SOURCE_TAG, SOURCE_TAG, run_label, c["sector"],
                  c["catalyst"], c["thesis"], payload), fetch=None)
        # roll-on event (reason_codes + payload are jsonb)
        _execute("""INSERT INTO incubator_events (symbol, strategy_id, event_type, reason_codes, payload, created_at)
                    VALUES (%s,%s,'roll_on',%s::jsonb,%s::jsonb,NOW())""",
                 (sym, STRAT, json.dumps(["claude_challenger", c["conviction"]]), payload), fetch=None)
        # return-by-origin attribution (source_detail is jsonb)
        _execute("""INSERT INTO rec_ticker_attribution
                    (symbol, source_type, source_ref_table, source_detail, rationale,
                     first_seen_at, last_seen_at, occurrences, created_at, updated_at)
                    VALUES (%s,%s,'incubator_universe',%s::jsonb,%s,NOW(),NOW(),1,NOW(),NOW())""",
                 (sym, SOURCE_TAG, json.dumps({"theme": c["theme"], "conviction": c["conviction"]}),
                  c["thesis"]), fetch=None)
        written += 1
    return {"written": written, "run_label": run_label}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write to incubator + attribution (default dry-run)")
    ap.add_argument("--show", action="store_true", help="print the curated list")
    a = ap.parse_args()
    print(f"[challenger] curating {TARGET_N} names via Claude ({MODEL})…")
    cands = curate()
    print(f"[challenger] Claude returned {len(cands)} valid unique candidates")
    sectors = sorted({c["sector"] for c in cands if c["sector"]})
    themes = sorted({c["theme"] for c in cands if c["theme"]})
    print(f"[challenger] diversity: {len(sectors)} sectors, {len(themes)} themes")
    if a.show or not a.apply:
        for c in cands[:120]:
            print(f"  {c['symbol']:6s} {c['conviction']:6s} {c['sector'][:18]:18s} {c['theme'][:26]:26s} {c['thesis'][:60]}")
    res = infuse(cands, a.apply)
    print(f"[challenger] {'APPLIED' if a.apply else 'DRY'} — {res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
