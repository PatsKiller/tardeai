# Goal Lap Pipeline

Status:      ACTIVE
as_of:       2026-09-19
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0

**Related:** `docs/AGENT_ROSTER.md` · `config/systemd/agent_runtime/README.md` ·
`scripts/lib/goal_budget.py` · `scripts/lib/goal_generation.py`

## What a lap is

A *lap* is one bounded attempt at one open goal. A goal earns a new lap only when
its **generation key** changes:

```
dedup_key = goal:{goal_id}:{predicate_version}:{ledger_digest}
```

The digest moves only when a lap learns something. Two laps that reach the same
conclusion therefore hash identically — which is how "this agent is repeating
itself" stays visible instead of looking like progress.

## The only sanctioned path

```
open goal
  -> goals:laps producer adapter        (scripts/agent_runtime/trigger_sources.py)
  -> gate_candidate CHARGES a lap       (scripts/lib/goal_budget.py)
  -> trigger_intake  ON CONFLICT dedup  (agentic_runtime.trigger_intake)
  -> runtime leases and processes       (scripts/agent_runtime_live_providers.py)
  -> append_lap writes the ledger       (data/cio/cio_goal_laps.jsonl)
```

The budget binds at the **producer**, where a lap is *authorised* — deliberately
not inside the runtime, which runs as the agent. An agent that can reach its own
ledger can extend its own budget.

## Operator switches

| Flag | File | Effect |
|---|---|---|
| `AGENT_RUNTIME_GOAL_LAPS=1` | `~/.config/tradeai/agent-operator.env` | Arms the `goals:laps` adapter. **Unset = inert** (`NOT_CONFIGURED`, zero candidates). |
| `AGENT_RUNTIME_INPROCESS_GOAL_JOBS=1` | — | Restores the **retired** in-process minter. Leave unset. |

`agent-operator.env` is the file the **producer unit** loads.
`agent_runtime_overrides.env` is sourced by the three §17 cron lines and is *not*
read by the producer — setting the flag there looks armed and does nothing.

## Who may own a lapping goal

A goal's owner must be in `FLEET` **and** `is_operable_now`. `AGENT_ALIASES`
(`guardian → risk_agent`, `tax_agent → ledger`) is applied only in `run_once`, so
the adapter resolves it before checking.

Five agents are `DESIGNED` / not operable: `aegis`, `ledger`, `maria`,
`risk_agent`, `vega`. Their runners print `no-work … not SHADOW-operable` and
exit, so a lap enqueued for them can never be leased — and because the budget
charges at enqueue, admitting one would spend the goal's allowance on work
nothing will ever do. The adapter skips them and names them in its probe.

## What this replaced, and why

Measured 2026-09-17/18, before the rewire:

| | |
|---|---|
| Minting rate | **36 laps/hour**, continuously |
| `lap` counter | reached **85** against a `max_laps` of **12** |
| Distinct dedup keys | **3** across 184 rows |
| Laps carrying `model_error` | **184 / 184** |
| Laps closing a need | **0 / 184** |
| Goal-keyed rows in `trigger_intake` | **0** |

`job_source` built goal `JobRequest`s **in-process** and never enqueued them, so
they reached neither the intake dedup nor the budget gate. `goal_budget.json` did
not exist — not because the gate failed open, but because it was never called.

A second defect sat behind it: `gate_candidate` charges before `store.enqueue`,
so an enqueue refused as `DUPLICATE` had already been paid for. **36 charged, 3
real** — each goal's whole allowance burned in 22 minutes, ending at
`LAP_BUDGET_EXHAUSTED`, which is terminal. `refund_lap` now returns an unadmitted
lap.

## Guards

- `scripts/check_goal_work_minters.py` — ratchets the **set** of modules able to
  mint goal work (3 declared). A new one fails the build. It cannot judge whether
  a minter is correctly budgeted; that stays a human call.
- `tests/test_goal_work_minter_ratchet.py` — includes a planted probe proving the
  checker can go RED, and a control proving detection cannot be silently weakened.
- `scripts/lib/goal_budget.py` — cumulative per `(goal_id, predicate_version)`;
  an unreadable ledger DENIES, an absent one is a legitimate empty document.

## Reading the state

```bash
cat  data/runtime/goal_budget.json                 # laps / refunded / denied per goal
wc -l data/cio/cio_goal_laps.jsonl                 # laps actually appended
python3 scripts/check_goal_work_minters.py         # the minter ratchet
grep -c GOAL_STATUS_CHANGED data/cio/cio_goals.jsonl   # still 0 — see below
```

## Known limits

- **`GOAL_STATUS_CHANGED` is still 0.** Laps are bounded and honest, but no goal
  closes: every lap dies at `PROVIDER_BLOCKED` (financial agents must route
  through the governed gateway), so nothing is learned, the digest never moves,
  and one lap per generation is correct. That is a provider-wiring issue, not a
  loop defect.
- Three of four live goals declare empty `success_criteria`, so they carry a
  single `unspecified` need.
- `risk_agent`'s queue holds 64 stale `SCHEDULED_SWEEP` rows from 2026-09-15
  (`attempt_count 0`), pinning it at `max_queue_depth`. Harmless now that the
  adapter skips inoperable owners; clearing it is an operator decision.
