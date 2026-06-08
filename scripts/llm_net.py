#!/usr/bin/env python3
"""llm_net.py — resilient HTTP for LLM calls: retry transient network/DNS/timeout + 429/5xx with backoff.

Does NOT retry genuine failures (400/401/403 — e.g. credit-balance, bad key) so they surface immediately.
Use for external LLM lanes (cloud) and local Ollama (transient connection resets). Advisory infra only.

  from llm_net import urlopen_retry
  body = urlopen_retry(req, timeout=120)   # returns response bytes; raises after exhausting retries
"""
import time, socket, urllib.request, urllib.error

_TRANSIENT_HTTP = {429, 500, 502, 503, 504}


def urlopen_retry(req, timeout=120, attempts=3, base=1.0):
    """urllib.request.urlopen with retry-on-transient. Returns response bytes. Re-raises the last error."""
    last = None
    for i in range(attempts):
        try:
            return urllib.request.urlopen(req, timeout=timeout).read()
        except urllib.error.HTTPError as e:
            # server responded — retry only transient codes (rate-limit / 5xx); surface 4xx immediately
            if e.code in _TRANSIENT_HTTP and i < attempts - 1:
                last = e; time.sleep(base * (2 ** i)); continue
            raise
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
            # DNS / connection / timeout = transient → back off and retry
            last = e
            if i < attempts - 1:
                time.sleep(base * (2 ** i)); continue
            raise
    if last:
        raise last


def post_retry(url, json_payload, timeout=120, attempts=3, base=1.0, headers=None):
    """requests.post with retry-on-transient (for callers using `requests`). Returns the Response.
    Retries connection/timeout + 429/5xx; surfaces 4xx via the returned Response (caller checks)."""
    import requests
    last = None
    for i in range(attempts):
        try:
            r = requests.post(url, json=json_payload, timeout=timeout, headers=headers or {})
            if r.status_code in _TRANSIENT_HTTP and i < attempts - 1:
                last = r; time.sleep(base * (2 ** i)); continue
            return r
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, OSError) as e:
            last = e
            if i < attempts - 1:
                time.sleep(base * (2 ** i)); continue
            raise
    return last
