#!/usr/bin/env python3
"""llm_health_gate.py — Ollama/model health preflight for the LLM-review pipeline.

Prevents the review cron from flooding trade_llm_reviews with infrastructure-error rows when Ollama is
down. Short timeouts, never hangs. Returns a structured health dict with a normalized failure_class.
Read-only probe (GET /api/tags + tiny bounded /api/generate). No trading/DB writes here.
"""
import json, os, time, urllib.request, urllib.error, datetime


def check_ollama_health(base_url: str | None = None, model: str | None = None,
                        timeout_sec: float = 5.0, generate_probe: bool = True) -> dict:
    base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
    model = model or os.environ.get("HERMES_LOOP_MODEL") or "gemma3:4b"
    out = {"healthy": False, "base_url": base_url, "model": model, "ollama_reachable": False,
           "model_available": False, "generate_probe_ok": False, "latency_ms": None,
           "failure_class": None, "message": "", "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}

    def _cls(e):
        s = str(e).lower()
        if "refused" in s:
            return "connection_refused"
        if "timed out" in s or "timeout" in s:
            return "timeout"
        if "closed" in s:
            return "connection_closed"
        if "500" in s:
            return "http_500"
        return "invalid_response"

    # 1) /api/tags reachability + model presence
    t0 = time.time()
    try:
        req = urllib.request.Request(base_url + "/api/tags")
        tags = json.loads(urllib.request.urlopen(req, timeout=timeout_sec).read())
        out["ollama_reachable"] = True
        out["latency_ms"] = int((time.time() - t0) * 1000)
        names = [m.get("name", "") for m in tags.get("models", [])]
        out["model_available"] = any(model == n or model.split(":")[0] == n.split(":")[0] for n in names)
        if not out["model_available"]:
            out["failure_class"] = "model_missing"
            out["message"] = f"model {model} not in {names[:8]}"
            return out
    except urllib.error.URLError as e:
        out["failure_class"] = _cls(e.reason if hasattr(e, "reason") else e)
        out["message"] = f"/api/tags failed: {e}"
        return out
    except Exception as e:
        out["failure_class"] = _cls(e)
        out["message"] = f"/api/tags error: {e}"
        return out

    # 2) optional tiny bounded generate probe
    if generate_probe:
        try:
            body = json.dumps({"model": model, "prompt": "ping", "stream": False,
                               "options": {"num_predict": 1}}).encode()
            req = urllib.request.Request(base_url + "/api/generate", data=body,
                                         headers={"Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=max(timeout_sec, 15.0)).read())
            out["generate_probe_ok"] = bool(r.get("response") is not None or r.get("done"))
        except Exception as e:
            out["failure_class"] = _cls(e)
            out["message"] = f"generate probe failed: {e}"
            return out
    else:
        out["generate_probe_ok"] = True

    out["healthy"] = out["ollama_reachable"] and out["model_available"] and out["generate_probe_ok"]
    out["message"] = "ok" if out["healthy"] else "unhealthy"
    return out


if __name__ == "__main__":
    import sys
    m = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(check_ollama_health(model=m), indent=2))
