#!/usr/bin/env python3
"""llm_health_check.py — three-lane LLM review health snapshot (operator 2026-06-19).

Observability wrapper. The per-lane availability check ALREADY lives in llm_lane.available() (Grok xAI
proxy :8645, ChatGPT codex proxy :8646, local gemma) — this DELEGATES to it (no duplicate probing) and
adds the review-corpus quality read so the operator has one honest health view. Read-only; cheap
pre-flights only (no generation tokens).

Note (2026-06-19): the live review corpus is healthy — ~97% valid, all lanes up. This endpoint exists
to keep it observable, not because there was a crisis.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

LANES = ("local", "grok", "chatgpt", "deepseek-flash", "deepseek-v4-pro")


def lane_status() -> dict:
    """Live per-lane availability via the canonical source (llm_lane.available). Never raises."""
    out = {}
    try:
        import llm_lane
        for lane in LANES:
            try:
                out[lane] = {"available": bool(llm_lane.available(lane))}
            except Exception as e:
                out[lane] = {"available": False, "reason": str(e)[:80]}
    except Exception as e:
        for lane in LANES:
            out[lane] = {"available": False, "reason": f"llm_lane import failed: {str(e)[:60]}"}
    out["any_available"] = any(v.get("available") for v in out.values() if isinstance(v, dict))
    return out


def corpus_quality(days: int = 30) -> dict:
    """Review-corpus quality from paper_trade_multi_reviews (real schema: model_used/review_text). Reports
    valid vs error/empty so a degraded lane shows up as falling validity, by model."""
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("""
            SELECT model_used,
              CASE WHEN review_text ILIKE '%%timed out%%' OR review_text ILIKE '%%timeout%%' THEN 'timeout'
                   WHEN review_text ILIKE '%%connection refused%%' THEN 'conn_refused'
                   WHEN review_text ILIKE '%%error%%' OR review_text ILIKE '%%unavailable%%' THEN 'error'
                   WHEN review_text IS NULL OR review_text = '' THEN 'empty'
                   ELSE 'valid' END AS category,
              count(*) AS n
            FROM paper_trade_multi_reviews
            WHERE created_at > now() - (%s || ' days')::interval
            GROUP BY 1, 2 ORDER BY 3 DESC""", (days,))
        rows = [{"model": r[0], "category": r[1], "n": r[2]} for r in cur.fetchall()]
        total = sum(r["n"] for r in rows)
        valid = sum(r["n"] for r in rows if r["category"] == "valid")
        return {"window_days": days, "total": total, "valid": valid,
                "valid_rate": round(valid / max(total, 1), 3),
                "by_model_category": rows}
    except Exception as e:
        return {"error": str(e)[:120]}


def check_all_lanes(days: int = 30) -> dict:
    return {"lanes": lane_status(), "review_corpus": corpus_quality(days),
            "note": ("5 lanes: local (Ollama gemma3:4b), grok (xAI OAuth :8645), chatgpt (codex OAuth :8646), "
                     "deepseek-flash (paid API), deepseek-v4 (paid API, R1 reasoning). "
                     "Availability via llm_lane.available(); corpus from paper_trade_multi_reviews.")}


if __name__ == "__main__":
    import json
    r = check_all_lanes()
    print(json.dumps(r, indent=2, default=str))
    up = [k for k, v in r["lanes"].items() if isinstance(v, dict) and v.get("available")]
    print(f"\n{'✓ lanes up: ' + str(up) if up else '⚠ ALL LANES DOWN'} · "
          f"corpus valid_rate={r['review_corpus'].get('valid_rate')}")
