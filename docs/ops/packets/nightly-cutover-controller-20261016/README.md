# Nightly cutover controller 2026-10-16: an enforced state machine for the approved n8n cutover

```
Status:     DISARMED (no grant names it; registry row PAUSED; no dispatch block; no workflow imported)
as_of:      2026-10-16
Authority:  operator, in writing, 2026-10-16: "building, testing and operating a bounded nightly automatic cutover
            process for the already approved migration scope, including the necessary controlled crontab edits";
            AGENTS.md 12.0.0 §23.25
Owner:      Agent A (Chief Architect), operator-approved
```

## What it is

The controller is `scripts/nightly_cutover_controller.py`, registered as lane `nightly-cutover-controller`.

- **Evaluator.** `scripts/lib/nightly_cutover.py` is the only evaluator. It serves `plan`, `--dry-run` and `--apply`. `--apply` gathers the world again and evaluates it again itself; it never reads an earlier plan.
- **Crontab edits.** These go through a narrow host capability, `scripts/nightly_cutover_cron_edit.py`. It can only:
  - comment the lines that the plan names for one lane;
  - uncomment lines from a rollback receipt.
- **Config.** `config/nightly_cutover_controller.json` holds the cap (`max_lanes_per_night`, default 5), the proof age, the forced-canary policy, the downstream evidence per sender lane, the registry root and the grant token.

## Per-lane states

A lane moves through these states in order. A failed check moves the lane to `held:<reason>`.

| State | What must hold |
|---|---|
| candidate | The lane is in the §23.25 cohort. It is **not**: an F07 lane, a `registry_systemd` lane, one of the four holds, or an unknown family. Its registry row is an ACTIVE cron row at stage canary with `dispatch.mode` live. Its retire lines are exact. |
| evidence_ok | **Versions agree:** the CURRENT `GIT_SHA` equals the run's `code_sha`; the allowlist and health-contract versions (sha16) equal the run's `policy` block; the n8n workflow graph hash, live, equals the git copy in CURRENT; the registry-root row equals the CURRENT row; the lane is relay-live; the health contract is REVIEWED at stage canary. **Qualifying live run:** state RUN_DONE, exit 0, not stage-clamped, not lock-skipped, receipt from this attempt, `output_verdict` either `produced` or `empty_allowed`, and no older than 72 h. Sender lanes also need downstream evidence. F09 lanes need a natural `d:` slot. P1 lanes need **one completed NYSE session** after a valid proof. |
| protected | Append, send and LLM lanes need: an effect key with `n8n_claim` true; ledger owner `n8n`; and on **every remaining live crontab line** for the lane, the served wrapper with the 10-16 semantics plus the exact `env TRADEAI_EFFECT_CLAIM=<lane> bash scripts/effect_claim_cron.sh <lane>` switch. |
| drained | No in-flight run. An old in-flight run is named separately as `stale_in_flight_run`. No CLAIMED or UNKNOWN effect claim; these are never auto-released. |
| applied | (apply only) The lines were commented under `flock /tmp/n8n_cutover.lock`, with the crontab sha256 equal to the evaluated one. Also: a 0600 backup exists, the read-back is byte-exact, and ownership checks out. |
| reconciled | (apply only) In the registry root: the registry row became the §23.11 dispatcher row; the health contract moved to stage cutover, with the canary binding that counted a cron-twin lock skip as healthy rewritten; the per-lane rollback receipt was written. |

**Cohort STOP.** Any of these stops the whole run, with exit code 2:
- the ledger, CURRENT, crontab, registry, allowlist, policy or n8n workflow inventory cannot be read;
- CURRENT changes mid-run;
- a crontab lock or hash check fails;
- a registry write fails.

A lane that was already applied when the stop came is rolled back first.

**Summary.** After an apply, at most one summary line goes out through `send_telegram(priority="P3")`, which routes to the digest.

**Forced canaries.** These run only in apply. For a lane held only because it has no qualifying run, the controller sends one dry run, then one live run, through the gateway's `host_run_request` (`coordination/run`), and the stage clamp applies. Two kinds of lane never get one:
- F09 lanes, which take natural proof only;
- lanes with an n8n-armed effect key, whose live run needs the dispatcher's slot key.

## P1 fix

The old `n8n_cutover_wave.p1_overlap_problems` counted any trading **date** after the proof. So crossing midnight counted as a session. It also used the federal holiday table, which closes on Columbus Day and Veterans Day and opens on Good Friday.

The new rule is `completed_sessions_after(proof, now)`. It counts a session only if the session opened after the proof and has closed by now. It uses `cio_market_session.nyse_holidays` and `nyse_early_closes`, so early closes at 13:00 count. Tests cover both bugs.

## Arming (operator / Agent A)

```
bin/guard grant cron --for 14h --uses 20 --reason "nightly-cutover-controller: arm the nightly n8n cutover controller (PR #<N> sha <head>), AGENTS §23.25; comment-only edits of planned lines, cap 5/night"
```

The controller reads the grant ledger read-only and never consumes a use. To disarm, revoke the grant: `bin/guard revoke cron`.

For n8n to trigger the controller, a registry PR must add a dispatch block and set `state: ACTIVE`. Without that PR, the operator runs it by hand:

```
cd ~/trade-ai-releases/portfolio-server/CURRENT && .venv/bin/python scripts/nightly_cutover_controller.py --dry-run
cd ~/trade-ai-releases/portfolio-server/CURRENT && .venv/bin/python scripts/nightly_cutover_controller.py --apply
.venv/bin/python scripts/nightly_cutover_controller.py rollback --receipt <state>/data/runtime/nightly_cutover/rollback/<lane>-<ts>.json
```

## Policy amendment (proposed; not edited into AGENTS.md by this PR)

A recurring automated crontab edit is a standing host-crontab act (§0 rule 7, §17, §23.12). The proposed minimal amendment is a MINOR version (adds a bounded authority under an existing directive; §0, §2, §2A, §7A, §17 and §22 stay byte-identical). Its text, as one §23.25 bullet:

> **Nightly cutover controller (12.1.0).** Under the operator's written approval of 2026-10-16, the host lane `nightly-cutover-controller` may comment (never delete) the primary crontab line of at most `max_lanes_per_night` §23.25 lanes per night. It may do so only while an active `cron` grant names `nightly-cutover-controller`, and only for a lane its single evaluator has taken through candidate, evidence_ok, protected and drained. The edit is made by `scripts/nightly_cutover_cron_edit.py` alone, under the cutover lock, with hash, backup, byte-exact read-back and a per-lane rollback receipt. n8n may only trigger the lane; it gets no shell and no control-file authority. The edit grants no broker, order, secret, systemd or §17 authority.

Approval phrase (§20): `APPROVE_AGENTS_POLICY_12_1_0 <pr_number> <head_sha>`.
