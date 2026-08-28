# Phase 8 analysis — P8.3, P8.4, P8.6

Three deliverables the brief asked for as analysis rather than code. Grouped in
one review because none of them changes a line of production code and two of
them argue against changing any.

`[VERIFIED]` = a command was run and its output is quoted.
`[CODE]` = read from source. `[DOC-CLAIM]` = a document asserts it.

Posture: `READ_ONLY_ADVISORY`, `MBI 0`.

---

## P8.3 — the `$PROJ/logs` fork: #569's fix shape does NOT transfer

### Inventory `[VERIFIED]`

```
path      /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/logs
entries   4,148          size 1.3 GB
writers   342 cron entries (`cd $PROJ`) + 83 systemd units
content   3,966 .log · 115 .md · 19 .json · 13 .jsonl · 6 .txt · 3 .gz · 2 .lock
```

State rather than logs, and append-only history, both live here:

```
append-only (.jsonl)                  size
  safe_flock_events.jsonl             64.4 MB
  llm_router_safety.jsonl             56.7 MB
  llm_routing_audit.jsonl             38.3 MB
  health_root_cause_memory.jsonl       6.6 MB
  health_agent_remediation.jsonl       1.3 MB
  health_agent.jsonl                   829 KB
  claude_escalation_retry_cmd.jsonl    753 KB
  (+ 6 smaller)

state (.json)
  claude_escalation_queue.json          10 KB   <- a live remediation queue
```

### Why the fix shape does not apply `[VERIFIED]`

#569 worked because each release's `logs/` **started empty** — it was gitignored
and never rsynced — so moving it to canonical storage was a pure rename and lost
nothing. That is not the situation here. 15 files exist in both trees and **14
of them differ**:

```
file                                proj        persist     verdict
claude_escalation_queue.json        10,478      6,282       DIFFER
claude_escalation_retry_cmd.jsonl   752,754     87,013      DIFFER
health_agent.jsonl                  828,876     4,625       DIFFER
health_agent_remediation.jsonl      1,291,483   38,271      DIFFER
safe_flock_events.jsonl             64,432,929  22,000      DIFFER
claude_escalation.log               25,309,752  101,999     DIFFER
hermes_scope_governor.log           13,654,895  4,775       DIFFER
research_scheduler.log              15,974,731  783         DIFFER
(+ 6 more)                                                  DIFFER
claude_escalation_queue.json.lock   0           0           identical
```

Symlinking `$PROJ/logs` at canonical storage would point 342 cron entries and 83
units at the much smaller copies and interleave two divergent append-only
histories. That is a machine merging divergent evidence stores, which the
standing rule forbids, and it is not reversible once the appends interleave.

### Which forks are live, and which are dormant `[VERIFIED]`

The distinction matters because only one of these is an operational hazard.

```
                                  proj last write   persist last write   live fork?
claude_escalation_queue.json      08-27 20:50:28    08-27 20:52:31       YES  (50 vs 18 entries)
safe_flock_events.jsonl           08-27 20:50       08-27 20:51          YES
health_agent.jsonl                08-07 21:34       08-27 20:50          no — proj is dormant history
health_agent_remediation.jsonl    08-07 21:31       08-27 20:50          no — proj is dormant history
```

The health-agent histories moved to the persistent path three weeks ago; their
`$PROJ` copies are frozen history, not a competing writer. **Two stores are
genuinely written by both sides within minutes of each other today.**

### An honest note about #569

Before #569 the release-side copies were ephemeral — reset on every deploy. #569
made them durable. That is still the right change (evidence was being discarded
every deploy), but it converted an ephemeral fork into a durable one for these
15 files. That is a cost of #569 worth stating plainly rather than discovering
later.

### Recommendation — operator decision, no code here

1. **Do nothing to the 13 dormant files.** They are history. Leave them.
2. **`claude_escalation_queue.json` is the only urgent one.** Two live queues
   for the same remediation lane means either consumer can act on a partial
   view. See P8.4: the queue is derived state, so the safe fix is to make one
   path canonical and let the other be re-derived — not to merge them.
3. **`safe_flock_events.jsonl`** is append-only evidence with two live writers.
   Either give it one writer or accept two shards and say so in the registry.
4. Do not touch the 146 historical release directories. They are evidence.

---

## P8.4 — triage of the abandoned escalation entries: replay nothing

The pre-#569 deploy abandoned an 18-entry queue. It was deliberately not
replayed. That was correct, and the evidence now shows it was also unnecessary.

### Triage table `[VERIFIED]`

`still holds` = the health agent re-derives this component from live state now.

