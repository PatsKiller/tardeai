# Schwab Public Repo Intake Memo (read-only review)

Status:      ACTIVE
as_of:       2026-06-10T22:29:34-04:00
Measured at: efcc51365 / not measured

**Prepared:** 2026-06-11 · **Type:** reference review only — **no code adopted, no dependencies added, no
production changes.** Metadata pulled live from the GitHub API on 2026-06-11.

Purpose: survey the public Schwab-API Python ecosystem to (a) confirm our current wrapper choice, (b) identify
*conceptual* references for the deferred READY items (streaming/Level-II, option-chain, batch-quote, market-
hours — see [`../architecture/SCHWAB_API_CAPABILITY_MAP.md`](../architecture/SCHWAB_API_CAPABILITY_MAP.md)),
and (c) record what must NOT be copied. Nothing here authorizes a build.

## 1. License / maintenance / risk

| Repo | License | Last push | Stars | Risk notes |
|---|---|---|---|---|
| **alexgolec/schwab-py** | MIT | 2025-08-04 | 434 | ✅ **our current REST wrapper.** Official-OAuth, well-structured, successor to tda-api. Slower cadence (~10 mo since push) — watch for upstream lag. |
| **tylerebowers/Schwabdev** | MIT | 2026-05-09 | 808 | ✅ most active + popular; first-class **streaming/websocket** support. Reference-quality. MIT = safe to learn from. |
| **bluedabadi/SchwabAutoTrading** | MIT | 2025-12-27 | 147 | Options auto-trading *strategy* bot, not a wrapper. MIT. Strategy logic — out of scope for us (we don't import trading logic). |
| **roninio/Schwab-API-AI-AGENT** | MIT | 2026-05-19 | 27 | Active "AI agent" over the API; no description. MIT. Concept-only interest; unaudited agent code — do not run. |
| **dhonn/schwab-python-api** | MIT | 2024-05-13 | 13 | **Stale (~2 yr).** Standard + Streaming API client. MIT. Streaming concept reference only; do not depend on a 2-yr-stale client. |
| **itsjafer/schwab-api** | MIT | 2024-08-09 | 269 | ⚠️ **REVERSE-ENGINEERED / web-app session scraping — NOT the official OAuth API.** ToS-violation + fragility risk. **Anti-pattern.** Do not use or emulate. |
| **jaycollett/SchwabPy** | MIT | 2025-12-05 | 1 | New, ~no adoption. MIT. Nothing schwab-py doesn't already do better. |
| **jononon/algo-trading-schwab** | **NONE** | 2024-09-10 | 32 | ⛔ **NO LICENSE = all rights reserved.** Cannot copy any code, even a snippet. Stale strategy bot. |
| **hedge0/OptionsKillerBotPython** | **NOASSERTION** | 2024-10-22 | 0 | ⛔ License unrecognized by GitHub (`NOASSERTION`) — treat as **do-not-copy until a human verifies the LICENSE file.** Options-mispricing + delta-hedge bot; stale. |

## 2. What we CAN reuse — conceptually (ideas, not code)
- **Streaming reconnect/heartbeat shape** (Schwabdev): how to structure a long-lived websocket — subscribe
  payloads, login/logout frames, reconnect-on-drop, `streamerInfo` handshake from `userPreference`. We'd
  re-implement under our own boundary + Rule-9 isolation, not import it.
- **Option-chain request/response shape** (schwab-py + Schwabdev): the `contractType / strikeCount / range /
  expMonth / includeUnderlyingQuote` parameters and the strike-map JSON shape — useful when we normalize our
  existing passthrough stub.
- **Batch-quote ergonomics** (schwab-py `get_quotes`): the comma-joined-symbols + `fields` pattern.
- **Market-hours / calendar** (schwab-py `get_market_hours`): the per-market `isOpen` + session-window shape.
- **Token-refresh-through-a-manager** (both): confirms our design (the wrapper never owns token storage) is
  the right pattern — already implemented in `schwab_token_manager` + `schwab_transport`.

## 3. What must NOT be copied
- **Any code from `jononon/algo-trading-schwab` (NO LICENSE)** — all rights reserved; not even a function.
- **Any code from `hedge0/OptionsKillerBotPython` (NOASSERTION)** — license indeterminate; do-not-copy.
- **`itsjafer/schwab-api`'s entire approach** — reverse-engineered web-session scraping; copying or emulating
  it would violate Schwab's ToS and break our official-OAuth-only posture.
- **Any trading/order/strategy logic** from the bot repos (bluedabadi, hedge0, jononon, roninio) — even where
  MIT-licensed, we do not import execution logic; Schwab stays read-only and Stage-2 writes are fenced.
- **Verbatim source from any repo** — MIT permits reuse but our policy is concept-only here; if we ever lift a
  snippet, it goes through a licensing/attribution check first (none is authorized by this memo).

## 4. Candidate references for the deferred READY work (review targets, not imports)
| Future work | Primary reference | Note |
|---|---|---|
| **Streaming / Level-II** | **Schwabdev** stream client (its `stream`/websocket module) | The only mature streaming reference here. Spike-only; Rule-9: must NOT touch screeners/match-mins/GO-WAIT/ATM even if built. |
| **Option chain** | schwab-py client option-chain method (already wrapped as our passthrough stub) | Normalize against the live payload at wire-time; Schwabdev as a cross-check. |
| **Batch quotes** | schwab-py `get_quotes` | Cheaper watchlist refresh than per-symbol; already named in the capability map gap list. |
| **Market hours** | schwab-py `get_market_hours` | Confirm/replace live-path market-hours gating. |

**These market-data capabilities already exist in schwab-py (which we use)** — so the "future work" is mostly
wiring our own read methods through `schwab_transport`, NOT adopting a new library. Streaming is the only area
where Schwabdev offers something schwab-py lacks.

## 5. Decision (explicit)
- **Keep `alexgolec/schwab-py` as the current REST request/response wrapper.** It is MIT, official-OAuth,
  already integrated at the `schwab_transport` boundary, and covers the READY market-data items (option-chain,
  batch-quote, market-hours) via methods we can wrap ourselves.
- **`tylerebowers/Schwabdev` is recorded ONLY as a future streaming / Level-II spike reference** — not a
  dependency, not adopted. If/when a streaming spike is authorized (separate gated prompt), Schwabdev's
  websocket structure is the reference to study; the implementation would still live behind our own boundary
  with the write-fence and Rule-9 isolation intact.
- **All other repos: reference-awareness only.** No reuse (license/maintenance/risk reasons above).

## 6. No production dependency changes
This memo adds **zero** dependencies and **zero** code. `requirements`/imports unchanged; `schwab-py` remains
the sole Schwab library. No new packages, no vendored files, no spikes started. Any future adoption requires a
separate, explicitly-scoped, gated prompt.

## Cross-references
- [`../architecture/SCHWAB_API_CAPABILITY_MAP.md`](../architecture/SCHWAB_API_CAPABILITY_MAP.md) — the READY/FENCED/N-A map these references map onto.
- [`../architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md`](../architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md) — the read-only foundation + write fence (validator 12/12).
