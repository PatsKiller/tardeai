# Authority — READ_ONLY_ADVISORY

**Contract:** The CIO desk is **advisory only**. No component on the situation→plan→Telegram path or the WakeDispatcher→RunWorker path may place orders, change stops, mutate risk limits, or perform 2FA / broker auth.

This is enforced in product language, tool allowlists, and store metadata (`authority: READ_ONLY_ADVISORY` on thesis, plans, learning rows).

---

## Allowed (live)

| Capability | Notes |
|---|---|
| Detect situations S0–S8 | Data Broker evidence; no invented numbers |
| Create / update / supersede **plans** | Durable JSONL; options + evidence_refs |
| Enrich plans (LLM or template) | Policy-gated; may force template |
| Notify operator | Dedicated CIO Telegram bot; fingerprint ledger |
| Record dispositions | ack / rate / defer / done / reject |
| Publish thesis versions | Pin advance; learning append |
| Desk synthesis note | Portfolio-aware advisory text |
| Enqueue Hermes **research** gaps | Research only, not trading |
| UI read of plans / thesis | Command Center `/v3/cio` |
| Gate-B advisory run tools | Health, snapshot, specialist handoff, Hermes challenge, governed synthesis, action **write** (ledger), notification enqueue |

---

## Forbidden (live non-goals)

| Action | Why |
|---|---|
| Broker place / cancel / modify **order** | Execution authority not granted |
| Create / move / cancel **stops** from chat or situations | Same |
| Risk limit change / override | Forbidden tool set on RunWorker |
| Model portfolio / tax strategy **execute** | Forbidden |
| Infrastructure remediate / scheduler / budget override | Forbidden |
| Authority escalate | Forbidden |
| 2FA / broker login / credential use via chat | Out of scope |
| Unattended auto-trade from recommendations | Never |

RunWorker encodes this as explicit allow/deny tool sets in [`scripts/lib/cio_run_worker.py`](../../scripts/lib/cio_run_worker.py):

- `ADVISORY_ONLY_TOOLS` — health, snapshot, handoff, hermes challenge, governed synthesis, action write, notification enqueue  
- `FORBIDDEN_TOOLS` — broker_*, risk_*, execute paths, infrastructure, authority_escalate, etc.

Situation and Telegram code paths never call broker APIs for execution.

---

## Telegram vs UI

### Telegram (dedicated CIO bot)

| Item | Live behavior |
|---|---|
| Bot | Dedicated **CIO** bot process (`scripts/cio_telegram_bot.py`) — **not** the main OpenClaw bot |
| Config | Host env file for bot token + allowlisted chat IDs (never commit secrets) |
| Commands | `/cio thesis`, `/cio ack|rate|defer|done|reject <plan_id>`, free-text → S0 continuity plans |
| Output | Structured plan cards, deep-link paths to CC, desk pin on replies |
| Notify | Situation notify optional; once-per-fingerprint; material types preferred |

Chat cannot approve trading. “Ack” means **acknowledge and monitor**, not execute.

### Command Center UI (`/v3/cio`)

| Item | Live behavior |
|---|---|
| Hub | CIO plans list / plan detail when route + API are deployed |
| Deep links | Prefer **path-style** links (`/v3/cio?plan=<plan_id>`); host may prefix a Tailscale or LAN base URL for absolute links — treat base as deployment config, not as a public internet primary story |
| API | [`scripts/api_v3_cio.py`](../../scripts/api_v3_cio.py) |
| Authority | Read + disposition endpoints only as implemented; no order tickets |

### WhatsApp

Experimental/runbook path exists (`docs/cio/CIO_WHATSAPP_CONVERSE_RUNBOOK.md`). Same READ_ONLY contract; do not assume production parity with Telegram.

---

## Language to keep consistent

Use in every operator-facing surface:

> No orders/stops from chat · **READ_ONLY_ADVISORY**

Plans and thesis records should carry `authority: READ_ONLY_ADVISORY` in storage.

---

## Scope: execution authority vs. data/decision authority

Everything above governs whether the CIO Desk itself may **execute** anything
(orders, stops, risk limits) — it does not describe whether *other platform
systems* consult the CIO Desk's situations/plans/thesis before acting. Those
are two different questions. As of 2026-08-27 (see
[`docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md`](../audits/CIO_PLATFORM_AUDIT_2026-08-27.md),
finding C1), the platform's daily mechanical rebalance-drift alert
(`scripts/portfolio_rebalancer.py`) runs entirely independent of the CIO
Desk — see [ARCHITECTURE.md § Where CIO Desk does not participate at all](./ARCHITECTURE.md#where-cio-desk-does-not-participate-at-all).
Do not read `READ_ONLY_ADVISORY` as implying every recommendation surface on
the platform is CIO-gated; it is not, today, by design.

---

## Related

- [ARCHITECTURE.md](./ARCHITECTURE.md) — Track A / Track B  
- [SITUATIONS.md](./SITUATIONS.md) — plan options are advisories, not tickets  
- [THESIS.md](./THESIS.md) — pin always cites authority  
