Status:      ACTIVE
as_of:       2026-07-28T00:17:07-04:00
Measured at: efcc51365 / not measured

ActiveTrader Image-Generation Prompts and Codex Build Prompt

Canonical implementation folder:
Trade\_AI\_Docs\_v2/docs/design/ActiveTrader\_Implementation\_Pack\_2026-07-27\_v1
https://drive.google.com/drive/folders/1LFVCEPt243vdKYyBrVfRcFdaBByRDvnw

PART I — IMAGE-GENERATION PROMPTS

Shared visual language
Use a dark institutional trading-terminal aesthetic: near-black canvas, charcoal panels, thin cool-gray borders, off-white headings, muted blue-gray secondary text, emerald pass states, red veto/sell states, amber shadow/manual-paper warnings, and restrained blue data bars. Use a monospaced font for prices, risk, timing, and account values. Keep the interface dense but readable, with evidence before action. No gradients, glossy effects, mascots, or decorative charts. Desktop width 1800 px. Crisp vector UI, no photographic content.

Figure 1 — Active trade window
Create a full-width desktop trading review card for ticker QTTB at $3.42, up 18.3%. Top-right badges: “TRIGGER lane” and “manual paper / no automatic order path.” The content order is evidence, levels, gates, action, sizing, permission rail. Show a large IGN score 72 with delta \+19 / 6m. Beside it, six horizontal blue subscore bars labeled v\_rvol 88, v\_burst 81, v\_cat 64, v\_disp 57, v\_liq 41, v\_rs 69\. Show chips for ACCEL, MICRO PULLBACK, profiled cohort, T2 0.50x. Show the state chain IDLE \> IMPULSE \> PULLBACK \> ARMED \> TRIGGERED with ARMED highlighted green and a countdown t+00:41. Show metrics entry ref 3.42, stop ref 3.29, R 0.13 / 380bp, leg/R 2.8x, float 8.4M, RVOL\_tod 11.6x. Show numeric gate chips: PASS slip 21bp \<= 57bp, PASS LULD 6.1% clear, PASS VDU 0.44x, PASS above VWAP, SSR off, MACD 5m \+0.02 logged, profile 20 sess. Below, show disabled order-grid controls: Buy Bid, Sell Ask, Buy Ask, Sell Bid, Buy MKT, Sell MKT, Cancel All, Cancel, Reverse, Flatten, POS flat, ORD none. Quantity 500 with presets 100, 300, 500, 1k, 2k, 2.5k and tier-derived size 384\. Footer says “Alpaca Paper eligible · Schwab/Moomoo/live venues read-only” and buttons “Prepare paper route” and “Dismiss.” The button area must visually read as lower authority than the evidence area.

Negative prompt: live-order success state, filled-order animation, broker logos, bright neon, candlestick chart, people, mobile phone, white background, auto-send toggle, preselected live account.

Figure 2 — Permission queue
Create a compact dark terminal panel titled “Permission queue.” Top-right amber badge: “manual paper / 2 reviewable.” Four horizontally structured rows. QTTB 72 and LASE 66 have green left rails and read “ARMED / profiled / T2,” each with setup labels MICRO PULLBACK and L2 MOMENTUM, risk/slippage/leg details, and a right-side Review button. GRAB 63 and XRX 61 have red left rails and explicit veto copy: “VETOED — stop inside spread” and “VETOED — LULD headroom 1.4%,” with “no action” at right. Keep vetoed rows visible and legible. Order by urgency and expiry, with IGN as a secondary sort indicator. Use monospaced figures and no charts.

Negative prompt: hiding rejected rows, green checkmarks without measured values, live buy buttons, bright marketing design, broker logos, portfolio P\&L dashboard.

Figure 3 — Manual paper account allocation dialog
Create a centered modal titled “Prepare manual paper order — QTTB long.” Subtitle: entry 3.42, stop 3.29, R 0.13, tier T2 0.50x, IGN 72\. Top-right green status “paper account verified.” Table columns: Account, Permissions, Buying power, Shares, Notional, Risk. Rows: Schwab Taxable, Schwab Rollover IRA, Schwab Roth IRA, Alpaca Paper, Alpaca Taxable Live, Moomoo/OpenD. Only Alpaca Paper is selectable. Schwab rows are visible but disabled and labeled current integration read-only; Alpaca Live is read-only/cannot route; Moomoo is L2+tape data-plane/execution disabled. Show per-account share inputs, no automatic splitting, and the cap as a visible rule. Add summary band: selected accounts, total shares, paper notional, paper risk at stop. Footer states that final submission is intentionally absent and requires a separate manual confirmation ceremony. Buttons: Cancel and disabled “Confirm paper order.”

Negative prompt: selected live account, live 2FA success, multiple live accounts checked, automatic allocation, active Confirm button, hidden restrictions, green live-execution badge.

PART II — CODEX BUILD PROMPT

Reference location
Google Drive implementation pack:
Trade\_AI\_Docs\_v2/docs/design/ActiveTrader\_Implementation\_Pack\_2026-07-27\_v1

