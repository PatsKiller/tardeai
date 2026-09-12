# FUTURE — the next moves, in the order they unblock each other

Campaign `trade-ai-maturity-overnight-20260912`. Each item names what it unblocks
and what would prove it done. Nothing here is a plan for a level to award itself.

---

## Immediately, and by someone with authority this campaign did not hold

### F1 · Adjudicate the state-root split — unblocks L1, the live board, and MVL counters

The single highest-leverage item. `STATE_ROOT_RECONCILIATION_RUNBOOK.md` carries
the per-file direction census and the exact procedure. Needs guard scope
`state-write` for `data/portfolios/state`, and a human decision on the 19 files
whose served copy is the newer one.

**Done when:** `scripts/check_state_root_split.py` exits 0, and the Oscillator
board's `as_of` is within its producer's cadence rather than 17 days old.

### F2 · Fast-forward the canonical tree — unblocks a single epoch identity

2 commits behind; 106 cron lines execute from it. Needs guard scope `maintree`.
Two tracked files must never take main's version:
`infra/searxng/core-config/settings.yml` (live, bind-mounted, holds the instance
key) and `config/hermes_score_weights.yaml` (locally newer than upstream, v11 vs
v9, never committed upstream).

**Done when:** `git rev-parse HEAD` in the canonical tree equals `origin/main`
and both files are untouched.

---

## Next, and mechanical

### F3 · Give the starved lanes a floor — unblocks L3 authoring at 14:00Z

`config/llm_lane_floors.json` ships empty, which is exactly today's behaviour.
Setting

```json
{"floors": {"l3_judgment_author": 0.20, "governed_research_producer": 0.15}}
```

reserves budget the advisory lanes cannot take. Two adjacent corrections belong
with it: register `l3_judgment_author` in `llm_process_config` (it has no row, and
an unregistered lane skipped the process cap entirely), and source
`LLM_GLOBAL_DAILY_USD_CAP` from one place instead of from each caller's own
environment — five cron lines currently pass `0.50` and two pass `7.00`.

**Done when:** an organic wake inside the 14:00Z–01:00Z window records
`l3_judged` with a non-zero `cost_usd`, a `prompt_digest`, a `release`, and a
`judgment_id` unique to that judgment.

### F4 · Refuse a prediction that cannot fail — unblocks L4

`validate_author_judgment` already refuses a missing falsifier. The commitment
producer should refuse a *vacuous* one by the same principle, using
`claim_is_falsifiable()` from `scripts/lib/commitment_outcome_sweep.py`, which
already classifies both live failure shapes. Then schedule
`scripts/sweep_commitment_outcomes.py --apply`.

**Done when:** at least one commitment passes its horizon and receives a durable
CONFIRMED or REFUTED outcome joined by `commitment_id`, and a `LessonCandidate@v1`
exists in PROPOSED state that no producer ratified for itself.

### F5 · Make Sentinel cite its evidence — unblocks MVL

0 of 140 reviews carry a retrieval, evidence-ref or memory-fact field. Until a
review says what it looked at, it cannot be audited and its verdicts cannot be
adjudicated — which is also why the 4 FAILs give a fail rate and not a
false-positive rate.

**Done when:** ≥95% of eligible reviews carry retrieval, and the four FAIL
verdicts have an adjudication path so an FP rate is measurable rather than
inferred.

---

## Then, and only then

### F6 · M2 on one post-promote epoch

Everything except one clause rebuilds within three hours of a promote. The
exception is a **genuine inbound operator message**. It must arrive from a
person; synthesising it would manufacture the precise evidence M2 exists to
demand, and this campaign did not.

### F7 · L5, which cannot be claimed from this campaign's work

L5 requires an *observed unattended* detect → diagnose → bounded proposal →
authorized repair or refusal → verify → rollback → durable operator report. An
overnight agent repairing defects is not that loop, and the health predicate that
this campaign fixed had never been wired into anything (`check_dark_contracts`
lists it as a known-dark module). Wiring the detector to something that acts is
the prerequisite.

---

## Standing constraints that shape all of the above

- The deterministic core never learns in place; lessons stay candidates until
  someone other than their producer ratifies them.
- No LLM in tick, fire, stop, broker-write, kill-switch or protective paths;
  `MBI_BEHAVIOR=0`.
- An agent cannot validate or score its own artifact — `evaluate_outcome`
  enforces this and the sweep preserves it.
- A cron job is not an agent, and `exit 0` is not evidence: every lane is proven
  by a durable artifact or declared UNVERIFIABLE.
