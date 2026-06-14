#!/usr/bin/env python3
"""check_local_model_fleet.py — ping EVERY installed local model, report health.

Why this exists: the older check_local_llm_health.py only exercises the single SAFE
model (gemma3:4b). That meant gemma3:12b could 500 on every prompt for days without
anything noticing (it did — 2026-06-14). This walks the WHOLE Ollama fleet from
/api/tags, pings each model with a tiny prompt (generation) or a short input
(embedding), and records ok / latency / failure-reason per model.

Severity model (no hardcoded model names — all derived from config/.env):
  • CRITICAL models = the ones the system actually defaults to:
      DEFAULT_LOCAL_LLM_MODEL (local_llm_config) ∪ LOCAL_LLM_MODEL ∪ LOCAL_LLM_SAFE_MODEL
      ∪ CRITICAL_LOCAL_MODELS (comma-list, optional).
    If ANY critical model fails → exit 1 (and a `critical` alert when --alert).
  • Every other installed model is informational: a failure is a WARN (alert
    severity `warning`), exit stays 0 — so a broken-but-unused 12b is surfaced,
    not silently ignored, without blocking the gate that protects live paths.

Models can be excluded from the ping (e.g. the 17GB overnight model on a tight box)
via LLM_HEALTH_SKIP_MODELS (comma-list, substring match). Each ping uses keep_alive=0
so heavy models don't stay resident after the probe.

Usage:
  python3 scripts/check_local_model_fleet.py            # human table, exit 0/1
  python3 scripts/check_local_model_fleet.py --json      # machine JSON to stdout
  python3 scripts/check_local_model_fleet.py --alert      # write alert_events row on any failure
Exit 0 = all CRITICAL models healthy, Exit 1 = a critical model failed (or Ollama down).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

try:
    from local_llm_config import DEFAULT_LOCAL_LLM_MODEL
except Exception:
    DEFAULT_LOCAL_LLM_MODEL = "gemma3:4b"

OLLAMA_BASE = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
PING_TIMEOUT = int(os.getenv("LLM_HEALTH_PING_TIMEOUT", "60"))
FORCE_CPU = os.getenv("FORCE_LOCAL_LLM_CPU", "false").strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(key: str) -> set[str]:
    return {m.strip() for m in os.getenv(key, "").split(",") if m.strip()}


def _critical_models() -> set[str]:
    """Models the system relies on by default — a failure here is exit-1."""
    crit = {DEFAULT_LOCAL_LLM_MODEL}
    for key in ("LOCAL_LLM_MODEL", "LOCAL_LLM_SAFE_MODEL"):
        v = os.getenv(key, "").strip()
        if v:
            crit.add(v)
    crit |= _csv_env("CRITICAL_LOCAL_MODELS")
    return {m for m in crit if m}


def _skip_models() -> set[str]:
    return _csv_env("LLM_HEALTH_SKIP_MODELS")


def _http_post(path: str, payload: dict, timeout: int):
    req = urllib.request.Request(
        f"{OLLAMA_BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _list_models() -> list[dict]:
    req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags", method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data.get("models", [])


def _is_embedding(name: str) -> bool:
    n = name.lower()
    return "embed" in n


def _ping_generation(model: str) -> tuple[bool, str, float]:
    """Tiny deterministic prompt. Returns (ok, detail, latency_s)."""
    options = {"temperature": 0.0, "num_predict": 8}
    if FORCE_CPU:
        options["num_gpu"] = 0
    payload = {
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "think": False,
        "keep_alive": 0,          # don't leave it resident after the probe
        "options": options,
    }
    t0 = time.monotonic()
    try:
        data = _http_post("/api/chat", payload, PING_TIMEOUT)
        dt = time.monotonic() - t0
        content = (data.get("message", {}) or {}).get("content", "").strip()
        if not content:
            return (False, "empty response", dt)
        # Degenerate-output detection: a broken model load (e.g. gemma3:12b on
        # 2026-06-14) returns ONLY special tokens like <pad>/<unk>/<eos>. Strip
        # them — if nothing real is left, the model ran but produced garbage.
        import re as _re
        real = _re.sub(r"<\s*(pad|unk|eos|bos|s|/s)\s*>", "", content,
                       flags=_re.IGNORECASE).strip()
        if not real:
            return (False, f"degenerate output (special-tokens only): {content[:32]!r}", dt)
        return (True, f"resp={real[:40]!r}", dt)
    except urllib.error.HTTPError as e:
        return (False, f"HTTP {e.code} {e.reason}", time.monotonic() - t0)
    except Exception as e:
        return (False, f"{type(e).__name__}: {str(e)[:60]}", time.monotonic() - t0)


def _ping_embedding(model: str) -> tuple[bool, str, float]:
    payload = {"model": model, "input": "health probe", "keep_alive": 0}
    t0 = time.monotonic()
    try:
        data = _http_post("/api/embed", payload, PING_TIMEOUT)
        dt = time.monotonic() - t0
        embs = data.get("embeddings") or data.get("embedding")
        dim = len(embs[0]) if embs and isinstance(embs[0], list) else (len(embs) if embs else 0)
        if not dim:
            return (False, "no embedding returned", dt)
        return (True, f"dim={dim}", dt)
    except urllib.error.HTTPError as e:
        return (False, f"HTTP {e.code} {e.reason}", time.monotonic() - t0)
    except Exception as e:
        return (False, f"{type(e).__name__}: {str(e)[:60]}", time.monotonic() - t0)


def run() -> dict:
    critical = _critical_models()
    skip = _skip_models()

    try:
        installed = _list_models()
    except Exception as e:
        return {"ollama_reachable": False, "error": str(e), "base_url": OLLAMA_BASE,
                "results": [], "critical_failed": list(critical), "all_critical_ok": False}

    results = []
    for m in sorted(installed, key=lambda x: x.get("name", "")):
        name = m.get("name", "")
        if not name:
            continue
        is_crit = name in critical
        if any(s in name for s in skip):
            results.append({"model": name, "kind": "skipped", "ok": None,
                            "critical": is_crit, "detail": "skipped via LLM_HEALTH_SKIP_MODELS",
                            "latency_s": None})
            continue
        kind = "embedding" if _is_embedding(name) else "generation"
        ok, detail, latency = (_ping_embedding(name) if kind == "embedding"
                               else _ping_generation(name))
        results.append({"model": name, "kind": kind, "ok": ok, "critical": is_crit,
                        "detail": detail, "latency_s": round(latency, 2)})

    critical_failed = [r["model"] for r in results if r["critical"] and r["ok"] is False]
    noncrit_failed = [r["model"] for r in results if not r["critical"] and r["ok"] is False]
    return {
        "ollama_reachable": True,
        "base_url": OLLAMA_BASE,
        "default_model": DEFAULT_LOCAL_LLM_MODEL,
        "critical_models": sorted(critical),
        "results": results,
        "critical_failed": critical_failed,
        "noncritical_failed": noncrit_failed,
        "all_critical_ok": not critical_failed,
    }


def _emit_alert(report: dict) -> None:
    crit = report.get("critical_failed", [])
    noncrit = report.get("noncritical_failed", [])
    if report.get("ollama_reachable") and not crit and not noncrit:
        return
    if not report.get("ollama_reachable"):
        severity, headline = "critical", f"Ollama unreachable at {report.get('base_url')}"
    elif crit:
        severity = "critical"
        headline = f"CRITICAL local model(s) failing: {', '.join(crit)}"
    else:
        severity = "warning"
        headline = f"Local model(s) failing (non-critical): {', '.join(noncrit)}"
    lines = [headline]
    for r in report.get("results", []):
        if r.get("ok") is False:
            tag = "CRIT" if r["critical"] else "warn"
            lines.append(f"  [{tag}] {r['model']} — {r['detail']}")
    try:
        # alert_events.alert_type is a curated CHECK set — reuse 'system_health'
        # (same convention as protection_alerts.py / log_error_scraper.py); the
        # precise class rides in raw_text + parsed_payload.kind.
        from alert_event_writer import save_alert_event
        save_alert_event(
            alert_type="system_health",
            raw_text="[local_model_health] " + "\n".join(lines),
            severity=severity,
            source_script="check_local_model_fleet.py",
            parsed_payload={"kind": "local_model_health",
                            "critical_failed": crit, "noncritical_failed": noncrit,
                            "results": report.get("results", [])},
        )
        print(f"[alert] wrote system_health/local_model_health alert (severity={severity})")
    except Exception as e:
        print(f"[alert] could not write alert event: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Ping every installed local model and report health.")
    ap.add_argument("--json", action="store_true", help="emit machine JSON to stdout")
    ap.add_argument("--alert", action="store_true", help="write an alert_events row on any failure")
    args = ap.parse_args()

    report = run()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("=" * 68)
        print("Local Model Fleet Health")
        print("=" * 68)
        if not report["ollama_reachable"]:
            print(f"  [FAIL] Ollama unreachable at {report['base_url']} — {report.get('error')}")
        else:
            print(f"  base={report['base_url']}  default={report['default_model']}")
            print(f"  critical={', '.join(report['critical_models'])}")
            print("-" * 68)
            for r in report["results"]:
                if r["ok"] is None:
                    badge = "SKIP"
                elif r["ok"]:
                    badge = "OK  "
                else:
                    badge = "FAIL"
                crit = "*" if r["critical"] else " "
                lat = f"{r['latency_s']:>6.2f}s" if r["latency_s"] is not None else "   -  "
                print(f"  [{badge}]{crit} {r['model']:<26} {r['kind']:<10} {lat}  {r['detail']}")
            print("-" * 68)
            print("  (* = critical model — a failure here exits non-zero)")
        print("=" * 68)
        if report["ollama_reachable"]:
            if report["all_critical_ok"]:
                nc = report.get("noncritical_failed") or []
                print("PASS" + (f"  (non-critical failing: {', '.join(nc)})" if nc else ""))
            else:
                print(f"FAIL — critical models failing: {', '.join(report['critical_failed'])}")
        else:
            print("FAIL — Ollama unreachable")
        print("=" * 68)

    if args.alert:
        _emit_alert(report)

    return 0 if (report["ollama_reachable"] and report["all_critical_ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
