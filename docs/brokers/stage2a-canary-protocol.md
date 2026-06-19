# Stage 2a — Shadow Validation Protocol (manual orders + read-only API)

**Status:** SCHEDULED — session date committed **2026-06-22 (Monday)** in `scripts/brokers/canary_gate.py`
(`CANARY_SESSION_DATE`; rescheduled 06-12 → 06-13 → 06-15 → 06-22, prior gates auto-expired fail-closed).
Operator risk caps locked 2026-06-12 (unchanged). Doc rev 2026-06-19. paperMoney is NOT API-visible
(operator-confirmed), so tests are tiny REAL orders placed MANUALLY in thinkorswim; the API surface stays
read-only throughout (no-writes validator green; execution BROKER_DISABLED).

> **⛔ PREREQUISITE (P0, before this session runs):** OpenAI + OpenClaw API key rotation (open P0 items)
> must be completed first. Do NOT run the canary until those are closed.

## Operator risk caps (locked 2026-06-12 — these supersede all earlier sizing)
- **1–2 tickers per session**, price **$2–$4**, liquidity-screened **at session time** (spread ≤ ~1%,
  volume ≥ ~5M, supports the order types under test, ZERO footprint in holdings/watchlists/paper history).
  Documented fallback: the **cheapest liquid qualifying name** from the same screen.
- **≤ 10 shares per order.** Orders 1–6 far-from-market + manual cancel (**~$0 realized**). **≤ 1
  attended marketable micro-fill** (~**$40 peak exposure** worst case at 10 sh × $4).
- These same caps are HARDCODED in `scripts/brokers/canary_gate.py` (commit-only, fail-closed, empty
  allowlist between sessions). **Commit the screened symbol(s) to `CANARY_SYMBOL_ALLOWLIST` at session
  start; revert/rotate by commit after the session.**
- ⚠️ The previously screened ITUB ($7.91) / SNAP ($5.33) **violate the $2–$4 cap** — do NOT reuse them.

## SESSION SCREEN — carried from 2026-06-12, ⚠️ MUST RE-SCREEN for the 2026-06-22 session
| Pick | Px (AH, 06-12) | Spread (06-12) | Avg vol | Why |
|---|---|---|---|---|
| **PRIMARY: GRAB** | $3.37 | 0.6% | 51.2M | superapp mega-name; deepest book in band; ZERO footprint (never held/watched/papered/journaled) |
| **FALLBACK: XRX** | $3.45 | 0.9% | 6.3M | NYSE household name; zero footprint |
| (screened out) | | | | VIDA drifted to $4.20 (above cap) · ABEV/BBD/CIG have footprint · LYG/ERIC > $4 |

Currently committed: `CANARY_SYMBOL_ALLOWLIST = ("GRAB", "XRX")` (from the deferred 06-12 screen; never
rotated back since the session kept rescheduling). Gate verified live (10 sh @ $3.40 passes; @ $4.05
blocked "price > $4 cap"). **⚠️ These quotes are ~10 days stale — at the 2026-06-22 open you MUST re-run
the $2–$4 liquidity screen and re-verify GRAB/XRX (price still in band, spread ≤ ~1%, vol ≥ ~5M, still
zero footprint); replace either pick by commit if it has drifted out of band. ROTATE the allowlist back
to `()` by commit after the session.**

## Pre-session checklist (system side — all read-only)
1. Re-run the $2–$4 liquidity screen; **commit** the pick (+fallback) to the hardcoded gate allowlist.
   Canary tagging (`schwab_round_trips.canary`) keys off this same committed list — proven to move zero
   analytics aggregates (tests/test_canary_exclusion.py).
2. Start the shadow-reconciliation harness: `scripts/schwab_shadow_recon.py --watch --interval 30`
   (reads orders back every ~30s; diffs Schwab's actual representation vs the translator's predicted
   payload; **∅ = pass, modulo documented renames**; results → `schwab_shadow_recon_runs/_items`, the
   Broker Orders tab, and `docs/brokers/stage2a-reconciliation-log.md`).
3. Start the poll-based activity capture: `scripts/schwab_activity_capture.py --watch --interval 30`
   (ACCT_ACTIVITY-equivalent fill/status payloads → `schwab_activity_log`, surfaced in the Broker
   Orders safety log; streaming deferred).
4. **Fresh OAuth token at session start** (`schwab_token_manager` health green for the session account).
5. Draft each planned order in the ToS-style Broker Orders panel FIRST (the draft is the translator
   prediction the harness reconciles against).

