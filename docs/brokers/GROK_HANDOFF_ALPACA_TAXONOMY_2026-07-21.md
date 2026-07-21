# Handoff Package for Grok Analysis — Alpaca / Paper / Paca Taxonomy

**Date:** 2026-07-21  
**Source system:** Trade AI v12 (repo `tardeai` / path `trade-ai-v12-rebuild`)  
**Git commit (docs):** `f3cb6f71` — *Docs: Alpaca paper due diligence and trading-env taxonomy*  
**Purpose:** Self-contained brief so another Grok (or analyst) can review findings **without** confusing public Drive noise with this project's docs.

---

## 0. Critical correction — ignore these public Drive hits

| Public / indexed item | Relevance to Trade AI |
|----------------------|------------------------|
| **Magnartis Ltd** folder / “Alpaca Broker API Integration Guide v012024.pdf” | **NOT ours.** Generic partner/broker-dealer material. Do not treat as project docs. |
| **temp tradebot** / random `alpaca_client.py` on public Drive | **NOT ours.** Unrelated third-party bot. |
| Any random “Paca” product branding online | **Not our naming.** “Paca” here is **operator shorthand** for *live Alpaca personal/IRA*, invented for taxonomy clarity. |

**Authoritative docs live in:**

1. **Git repo** under `docs/brokers/` (MS-01 is source of truth).  
2. **Google Drive folder** `Trade_AI_Docs_v2` (one-way mirror via `scripts/sync-docs-to-drive.sh`, account operator-owned).  
3. **Not** Magnartis, not temp tradebot.

If you only have public web search, you **will not** see the correct docs unless the operator shares Drive links or pastes file contents.

---

## 1. What was completed (this session)

A full due-diligence pass on **Alpaca paper** as Path A, plus taxonomy for future live accounts:

| Deliverable | Repo path | Role |
|-------------|-----------|------|
| Full audit | `docs/brokers/ALPACA_DUE_DILIGENCE_AUDIT_2026-07-21.md` | Inventory, risks, refactor backlog |
| Taxonomy | `docs/brokers/trading-environments.md` | Env IDs, credentials, glossary |
| As-is paper | `docs/brokers/paper-trading.md` | Operator procedures + Mermaid |
| Future live | `docs/brokers/paca-accounts.md` | Personal + IRA gaps, phased plan |
| Pointers | `docs/PROPOSAL_EXECUTION_PATHS.md`, `DOCUMENTATION_INDEX.md`, `CHANGELOG.md` | Cross-links |

**Code:** Documentation only. **No live Alpaca endpoint enabled.** Paper fail-closed guards left intact.

**Drive sync:** Completed 2026-07-21 (~16:05–16:07 UTC) — files under `docs/brokers/` uploaded to `Trade_AI_Docs_v2`.

---

## 2. System context (must understand before analyzing)

### Two execution paths (already in production)

| Path | Capital | Broker | Automation |
|------|---------|--------|------------|
| **A — Paper auto** | Simulated | **Alpaca paper only** | Approve → gates → `alpaca_paper_adapter` → `paper-api.alpaca.markets` · **no 2FA** |
| **B — Live** | Real | **Schwab** (API+2FA) / **Fidelity** (manual FA) | Promote to broker · **not Alpaca** |

### Environment taxonomy (canonical, 2026-07-21)

| Env ID | Meaning | Status |
|--------|---------|--------|
| `paper` | Alpaca paper sandbox | **LIVE Path A** |
| `paca_personal` | Live Alpaca taxable / individual | **NOT IMPLEMENTED** |
| `paca_ira` | Live Alpaca Traditional/Roth IRA | **NOT IMPLEMENTED** |

**Rule:** Never re-point paper adapters to `api.alpaca.markets`. Live needs a new adapter + credentials + ExecutionGuard mode.

### Account keys (paper naming debt)

| account_key | Notes |
|-------------|--------|
| `tradeai_automated` | Canonical ATM account (`config/atm_config.yaml`) |
| `alpaca_paper` | Legacy strategy/YAML/defense labels — still widespread |
| `ALPACA_PAPER` | DB display string on some `paper_trades` rows |

All three map to env `paper` today.

---

## 3. Core code map (for code analysis)

### Equity paper

- `scripts/alpaca_paper_adapter.py` — **only** general equity `POST /v2/orders`; hard-defaults paper host; **raises** if live URL detected  
- `scripts/proposal_paper_submitter.py` — Path A gates; requires `ALPACA_MODE=paper` + paper URL  
- `scripts/broker_confirm_alpaca.py`, `alpaca_paper_reconciler.py`, `paper_trade_monitor.py`, `alpaca_stop_manager.py`  
- `scripts/broker_adapter.py` / `broker_config.py` — partial abstraction  
- `scripts/brokers/` — ADR-B1 interfaces; mode `PAPER_TRAINING` distinct from Schwab  

### Options paper (stricter)

