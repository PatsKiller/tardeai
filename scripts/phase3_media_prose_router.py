#!/usr/bin/env python3
"""phase3_media_prose_router.py — Route approved media/prose workflows to gemma3:4b.
Refuses blocked workflows. Falls back to qwen3:14b on failure.
Does NOT change production routing for trading/execution."""
import argparse, json, sys, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
OLLAMA = "http://localhost:11434"

from phase3_media_prose_routing_policy import load_policy, assert_workflow_allowed, get_model_for_workflow, get_fallback_model

SAFE_PREFIX = ("You are performing read-only media/prose processing. "
               "Use only the provided text. Do not make trade recommendations. "
               "Do not give buy/sell/hold instructions. Do not discuss execution.\n\n")

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [phase3-router] {msg}", flush=True)

def generate(model, prompt, timeout=90):
    data = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.2, "num_predict": 400}}).encode()
    start = time.monotonic()
    try:
        req = urllib.request.Request(f"{OLLAMA}/api/generate", data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
        lat = round((time.monotonic() - start) * 1000, 1)
        return {"response": result.get("response", ""), "latency_ms": lat,
                "eval_count": result.get("eval_count", 0), "model": model}
    except Exception as e:
        return {"response": "", "latency_ms": round((time.monotonic() - start) * 1000, 1),
                "error": str(e)[:200], "model": model}

def main():
    p = argparse.ArgumentParser(description="Phase 3C media/prose router")
    p.add_argument("--workflow", required=True)
    p.add_argument("--text", default=None)
    p.add_argument("--input-file", default=None)
    p.add_argument("--config", default=None)
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    policy = load_policy(args.config)
    try:
        assert_workflow_allowed(args.workflow, policy)
    except RuntimeError as e:
        result = {"status": "BLOCKED", "workflow": args.workflow, "reason": str(e)}
        if args.verbose: log(f"BLOCKED: {e}")
        print(json.dumps(result, indent=2))
        if args.output_json: Path(args.output_json).write_text(json.dumps(result, indent=2))
        sys.exit(1)

    text = args.text or (Path(args.input_file).read_text() if args.input_file else "")
    if not text:
        print(json.dumps({"status": "error", "reason": "No input text"}))
        sys.exit(1)

    model = get_model_for_workflow(args.workflow, policy)
    if args.verbose: log(f"Workflow '{args.workflow}' → model={model}")

    if args.dry_run:
        result = {"status": "DRY_RUN", "workflow": args.workflow, "model": model, "text_len": len(text)}
        print(json.dumps(result, indent=2))
        return

    prompt = SAFE_PREFIX + text
    r = generate(model, prompt)
    fallback_used = False

    if r.get("error") or not r.get("response", "").strip():
        fb = get_fallback_model(policy)
        if args.verbose: log(f"Fallback to {fb}: {r.get('error', 'empty response')}")
        r = generate(fb, prompt)
        fallback_used = True

    result = {
        "status": "OK", "workflow": args.workflow, "model": r.get("model"),
        "fallback_used": fallback_used, "latency_ms": r.get("latency_ms"),
        "output_len": len(r.get("response", "")), "eval_count": r.get("eval_count"),
        "response_preview": r.get("response", "")[:300],
    }

    if args.verbose:
        log(f"OK: model={r.get('model')} lat={r.get('latency_ms')}ms len={result['output_len']} fb={fallback_used}")

    if args.output_json: Path(args.output_json).write_text(json.dumps(result, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).write_text(f"# Phase 3C Router Result\n\n"
            f"Workflow: {args.workflow}\nModel: {r.get('model')}\n"
            f"Latency: {r.get('latency_ms')}ms\nFallback: {fallback_used}\n\n"
            f"## Output\n\n{r.get('response', '')[:500]}\n")
    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    main()