```
component                                            critical  retry_cmd                        still holds
health:data_quality:risk_management_stale            no        —                                YES
health:data_quality:data_source_stale                no        external_market_data_ingest.py   YES
health:execution_health:agent_jobs_contained         YES       —                                YES
health:execution_health:pipeline_failures            YES       remediate_pipeline_failures.py   YES
health:execution_health:agent_jobs_stuck             YES       —                                YES
health:execution_health:release_manifest_warn        no        —                                YES
health:execution_health:proposal_link_rate_low       no        —                                no
health:execution_health:proposal_thesis_broken       no        —                                YES
health:execution_health:approved_paper_test_stuck    no        cleanup_stale_proposals.py       YES
health:execution_health:db_idle_txn_kills            no        —                                no
health:intelligence_quality:catalyst_type_quality    no        —                                YES
health:intelligence_quality:hermes_embed_failures    no        hermes_embedding_worker.py       YES
health:intelligence_quality:hermes_scope_governor_*  YES       hermes_scope_governor.py         YES
health:intelligence_quality:hermes_governed_universe no        —                                YES
health:intelligence_quality:hermes_event_feeder_*    YES       —                                YES
health:risk_protection:stop_alerts                   no        —                                YES
health:execution_health:cron_dead_script_ref         no        —                                YES
health:execution_health:synthesis_processing_stuck   no        reset_stuck_agent_jobs.py        no

5 critical · 6 with a retry_cmd · 15 of 18 conditions still hold
```

### The finding that settles it `[VERIFIED]`

```
abandoned entries already re-queued somewhere live : 17 of 18
abandoned and not currently queued anywhere        :  1
    health:execution_health:db_idle_txn_kills   (condition no longer holds)
```

**The escalation queue is derived state, recomputed from live conditions each
cycle — not a durable work list.** Every entry whose condition still holds has
already been re-raised. The single entry that was not re-raised is one whose
condition has cleared, so replaying it would have acted on a problem that no
longer exists.

### Recommendation

**Replay nothing.** Not as a precaution — as a measured conclusion: there is
nothing to recover. Per entry, the recommendation is identical (no action), and
the reason is the same for all 18.

The wider lesson is about the queue's status, not its contents: because it is
re-derivable, losing it costs nothing, which means it does not need durable
storage at all. That is the cheapest resolution of the P8.3 queue fork — declare
one path canonical, let the other be re-derived, and stop treating a cache as
history.

---

## P8.6 — decision memo: the two-writer holdings question

Two jobs write two `holdings.json` files. Since #570 each is internally
consistent; they still differ from each other on price and mtime. Deferred three
times, correctly. This memo lays out the options. **No implementation.**

`never_auto_remediate` stays on the finding under every option below.

### What is actually true today `[VERIFIED]`

- both copies reconcile internally: `delta 0.00` on each
- they differ because two jobs price the book at different times
- all 30 positions match by `(symbol, account)`; `shares` differs on 0 of 30
- the divergence is entirely `price` / `market_value` / `as_of` / `shares_synced_at`

So this is not a correctness bug any more. It is an **ownership** question: two
writers, no declared primary, and a reader that silently picks one.

### Option A — one writer, one file; the other path reads it

*What breaks:* every job that writes holdings from `$PROJ` must be repointed;
~1,100 checkout-relative call sites are the outer bound of the blast radius,
though only the writers matter. Any job that assumed it could write its own copy
fails loudly rather than silently diverging — which is the point.

*Cost:* the largest of the three. Requires auditing which jobs write vs read,
and a cutover with a rollback path.

*What stops regression:* `store_consistency` already detects a second copy
appearing. Add a write-path assertion that refuses a holdings write outside the
canonical path, so a new writer fails at its first attempt rather than at the
next audit.

*Best when:* the intent is that there is one book, and any second copy is a bug.

### Option B — two writers, explicit primary, declared maximum divergence

*What breaks:* nothing immediately. The registry gains a declared primary and a
tolerance (say, price divergence under X% and age under Y minutes); breaching it
becomes a finding rather than a silent difference.

*Cost:* the smallest. Mostly registry metadata plus a check that already exists
in `store_consistency`.

*What stops regression:* the tolerance is the guard. Its weakness is that a
tolerance nobody tunes becomes a tolerance nobody trusts — the same failure the
freshness flag had before P7.5.

*Best when:* both copies genuinely serve different consumers and convergence is
not required, only bounded divergence.

### Option C — two writers by design, difference surfaced not resolved

*What breaks:* nothing. The UI and the CIO both learn to show "priced at
16:45" vs "priced at 16:52" rather than a single number.

*Cost:* low in code, high in interface — every surface showing a portfolio total
must carry its as-of, or it lies by omission.

*What stops regression:* nothing structural. This option accepts the fork and
depends on discipline at every display site, which is the assumption that has
failed most often in this codebase.

### Recommendation: **Option A**, with Option B as the staging step

The strongest evidence is what the two copies actually differ on: only pricing
timestamps. There is no consumer that needs two differently-priced books; the
second copy exists because two jobs happen to write, not because anyone asked
for two. Option C institutionalises an accident.

Take B first as a same-week change — declare the primary and the tolerance, so
the fork is bounded and monitored while the writer audit happens — then A as the
real fix. That sequence gets the safety of a declared primary immediately
without a risky cutover, and ends with one book.

What would change this recommendation: evidence that a real consumer requires
the intraday-priced copy while another requires the settled one. That has not
been found, but it has not been exhaustively ruled out either, and it is the one
fact that would make B the destination rather than the staging post.
