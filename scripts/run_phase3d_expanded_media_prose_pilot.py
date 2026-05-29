#!/usr/bin/env python3
"""run_phase3d_expanded_media_prose_pilot.py — Expanded Phase 3D media/prose pilot."""
import argparse, json, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
OLLAMA = "http://localhost:11434"

from phase3_media_prose_routing_policy import load_policy, is_workflow_allowed, is_workflow_blocked

PILOT_ITEMS = [
    {"wf": "youtube_transcript_summary", "text": "A YouTube transcript discusses Q2 earnings for defense contractors, sector rotation into value, and risk management for momentum traders."},
    {"wf": "transcript_cleanup", "text": "uh so basically the the company reported uh revenue of like 320 million which was uh above estimates and they uh raised guidance for next quarter"},
    {"wf": "content_digest", "text": "This week's portfolio review: defense allocation 38%, 3 recovery candidates improving, 2 paper proposals pending, Aegis identified 2 BDC income opportunities."},
    {"wf": "report_prose_polish", "text": "The results was mixed. Defense stock under pressure. Recovery candidate showing improvement. Income position held steady with dividend."},
    {"wf": "article_summary", "text": "Lockheed Martin beat Q2 estimates with revenue of $18.1B. Raised FY guidance. F-35 deliveries on track. Backlog at record $156B. Dividend increased 5%."},
    {"wf": "news_summary", "text": "RTX announced restructuring of its Pratt & Whitney unit, expecting $500M in charges but $1.5B in annual savings by 2028. Stock rose 3% on the news."},
    {"wf": "content_classification", "text": "Reviewed my AVAV trade. Entry was clean but stop was too tight. Lesson: give momentum trades room."},
    {"wf": "neutral_market_digest", "text": "S&P 500 rose 0.4%. VIX at 14.2. 10Y yield steady at 4.35%. Oil down 1.2%. Gold flat. Defense sector +0.8%. Small caps lagged."},
    {"wf": "documentation_summary", "text": "This document describes the Phase 2H bounded offline hybrid RAG approval policy. It approves hybrid RAG only for deep/offline read-only workflows."},
    {"wf": "source_note_cleanup", "text": "notes: rtx - recovery watch. thesis improving. stopped out at 118 but now at 127. insider buying (cfo). consider re-entry if holds above 125."},
    {"wf": "media_metadata_enrichment", "text": "Video title: 'Defense Stocks 2026 Q2 Update'. Channel: InvestorEdge. Duration: 42min. Published: 2026-05-10. Tags: defense, earnings, sector rotation."},
    {"wf": "post_market_narrative_draft", "text": "Today's portfolio: +0.3%. Defense led by LMT +1.2%. RTX recovery watch improving. JEPI dividend confirmed. No new proposals submitted."},
    {"wf": "weekly_summary_draft", "text": "Week ending 2026-05-09: portfolio +1.1%. 3 recovery candidates improved. 2 proposals approved pending execution recheck. Aegis ran 45 overnight reviews."},
    {"wf": "non_trading_social_draft", "text": "This week we explored how defense sector rotation affects income-focused portfolios. Key takeaway: diversification across dividend and growth names matters."},
    {"wf": "markdown_cleanup", "text": "## heading\n\nthis is some badly formated markdown with **bold** and _italic_ and some bullet points\n- item 1\n- item2\n-item 3"},
]

SAFE_PREFIX = ("You are performing read-only media/prose processing. "
               "Use only the provided text. Do not make trade recommendations.\n\n")

def generate(model, prompt, timeout=90):
    data = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.2, "num_predict": 300}}).encode()
    start = time.monotonic()
    try:
        req = urllib.request.Request(f"{OLLAMA}/api/generate", data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
        return {"response": result.get("response", ""), "latency_ms": round((time.monotonic() - start) * 1000, 1),
                "model": model, "eval_count": result.get("eval_count", 0)}
    except Exception as e:
        return {"response": "", "latency_ms": round((time.monotonic() - start) * 1000, 1),
                "model": model, "error": str(e)[:150]}

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [phase3d-pilot] {msg}", flush=True)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=None)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    policy = load_policy(args.config)
    items = PILOT_ITEMS[:args.limit]
    log(f"Phase 3D pilot: {len(items)} items")

    if args.dry_run:
        for i, it in enumerate(items, 1):
            allowed = is_workflow_allowed(it["wf"], policy)
            blocked = is_workflow_blocked(it["wf"], policy)
            log(f"  {i}. [{it['wf']}] {'ALLOWED' if allowed else ('BLOCKED' if blocked else 'UNKNOWN')}")
        return

    results = []
    start = time.monotonic()
    model = policy.get("candidate_model", "gemma3:4b")
    fallback = policy.get("fallback_model", "gemma3:4b")

    for i, it in enumerate(items, 1):
        if not is_workflow_allowed(it["wf"], policy):
            results.append({"wf": it["wf"], "status": "blocked_or_unknown"})
            if args.verbose: log(f"  [{i}/{len(items)}] {it['wf']}: SKIPPED (not approved)")
            continue

        r = generate(model, SAFE_PREFIX + it["text"])
        fb = False
        if r.get("error") or not r.get("response", "").strip():
            r = generate(fallback, SAFE_PREFIX + it["text"])
            fb = True

        entry = {"wf": it["wf"], "status": "ok", "model": r.get("model"), "fallback": fb,
                 "latency_ms": r.get("latency_ms"), "output_len": len(r.get("response", "")),
                 "preview": r.get("response", "")[:150]}
        results.append(entry)
        if args.verbose:
            log(f"  [{i}/{len(items)}] {it['wf']}: {r.get('model')} {r.get('latency_ms'):.0f}ms "
                f"len={entry['output_len']} fb={fb}")

    elapsed = round(time.monotonic() - start, 1)
    ok = [r for r in results if r.get("status") == "ok"]
    agg = {
        "total": len(results), "ok": len(ok), "skipped": len(results) - len(ok),
        "avg_latency_ms": round(sum(r.get("latency_ms", 0) for r in ok) / max(len(ok), 1), 0),
        "fallback_count": sum(1 for r in ok if r.get("fallback")),
        "elapsed_s": elapsed,
        "workflows_tested": list(set(r["wf"] for r in ok)),
    }

    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "phase": "phase3d",
              "aggregate": agg, "results": results}

    log(f"Done: {agg['ok']}/{agg['total']} ok, {agg['skipped']} skipped, "
        f"lat={agg['avg_latency_ms']}ms, fb={agg['fallback_count']}, {elapsed}s")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).write_text(
            f"# Phase 3D Expanded Pilot\n\n**Date:** {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"| Metric | Value |\n|--------|-------|\n"
            f"| Total | {agg['total']} |\n| OK | {agg['ok']} |\n| Skipped | {agg['skipped']} |\n"
            f"| Avg latency | {agg['avg_latency_ms']}ms |\n| Fallbacks | {agg['fallback_count']} |\n"
            f"| Workflows | {len(agg['workflows_tested'])} |\n| Elapsed | {elapsed}s |\n")

if __name__ == "__main__":
    main()
