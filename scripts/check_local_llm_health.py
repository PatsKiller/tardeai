#!/usr/bin/env python3
"""check_local_llm_health.py — Local LLM health gate for Trade AI.

Validates:
1. Ollama API reachable
2. qwen3:14b NOT loaded
3. gemma3:4b numeric test (CPU)
4. gemma3:4b JSON test (CPU)
5. Disabled model routing (a disabled model is blocked and never resolves to itself)
6. At most one generation model loaded after tests
7. No classifier/apply LLM job running, other than the caller's own ancestor chain

Exit 0 = PASS, Exit 1 = FAIL.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

OLLAMA_BASE = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
SAFE_MODEL = os.getenv("LOCAL_LLM_SAFE_MODEL", "gemma3:4b").strip()
DISABLED_MODELS = set(
    m.strip() for m in os.getenv("DISABLED_LOCAL_LLM_MODELS", "").split(",") if m.strip()
)
FORCE_CPU = os.getenv("FORCE_LOCAL_LLM_CPU", "false").strip().lower() in {"1", "true", "yes", "on"}
HEALTH_TIMEOUT = 120


def _get_loaded_models():
    req = urllib.request.Request(f"{OLLAMA_BASE}/api/ps", method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
        return [m.get("name", "") for m in data.get("models", [])]


def _unload_model(name):
    payload = json.dumps({"model": name, "keep_alive": 0, "prompt": ""}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate", data=payload,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    urllib.request.urlopen(req, timeout=10)


def _call_ollama(prompt, model, timeout=HEALTH_TIMEOUT):
    options = {"temperature": 0.0, "num_predict": 64}
    if FORCE_CPU:
        options["num_gpu"] = 0
    payload = json.dumps({
        "model": model, "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "think": False, "options": options
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
        return data.get("message", {}).get("content", "").strip()


def _parse_json_response(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def _ancestor_pids(pid: int, limit: int = 32) -> set[int]:
    """Every ancestor of `pid` up to init (ppid from /proc/<pid>/stat field 4, after the comm field).

    This gate runs as the preflight of `trade_close_llm_analyzer.py --apply`, whose own command
    line matches the pattern check 7 rejects. In the cron shape the chain is

        cron → bash -c (… safe_flock.sh … trade_close_llm_analyzer.py … --apply)
             → bash safe_flock.sh → python analyzer → python check_local_llm_health.py

    so the self-match sits three levels up, not one. Excluding only pid/ppid/grandparent flagged
    the lane's own run and refused it — [FAIL] no_unsafe_jobs on every weekly slot. Comm may
    contain spaces and parentheses, so the parent id is read from the tail after the last ')'."""
    seen: set[int] = set()
    current = pid
    for _ in range(limit):
        try:
            stat = Path(f"/proc/{current}/stat").read_text()
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            break
        if ppid <= 1 or ppid in seen:
            break
        seen.add(ppid)
        current = ppid
    return seen


UNSAFE_MARKERS = (
    ("trade_strategy_classifier", "classifier"),
    ("trade_close_llm_analyzer", "analyzer"),
)


def _unsafe_job(ps_stdout: str, exclude_pids: set[int]) -> tuple[bool, str]:
    """Scan `ps -eo pid,args` output for a classifier/analyzer --apply job outside `exclude_pids`."""
    for line in ps_stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("PID"):
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        args = parts[1]
        if pid in exclude_pids:
            continue
        for marker, label in UNSAFE_MARKERS:
            if marker in args and "--apply" in args:
                return False, f"{label} --apply running (pid {pid}): {args[:120]}"
    return True, "no unsafe jobs"


def _check_no_unsafe_jobs():
    """Check no classifier/apply or trade_close_llm_analyzer/apply jobs are running.
    Excludes the caller's whole ancestor chain (this script runs as preflight from --apply)."""
    try:
        exclude_pids = {os.getpid()} | _ancestor_pids(os.getpid())
        result = subprocess.run(
            ["ps", "-eo", "pid,args"], capture_output=True, text=True, timeout=5
        )
        return _unsafe_job(result.stdout, exclude_pids)
    except Exception as e:
        return False, f"process check error: {e}"


