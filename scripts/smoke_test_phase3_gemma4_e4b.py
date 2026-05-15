#!/usr/bin/env python3
"""smoke_test_phase3_gemma4_e4b.py — Quick structured smoke test for gemma4:e4b.
Compares against qwen3:14b baseline using /no_think mode for fair media/prose comparison.
Does NOT change production routing."""
import argparse, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OLLAMA = "http://localhost:11434"
LOCK = "/tmp/tradeai_phase3a_gemma4_smoke.lock"

TESTS = [
    {"id": "summary_transcript", "cat": "transcript_summary",
     "prompt": "Summarize this in 3 concise bullets:\nA long earnings call transcript discusses Q2 revenue growth of 12%, management's cautious outlook on sector rotation away from defense, and new risk management guidelines requiring tighter stop placement on momentum positions."},
    {"id": "news_digest", "cat": "news_summary",
     "prompt": "Write a 2-sentence neutral digest:\nLockheed Martin reported better-than-expected quarterly earnings. The defense giant raised full-year guidance citing strong international demand for F-35 jets and missile defense systems."},
    {"id": "prose_polish", "cat": "report_polish",
     "prompt": "Rewrite as a concise analyst paragraph:\nThe portfolio had mixed results last week. Defense stocks were under pressure due to budget uncertainty. Recovery candidates like RTX showed improvement. Income positions held steady."},
    {"id": "classify", "cat": "classification",
     "prompt": "Classify as exactly one of: transcript, news, trade_journal, proposal.\n\nContent: 'Reviewed my AVAV trade. Entry was clean at breakout but I moved my stop too early, getting shaken out before the move completed.'"},
    {"id": "fact_extract", "cat": "fact_extraction",
     "prompt": "Extract only factual statements. Do NOT make trade recommendations.\n\nRTX closed at $127.50, up 2.3%. Volume was 1.2x average. RSI is at 62. Above 200-day MA. CFO bought shares per Form 4."},
]

PROMPT_STYLES = {
    "plain": lambda p: p,
    "system": lambda p: f"You are a concise content summarizer. Use only source text. No trade recommendations.\n\n{p}",
    "chatml": lambda p: f"<start_of_turn>user\n{p}\n<end_of_turn>\n<start_of_turn>model\n",
}

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [smoke] {msg}", flush=True)

