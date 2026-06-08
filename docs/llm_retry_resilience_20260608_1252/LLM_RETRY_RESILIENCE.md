# LLM Retry-with-Backoff Resilience (2026-06-08)
Transient host DNS blips (Errno -3) and 5xx/429 were surfacing as "LLM request failed". Added resilient HTTP.

- `scripts/llm_net.py` — `urlopen_retry(req, timeout, attempts=3, base=1.0)`: retries on transient errors
  (URLError/DNS, socket timeout, ConnectionError/OSError, HTTP 429/500/502/503/504) with exponential backoff;
  **does NOT retry genuine failures** (400/401/403 — e.g. credit-balance, bad key) so they surface immediately.
- Wired into: `hermes_external_researcher.py` (Anthropic + openai-compat + xai-proxy cloud calls) and
  `catalyst_classifier.py` (_llm local Ollama, 2 attempts/0.5s base).
- Verified: transient DNS → 3 attempts + backoff then raise; HTTP 400 → 1 attempt (no retry); HTTP 503 →
  3 attempts; Grok lane + classifier still functional.
- Effect: a brief DNS/network hiccup is now retried transparently instead of failing the LLM request.
  Advisory infra only; no scoring/trade/GO-WAIT change. (Local-only deep-research/monthly advisory unaffected
  by DNS; same helper can be added if desired.)
