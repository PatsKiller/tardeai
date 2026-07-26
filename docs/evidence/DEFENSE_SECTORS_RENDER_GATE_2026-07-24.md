# Defense/Sectors Fixture-Driven Render Gate

**Date:** 2026-07-24
**Branch:** `agent/defense-sectors-institutional-polish` (PR #166, draft)
**Branch SHA at validation:** `5651b7da2eccf0fc4f7c42ce2737dff08abf7008`
**Build:** `cc-v3 3.12+mrz8qssn`
**Playwright:** 1.61.1 · chromium
**Served from:** `vite preview` on `127.0.0.1:4173` — **not** port 7777, **not** deployed

---

## Result

**10 / 10 PASS.**

Every API call is intercepted with a sanitized fixture, so the gate is deterministic and
independent of live market data, the database and whatever the desks happen to be showing
that day.

## Fixtures

| Fixture | SHA-256 (16) | Source endpoint |
|---|---|---|
| `defense_posture.json` | `ec438e725f9bda81` | `/api/v2/defense/posture` |
| `defense_industries.json` | `9fa1356249287261` | `/api/v2/defense/industries` |
| `defense_recommendations.json` | `8ad27f70269f2ef0` | `/api/v2/defense/recommendations` |
| `sectors_monitor.json` | `395632523a00d2bf` | `/api/v2/sectors/monitor` |

Captured over loopback and sanitized by `e2e/fixtures/sanitize_fixtures.py`.

**Masked:** account identifiers (6, aliased `ACCOUNT_A`…`ACCOUNT_F`, including occurrences
embedded in composite ladder ids), dollar amounts, share/contract counts, equity balances,
free-text notes, order/ticket identifiers, internal URLs, credential-shaped strings.

**Preserved deliberately:** JSON shape, sector/industry labels, `as_of` and `captured_at`
dates, state classifications, quality/provenance blocks, the empty `get_into` lane, the
withheld hedge structure, thin-coverage and missing-CIO markers.

---

## Per-run detail

| Route | Viewport | Screenshot | Console errors | Page errors | H-overflow | Result |
|---|---|---|---:|---:|---:|---|
| `/v3/defense` | 1440×1000 | `defense-sectors-render-gate/2026-07-24/v3-defense_1440x1000.png` | 0 | 0 | 0 px | **PASS** |
| `/v3/defense` | 1280×800 | `…/v3-defense_1280x800.png` | 0 | 0 | 0 px | **PASS** |
| `/v3/defense` | 768×1024 | `…/v3-defense_768x1024.png` | 0 | 0 | 0 px | **PASS** |
| `/v3/defense` | 390×844 | `…/v3-defense_390x844.png` | 0 | 0 | 0 px | **PASS** |
| `/v3/sectors` | 1440×1000 | `…/v3-sectors_1440x1000.png` | 0 | 0 | 0 px | **PASS** |
| `/v3/sectors` | 1280×800 | `…/v3-sectors_1280x800.png` | 0 | 0 | 0 px | **PASS** |
| `/v3/sectors` | 768×1024 | `…/v3-sectors_768x1024.png` | 0 | 0 | 0 px | **PASS** |
| `/v3/sectors` | 390×844 | `…/v3-sectors_390x844.png` | 0 | 0 | 0 px | **PASS** |

Screenshots are full-page, committed under
`docs/evidence/defense-sectors-render-gate/2026-07-24/`.

Per-viewport assertions: no horizontal document overflow (≤1 px tolerance), no uncaught
page errors, no application console errors, primary heading present with non-zero width and
not pushed off-canvas, and `Tab` reaching an interactive control.

## Content assertions (1440×1000)

| Assertion | Route | Result |
|---|---|---|
| `No governed add card is active` — empty add lane is stated, not silent | `/v3/defense` | **PASS** |
| `model critique only` — model output labelled, never presented as market truth | `/v3/defense` | **PASS** |
| `WITHHELD` — failed hedge structure withheld rather than guessed | `/v3/defense` | **PASS** |
| `screen match` — replaces "setups" | `/v3/sectors` | **PASS** |
| `RESEARCH WATCH` — research lane labelled, no unauthorized ADD state | `/v3/sectors` | **PASS** |
| Sector → ETF hierarchy visible (`XL*` tickers present) | `/v3/sectors` | **PASS** |

The empty `get_into` lane in the fixture carries the reason
*"DEFENSIVE LEAN active: cyclical rotate-ins excluded — no defensive sector
(Utilities/Staples/Healthcare) is LEADING+underweight right now"*, which independently
corroborates conflict **C-1** in `DEFENSIVE_LEAN_REVIEW_2026-07-24.md`.

---

## Two real defects the gate caught

Both were bugs in the **gate/fixtures**, not in PR #166, and both would have produced a
false PASS:

1. **Route precedence.** The catch-all `**/api/**` handler was registered *after* the
   specific fixture routes. Playwright matches handlers last-registered-first, so the
   catch-all swallowed all four fixtures and every panel rendered empty. Layout assertions
   passed over a blank page. Fixed by registering the catch-all first; the ordering
   requirement is now commented in the spec.
2. **Sanitizer corrupting payload shape.** Two over-broad rules nulled structures the UI
   dereferences: any key containing `account` had its children renamed (so
   `account_capabilities.accounts` disappeared), and a bare `ticket` pattern matched
   `sell_ticket`, an object carrying a display line, replacing it with `null` and throwing
   `TypeError: Cannot read properties of null (reading 'line')`. Fixed by restricting
   renaming to genuinely account-keyed maps and by never nulling a dict or list —
   structures are recursed into instead.

A third issue was caught on review rather than by a test: real account identifiers
(`schwab_rollover_ira`, `schwab_roth_ira`) survived inside composite ladder id strings such
as `XLI-<account>-2026-07-24` even after the map keys were aliased. A global
longest-match-first substitution pass now removes them, and a grep for broker/account
patterns over the committed fixtures returns clean.

---

## Assertions requested but not asserted, and why

Stated rather than quietly dropped:

| Requested | Status |
|---|---|
| "stale sector warning visible" | **NOT ASSERTED** — the captured board is current; no sector in the fixture breaches the staleness SLA, so there is no warning to assert on. Asserting it would require a hand-edited fixture, which would test the fixture rather than the UI. |
| "narrow participation warning visible" | **NOT ASSERTED** — no such string is rendered on this branch. |
| "industry refresh not labeled close-confirmed" | **NOT ASSERTED as a string.** The branch's head commit is *"fix(ui): distinguish industry refresh from close confirmation"*, and the payload carries `capture_kind`, but no `close-confirmed` literal is rendered, so there is no text to assert against. The negative ("must not say close-confirmed") would pass vacuously and is therefore not evidence. |
| "failed XLI hedge marked WITHHELD" | **PARTIALLY ASSERTED.** `WITHHELD` is asserted and passes. But in this capture **XLI's hedge did not fail** — XLI is in `hedging_radar.coverage.covered`; the failures are `DIVI` and `AMANX`. The brief's premise does not match the live data, so the generic mechanism is asserted rather than an XLI-specific claim. |
| "thin coverage visible" / "missing CIO view visible" | **NOT ASSERTED at DOM level.** Both states are present in the fixture (`thin_coverage` appears 65 times) but are rendered inside collapsed sector panels that require interaction to expand. Asserting them needs a click-through the current spec does not perform. |

---

## Remaining visual defects

**None observed** at any of the four viewports on either route. No horizontal overflow, no
clipped headings, no console or page errors.

---

## Reproduce

```bash
cd apps/command-center-v3
npm ci && npm run build
npm run preview -- --port 4173 --strictPort &
PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 \
  npx playwright test e2e/defense-sectors-render-gate.spec.ts
```

---

## Status

**NOT DEPLOYED.** Validated against a local `vite preview` on port 4173. Nothing was served
on port 7777, no service was restarted, and PR #166 remains **draft**.
