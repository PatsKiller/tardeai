# Brave September count — reconciliation

**Date:** 2026-09-05
**Status:** the DIVERGENCE is closed; the NUMBER is not, and is not ours to close.
**Rule:** AGENTS.md §0.5 — never auto-remediate divergent copies of an authoritative store.

---

## The question as it was posed

> September's Brave count is unreconciled — L2 says none/54, L3 says 60.

That framing was mine and it was loose in two ways. Both are corrected here by
measurement.

## What is actually true

### August was never a divergence

| ledger | August |
|---|---|
| L3 `search_budget.json` | 25 |
| L2 `brave_search_budget.json` (dev tree) | 158 |
| L2 (persistent-state) | 150 |

This reads like a catastrophic disagreement and is not one. **L3 was created on
2026-08-30** (`lib/search_budget.py` docstring; PR #719), and its earliest daily
key is `2026-08-31`. It counted one day of August. L2 counted the month. The two
are measuring different intervals, and neither is wrong.

Reporting 25-vs-158 as a divergence would have been the same error as reading a
provider's unmetered `0` as a ceiling of zero: a number compared against another
number that does not mean the same thing.

### September agreed exactly until the day it was examined

| | L3 | L2 (dev tree) |
|---|---|---|
| September total | **60** | **54** |
| of which 2026-09-05 | 8 | 2 |
| **through 2026-09-04** | **52** | **52** |

**They agreed exactly — 52 and 52 — through 2026-09-04.** The entire six-call gap
opened on 2026-09-05. This is not months of accumulated drift; it is one day.

L2's last write was `13:30:03`; L3 continued to `17:30:03`. Six calls were
recorded in L3 after 13:30 that no L2 copy saw.

### What was ruled out, and what was not

Ruled out by measurement:

- **Permissions.** The L2 file is `-rw-rw-r--` and its directory was written by
  other processes at 16:45, 17:11 and 17:20 the same day.
- **A different copy taking the writes.** Of the eight copies of that basename on
  this host, **exactly one was modified on 2026-09-05**, and it stopped at 13:30.
  No release-directory copy was written at all.
- **A caller bypassing the client.** `web_research.py` — credited with all 60 of
  September's calls in L3 — imports only `brave_search.search`; it makes no direct
  `search_budget` call.

**Not established:** which of the paths through `search()` incremented L3 without
incrementing L2 after 13:30. `_save_budget` was a bare `write_text` wrapped in
`except Exception: pass`, so a failed write left no trace anywhere. **The
mechanism for the six is unattributed and is recorded as unattributed.**

## Which number to trust, and which question stays open

Two different questions were being conflated:

**1. Which of our two counters is right?** — answerable, and answered: **L3.**
It writes under an exclusive `flock` with an atomic rename. L2 was an unlocked
read-modify-write whose save swallowed every exception, so it could silently lose
an increment and could not report that it had. Between a counter that can lose
writes invisibly and one that cannot, the higher count from the atomic one is the
better estimate. **L3's 60 is the September figure to use.**

**2. What did Brave actually bill?** — **UNRESOLVED, and not resolvable from this
box.** Rate-limit headers state limits, not usage or price. The provider's own
dashboard is the only authority, and it has previously disagreed with this system
by a factor of six: `lib/search_budget.py` was built because the ledger read
150/month for 2026-08 while the dashboard read roughly 1,000.

**Neither number was written into the other.** No merge was performed.

## What was changed instead

The divergence class is removed rather than the discrepancy patched.

L2 still counted for exactly one reason: it held `CALLER_CAPS`, per-caller daily
limits that the canonical ledger had no equivalent of. Those now live in
`lib/search_budget.CALLER_DAILY_CAPS` and bind for **every** caller, including the
ones that never imported the Brave client. With its last unique job moved, L2
stops counting:

- `brave_search._record_call` is retired and writes nothing. The files remain in
  place, unwritten, readable as history. **Nothing was deleted** — and deleting
  the persistent-state copy would have been unsafe for a separate reason: the
  serving release symlinks into it, and `_load_budget()` rebuilds a fresh zero
  counter on a missing file, which is a fail-open into unbudgeted calls.
- `search()` and `search_news()` now **reserve** through `try_consume` before the
  request and **refund** on every failure path. They previously checked, called,
  and then recorded — a check-to-use gap in which two processes could both
  observe an under-limit counter and both spend. `lib/search_budget` names this
  in its own `check` docstring, and the two `aegis` callers that bypass the
  client were already using `guard()` correctly, which made them more correct
  than the sanctioned path.
- Refunds are recorded under their own key, never as denials. Denial history is
  read to answer "did the budget refuse us"; conflating a refund with a refusal
  would make that history unreadable.

Validated by `scripts/dry_run_brave_budget_reconciliation.py` — 20 properties
against an isolated ledger, including a proof that the production ledger is
byte-identical afterwards.

## What the operator still owns

Compare **L3's 60** against the Brave dashboard's September figure.

- If they agree, the reconciliation is closed and this document records how.
- If the dashboard is materially higher, there is still an unbudgeted caller. The
  known candidate is `phase2b_analyst.py:276-352` — its own key, its own
  `urllib` request, touching no ledger and passing no gate. It is currently
  **dormant** (no cron entry, no systemd unit, no importer but itself, last
  touched 2026-04-18), so it is a loaded gun rather than a live leak. It also
  still carries `# Limit to top 5 to stay within 2000/mo free tier` — a third
  invented provider limit, and a different number again from the 1,000 that was
  removed from `brave_search.py`.

Nothing here should be read as certifying the September figure against the
provider. It certifies only that this system now has one counter instead of two.
