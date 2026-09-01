# Hermes Model Canary Status — 2026-06-06

Status:      ACTIVE
as_of:       2026-06-06T21:18:13-04:00
Measured at: efcc51365 / not measured

## Live canary results (this session, direct Ollama /api/generate, num_ctx=4096, temp=0)
| Model | Exact-string canary | Math canary (2+2) | Verdict |
|-------|--------------------|--------------------|---------|
| gemma3:4b | `HERMES_4B_STILL_OK` ✓ | `4` ✓ | **Approved stable default** (default + tradeai) |
| gemma3:12b-ctx4k | `HERMES_12B_TEXT_OK` ✓ | `4` ✓ | Experimental constrained alias (tradeai12b only) |

Canary prompts used:
```
Return exactly: HERMES_4B_STILL_OK
Return exactly: HERMES_12B_TEXT_OK
Answer with only the number: 2+2
```

## Model policy (operator-observed + live-verified)
- **gemma3:4b** — direct-Ollama exact-string + math canaries pass (live, this session); approved stable
  default for `default` and `tradeai`; tools disabled.
- **gemma3:12b** — operator-observed: failed / returned garbage under large/default context; works via native
  `/api/generate` only when constrained to `num_ctx=4096`; `/v1` chat path unstable unless constrained by a
  model alias. NOT approved as default/tradeai. (Large-context failure is operator-reported; not re-run here.)
- **gemma3:12b-ctx4k** — experimental context-gated Ollama alias; canaries pass live (constrained); used only
  by `tradeai12b`; tools disabled; advisory only.
- **qwen3:14b** — must NOT be reintroduced as Hermes default. Live `ollama list` confirms it is absent
  (only `qwen3-embedding:8b`, an embeddings model). Treat as stale/removed.
- **Codex** — allowed later for `dev` profile only; human-invoked development mode; NOT autonomous runtime;
  NOT Trade AI runtime.

## Promotion gate (a model may not become default/tradeai unless ALL hold)
1. direct Ollama canaries pass
2. Hermes no-tools chat passes
3. it does not hallucinate current/version/system facts when instructed not to
4. the profile SOUL clearly states current-fact limits