- `scripts/lib/options_pipeline/alpaca_paper.py` — hostname **must** be exactly `paper-api.alpaca.markets`; LIMIT only; qty=1; no auto-submit without operator confirm; refuses LIVE-named env vars  
- `scripts/alpaca_paper_options_executor.py` — operator CLI  

### Env vars (paper as-is — do not put real secrets in analysis)

- `ENABLE_ALPACA_PAPER`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`  
- `ALPACA_MODE=paper`, `ALPACA_BASE_URL` / `ALPACA_PAPER_BASE_URL`  
- `LIVE_TRADING_ENABLED`, `LLM_DISABLE_LIVE_EXECUTION`  

**Proposed future split:** `ALPACA_PAPER_*` vs `ALPACA_PERSONAL_*` vs `ALPACA_IRA_*` (see trading-environments.md).

### Prior discovery still valid

- `docs/brokers/current-state-alpaca-integration.md` (2026-06-11 equity lifecycle trace)  
- `docs/brokers/broker-abstraction-adr.md`  
- `docs/brokers/execution-safety-guards.md`  

---

## 4. Key findings (executive)

1. **Alpaca today = paper training only.** Live money is Schwab/Fidelity.  
2. **Paper locks are strong** (mode + host + options LIVE-env refuse).  
3. **Highest risk for “Paca” expansion:** reusing `ALPACA_API_KEY` / extending `AlpacaPaperAdapter` for live.  
4. **~800 files** mention “alpaca” (docs-heavy); runtime surface is small (table in audit).  
5. **Trading API paper ≠ Broker API** for multi-account/managed products. Trade AI paper path uses **Trading API paper host**. Live personal/IRA may need account-scoped live Trading API and/or Broker API depending on product — **verify on Alpaca docs at implementation time**; do not assume Magnartis PDF applies to this retail setup.  
6. **Secret hygiene:** local `.env.bak*` may contain historical keys — never paste into chats/Drive docs; rotate if exposed.

---

## 5. Trading API vs Broker API (analysis note for Grok)

| Layer | Paper Path A (current) | Live “Paca” (future) |
|-------|------------------------|----------------------|
| Typical API | Alpaca **Trading API** paper | Trading API **live** host and/or **Broker API** if multi-account/partner model |
| Host | `paper-api.alpaca.markets` | `api.alpaca.markets` (live) |
| Auth | Key ID + secret | Separate live keys; never paper keys |
| IRA | N/A | Account subtype / product flags; contributions often portal-side |
| Trade AI stance | Implemented + locked | Scaffold only after taxonomy + factory; Path-B-like human gates |

If analyzing third-party “Broker API Integration Guide” PDFs: treat as **vendor background**, not as description of this codebase.

---

## 6. What we want the other Grok to do

Paste this section as the **task**:

```text
You are analyzing Trade AI v12's Alpaca paper path and future Paca personal/IRA taxonomy.

CONTEXT: Read the handoff doc and (if provided) the four broker markdown files:
- ALPACA_DUE_DILIGENCE_AUDIT_2026-07-21.md
- trading-environments.md
- paper-trading.md
- paca-accounts.md

IGNORE public Drive folders Magnartis Ltd and temp tradebot — they are not this project.

TASKS:
1. Critique the taxonomy (paper / paca_personal / paca_ira) for clarity and migration risk.
2. Rank the P0–P3 refactor backlog; suggest concrete module/file changes.
3. Clarify when Trading API live vs Broker API would be required for personal vs IRA.
4. Propose a config schema (YAML) and factory interface that cannot accidentally use paper credentials on live.
5. List test cases that must stay green forever (paper host invariants).
6. Flag any contradiction with Path A vs Path B (Schwab/Fidelity) as documented.
7. Do NOT invent code that enables live submits; recommendations only unless operator authorizes implementation.

OUTPUT: Structured markdown report with recommendations and open questions for the operator.
```

---

## 7. Operator questions still open

1. First live Alpaca product: **personal only**, or **IRA first**?  
2. Were paper keys in `.env.bak*` ever shared externally? (rotate if yes)  
3. Timeline to retire `alpaca_paper` account_key in favor of `tradeai_automated`?  
4. Will retirement capital stay on Schwab IRA, with Paca IRA optional only?

---

## 8. How to feed this Grok the full docs

**Option A — Paste:** Attach or paste the four markdown files from `docs/brokers/`.  

**Option B — Drive:** Share links from operator Drive folder **Trade_AI_Docs_v2** → `docs/brokers/` for those four filenames (not Magnartis).  

**Option C — Git:** Clone/pull `main` at/after `f3cb6f71` and read those paths.

---

## 9. Explicit non-goals already enforced

- No `api.alpaca.markets` in paper adapter  
- No live keys in paper env var names (until split lands)  
- No auto Path A for real money  
- Paper remains default for ATM  

---

*End of handoff. Primary audit body is `ALPACA_DUE_DILIGENCE_AUDIT_2026-07-21.md`.*