def _routing_blocked(resolved: str, was_blocked: bool, *, safe_model: str, retired: str,
                     requested: str = "qwen3:14b") -> bool:
    """A disabled model must be blocked and must never resolve to itself.

    2026-11-07: local generative is retired — scripts/local_llm.py is a facade over DeepSeek Flash
    and `_resolve_model("qwen3:14b")` answers ("LOCAL_GENERATIVE_RETIRED", True). The old test
    `resolved == SAFE_MODEL` therefore could never pass again, and failed the gate every week.
    The safe model is still accepted, so the check holds if the facade is ever un-retired."""
    if not was_blocked or not resolved:
        return False
    return resolved != requested and resolved in {retired, safe_model}


def main():
    checks = []
    all_pass = True

    def check(name, passed, detail=""):
        nonlocal all_pass
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        msg = f"  [{status}] {name}" + (f" — {detail}" if detail else "")
        print(msg)
        checks.append({"check": name, "status": status, "detail": detail})

    print("=" * 60)
    print("Local LLM Health Check")
    print("=" * 60)

    # 1. Ollama reachable
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/ps", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            json.loads(resp.read())
        check("ollama_reachable", True, OLLAMA_BASE)
    except Exception as e:
        check("ollama_reachable", False, str(e))
        print("\nFAIL — Ollama not reachable, cannot continue")
        sys.exit(1)

    # 2. qwen3:14b not loaded — unload if present
    loaded = _get_loaded_models()
    qwen_loaded = any("qwen3" in m for m in loaded)
    if qwen_loaded:
        print("  [INFO] qwen3:14b found loaded, unloading...")
        try:
            _unload_model("qwen3:14b")
            time.sleep(1)
            loaded = _get_loaded_models()
            qwen_loaded = any("qwen3" in m for m in loaded)
        except Exception as e:
            print(f"  [WARN] Unload attempt failed: {e}")
    check("qwen3_not_loaded", not qwen_loaded,
          f"loaded: {loaded}" if qwen_loaded else "clean")

    # 3. gemma3:4b numeric test
    try:
        result = _call_ollama("Return only the number 4. No other text.", SAFE_MODEL)
        has_4 = "4" in (result or "")
        check("gemma3_numeric", has_4, f"got: {repr(result)}")
    except Exception as e:
        check("gemma3_numeric", False, str(e))

    # 4. gemma3:4b JSON test
    try:
        result = _call_ollama(
            'Return valid JSON only with exact shape {"answer":4,"status":"ok"}. No other text.',
            SAFE_MODEL
        )
        parsed = _parse_json_response(result)
        valid = (parsed is not None and parsed.get("answer") == 4 and parsed.get("status") == "ok")
        check("gemma3_json", valid, f"parsed: {parsed}")
    except Exception as e:
        check("gemma3_json", False, str(e))

    # 5. Disabled model routing: blocked, and never resolved to the disabled model itself
    from local_llm import _resolve_model, OLLAMA_MODEL as RETIRED_MODEL
    resolved, was_blocked = _resolve_model("qwen3:14b")
    blocked_ok = _routing_blocked(resolved, was_blocked, safe_model=SAFE_MODEL,
                                  retired=RETIRED_MODEL)
    check("disabled_model_routing", blocked_ok,
          f"qwen3:14b → {resolved}, blocked={was_blocked}")

    # 6. At most one generation model loaded
    loaded_after = _get_loaded_models()
    gen_models = [m for m in loaded_after if "embed" not in m.lower()]
    check("max_one_model", len(gen_models) <= 1,
          f"loaded: {gen_models}")

    # 7. No unsafe classifier/apply jobs
    safe, detail = _check_no_unsafe_jobs()
    check("no_unsafe_jobs", safe, detail)

    # Summary
    print("=" * 60)
    if all_pass:
        print("PASS")
    else:
        print("FAIL")
        failed = [c["check"] for c in checks if c["status"] == "FAIL"]
        print(f"Failed checks: {', '.join(failed)}")
    print("=" * 60)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
