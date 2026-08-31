# Cloud-OAuth Lane Usage

Status:      ACTIVE
as_of:       2026-06-29T09:25:34-04:00
Measured at: efcc51365 / not measured

_Generated: 2026-06-29T09:24:43.906108_  

| Lane | Port | Reachable | Calls today | Auth fails | Paid fallbacks | Status |
|------|-----:|-----------|------------:|-----------:|---------------:|--------|
| grok | 8645 | reachable | 0 | 0 | 0 | ok |
| chatgpt | 8646 | reachable | 0 | 0 | 0 | ok |

> Free rolling-OAuth lanes (Grok :8645, ChatGPT codex :8646). Offload heavy T3 LLM here to free the local GPU; monitor so we stay in free limits and never silently use a paid key.

> Read-only. No broker writes. Never routes free-only requests to a paid key.

