# PHASE 189E — Corrected Market-Open Operator Digest

Status:      HISTORICAL
as_of:       2026-06-02T09:35:38-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 09:32 ET (post-open) · Alpaca **paper** only · Live endpoint blocked

> **Framing correction (supersedes Phase 188's "naked positions"):** No position is naked. All 6
> open paper positions hold a **live, re-verified broker stop**. The real issue is that
> **protection metadata is untracked/unverified in the DB for ANY, SNOW, TMHC**, and the health +
> Hermes layers failed to escalate that. This is a tracking/observability defect, not an
> unhedged-book emergency.

## Status line

| Item | Post-open status |
|---|---|
| Watch | ✅ fired 09:30:02 ET |
| ELMT | **REJECTED** premarket (aged out, `auto_blocked_230min`); ~31% open spread; did not clear |
| Book hedged? | **YES** — 6/6 broker stops live (status=new), re-verified 09:32 |
| Untracked stops (DB) | **3** — ANY, SNOW, TMHC |
| SNOW gain | **STALE mark corrected** — real ≈ **+13.3% (+$251.50)**, not the +18%/+$348 stale mark |
| ANY | **+$569.48 live (+5.75R)** — biggest unprotected-upside; stop only near breakeven, no TP |
| New trades at open | 0 |
| Operator action | **YES — profit-protection review (ANY, SNOW) + record/verify stops; non-urgent (stops exist)** |

## Severity & post-open change
- **ANY** — severity **P1**. Post-open price *rose* (4.05→4.15), gain grew to +$569; severity
  unchanged but reinforced: large winner, stop near breakeven, no take-profit/trailing, untracked.
- **SNOW** — severity **P1**, but **de-escalated on facts**: the +18% was a stale mark; live is
  +13.3%. Its broker stop @254.38 already locks a gain above entry. Untracked in DB.
- **TMHC** — severity **P2**. ~flat; stop @68.02 live but unrecorded and note never broker-confirmed.
- **ELMT** — remained **blocked/rejected**; correct behavior; no operator action.

## Is urgent operator attention needed now?
**No emergency.** Because broker stops exist and were re-verified, the downside is covered. What is
needed (non-urgent, Phase 190): (1) make protection **provable** by recording `stop_order_id` /
`stop_verified_at`; (2) decide profit protection on ANY (+$569) and SNOW (+$251) — trailing/TP;
(3) fix the health/Hermes blind spots so an unprotected position would actually alert.

## Telegram — actionable conditions MET; payload prepared, **NOT auto-sent** (awaiting operator OK)

> Conditions satisfied: untracked broker stops on active paper positions (3) + missing take-profit
> on large gains (ANY +$569, SNOW +$251) + a confirmed system defect (health/Hermes non-escalation).
> Per phase rule, not auto-sending — confirm to dispatch.

```
🟠 ATM Paper — Market-Open (2026-06-02 09:32 ET)
Book is HEDGED (6/6 broker stops live, re-verified). NOT naked.
But DB protection metadata is UNTRACKED for 3 active positions:
• ANY  +$569 (+5.75R) stop@3.07 live but unrecorded; no take-profit  [P1 review]
• SNOW +$251 (~+13.3%, prior +18% was a stale mark) stop@254.38 live, unrecorded; no TP  [P1]
• TMHC  flat, stop@68.02 live but unrecorded; note not broker-confirmed  [P2]
ELMT: rejected premarket (aged out), ~31% open spread — correctly not traded.
Defect: stop_order_id never persisted; health(log-swallowed) + Hermes(no view/rule) didn't escalate.
0 trades at open. Paper-only. Live endpoint blocked. No mutations. Fix = Phase 190.
```