## Session rails (non-negotiable)
READ-ONLY API the entire session · ALL placement/modification/cancellation happens manually in
thinkorswim · operator attended start-to-finish · quiet window 11:30–14:00 ET · ONE order at a time —
reconcile PASS/FAIL before the next. **Abort immediately on:** unexpected fill · ANY API-write attempt
(must be impossible — validator green) · reconciliation mismatch beyond documented renames · OAuth
token expiry mid-session.

## Test battery (operator places in ToS; ≤10 sh; X = the screened $2–$4 canary)
| # | Manual order | Hypothesis (what Schwab will show) | Pass criterion | UNVERIFIED # | Fill risk |
|---|---|---|---|---|---|
| 1 | BUY ≤10 X LIMIT ~50% below mkt — wait 60s — CANCEL | order JSON matches predicted payload; lifecycle WORKING→CANCELED | shadow diff ∅ (mod. renames); cancel propagates ≤30s | #3 status enum | none (~$0) |
| 2 | Same, GTC + PM session | duration/session round-trip faithfully | diff ∅ on session/duration fields | #8 sessions/TIF | none |
| 3 | OTOCO: BUY ≤10 X LIMIT far-below w/ bracket (TP/SL) — CANCEL | TRIGGER→OCO child structure as translator predicts | child structure diff ∅; parent cancel kills children | #1 (partial) | none |
| 4 | OTOCO w/ TRAILING_STOP exit (3% LAST) — CANCEL | stopPriceLinkBasis/Type/Offset represented as predicted | trailing fields diff ∅ | #4 trailing repr | none |
| 5 | MODIFY #1-style order's limit in ToS before cancel | replace-as-experienced: new order or amended? | read-back shows the modification; harness flags shape | #2 (read side) | none |
| 6 | OCO multi-target prep (2 exits, ≤half position each) — verify accept, CANCEL (do after 7 if position needed) | multi-target OCO accepted; qty split as predicted | accept + diff ∅ | #1 multi-target | none |
| 7 | **THE micro-fill:** BUY ≤10 X marketable LIMIT @ ask (≤$40 notional) | FILL lifecycle + activity payload shape | fill event captured in `schwab_activity_log` w/ full payload | #6 fill events | ≤$40 position |
| 8 | Attach OCO exits to the live position (TP +2% / SL −2%) | live children activate against the position | children visible+linked in read-back | #1, #5 live children | ±~$1 |
| 9 | SELL to close (marketable limit) → ingestion | close lifecycle; round-trip lands **canary-tagged**, excluded from stats | `schwab_round_trips` row `canary=true`; zero aggregate movement | #7 ingestion | spread |

Expected realized cost ≈ spread on ≤10 shares ≈ cents; worst-case exposure ≤$40, attended.

## Outputs
`stage2a-reconciliation-log.md` (per-order: ToS intent vs API representation vs translator prediction) ·
resolved/remaining UNVERIFIED register updates · activity payload captures (`schwab_activity_log`) ·
post-session: canary exclusion re-proof (`tests/test_canary_exclusion.py`) + allowlist rotation commit.

## What this CANNOT validate (stays for gated Stage 2b API canaries — L4, separately gated)
API-side `replace_order` semantics · priceLink fields on API submission · API reject taxonomy.

## Plain-English: what the ≤10-share orders actually test
These orders test NOTHING about making money. They test the things we cannot know without watching
Schwab handle a real order — everything we built is verified against the SDK's SCHEMA, not Schwab's
RUNTIME behavior, and Schwab offers no sandbox. Orders 1–6 (never fill, ~$0): response JSON shape for
OTOCO/trailing/multi-target, the real status lifecycle enum, whether cancelling a TRIGGER parent
cancels children, AM/PM/GTC round-tripping. Orders 7–9 (one ≤$40 attended fill): what a FILL looks
like in the activity stream, whether attached OCO exits actually arm against a live position, and
whether the round trip flows into ingestion correctly (canary-tagged, excluded from stats). Without
this, the first live order the system ever places WOULD BE the test.

## Where the approval channels live (two-channel anti-fat-finger, testable now)
1. **Telegram** — proposals chat: ✅ Approve button (or manual code). The message includes the
   **Tailscale deep-link** `https://<TAILSCALE_HOSTNAME>/v3/trading?tab=Broker+Orders&intent=<id>`
   straight to the exact order item.
2. **Web** — Command Center → Trading → Broker Orders → the order's 🔐 panel: a confirm popup that
   requires **typing the ticker** (a click alone never confirms). Single-use, TTL 10 min, one order
   at a time. Both channels can be exercised end-to-end TODAY — and execution still ends BLOCKED by
   the guard (correct this phase).