def generate(model, prompt, options=None, timeout=90):
    opts = options or {}
    data = json.dumps({"model": model, "prompt": prompt, "stream": False, "options": opts}).encode()
    start = time.monotonic()
    try:
        req = urllib.request.Request(f"{OLLAMA}/api/generate", data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
        lat = round((time.monotonic() - start) * 1000, 1)
        return {"response": result.get("response", ""), "latency_ms": lat,
                "eval_count": result.get("eval_count", 0),
                "load_ms": round(result.get("load_duration", 0) / 1e6, 1)}
    except Exception as e:
        return {"response": "", "latency_ms": round((time.monotonic() - start) * 1000, 1),
                "error": str(e)[:200], "eval_count": 0, "timeout": True}

def score(test, text):
    r = text.strip()
    s = {}
    s["instruction"] = 4 if len(r) > 20 else (2 if len(r) > 5 else 0)
    s["factuality"] = 3
    if "bullet" in test.get("cat", "") and any(c in r for c in ["•", "- ", "* ", "1."]):
        s["formatting"] = 5
    elif "classif" in test.get("cat", "") and any(w in r.lower() for w in ["transcript", "news", "trade_journal", "proposal"]):
        s["formatting"] = 5
    else:
        s["formatting"] = 3
    s["concision"] = 5 if len(r) < 400 else (3 if len(r) < 800 else 1)
    trade_words = ["buy", "sell", "hold", "recommend", "entry point", "target price"]
    s["safety"] = 2 if any(w in r.lower() for w in trade_words) else 5
    s["total"] = round(sum(s.values()) / len(s), 1)
    return s

def unload_restore():
    log("Cleanup: unload gemma4, restore production...")
    try:
        urllib.request.urlopen(urllib.request.Request(f"{OLLAMA}/api/generate",
            data=json.dumps({"model": "gemma4:e4b", "keep_alive": 0, "prompt": ""}).encode(),
            headers={"Content-Type": "application/json"}), timeout=15)
    except Exception: pass
    time.sleep(3)
    try:
        urllib.request.urlopen(urllib.request.Request(f"{OLLAMA}/api/generate",
            data=json.dumps({"model": "qwen3:14b", "prompt": "/no_think\nok",
                             "options": {"num_predict": 1, "think": False}}).encode(),
            headers={"Content-Type": "application/json"}), timeout=120)
    except Exception: pass
    try:
        urllib.request.urlopen(urllib.request.Request(f"{OLLAMA}/api/embeddings",
            data=json.dumps({"model": "nomic-embed-text", "prompt": "restore"}).encode(),
            headers={"Content-Type": "application/json"}), timeout=30)
    except Exception: pass

def main():
    p = argparse.ArgumentParser(description="Phase 3A gemma4:e4b quick smoke test")
    p.add_argument("--candidate-model", default="gemma4:e4b")
    p.add_argument("--baseline-model", default="qwen3:14b")
    p.add_argument("--quick", action="store_true", help="Quick mode (default)")
    p.add_argument("--full-matrix", action="store_true")
    p.add_argument("--baseline-limit", type=int, default=5)
    p.add_argument("--candidate-limit", type=int, default=12)
    p.add_argument("--baseline-no-think", action="store_true", default=True)
    p.add_argument("--per-call-timeout-sec", type=int, default=90)
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    # Lock
    if os.path.exists(LOCK):
        try:
            pid = int(Path(LOCK).read_text().strip())
            os.kill(pid, 0)
            log(f"ABORT: Another smoke test running (pid={pid})")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            os.remove(LOCK)
    Path(LOCK).write_text(str(os.getpid()))

    try:
        _run(args)
    finally:
        try: os.remove(LOCK)
        except: pass

def _run(args):
    tests = TESTS[:args.baseline_limit]
    styles = list(PROMPT_STYLES.items())
    if not args.full_matrix:
        styles = styles[:3]

    log(f"Quick smoke: baseline={args.baseline_model} (/no_think), candidate={args.candidate_model}")
    log(f"Baseline tests: {len(tests)}, Candidate limit: {args.candidate_limit}")

    results = []
    partial_path = Path(args.output_json.replace(".json", ".partial.json")) if args.output_json else None
    start = time.monotonic()

    # Baseline with /no_think
    log("--- Baseline (qwen3:14b /no_think) ---")
    base_opts = {"temperature": 0.2, "num_predict": 160, "num_ctx": 2048}
    if args.baseline_no_think:
        base_opts["think"] = False

    for test in tests:
        prompt = f"/no_think\nYou are a concise content summarizer. No trade recommendations.\n\n{test['prompt']}"
        r = generate(args.baseline_model, prompt, base_opts, args.per_call_timeout_sec)
        s = score(test, r.get("response", ""))
        entry = {"test_id": test["id"], "model": args.baseline_model, "style": "no_think",
                 "options": "default", **r, "scores": s}
        results.append(entry)
        if args.verbose:
            log(f"  base {test['id']}: {r['latency_ms']:.0f}ms score={s['total']} len={len(r.get('response',''))}"
                f"{' TIMEOUT' if r.get('timeout') else ''}")
        if partial_path:
            partial_path.write_text(json.dumps({"partial": True, "results": results}, indent=2, default=str))

    # Candidate
    log(f"--- Candidate ({args.candidate_model}) ---")
    cand_opts = {"temperature": 0.2, "num_predict": 160, "num_ctx": 2048}
    cand_count = 0

    for style_name, style_fn in styles:
        if cand_count >= args.candidate_limit:
            break
        for test in tests:
            if cand_count >= args.candidate_limit:
                break
            prompt = style_fn(test["prompt"])
            r = generate(args.candidate_model, prompt, cand_opts, args.per_call_timeout_sec)
            s = score(test, r.get("response", ""))
            entry = {"test_id": test["id"], "model": args.candidate_model, "style": style_name,
                     "options": "default", **r, "scores": s}
            results.append(entry)
            cand_count += 1
            if args.verbose:
                log(f"  cand [{style_name}] {test['id']}: {r['latency_ms']:.0f}ms score={s['total']} "
                    f"len={len(r.get('response',''))}{' TIMEOUT' if r.get('timeout') else ''}")
            if partial_path:
                partial_path.write_text(json.dumps({"partial": True, "results": results}, indent=2, default=str))

    elapsed = round(time.monotonic() - start, 1)

    # Aggregate
    base = [r for r in results if r["model"] == args.baseline_model and not r.get("timeout")]
    cand = [r for r in results if r["model"] == args.candidate_model and not r.get("timeout")]
    b_avg = round(sum(r["scores"]["total"] for r in base) / max(len(base), 1), 2)
    c_avg = round(sum(r["scores"]["total"] for r in cand) / max(len(cand), 1), 2)
    b_lat = round(sum(r["latency_ms"] for r in base) / max(len(base), 1), 0)
    c_lat = round(sum(r["latency_ms"] for r in cand) / max(len(cand), 1), 0)
    best_c = max(cand, key=lambda r: r["scores"]["total"]) if cand else {}
    timeouts = sum(1 for r in results if r.get("timeout"))

    verdict = "CANDIDATE_BETTER" if c_avg > b_avg + 0.3 else ("TIE" if abs(c_avg - b_avg) <= 0.3 else "BASELINE_BETTER")

    report = {
        "timestamp": datetime.now().isoformat(), "mode": "quick",
        "candidate": args.candidate_model, "baseline": args.baseline_model,
        "baseline_mode": "no_think", "total_tests": len(results),
        "baseline_tests": len(base), "candidate_tests": len(cand), "timeouts": timeouts,
        "elapsed_s": elapsed, "baseline_avg_score": b_avg, "candidate_avg_score": c_avg,
        "baseline_avg_latency_ms": b_lat, "candidate_avg_latency_ms": c_lat,
        "best_candidate": {"test_id": best_c.get("test_id"), "style": best_c.get("style"),
                           "score": best_c.get("scores", {}).get("total"), "latency": best_c.get("latency_ms")},
        "verdict": verdict, "results": results,
        "notes": ["qwen3 baseline used /no_think for fair media/prose comparison",
                   "gemma4:e4b is 9.6 GB — fails lightweight co-residency goal",
                   "no production routing changed"],
    }

    log(f"=== Results ===")
    log(f"Baseline: score={b_avg}, lat={b_lat}ms ({len(base)} tests)")
    log(f"Candidate: score={c_avg}, lat={c_lat}ms ({len(cand)} tests)")
    log(f"Best candidate: {best_c.get('test_id')} [{best_c.get('style')}] score={best_c.get('scores',{}).get('total')}")
    log(f"Timeouts: {timeouts}")
    log(f"Verdict: {verdict}")
    log(f"Elapsed: {elapsed}s")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        lines = ["# Phase 3A gemma4:e4b Quick Smoke Test", f"\n**Date:** {datetime.now().strftime('%Y-%m-%d')}",
                 "\n**Note:** qwen3 baseline used /no_think. gemma4:e4b is 9.6 GB (not lightweight).",
                 f"\n## Results\n", f"| Metric | Baseline (qwen3) | Candidate (gemma4) |",
                 f"|--------|------------------|-------------------|",
                 f"| Avg score | {b_avg} | {c_avg} |",
                 f"| Avg latency | {b_lat}ms | {c_lat}ms |",
                 f"| Tests | {len(base)} | {len(cand)} |",
                 f"| Timeouts | — | {timeouts} |",
                 f"| Verdict | — | **{verdict}** |",
                 f"\n## Production Impact\n\nNone.\n"]
        Path(args.output_md).write_text("\n".join(lines))

    unload_restore()
    log("Done.")

if __name__ == "__main__":
    main()
