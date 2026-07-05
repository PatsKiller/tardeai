# External LLM Usage Policy & Approval Process (2026-06-07)

Governs all external/cloud LLM use (Claude/Anthropic, ChatGPT/OpenAI, Grok/xAI, consensus panel) by Hermes.
Internal local models (gemma3 via Ollama) are NOT covered here. **Advisory-only; paper-only; live trading PROHIBITED.**

## 1. Scope & current status
- Claude lane: **wired** (advisory, manual, redaction-first; blocked only by Anthropic credits).
- ChatGPT / Grok / consensus: **designed, not wired**.
- No external lane is automated or scheduled. No external call happens without an explicit operator action.

## 2. Limited criteria — external use is PERMITTED ONLY when ALL hold
1. The request matches a documented escalation trigger (see §6 / PHASE210G).
2. The decision is high-stakes or low-confidence enough to justify external cost (P0/P1; P2 weekly batch).
3. The packet can be fully **redacted** to whitelisted, high-level context (no sensitive data must be required).
4. The operator explicitly runs it (`--apply`) after reviewing the dry-run packet.
If any condition fails → stay internal (tradeai / internal deep research) and tell the operator why.

## 3. Approval process (per-call, operator-gated)
1. **Dry-run first (mandatory):** the runner defaults to dry-run and prints the exact REDACTED packet.
2. **Operator review:** the operator inspects the redacted packet (verifies no sensitive data, correct question).
3. **Operator approval = the `--apply` action:** only the operator runs `--apply`. There is no auto-send,
   no web-UI send button, no scheduled external call. Approver = **operator / CIO (John)**.
4. **Audit:** every call (incl. dry-run/error) is stored in `hermes_external_research` (redacted inputs +
   structured response + status). Usefulness is scored later vs. outcome (learning feedback).
5. **Automation requires a separate written gate:** wiring any external lane into cron/systemd, or adding a
   UI send button, requires an explicit, separate operator approval — not covered by this policy.

## 4. Data-class restrictions — NEVER sent to an external LLM
secrets / API keys / tokens · `.env` content · broker credentials · account numbers · raw holdings or
dollar amounts · position sizes · unredacted PII / emails · raw order/stop/proposal payloads.
Only a redacted, whitelisted context (symbol, strategy name, anonymized counts, the question) may be sent.
Redaction is enforced in code (verified: amounts/account#/keys stripped) plus a second whole-packet pass.

## 5. Cost & privacy controls
- One external call per invocation; operator chooses model (cost-aware default `claude-sonnet-4-6`).
- Credits/billing are operator-managed (the tool never purchases or stores billing material).
- API keys are read from the environment at call-time only — never stored in DB, logged, or returned.
- Rate/volume: manual invocation is the rate limit today; any batch/auto mode needs §3.5 approval + a daily cap.

## 6. Escalation ladder (from PHASE210G)
- **P0** — escalate before recommendation (stop/protection defect; high-$ giveback; tax/SSDI/IRMAA-critical).
- **P1** — escalate overnight (sharp TradeAI-vs-Hermes disagreement; weak-evidence/high-impact).
- **P2** — queue for weekly research. **P3** — no external escalation.
- Routing: Claude = high-stakes/tax/retirement/legal/final challenge · ChatGPT = code/synthesis/second opinion ·
  Grok = market/social/news narrative (source-scored) · Consensus = sharp internal disagreement + high importance.

## 7. Prohibited (hard)
No execution; no broker/order/stop/proposal/holdings mutation; no GO/WAIT change; no strategy-scoring change;
no live trading; no autonomous/scheduled external calls; no credential storage/paste; no sending sensitive
data class (§4). External advice is **advisory input to the operator only** — never an executed action.

## 8. References
PHASE210D (lane design), PHASE210G (triggers), HERMES_CLAUDE_EXTERNAL_LANE_20260607 (Claude lane),
endpoint `/api/v2/hermes/external-research` (audit view), table `hermes_external_research`.

---
## Update (2026-06-07): ChatGPT = openai-codex OAuth (free), NOT OpenAI API
ChatGPT lane wired to the FREE ChatGPT-subscription OAuth (provider openai-codex) via Hermes CLI one-shot — the metered OpenAI API route was removed. auth_pending until `hermes auth add openai-codex --type oauth`. Grok via xAI API (free xai-oauth proxy available). See HERMES_EXTERNAL_LANES_STATUS_20260607.md.

---
## Grok repointed to free xai-oauth proxy (2026-06-07)
Grok no longer uses the metered xAI API key — it routes through the free xai-oauth proxy (hermes proxy start --provider xai, :8645). auth_pending until operator OAuth + proxy start.

---

## 2026-07-05 Update — Cloud Consensus Verdicts (supersedes stale sections above where they conflict)

**Cloud dual-consensus (Grok + ChatGPT OAuth lanes) is now WIRED for broker-proposal oversight** (PR #114, `scripts/cloud_consensus_verdict.py`):
- **Dormant by default** — runs only when invoked manually or via a future cron; no scheduler is installed as of this writing (first real verdicts to be observed manually before scheduling).
- **Advisory-only and status-neutral** — its only write is its own `cloud_consensus_verdicts` table; it never changes proposal status, never touches broker/approval/execution/2FA paths (enforced by tests).
- **Consensus rule** — both lanes must independently AGREE → `CLOUD_APPROVE` (card chip); any split/caution/lane failure fails closed to `ESCALATED` with one throttled Telegram notice per proposal per 24h.
- **Capped and qualified** — max 5 scorings/day; only unexpired proposals with a verified catalyst, sized within policy caps, not scored in the last 24h.
- **Kill-switched** — `config/cloud_consensus_policy.json` (`enabled`/`paused`); do-no-harm auto-pauses on win-rate degradation (Δ < −10 pts, n≥10) or lane disagreement >60% over 7d; resume is manual-only.

## Scheduling separation (policy)

| Pipeline | Allowed schedule | Rationale |
|---|---|---|
| Discovery Inbox / source / trend / topic discovery | May run **24/7** in observe-only / staging mode | Research discovery; advisory intake with operator-gated promotion; no trading-adjacent writes |
| Cloud consensus verdicts | **Manual, or Mon–Fri market hours only** (suggested `*/30 9-16 * * 1-5`, not yet installed) | Broker-proposal oversight tied to live quotes and the trading queue — not research; scoring stale weekend quotes wastes lanes and produces low-quality verdicts |
