# Model policy matrix

| Logical policy | Exact model ID | Thinking | Effort | Confirmation |
|----------------|----------------|----------|--------|--------------|
| FAST | deepseek-v4-flash | disabled | — | no |
| FAST_THINK | deepseek-v4-flash | enabled | high | no |
| PRO | deepseek-v4-pro | disabled | — | no |
| PRO_THINK | deepseek-v4-pro | enabled | high | no |
| PRO_MAX | deepseek-v4-pro | enabled | max | **yes** |

Verified 2026-08-03 via live `GET /v1/models` (only these two IDs listed).

Legacy `deepseek-chat` / `deepseek-reasoner` are **rejected** by Trade AI client (provider still HTTP 200 remaps both to Flash — never Pro).
