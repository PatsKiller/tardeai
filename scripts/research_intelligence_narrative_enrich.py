#!/usr/bin/env python3
"""LLM narrative enrichment for Research Intelligence Hermes rows.

Root cause of prior Ollama failures (2026-07-15):
  local_llm defaults LOCAL_LLM_NUM_PREDICT=300 — JSON briefs need ~600–1000 tokens.
  Responses truncated mid-object → parse fail (logged as "300 tokens").
  gemma3:4b also weak at strict JSON; timeouts when GPU contended.

This script:
  - Raises num_predict for the process before local calls
  - Uses a compact JSON-only prompt
  - Robust JSON extract/repair
  - Lane order: --lane auto → local, then OAuth grok, then chatgpt

Usage:
  python scripts/research_intelligence_narrative_enrich.py --dry-run --retirement-only
  python scripts/research_intelligence_narrative_enrich.py --apply --retirement-only --limit 5
  python scripts/research_intelligence_narrative_enrich.py --apply --lane grok --limit 5
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Must set BEFORE local_llm is imported (read at call time from env, but set early)
os.environ.setdefault("LOCAL_LLM_NUM_PREDICT", "1200")

PROMPT = """You are a financial intelligence editor. Reply with ONLY valid JSON (no markdown).

Title: {title}
Categories: {cats}
Symbol: {symbol}
Summary: {summary}
Thesis: {thesis}

