# Defense Desk v8 — Real Accounts · Quiet Alerts · The Oversight Stack (2026-07-18)

Status:      ACTIVE
as_of:       2026-08-21T20:25:01-04:00
Measured at: efcc51365 / not measured

## WS-ALERT (P0, all live defects fixed)
A1 account inversion: intent default = the CARD's real account (picker when multiple,
never silent); paper twin = separate intent labeled "Alpaca Paper (shadow)"
(config auto_paper_twin). A2 migration: action_queue.action varchar(30)→(80); mirror
failures audit always, Telegram once/class/day, never block the primary path.
A3 operator-click refusals = toast + execution log only. A4 one human template set
(display map; no raw IDs/tuples). A5 telegram_alert_router gates IGNORE-verdict
escalations (<60% confidence) to the ops digest — central chokepoint, measured by
the monthly alert-analytics noise review.

## WS-BRIEF + WS-FREE + WS-PILL (the oversight stack, Tiers deterministic + free)
`defense_oversight.py`: constitution generated FROM CONFIG (~9 rules), posture with
values, every card complete (arithmetic as rendered, tickets, factors), in-play book,
STRONGEST-OBJECTION-REQUIRED response contract, build-hash keyed (~4.8K tokens,
labeled estimate). Both free seats run on every recommendations build — quota-share +
lane-availability checked first, schema-strict parsing (unparseable keeps raw, never
coerced), cached per build (refresh never re-calls). Pills on every card:
DET·nf / ✦GPT / ✦GK (+⚖API slot) with reason tooltips + ⚖ split chip; memo panel
renders each seat's top-3 + strongest objection side-by-side.

## FIRST SEAT MEMOS (verbatim — these decide weekly_paid_review)
**ChatGPT (2 CONCUR / 11 QUALIFY / 7 OBJECT):** "The desk is acting less like a
retirement-scale defensive overseer and more like an active sector rotator: trimming
bond ballast and multiple core holdings to fund new sector bets in a mixed,
non-confirmed tape, while several cards are internally inconsistent. The best case
against current advice is that it increases complexity and style drift before
promotion review without delivering clearly superior risk reduction." Concerns:
mandate drift; CC ideas coexist with options_level=null; SHADOW promotion would
spike order-count/governance complexity.
**Grok (17 CONCUR / 1 QUALIFY / 2 OBJECT):** objected that short stops 3.7%/8.3%
"violate the constitution's stop>=10.0%" — **a misreading (the rule is ≤10% max
distance)**; also flagged 24.1% lagging-Tech book and pending Cost Basis export.
**Read:** ChatGPT's critique is substantive (the BND pair deserves that challenge);
Grok's top objection inverted a rule. Judge quality differs measurably — the case
for at least occasional paid review writes itself.

## DEFERRED to v8.1 (stated): WS-COHERE (cash-destination trim cards, industry-level
lookthrough lines for ≥$50K funds, coherence lint → brief §5), WS-PAID (⚖ modal,
cost-gated metered call, OBJECT-override interlock in the audit chain), quota/
unparseable UI fixtures (code paths shipped).

## Score: structural 9.5 / proven ~6 — the desk now has adversarial external review
on every build, with the first real memos in hand.

## v8.1 addendum (same day) — COHERE + PAID complete
C1 cash destinations (unpaired trims render cash + redeploy conditions; all current
trims paired). C2 industry lookthrough for ≥$50K funds — SCHG ~44% of top-10 industry
weight LAGGING vs SCHD ~25%: the contrast is now an argument. C3 coherence lint caught
two REAL tensions day one (BND + SPCX: HOLD stance with open trim ladders) — rendered
on-page and fed to brief §5. PAID: preview $0.261/review (4,877 real tokens) vs $25
monthly budget; proven to the API door — blocked only by empty Anthropic API credits
(no mock verdicts rendered; pill ④ populates on first funded run). OBJECT interlock
proven LIVE: ChatGPT objected to the BND trim citing the lint's own tension → stage
refused → override-ack staged + `oversight_override` in the audit chain. Pills also on
pair cards (operator ask). Friday auto oversight is ChatGPT OAuth (`llm_lane`
chatgpt, $0). Paid Claude is **manual** (`defense_weekly_paid_review.py --apply-paid`);
`oversight_paid.weekly_paid_review` stays false so the old cron script cannot auto-spend.
