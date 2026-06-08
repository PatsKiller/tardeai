#!/usr/bin/env python3
"""llm_net.py — resilient HTTP for LLM calls: retry transient network/DNS/timeout + 429/5xx with backoff.

Does NOT retry genuine failures (400/401/403 — e.g. credit-balance, bad key) so they surface immediately.
Use for external LLM lanes (cloud) and local Ollama (transient connection resets). Advisory infra only.

  from llm_net import urlopen_retry
  body = urlopen_retry(req, timeout=120)   # returns response bytes; raises after exhausting retries
"""
import os, json, time, socket, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

_TRANSIENT_HTTP = {429, 500, 502, 503, 504}
# one event per call that needed >=1 retry (success-first-try logs nothing → no overhead). Monitored by
# llm_retry_monitor.py to track transient failure/recovery rates over time.
_EVENTS = Path(__file__).resolve().parent.parent / "data" / "runtime" / "llm_retry_events.jsonl"


def _log_incident(kind, etype, retries, outcome):
    try:
        _EVENTS.parent.mkdir(parents=True, exist_ok=True)
        with _EVENTS.open("a") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "kind": kind,
                                "error_type": etype, "retries": retries, "outcome": outcome}) + "\n")
    except Exception:
        pass


def urlopen_retry(req, timeout=120, attempts=3, base=1.0):
    """urllib.request.urlopen with retry-on-transient. Returns response bytes. Re-raises the last error."""
    last = None; retries = 0
    for i in range(attempts):
        try:
            r = urllib.request.urlopen(req, timeout=timeout).read()
            if retries:
                _log_incident("urlopen", type(last).__name__, retries, "recovered")
            return r
        except urllib.error.HTTPError as e:
            if e.code in _TRANSIENT_HTTP and i < attempts - 1:
                last = e; retries += 1; time.sleep(base * (2 ** i)); continue
            if retries:
                _log_incident("urlopen", f"HTTP{e.code}", retries, "gave_up")
            raise
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
            last = e
            if i < attempts - 1:
                retries += 1; time.sleep(base * (2 ** i)); continue
            _log_incident("urlopen", type(e).__name__, retries, "gave_up")
            raise
    if last:
        raise last


def post_retry(url, json_payload, timeout=120, attempts=3, base=1.0, headers=None):
    """requests.post with retry-on-transient (for callers using `requests`). Returns the Response.
    Retries connection/timeout + 429/5xx; surfaces 4xx via the returned Response (caller checks)."""
    import requests
    last = None; retries = 0
    for i in range(attempts):
        try:
            r = requests.post(url, json=json_payload, timeout=timeout, headers=headers or {})
            if r.status_code in _TRANSIENT_HTTP and i < attempts - 1:
                last = r; retries += 1; time.sleep(base * (2 ** i)); continue
            if retries:
                _log_incident("post", f"HTTP{r.status_code}" if r.status_code in _TRANSIENT_HTTP else "recovered", retries,
                              "gave_up" if r.status_code in _TRANSIENT_HTTP else "recovered")
            return r
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, OSError) as e:
            last = e
            if i < attempts - 1:
                retries += 1; time.sleep(base * (2 ** i)); continue
            _log_incident("post", type(e).__name__, retries, "gave_up")
            raise
    return last
