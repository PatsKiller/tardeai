# Hermes Data Access — the one canonical way every consumer reads Hermes intelligence

**Status:** live · advisory/read-only · `scripts/hermes_data_access.py`

Every agent (Maria / Steph / Risk / Aegis / Alex / watchlist agents), the local LLMs (gemma),
and the OAuth lanes (Grok / ChatGPT) read Hermes data through **one** module so that *"what does
Hermes know about SYM?"* has a single, consistent answer everywhere — instead of each surface
re-querying the score / research / lane tables ad hoc and drifting.

## API

```python
from hermes_data_access import get_hermes_context, hermes_prompt_block

get_hermes_context("AMD")     # -> structured dict (for code/agents that want fields)
hermes_prompt_block("AMD")    # -> compact markdown to inject into ANY LLM/agent prompt
```

### `get_hermes_context(symbol, research_limit=3, external_limit=3) -> dict`
Everything Hermes knows about one symbol, from three sources:

| key | source table | contents |
|-----|--------------|----------|
| `score` | `hermes_score_history` | latest `composite` score, `rank`, factor `components`, `as_of` |
| `research` | `hermes_research_intelligence` | graded web-grounded notes: topic / thesis / summary / confidence / quality / freshness (excludes rejected/superseded) |
| `external_lanes` | `hermes_external_research` | prior Grok / ChatGPT opinions: recommendation / confidence / dissent / risk_flags |

Degrades to `{}` (or empty lists) on any DB error — safe to import anywhere.

### `hermes_prompt_block(symbol) -> str`
Compact markdown block built from `get_hermes_context`. Returns `""` when Hermes knows nothing
about the symbol (so callers can skip it cleanly). Example:

```
HERMES INTELLIGENCE — AMD (advisory research; verify before acting):
- Composite score 53.6 · rank #1087 (as of 2026-06-24 16:40:02)
- Research [2026-06-06] AMD autonomous thesis challenge: ... (conf 0.62)
- Grok lane: HOLD (conf 0.55) — dissent: valuation stretched vs peers
```

## Where it is wired

| Consumer | File | Injection point |
|----------|------|-----------------|
| Local LLM deep queue | `llm_context_engine.py` → `get_hermes_knowledge()` | prepended to the Hermes knowledge block in `build_context()` |
| Watchlist agents (Maria/Steph/Risk/Tax) | `process_watchlist_agent_jobs.py` → `_build_prompt()` | `{hermes_block}` after `context_text`, before RAG |
| OAuth lanes (Grok/ChatGPT) | `hermes_external_researcher.py` → `safe_context()` | `ctx["hermes_intelligence"]`, **redacted** as defense-in-depth |

The local LLM (gemma) is fed through both the watchlist-agent path and the deep-queue path, so it
receives the block on every run.

## Safety / constraints

- **Advisory only.** Hermes scoring feeds watchlist *ranking*, never live execution (which is
  separately gated). The block text says "verify before acting".
- **No secrets in the OAuth lane.** `safe_context()` is whitelisted (no dollar amounts, account ids,
  positions, or secrets). `hermes_prompt_block` contains only score/rank + research thesis + prior
  lane recommendations — all non-sensitive — and is still passed through `redact()` before it leaves
  the perimeter to an external lane.
- **Read-only.** This module never writes. Import failure or DB error degrades to empty, never raises.

## Related

- Self-learning + self-purging: `scripts/hermes_autonomous_self_tune.py` (auto-graft weights, prune stale state)
- Pipeline health watchdog: `scripts/hermes_pipeline_health.py` (lane freshness, alerter alive, queue jams, embed failures)
- Score weights: `config/hermes_score_weights.yaml`
