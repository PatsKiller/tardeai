# LLM Routing Matrix — Local vs Cloud-OAuth (+ local-LLM optimization assessment)

_2026-06-29. Built during the Monday-morning overload/outage investigation. Read-only analysis +
the routing plan. No broker writes; operator/2FA untouched._

## TL;DR

* **The local LLM setup is NOT optimized for this box** — the dominant problem is **`gemma4-31b`** served
  via CPU-spilling Vulkan (`llama-server` on :8081), which burns ~**3 CPU cores (288–345%)** per
  generation and starves the single-threaded dashboard server.
* This caused **today's dashboard outage (ERR_CONNECTION_RESET, load 8+)** via a feedback loop: the
  health agent's escalation handler investigated DEGRADED findings using **gemma4-31b**, which starved
  the dashboard → more endpoint timeouts → more findings → more 31B investigations.
* **Fix shipped:** a load/market-priority guard now skips the 31B tier during market hours or under high
  load (falls back to a lighter lane). The runaway process was terminated; load 8.25 → 3.38; dashboard
  recovered.
* **Routing principle:** keep only **fast, small, low-latency** work on the local GPU (gemma3:4b/12b +
  embeddings) for T1 market-critical advisory; **offload heavy research/synthesis to the free
  cloud-OAuth lanes** (Grok :8645, ChatGPT codex :8646) to free the local GPU during market hours.

## Local LLM reality (what's actually running)

| Asset | Detail | Assessment |
|-------|--------|------------|
| GPU | AMD/Vulkan (no `nvidia-smi`); `llama-cpp-vulkan` | consumer GPU; 31B models spill to CPU |
| `llama-server` :8081 | serving **`gemma4-31b-hf.gguf`** | ❌ **288–345% CPU**, CPU-spilling — the #1 contention source |
| ollama :11434 | `gemma3:4b` loaded (was at **128k context**, since reduced to 8k) | 4B is weak for analysis; 128k context was wasteful |
| ollama models installed | gemma3:4b, gemma3:12b(+ctx4k), gemma3:27b (17GB), **gemma3-overnight (17GB)**, qwen3:8b, qwen3-embedding:8b, nomic-embed-text (274MB) | too many large models competing for one GPU |
| embeddings | `nomic-embed-text` (30s timeout) | ❌ **times out under load** — starves the proposal-review worker |

**Is it the best model / optimized?** No:
1. **`gemma4-31b` should not run locally on this box** — it CPU-spills and dominates load. Use it via
   **cloud** (or drop it). For local "quality", **`gemma3:12b`** is the right ceiling (fits the GPU; the
   documented `local_llm_centralization` policy already names gemma3:12b primary / gemma3:4b fallback).
2. **Embeddings (`nomic-embed-text`) must never compete with a big generation** — when a 17–31GB model
   loads, the embed model goes cold and the 30s timeout fails. Raise the timeout to 90s (shipped) and
   keep embeddings on a dedicated lane / pinned.
3. **One big model at a time** — `prevent_qwen3_gemma_coresidency` already exists in policy; extend the
   same discipline so only ONE heavy model is resident, and never during the 06:00–12:00 market window.

## The routing matrix

**Lanes:** `local-sm` = gemma3:4b/12b on ollama (fast) · `local-embed` = nomic-embed-text · `cloud-grok`
= xAI OAuth :8645 (free) · `cloud-chatgpt` = ChatGPT codex OAuth :8646 (free) · `local-31b` =
gemma4-31b (avoid).

| Use / job | Tier | Current backend | **Recommended** | Why |
|-----------|------|-----------------|-----------------|-----|
| Scalp critic / momentum advisory | T1 | local-sm | **local-sm** | low-latency, market-critical, advisory |
| Proposal validation gates | T1 | deterministic (no LLM) | none | gates are deterministic — keep it that way |
| Proposal-review worker (RAG) | T1 | local-embed + local-sm | **local-embed (pinned) + local-sm** | needs fast embeddings; protect from big-model eviction |
| News→catalyst / SEC context | T2 | local-sm / none | local-sm | light classification |
| Proposal enrichment | T2 | local-sm | **cloud** (grok/chatgpt) | heavier; offload to free GPU |
| Hermes research / discovery / scoring / topic synth | T3 | local-sm + some cloud | **cloud** | background; must not touch local GPU in market hours |
| Inference cycles / intelligence enrichment / narratives | T3 | local-sm | **cloud** | heavy synthesis; offload |
| **Escalation investigation (health agent)** | infra | **local-31b** | **cloud or local-sm; NEVER 31b in market hours** | ❌ caused today's outage; now guarded |
| Deep overnight LLM window | T3 | local (gemma3-overnight) | local, **22:00–03:00 only** | fine overnight when nothing else needs the GPU |
| Trade-close LLM analyzer / journal review | T3 | local + grok | **cloud-grok** | already partly cloud; finish the move |
| Embeddings / RAG index | infra | local-embed | **local-embed** | small, keep local, pin it |

**23 cron jobs are currently local but should move to cloud-OAuth** (see `JOB_SCHEDULE_AUDIT.md`
`cloud_offload_candidates`). 13 frequent T3 LLM jobs are now **guarded** (defer during 06:00–12:00 ET);
8 single-shot morning jobs (pre-open inference, morning synthesis, 9am topic ingestion) should be
**offloaded to cloud** (they're meant to run in the morning, so guarding would kill them — cloud lets
them run on time without the local GPU).

## Cloud-OAuth: free, but must be monitored

The Grok (:8645) and ChatGPT codex (:8646) lanes are **free rolling-OAuth** (token kept alive by
`oauth_lane_keepalive`). Offloading to them is the right move, but we must **monitor usage** so we don't
(a) exhaust free quotas, (b) silently fall back to a paid key, or (c) let a token lapse. See the new
`cloud_oauth_usage_monitor.py` + the health-agent collector (counts per-lane calls/day, flags
auth-failures and paid-fallback). **Never route free-only requests to a paid Claude/OpenAI key.**

## Concrete recommendations (priority order)

1. **Do not run `gemma4-31b` locally during market hours.** ✅ shipped (escalation 31B guard); next:
   route escalation "best quality" to **cloud-grok/chatgpt**, keep `gemma3:12b` as the local ceiling.
2. **Offload the 23 T3 cloud-candidates** to :8645/:8646 (frees the local GPU 06:00–12:00).
3. **Pin embeddings** + 90s timeout (timeout shipped) so the proposal worker never starves.
4. **One heavy model at a time**, never in the market window (extend the existing co-residency policy).
5. **Monitor cloud-OAuth usage** (shipped) to stay inside free limits and catch paid-fallback.

## Safety

No live trades, no broker writes, operator/2FA untouched. The escalation 31B guard and the LLM-priority
guard only yield **background/advisory** LLM work to time-sensitive market work and the dashboard — they
never touch a gate, a broker path, or the deterministic validation logic. LLMs remain advisory only.
