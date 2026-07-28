Momentum Scalp Signal Engine  
ActiveTrader dedicated tab — implementation specification  
Trade AI v12 · revision v0.2 · 27 July 2026

STATUS  
Design and build reference. Manual paper testing only; no automatic or live order path.

1\. PURPOSE AND CONTROLLING POSTURE

This revision converts the supplied active trade window mockups into a dedicated TradingHub tab contract. It preserves the evidence-first reading order and veto visibility while aligning the first build with the operator mandate: manual testing in a verified paper account, no AUTO\_PAPER, no automatic paper submission, and no live routing.

\- The page is a separate TradingHub tab named ActiveTrader.  
\- Evidence, setup identity, levels, and deterministic gates appear before order-shaped controls.  
\- Vetoed signals stay visible for audit.  
\- Only an explicitly verified paper account can become selectable in the initial workflow.  
\- Schwab, Moomoo, and Alpaca Live remain visible but non-routable under current ActiveTrader authority.  
\- Thinkorswim remains a manual handoff/export workflow rather than an API-routable account.

2\. CURRENT BROKER AND PLATFORM MATRIX

Schwab  
Current role: primary future venue; account/position and operator-route surfaces exist.  
ActiveTrader v1 treatment: show accounts and restrictions, disabled/read-only.  
Authority: no ActiveTrader live route in this pack.  
Evidence: docs/implementation/ACTIVE\_TRADER\_VENUE\_ELIGIBILITY\_v1.md and ACTIVE\_TRADER\_CURRENT\_GUARDRAILS.md.

Alpaca Paper  
Current role: existing paper environment and paper workflow.  
ActiveTrader v1 treatment: only account class eligible for the first manual-paper allocation draft.  
Authority: manual operator confirmation only; no automatic submit.

Alpaca Live  
Current role: live account may be visible/readable.  
ActiveTrader v1 treatment: visible but disabled with explicit cannot-route reason.  
Authority: structurally blocked; never a fallback.

Moomoo / OpenD  
Current role: Level 2 and tape data role; alternate future venue only by explicit operator opt-in.  
ActiveTrader v1 treatment: show venue health and data tier, not an enabled account row.  
Authority: Stage 0 data-plane only; no order path.  
Evidence: docs/operations/MOOMOO\_STAGE0\_FOUNDATION\_v1.md.

Thinkorswim  
Current role: manual watchlist import/export and manual entry handoff.  
ActiveTrader v1 treatment: show a manual handoff action outside the account-routing table.  
Authority: no API order routing.  
Evidence: scripts/tos\_exporter.py and imports/tos\_watchlists/README.md.

No additional execution venue is added by this revision. Finviz, Alpaca market data, Yahoo, and other observation providers are data sources, not account-routing choices.

3\. DEDICATED TAB LAYOUT

Add ActiveTrader beside the existing Scalp tab. Scalp remains the broad candidate screen; ActiveTrader is the focused permission-and-review surface.

Desktop layout:  
\[Permission queue 24–32%\] \[Active trade card 68–76%\]

Narrow layout:  
\[Permission queue\]  
\[Active trade card\]

Modal:  
Centered, scrollable, paper-account allocation only.

Header: session, mode, venue-health summary, source freshness, and Setups & strategy rules.  
Left rail: reviewable and vetoed signals with expiry-aware sorting.  
Main card: signal evidence, named setup, state machine, levels, measured gates, display controls, operator quantity, tier-derived quantity, and permission boundary.  
Modal: all known accounts/venues with disabled reasons; only verified paper accounts selectable.  
Footer: API source, last refresh, authority state, and zero-write statement.

4\. ACTIVE TRADE WINDOW

The card reads top to bottom as evidence → setup/state → levels → gates → display controls → sizing → permission boundary.

