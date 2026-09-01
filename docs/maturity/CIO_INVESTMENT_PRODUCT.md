# CIO Investment Intelligence Product (Program 3.5)

Status:      ACTIVE
as_of:       2026-08-18T08:46:57-04:00
Measured at: efcc51365 / not measured

READ_ONLY_ADVISORY. This is the missing synthesis layer between desks and Alex.

## Gap

The recurring dispatcher created CIO runs but called `CIORunWorker` with no
`synthesis_fn`, no action ledger, and no notification outbox. The fallback
was `recommendations = []`.

## Product

Every cycle now persists four books to `data/cio/cio_investment_brief.json`:

1. Market Temperament
2. Re-Entry Book (former holdings stay alive until retired)
3. Opportunity Book (ranked vs cash and former holdings)
4. Portfolio Action Book (DO NOW / WATCH / RE-ENTER IF / …)

Command Center: `/v3/cio` → **INVESTMENT BOOKS**
API: `GET /api/v3/cio/investment-product`

## RE_ENTER rule

Desk `IN_ZONE` / `READY` / `NEAR` is **WAIT/NEAR**, never auto `RE_ENTER`.

A candidate-specific governed `RE_ENTER` is written only when:

- the opportunity queue already carries `verdict=RE_ENTER`, or
- zone-ready + explicit `ADD` + valid Financial Senses + no restricting lesson
  **and** lesson influence is `CANARY` or `ACTIVE_ADVISORY`.

Those verdicts overlay the live capital-plan queue so the material scanner
can see candidate-specific authorization.

## Authority

`MEMORY_BEHAVIOR_INFLUENCE` remains `0`.
Worker `mode` remains `shadow` (advisory ledger only).
No broker / order / stop / risk / 2FA authority.