Before coding, locate the synchronized folder by exact name and verify all six graphics, the source DOCX, the revised implementation specification, the React/CSS code reference, and this prompt. Do not fabricate a server path when the sync target is unknown.

Objective
Build a new ActiveTrader tab beside the existing TradingHub tabs. Reproduce the supplied evidence-first visual structure using the current Command Center design system rather than embedding the PNGs as the live UI. The first implementation is MANUAL\_PAPER\_TEST\_ONLY and read-only with respect to automatic or live execution.

Required source review
Read current main and every governing AGENTS.md, then inspect:
\- apps/command-center-v3/src/pages/TradingHub.tsx
\- apps/command-center-v3/src/components/BrokerOrders.tsx
\- scripts/active\_trader/read\_api.py
\- scripts/active\_trader/read\_http.py
\- scripts/active\_trader/venue\_eligibility.py
\- docs/implementation/ACTIVE\_TRADER\_CURRENT\_GUARDRAILS.md
\- docs/implementation/ACTIVE\_TRADER\_VENUE\_ELIGIBILITY\_v1.md
\- docs/operations/MOOMOO\_STAGE0\_FOUNDATION\_v1.md
\- docs/strategies/MOMENTUM\_SCALP\_SIGNAL\_ENGINE\_v1.md
\- the synchronized implementation pack

Broker/platform truth
1\. Schwab — primary future venue and account/position source; current ActiveTrader route remains disabled/read-only unless a later explicit authority contract exists.
2\. Alpaca Paper — the only eligible account class for the initial manual-paper workflow.
3\. Alpaca Live — visible but disabled/read-only; never use as fallback.
4\. Moomoo/OpenD — Level 2 and tape data role; current Stage 0 data-plane only, no order path.
5\. Thinkorswim — manual watchlist/export/entry workflow; display as a manual handoff, not as an API-routable account.
Do not add IBKR, Robinhood, Webull, Tradier, Tastytrade, or another platform without repository evidence.

Page architecture
Add ActiveTrader to the TradingHub tab list and deep-link aliases. The tab contains:
\- page header with session, mode, venue-health summary, and Setups & strategy rules action;
\- left permission queue;
\- right active trade review card;
\- account allocation modal;
\- responsive narrow layout;
\- explicit empty/loading/error states;
\- current-source footer and timestamp.

Preserve the reading order:
evidence → setup/state → levels → gates → display controls → quantity → permission boundary

Permission queue
Show armed, triggered, vetoed, expired, and data-unavailable signals. Never hide vetoed signals. Each row includes symbol, price, IGN and delta, setup label, FSM state, cohort and data tier, R, stop bps, slippage, leg/R, veto reason or expiry, and a review action only when eligible for manual review.

Default sort priority:
1\. reviewable before non-reviewable;
2\. time to expiry ascending;
3\. IGN descending;
4\. symbol.

Active trade card
Implement all fields shown in Figure 1, including setup labels from the scalp setup registry. Gate chips carry measured values, not bare ticks. MACD remains logged/context unless current deterministic rules say otherwise. The order-button grid is visual/reference-only in the first PR. It must not call an order endpoint. Disabled controls are semantically disabled with explanatory tooltips. Operator quantity remains separate from tier-derived quantity; neither silently overwrites the other.

Account allocation modal
The modal opens from Prepare paper route and must:
\- refresh account and eligibility data at open;
\- show all known accounts/venues, including disabled ones and reasons;
\- allow selection only of explicitly verified paper accounts;
\- require per-account share entry;
\- never split shares automatically;
\- recompute simulated notional and stop risk;
\- exclude paper amounts from real portfolio-risk totals or label them simulated;
\- show Moomoo as data-plane only;
\- show Thinkorswim as a separate manual handoff, not an account checkbox;
\- contain no enabled submit button in this PR.

API work
Extend read-only /api/v3/active-trader/\* projections as needed. Every response preserves:
\- read\_only: true
\- write: false
\- auto\_route: false
\- canary: false
\- explicit authority block
\- venue state and source
\- timestamps and freshness
\- no secrets

Do not reuse a paper-proposal endpoint when it mixes automatic paper authority with this operator-only flow. Prefer an additive manual-paper draft/read contract.

Tests
Add pure component/state tests; permission-queue sorting; veto visibility; setup-label rendering; paper-only account eligibility; live-account disabled; Moomoo data-plane-only; Thinkorswim manual-handoff; modal keyboard/focus; desktop and narrow Playwright screenshots; API GET-only and zero-write authority; and an AST/import scan proving no order-submit client is imported by ActiveTrader components.

Deliverable sequence
1\. Read-only inventory and field map.
2\. Fresh branch from current main.
3\. Additive read API and fixtures.
4\. Dedicated ActiveTrader page/components.
5\. Tests and screenshots.
6\. Draft PR with exact authority statement.

Do not merge, deploy, change schedules, activate agents, request 2FA, or submit paper/live orders as part of this build prompt.
