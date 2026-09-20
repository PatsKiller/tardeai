# LLM Off-Peak Routing — operator guide

**Status: ARMED 2026-09-20** (operator). Deployed 2026-09-20 in PR #1134 and #1143.

| surface | armed | paid callers it covers (7-day out-of-window volume) |
|---|---|---|
| crontab, line 9 `LLM_DEFER_OFFPEAK=1` | **yes** | every cron-launched caller — `watchlist_maria_flash_narrative` (293), `watchlist_cio_synthesis_cron` (79), `advisory_desk_opinion` (262) |
| `tradeai-cio-reactive` drop-in | **yes** | `cio_plan_enrichment` (129) |
| `tradeai-hermes-cio-worker` drop-in | **yes** | `cio_hermes_research` (29) |
| `tradeai-cio-nightly-reflection` drop-in | **yes** | `reflective_critic_flash` (56) |
| `portfolio-server` | **no** | `hermes_external_research` (117) — arming needs a live API restart |

Roughly **850 of the 965** deferrable calls are covered. Measured baseline: 965 of 4,590
successful paid DeepSeek calls over 7 days (21%) fell outside the window.

**There is no single file that arms everything.** The runtime env at
`/run/user/$UID/tradeai/env` is rendered from Bitwarden Secrets Manager, not from the repo
`.env` (which is a legacy dual-write for cron that sources it), and a non-secret feature flag does
not belong in a secrets store. Cron-launched jobs inherit the crontab-level variable; **systemd
units do not**, so each paid caller that runs as a unit needs its own drop-in.

**To disarm:** delete the crontab line, or delete the unit's
`<unit>.service.d/offpeak-defer.conf` and `systemctl --user daemon-reload`. Nothing else changes.
The armed units are timer-driven oneshots, so arming and disarming need no restart.

**The critical allowlist is empty.** No caller is marked `critical`, so *everything* automated
outside the window defers. If a caller genuinely must be current overnight, set it in
Command Center → Ops → LLM Spend → **LLM Routing**; it takes effect on the next call.

## What problem this solves

When the free OAuth lanes are exhausted, paid work still has to reach DeepSeek. DeepSeek bills
peak hours at roughly **double** off-peak, so the operator's rule is: anything that is not
time-sensitive waits for the off-peak window; only the operator's own asks and callers marked
critical spend at peak.

Before this, the peak gate (`deepseek_offpeak.should_scheduled_skip`) logged `PEAK_SKIP` and
exited 0 — the work was **dropped**. Nothing recorded that a question went unasked, and nothing
ever asked it. The window arithmetic is unchanged; the drop is replaced by a durable queue.

## Where it lives in the Command Center

**Menu:** `Ops → LLM Spend` (route `/consumption`).

> The `/consumption` route existed since v3 but was never on the nav rail — the only way to
> reach it was to know the URL. It is now a menu entry.

**Page:** *LLM Consumption*. The header carries a button, **“LLM Routing — off-peak priority”**,
which opens the modal. Off-peak routing is a spend decision, so it sits behind a deliberate
action rather than inline controls a stray click can change.

**Modal:** *LLM Routing — off-peak priority*

| Column | Meaning |
|---|---|
| Caller | Display name and its `process_id` |
| Category | Registry category |
| Cap $/day | The caller's `daily_cost_cap_usd`, for context — **this modal never changes a cap** |
| Set by | `operator` (an explicit choice), `registry` (a seeded default), or `default` |
| Priority | The tier selector |

Changed rows highlight, the footer counts unsaved changes, and **only changed rows are sent** on
save. Saving every row would rewrite every caller's *Set by* to `operator` and destroy the
distinction the page exists to show: an unreviewed default must never read as a decision someone
made.

The header strip shows whether deferral is **ARMED**, whether the window is **OPEN**, how many
requests are queued, and when the next drain is due.

## The three priorities

| Tier | Behaviour |
|---|---|
| `critical` | Spends **now, at any hour**, including peak rates. |
| `standard` | Spends now **inside** the off-peak window; **queued** outside it. *(default)* |
| `deferred` | **Always queued** for the next off-peak window, never spends on demand. |

`standard` is the default, and an unknown caller gets it. A caller nobody has classified must not
silently acquire the right to spend at peak.

**Operator-initiated calls always run immediately**, whatever the caller's tier — that exemption
already existed in the off-peak rule and is unchanged.

## How the work comes back

Deferral is evaluated inside `gate_and_generate`, **after** the policy decision and **before** any
cost reservation — a deferred call must not consume the cap it never spent. The caller receives
`DeferredToOffPeak`, a `RuntimeError` subclass carrying the queue id and the run-after time, so a
caller that does not know about deferral degrades exactly as it would on any other refusal.

`scripts/drain_llm_deferred.py` (lane `llm-deferred-drain`) re-issues the queued calls inside the
window. It **refuses to run outside the window** — a drainer that ignores the window is only a
delayed way of paying peak prices. `--force` exists for an operator who means it.

- **Dedupe:** one pending row per identical `(process_id, prompt)`, enforced by a partial unique
  index. An hourly caller deferring for twelve hours would otherwise queue twelve copies and pay
  for twelve.
- **Expiry:** a queued question is about a moment. The TTL clock starts at the **window**, not at
  enqueue, so work deferred on Friday night for a Monday window is still alive when that window
  opens. Expired rows are counted, never silently dropped.
- **Heartbeat:** `data/runtime/llm_deferred_drain.json` is written on **every** run, including
  runs that drain nothing, so an empty queue and a dead drainer are distinguishable.

## If the queue is unreachable

The call is **refused, not paid**: `DEFERRAL_QUEUE_UNAVAILABLE`. If we cannot promise the work
will run later, quietly paying peak prices is the one outcome the operator ruled out.

## Arming it

1. Set the priorities in the modal first, so nothing is deferred that should not be.
2. Add `LLM_DEFER_OFFPEAK=1` to the environment the callers run under.
3. Install the drain cron (declared in `config/lane_registry.json`):

   ```
   10 10,13,16,19 * * * cd $PROJ && $PY scripts/drain_llm_deferred.py
   ```

   Use `crontab - < file`; `crontab <file>` fails silently.
4. Verify with `scripts/drain_llm_deferred.py --dry-run --json` before the first live drain.

> **`--dry-run` was destructive before #1143.** It called `claim_due()`, which moves rows
> `pending → claimed`, then printed and exited — so the preview consumed the work it was
> previewing and stranded it, invisible to `pending` counts. Fixed: the dry-run branch returns
> before `claim_due` is reachable, and `reclaim_stale()` returns claims older than 30 minutes to
> the queue (retiring anything past 3 attempts). **If you are on a release older than
> `348d4fdba`, do not run `--dry-run`.**

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v2/consumption/caller-priorities` | Tiers, callers with `tier_source`, queue summary |
| POST | `/api/v2/consumption/caller-priorities` | `{updates:[{process_id,tier}], updated_by}` |
| GET | `/api/v2/consumption/deferred-queue` | Pending and claimed requests |

An unknown `process_id` or tier is rejected and reported, never stored. Nothing on these routes
can raise a cost cap — cap changes remain an AGENTS §12 operator decision.

## Related

- `AGENTS.md` §12 — LLM governance and caps
- `scripts/lib/deepseek_offpeak.py` — the window arithmetic, unchanged by this
- `tests/test_llm_offpeak_deferral.py` — 24 tests, none of which touch a real database
