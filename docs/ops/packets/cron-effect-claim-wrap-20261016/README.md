# Cron effect-claim wrap 2026-10-16: the cron copy refuses itself when n8n owns the lane

```
Status:      PACKET (code + tests in the PR; the crontab is NOT CHANGED: operator, cron grant)
as_of:       2026-10-16
Authority:   operator "execute your recommendations" (2026-10-16); AGENTS.md §23.23 rule (4), §23.25
Target:      46 live crontab lines (read-only plan, 2026-10-16); no unit, no n8n workflow, no ledger write
Live apply:  apply.sh --apply under an active `cron` grant naming this packet; rollback.sh --apply reverses it
```

## Why

`scripts/lib/effect_claim.py` holds one owner per process: cron or n8n. On 2026-10-16, 31 processes had owner
`n8n`, but **no crontab line ran through `scripts/effect_claim_cron.sh`**. So owner=n8n did not stop the cron copy.
Only the shared `flock -n` kept the two schedulers apart, and n8n lost that race: there were 26 lock skips that day.

## Wrapper semantics (scripts/effect_claim_cron.sh, changed in this PR)

The wrapper is OFF unless the line sets `TRADEAI_EFFECT_CLAIM=<lane>`. When it is off, the wrapper `exec`s the
command unchanged. The rewritten line sets the variable for its own lane.

| Case | Result | Event (`logs/effect_claim_events.jsonl`) |
|---|---|---|
| owner **cron**, `cron_claim` true | Claims `fx:<process>:<slot>:v1` and runs the command. The child's exit code is kept. | `completed_claimed` |
| owner **cron** or no owner row, `cron_claim` false | Runs the command unclaimed. | `run_unclaimed_cron_claim_false`, `completed_unclaimed` |
| owner **n8n** (any `cron_claim`) | **exit 0**. The command does not run and no claim row is written. | `skipped_effect` |
| ledger **unreachable** | **Fails open**: the command runs unclaimed, which is today's behaviour; the flock still refuses an overlap. | `run_unclaimed_ledger_unreachable` (`cron_claim` true), or `owner=ledger_unreachable` in the detail (`cron_claim` false) |
| slot already claimed, or `cron_claim` true with no owner row | exit 75 (unchanged). | `refused_claim` |
| lane not keyed, or config unreadable | exit 65 (unchanged). | `refused_*` |

Before this PR:
- owner n8n exited 75;
- an unreachable ledger exited 2 and ran nothing;
- with `cron_claim` false the owner was never consulted.

Support added in `effect_claim.py`:
- **`owner --process P`**: a `mode=ro` read that never creates or migrates the ledger.
- **`run --decision-out FILE`**: writes the claim decision before the child starts. If the file is empty, the claim was never decided, so the wrapper knows the command did not run, and a fail-open run cannot be a second run.

## What the plan wraps

`plan.py` reads these inputs, all read-only:
- the LIVE crontab;
- `config/lane_registry.json`;
- `config/n8n_effect_keys.json`;
- `docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv` (families);
- the relay live list (lane names only);
- the coordination ledger's owner rows (`mode=ro`).

A line is wrapped only when all of these hold:
- It maps to exactly one lane (`TRADEAI_LANE` tag, else exactly one registry match).
- That lane has an effect key.
- Its family is §23.25-approved: not F07, not registry_systemd, not DEFERRED-I2. F09 is held for CD6 unless `--include-f09` is passed.
- It is not already wrapped.
- Its shape is certain: `cd $PROJ && [VAR=v] [flock … LOCK | bash …/safe_flock.sh LOCK] CMD … [>> log] [# comment]`, with no unquoted `; | & ( )` and no backtick.
- An armed lane has an owner row.
- A lane n8n owns is relay-live.

The wrapper is inserted inside the lock:

```
… flock -n /tmp/x.lock env TRADEAI_EFFECT_CLAIM=<lane> bash scripts/effect_claim_cron.sh <lane> $PY scripts/x.py …
```

Every other byte, and every other line, is unchanged.

Read-only run against the live crontab, 2026-10-16:
- **46 wrapped.**
  - 22 lines of n8n-owned processes, all relay-live. After the apply these exit 0 with `skipped_effect`.
  - 24 lines of staged lanes (no owner row, `cron_claim` false). These run exactly as before, after one read-only owner lookup.
- **2 skipped:**
  - `maturity-remeasure` (`CUR=$(…) && cd "$CUR"`, a compound prefix);
  - `trade-ai-scalp-live` (F09, held for CD6).
- **288 out of scope:** 287 lines with no effect key, and 1 line whose `TRADEAI_LANE` tag is not in the registry.

## Commands

Dry run (agent or operator). It writes only the work dir under `~/.local/state/tradeai/backups/`:

```
bash docs/ops/packets/cron-effect-claim-wrap-20261016/apply.sh
```

Plan only, without the backup dir:

```
python3 docs/ops/packets/cron-effect-claim-wrap-20261016/plan.py            # table
python3 docs/ops/packets/cron-effect-claim-wrap-20261016/plan.py --json     # machine plan
```

Apply. **Operator only**: it needs an active `cron` grant whose reason names this packet, and the PR must be promoted first. Precondition P1 refuses to install while CURRENT still serves the old wrapper.

```
bash docs/ops/packets/cron-effect-claim-wrap-20261016/apply.sh --apply
```

`apply.sh` takes these steps:
1. Runs `crontab -l` and keeps a backup copy, `crontab.backup`.
2. Builds the candidate from that LIVE text.
3. Checks:
   - `diff` +/− count = planned count;
   - the line count is unchanged;
   - unwrap(candidate) == unwrap(live), byte-exact.
4. Checks the preconditions:
   - P1: CURRENT serves the 10-16 wrapper;
   - P2: an active cron grant;
   - P3: the crontab is unchanged since the plan.
5. Installs with `crontab -` and reads it back with `cmp`.

Verify after the apply:

```
tail -f ~/trade-ai-releases/portfolio-server/CURRENT/logs/effect_claim_events.jsonl
```

`skipped_effect` means n8n owns the lane. For an n8n-owned lane, there should be no new cron runs in the lane's own log.

Rollback. It removes only this packet's prefix from the LIVE crontab, so other edits are kept. Dry run by default:

```
bash docs/ops/packets/cron-effect-claim-wrap-20261016/rollback.sh            # dry run
bash docs/ops/packets/cron-effect-claim-wrap-20261016/rollback.sh --apply    # operator, cron grant
```

If nothing else changed since the apply, the full restore is `crontab - < <work dir>/crontab.backup`.

## Tests

`tests/test_cron_effect_claim_wrap_20261016.py` is registered as the `cron_effect_claim_wrap_20261016` gate in
`scripts/run_cio_hardening_ci.py`. It covers:
- wrapper semantics;
- `owner` and `--decision-out`;
- plan mapping on a fixture crontab, with every skip reason;
- byte preservation and unwrap;
- a wrapped line run end to end by bash;
- `apply.sh` and `rollback.sh` against a fake `crontab`, including the byte-exact read-back.

`tests/test_canary_effect_keys_20261015.py`: owner n8n is now exit 0 with `skipped_effect` (was 75).
