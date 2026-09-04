# Research lane activation plan (NOT ACTIVATED)

**Status:** PREPARED AND TESTED — **not activated**
**Authority:** this lane is implementation-only. Activation changes what runs
and what the operator is paged about, and needs separate operator authorization.
**As of:** 2026-09-04

Every step below has been exercised against an isolated state root. None has
been applied to a live timer, service, cron entry or production store.

---

## Why activation is deliberately withheld

The inventory reports `NO_PRODUCTION_HISTORY` for Brave adoption and
`CONFIGURED_NOT_PROVEN` for 26 of 43 rows. Those labels are correct **and must
stay correct** until a governed run actually happens. Activating a lane does not
retire the label; a *successful governed run* does. Flipping a flag and then
reporting the lane as working would be precisely the "configuration read as
proof" failure this campaign exists to remove.

---

## A. Register the Brave router lane with the research health alarm

**Effect:** the operator starts being paged on `brave_key_missing`,
`brave_monthly_exhausted`, `brave_allowance_never_measured` and
`brave_producing_not_adopted`.

```python
# scripts/research_lane_health.py
from scripts.lib.brave_research_router import health as brave_router_health
COLLECTORS.append(brave_router_health)
```

`health()` already returns the collector row shape (`lane`, `ok`, `firing`,
`as_of`) — verified by `tests/test_brave_research_lanes.py`.

**Expected first result:** `ok=False`, firing
`brave_allowance_never_measured` and `brave_producing_not_adopted`. That is
correct: production has never measured the plan and nothing has cited a Brave
result yet. **Do not silence these to make the board green** — they are the
two facts the campaign exists to surface.

**Verify:** `python3 scripts/research_lane_health.py --json` shows the row.
**Roll back:** remove the one line.

## B. Measure the plan allowance in production

Production's ledger has never seen an `x-ratelimit-*` measurement — the one
measured call in this campaign was written to an isolated root, so the
production ceiling is still `CONFIGURED_NOT_PROVEN`.

```bash
python3 - <<'PY'
from scripts.lib.brave_research_router import search, Purpose, Priority, allowance_reconciliation
search("SEC EDGAR full text search", purpose=Purpose.PRIMARY_SOURCE_DISCOVERY,
       priority=Priority.HELD_CAPITAL, caller="operator-allowance-measurement")
print(allowance_reconciliation())
PY
```

**Cost:** exactly 1 Brave call, through the governed router, counted in the
production ledger. **Effect:** `brave_allowance_never_measured` stops firing and
the operator surface switches from `CONFIGURED_NOT_PROVEN` to
`MEASURED_UNMETERED`.

## C. Enable a routed collector (choose one, not all)

`AEGIS_BRAVE_ENABLED` defaults to `0`. Enabling it starts real scheduled spend.

```bash
# in the environment the cron entry sources
AEGIS_BRAVE_ENABLED=1
```

Projected volume with the router's quotas in force: **~156 calls/month** against
a local ceiling of 850 with a 127-call reserve
(`BRAVE_BUDGET_PROJECTION.json`). Without the quotas the same schedules project
1,028 — that gap is the router's whole contribution, and it is why enabling the
flag is safe now and was not before.

**Verify after one scheduled run:**
```bash
curl -s localhost:.../api/v2/research-intelligence/truth | jq '.brave_usage, .brave_adoption'
```
Expect `billed > 0`. Expect `adopted = 0` at first and **leave it visible** —
adoption only becomes non-zero when a downstream product calls
`record_adoption()`, which is step D.

**Roll back:** set the flag to `0`. Spend stops at the next run; nothing to undo.

## D. Wire adoption recording at the consumers

`phase2b_analyst` calls `record_adoption()`. `aegis_social_sentiment`,
`aegis_transcript_discovery` and `web_research` do not, so their evidence will
read as `PRODUCING_NOT_ADOPTED` however well it works.

This is a code change, not a flag, and belongs to a normal tranche. Until it
lands, `PRODUCING_NOT_ADOPTED` is an accurate description of those lanes, not a
defect in the alarm.

## E. Not covered by this plan

* **SearXNG engine pool** — `bing` is the only engine serving of four
  (`brave` suspended, `duckduckgo` timing out, `startpage` CAPTCHA). The repair
  is SearXNG configuration, which is a deployment action.
* **`topic_ingestion` Brave lane** — retired on an HTTP 402 that no longer
  reproduces. Reviving a lane requires operator intent, not a passing probe.
* **Command Center panel** — the API route is served and tested; no React page
  consumes it. Ordinary frontend work, no blocking dependency.

---

## Activation checklist

| # | Step | Reversible | Changes spend | Changes paging |
|---|---|---|---|---|
| A | register the health lane | yes (1 line) | no | **yes** |
| B | measure the plan | n/a | 1 call | no |
| C | enable a routed collector | yes (flag) | **yes** | no |
| D | wire adoption recording | yes (code) | no | no |

**Nothing in this file has been executed.** Lack of production history remains
visible on every surface until an authorized activation and a successful
governed run have both occurred.