JSON schema:
{{
  "lede": "one sentence",
  "executive_summary": ["para1", "para2"],
  "key_takeaways": ["t1", "t2", "t3"],
  "bull_case": "1-2 sentences or null",
  "bear_case": "1-2 sentences or null",
  "why_it_matters": "1-2 sentences for retirement/portfolio desk",
  "next_action": {{"label": "short CTA", "detail": "one sentence"}}
}}
Do not invent numbers or tickers. Be specific and actionable. Keep total under 500 words.
"""


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Largest {...} block
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    chunk = m.group(0)
    try:
        return json.loads(chunk)
    except Exception:
        pass
    # Repair truncated JSON: close open strings/brackets roughly
    repaired = chunk
    # Remove trailing incomplete key
    repaired = re.sub(r",\s*\"[^\"]*$", "", repaired)
    repaired = re.sub(r",\s*$", "", repaired)
    # Balance braces/brackets
    open_b = repaired.count("{") - repaired.count("}")
    open_a = repaired.count("[") - repaired.count("]")
    if repaired.count('"') % 2 == 1:
        repaired += '"'
    repaired += "]" * max(0, open_a) + "}" * max(0, open_b)
    try:
        return json.loads(repaired)
    except Exception:
        return None


def _normalize_narrative(nar: dict) -> dict | None:
    if not isinstance(nar, dict):
        return None
    lede = nar.get("lede")
    exec_sum = nar.get("executive_summary") or nar.get("overview") or nar.get("body")
    if isinstance(exec_sum, str):
        exec_sum = [p.strip() for p in re.split(r"\n\n+", exec_sum) if p.strip()]
    if not lede and not exec_sum:
        return None
    takeaways = nar.get("key_takeaways") or nar.get("takeaways") or []
    if isinstance(takeaways, str):
        takeaways = [takeaways]
    nxt = nar.get("next_action") or {}
    if isinstance(nxt, str):
        nxt = {"label": nxt[:80], "detail": nxt}
    if not isinstance(nxt, dict):
        nxt = {"label": "Read full analysis", "detail": str(nxt)[:200]}
    return {
        "lede": (lede or (exec_sum[0] if exec_sum else ""))[:320],
        "executive_summary": [str(p)[:600] for p in (exec_sum or [])][:4],
        "key_takeaways": [str(t)[:240] for t in takeaways][:5],
        "bull_case": (nar.get("bull_case") or None),
        "bear_case": (nar.get("bear_case") or None),
        "why_it_matters": (nar.get("why_it_matters") or "")[:400] or None,
        "next_action": {
            "label": str(nxt.get("label") or "Read full analysis")[:80],
            "detail": str(nxt.get("detail") or "")[:240],
        },
    }


def _lane_chain(preferred: str) -> list[str]:
    preferred = (preferred or "auto").lower()
    if preferred == "auto":
        return ["local", "grok", "chatgpt"]
    if preferred == "local":
        return ["local", "grok", "chatgpt"]
    if preferred == "grok":
        return ["grok", "chatgpt", "local"]
    if preferred == "chatgpt":
        return ["chatgpt", "grok", "local"]
    return [preferred]


def _generate_parsed(prompt: str, lanes: list[str], timeout: int = 180) -> tuple[dict | None, str | None]:
    """Try each lane until JSON narrative parses. OAuth after local failure."""
    import llm_lane
    last_err = None
    for lane in lanes:
        if not llm_lane.available(lane):
            print(f"  · skip {lane} (unavailable)")
            continue
        try:
            if lane == "local":
                os.environ["LOCAL_LLM_NUM_PREDICT"] = "1200"
            print(f"  · trying lane={lane}…")
            text = llm_lane.generate(
                prompt,
                lane=lane,
                timeout=timeout if lane != "local" else max(timeout, 180),
                process_id="ri_narrative_enrich",
                task_summary="ri narrative enrich",
                manual_trigger=True,
            )
            if not text or not str(text).strip():
                print(f"  · {lane} empty response")
                continue
            text = str(text).strip()
            nar = _normalize_narrative(_extract_json(text) or {})
            if nar:
                return nar, lane
            preview = text[:160].replace("\n", " ")
            print(f"  · {lane} parse fail preview={preview!r} → next lane")
        except Exception as e:
            last_err = e
            print(f"  · {lane} error: {str(e)[:160]}")
            continue
    if last_err:
        print(f"  · all lanes failed last={last_err}")
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument(
        "--lane", default="auto",
        choices=["auto", "local", "grok", "chatgpt"],
        help="auto = local then OAuth grok then chatgpt",
    )
    ap.add_argument("--retirement-only", action="store_true")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    from db_adapter import _execute, USE_DB
    if not USE_DB:
        print("DB unavailable", file=sys.stderr)
        return 2

    if args.retirement_only:
        rows = _execute(
            """
            SELECT id, topic, summary, thesis, symbol, research_type, evidence_json, confidence_score
            FROM hermes_research_intelligence
            WHERE status IN ('staged','reviewed','promoted')
              AND COALESCE(summary,'') <> ''
              AND (evidence_json IS NULL OR evidence_json->'narrative' IS NULL)
              AND (
                topic ~* '(roth|irmaa|medicare|ssdi|golden window|rmd|medicaid|mapt|conversion|retirement tax)'
                OR summary ~* '(roth conversion|irmaa|golden window|medicare part|ssdi|rmd|tax bracket)'
              )
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (max(args.limit * 2, 12),),
            fetch="all",
        ) or []
    else:
        rows = _execute(
            """
            SELECT id, topic, summary, thesis, symbol, research_type, evidence_json, confidence_score
            FROM hermes_research_intelligence
            WHERE status IN ('staged','reviewed','promoted')
              AND COALESCE(summary,'') <> ''
              AND (evidence_json IS NULL OR evidence_json->'narrative' IS NULL)
              AND research_type NOT IN ('stop_health','stop_curation','protection_advisory')
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (max(1, min(args.limit * 3, 40)),),
            fetch="all",
        ) or []

    from lib.research_intelligence import classify_text

    selected = []
    for r in rows:
        cats = classify_text(
            r.get("topic"), r.get("summary"), r.get("thesis"),
            research_type=r.get("research_type"),
        )
        if args.retirement_only and "retirement_tax" not in cats:
            cats = ["retirement_tax"] + [c for c in cats if c != "retirement_tax"]
        selected.append((r, cats))
        if len(selected) >= args.limit:
            break

    lanes = _lane_chain(args.lane)
    print(f"[narrative-enrich] candidates={len(selected)} apply={args.apply} lanes={lanes}")
    if not selected:
        return 0

    if not args.apply:
        for r, cats in selected:
            print(f"  · hermes:{r['id']} {(r.get('topic') or '')[:55]} cats={cats[:2]}")
        return 0

    ok, fail = 0, 0
    for r, cats in selected:
        prompt = PROMPT.format(
            title=(r.get("topic") or "")[:160],
            cats=", ".join(cats[:3]),
            symbol=r.get("symbol") or "—",
            summary=(r.get("summary") or "")[:900],
            thesis=(r.get("thesis") or "")[:350],
        )
        try:
            nar, used_lane = _generate_parsed(prompt, lanes, timeout=args.timeout)
            if not nar:
                print(f"  ! no narrative hermes:{r['id']} (all lanes failed)")
                fail += 1
                continue
            ev = r.get("evidence_json")
            if isinstance(ev, str):
                try:
                    ev = json.loads(ev)
                except Exception:
                    ev = {}
            if not isinstance(ev, dict):
                ev = {}
            ev["narrative"] = nar
            ev["narrative_model"] = used_lane
            ev["narrative_enriched_at"] = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat()
            _execute(
                """
                UPDATE hermes_research_intelligence
                SET evidence_json = %s::jsonb, updated_at = NOW()
                WHERE id = %s
                """,
                (json.dumps(ev), r["id"]),
                fetch=None,
            )
            print(f"  ✓ hermes:{r['id']} narrative via {used_lane}")
            ok += 1
        except Exception as e:
            print(f"  ! hermes:{r['id']} {e}")
            fail += 1

    print(f"[narrative-enrich] done ok={ok} fail={fail}")
    print(
        "Root cause note: default LOCAL_LLM_NUM_PREDICT=300 truncates JSON; "
        "this run uses 1200 + OAuth fallback."
    )
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