Required fields:  
\- symbol, last price, percentage change, lane, operating mode;  
\- IGN score and rolling delta;  
\- six subscore bars: v\_rvol, v\_burst, v\_cat, v\_disp, v\_liq, v\_rs;  
\- primary and matched setup labels;  
\- profiled/proxy cohort and data tier;  
\- FSM state chain and expiry countdown;  
\- entry reference, stop reference, R, stop basis points, leg/R, float, RVOL\_tod;  
\- measured gate chips for slippage, LULD, VDU, VWAP, SSR, MACD context, and profile sessions;  
\- display-only order controls;  
\- operator quantity separate from tier-derived quantity;  
\- manual-paper permission footer.

Gate chips carry numbers, not bare ticks. MACD and SSR remain context unless a deterministic rule explicitly promotes them.

5\. PERMISSION QUEUE

The queue shows armed, triggered, vetoed, expired, and data-unavailable signals. It never hides rejected rows.

Default sort:  
1\. reviewable before non-reviewable;  
2\. time to expiry ascending;  
3\. IGN descending;  
4\. symbol.

Clicking a row selects it in the main card. It does not arm or route anything.

6\. ACCOUNT ALLOCATION MODAL

The modal opens from Prepare paper route and refreshes account eligibility.

\- Show every known account or venue, including disabled rows and reasons.  
\- Only an explicitly verified paper account may be selected.  
\- Share count is entered per account and is never split automatically.  
\- Recompute simulated notional and stop risk.  
\- Paper amounts are excluded from real portfolio-risk totals or labeled simulated.  
\- Moomoo is data-plane only.  
\- Thinkorswim is a separate manual handoff.  
\- The initial reference build contains no enabled final submit button.

7\. READ API AND AUTHORITY CONTRACT

Suggested read endpoints:  
GET /api/v3/active-trader/permission-queue  
GET /api/v3/active-trader/signals/{signal\_id}  
GET /api/v3/active-trader/accounts  
GET /api/v3/active-trader/venue-eligibility?symbol=SYM\&venue=...

Every envelope preserves:  
read\_only: true  
write: false  
auto\_route: false  
canary: false  
authority.order: false  
authority.financial\_action: false

Account environment must be explicit: PAPER, LIVE, READ\_ONLY, or DATA\_ONLY. Unknown fails closed. Moomoo data availability and execution availability are separate fields. No venue is silently selected as a fallback.

8\. COMPONENT MAP

\- code/ActiveTraderPage.tsx — reference page, queue, signal card, modal.  
\- code/activeTrader.types.ts — typed signal/account/routing contracts.  
\- code/activeTrader.mock.ts — visual fixtures only.  
\- code/activeTrader.css — responsive visual reference.  
\- code/TradingHub.integration.patch.md — tab and polling integration sketch.  
\- documents/ACTIVE\_TRADER\_CODEX\_BUILD\_PROMPT\_v1.md — implementation handoff.  
\- documents/IMAGE\_GENERATION\_PROMPTS.md — design iteration prompts.

9\. ACCESSIBILITY AND TESTS

Required tests:  
\- veto visibility and deterministic queue ordering;  
\- setup-label rendering;  
\- measured gate rendering;  
\- operator and tier quantities remain separate;  
\- only verified paper accounts selectable;  
\- live/read-only/data-only rows disabled with reasons;  
\- Moomoo has no routable checkbox;  
\- Thinkorswim manual handoff is outside API routing;  
\- keyboard open/close, focus trap, focus return, ARIA labels;  
\- desktop and narrow screenshots;  
\- GET-only read API and zero write authority;  
\- no order-submit client imported by ActiveTrader components.

10\. GOOGLE DRIVE HANDOFF

Canonical folder:  
Trade\_AI\_Docs\_v2/docs/design/ActiveTrader\_Implementation\_Pack\_2026-07-27\_v1

Folder URL:  
https://drive.google.com/drive/folders/1LFVCEPt243vdKYyBrVfRcFdaBByRDvnw

Google Drive sync should preserve the graphics, code, and documents subfolders. Codex must locate the synchronized folder by exact name and verify its inventory. The server sync path is intentionally not invented; it must be discovered from the configured sync job.

This specification does not authorize live trading, automatic paper execution, Moomoo order routing, Schwab order routing, real 2FA, or agent-controlled financial action.  
