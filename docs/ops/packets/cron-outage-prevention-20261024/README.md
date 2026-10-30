# Cron outage prevention: source review and operator packet

Status: source candidate only. Both `config/release_wrapper_preflight.json`
and `config/cron_outage_watchdog.json` are disabled with review pending and no
invented approver. No host cron, unit, release, alert, broker or credential has
been changed by this package. Worker commits locally; the operator owns remote
publication, protected-source merge, installation and release.

## Activation (2026-10-25)

Operator directive 2026-10-25: "turn on everything... It shouldn't need me to turn on anything." The watchdog
(item 6) is admitted: `config/cron_outage_watchdog.json` is `enabled`/`REVIEWED`, lane `cron-outage-watchdog`
is registered (systemd, `tradeai-cron-outage-watchdog.timer`, every minute, receipt
`data/runtime/cron_outage_watchdog_latest.json`), and the release installs it: `cio_phase2_exact_main_deploy.sh
promote` runs `scripts/install_staged_units.py apply` over `config/staged_user_units.json` (dry-run first, the
one-time rl3 refusal ack, archive-on-replace, `enable --now`, first run, is-active + receipt readback; receipt
`data/runtime/staged_units_install_latest.json`). Preview with `cio_phase2_exact_main_deploy.sh units`; undo with
`scripts/install_staged_units.py rollback --release <CURRENT>`. It is a host timer, not n8n, by design: the alert
path must not depend on what it watches. Item 5 (wrapper preflight) stays pending.

## Review in order

1. Read the [incident report](../../incidents/INCIDENT_20261023_SAFE_FLOCK_CRON_OUTAGE.md),
   [wrapper inventory](wrapper-inventory.json) and [historical replay](historical-replay-summary.json).
   The seven generic protocols have isolated proof. 24 captured shell paths have
   no approved safe no-op protocol; they are deliberately unexecuted.
2. Resolve each inventory gap through a separately authorized engineering scope.
   In particular, `scripts/run_broker_proposal_curator.sh`,
   `scripts/run_broker_queue_autocal.sh` and `scripts/run_protection_pipeline.sh`
   require a named execution-engineering source grant before their code can be
   changed or tested against. No command here probes those producers or grants
   broker authority. Network/business entrypoints, external bin wrappers and
   daemon-restart launchers also remain held until an explicit safe protocol is
   reviewed. Never use ordinary execution, import or `--help` as a guessed no-op.
3. Review the 27 component bindings against the actual accepted registry and a
   fresh authorized scheduler capture. A stale or unavailable capture is not
   proof of the current host. Registry expression/match changes invalidate a
   binding. Unsupported systemd monotonic anchors, event schedules and absent
   success markers remain visible coverage gaps; they are not fixed by a log
   mtime or by multiplying the weekend-adjusted cadence.
4. Operator-only preview against the real layout, after admission authority and
   the cron-read grant are present:

   ```bash
   .venv/bin/python scripts/release_wrapper_preflight.py \
     --current "$HOME/trade-ai-releases/portfolio-server/CURRENT" \
     --captured-cron /path/to/operator-approved-crontab-capture.txt \
     --output /path/to/private-wrapper-preflight.json
   ```

   This is inspection only, runs safe true/no-op children and writes telemetry;
   it does not run any business producer. Quote the output before activation.
   Expect nonzero while coverage gaps exist. Native `--enforce` collects one
   fresh read-only crontab census, never retries a refused read through another
   path, and fails on unknown wrappers. That adds an explicit read dependency;
   no credentials are introduced.
5. Review and commit the exact source/config revision. Only when every required
   wrapper has a proven safe protocol may the operator change the release gate
   config to `review_status=REVIEWED`, name the real `approved_by`, and set
   `enabled=true`. The admitted post-promote hook then runs before pins/success;
   failure takes existing rollback and host P1. The train rejects stale, wrong
   SHA/path/config or inspection-only receipts. Disabling is explicitly reported
   PENDING_OPERATOR_ADMISSION, never represented as wrapper proof.
6. The independent watchdog can be reviewed separately, retaining all coverage
   warnings. Only the operator may mark its config reviewed/enabled, add its
   registry/catalogue admission and install/enable the two source unit files.
   This unit bypasses safe_flock, incident_notifier and n8n; sends go through the
   existing host P1 Telegram chokepoint. Observe a natural timer run, Health
   readback, successful delivery receipt and recovery before calling it live.

## Proposed registry admission (not operative)

The source timer is staged under `ops/systemd/tradeai-cron-outage-watchdog.*`.
It must be registered before installation. Suggested row: lane
`cron-outage-watchdog`, owner requires operator confirmation, scheduler kind
systemd / expression `tradeai-cron-outage-watchdog.timer`, cadence one minute,
initial state NEVER_SCHEDULED, output `data/runtime/cron_outage_watchdog_latest.json`.
Activation/state/owner review is not fabricated here. The latest JSON contains
the actual observation clock, lane gaps, active/refused events and delivery
outcome; old/future/dry-run reports make the Health row UNKNOWN.

The watchdog only reads declared nonsecret data/log receipt paths and wrapper
events (including timestamped stderr fallback from declared logs); it never queries a broker, DB, provider, crontab or systemctl. A receipt
write or delivery failure cannot become a successful alert. Actual notification
delivery is recorded separately from accepted/queued status. Saved trigger
decisions, orders, stops and scheduled authorities are untouched.

## Reproduce isolated proofs

```bash
PYTHONPATH=/home/johnclaw/.cache/rtc/nopg /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python -m pytest -q \
  tests/test_cron_outage_prevention_20261024.py tests/test_safe_flock_os_lock.py \
  tests/test_platform_health_20261021.py tests/test_release_window_20261016.py \
  tests/test_cio_deploy_receipt_truth_20261018.py
python3 scripts/check_test_host_paths.py --fail-on-new
python3 scripts/check_test_coverage.py --fail-on-new
```

Use an owned neutral TMPDIR (not a `/tests/` segment). Every file/process effect
in the fixture proof is confined to that fixture, with fake control effects and
a mocked Telegram chokepoint. No production `.env`, host units, live HTTP,
orders, provider or broker source is reached. Raw production logs/commands are
never committed; source hashes/windows and a redacted replay summary preserve
the evidence boundary.

PR metadata must start `[shared-infra]` and contain a `Real-layout proof:` line
naming the actual command/artifact. Coordinator reviews this source separately
and excludes it from mixed batches. The new workflow adds no required context
or branch-protection change. There is no push, merge, installation or release
command to run automatically from this packet.

A missing/unreadable wrapper journal is an independent monitor-blindness incident. Its repeated delivery is suppressed by the existing finding/reminder state; actual recovery sends a coverage-restored notice without claiming any business process recovered. No success timestamp or missing-fire count is invented.

## Local verification

The stable scoped/native profile passed 347 tests, including release train/controller, release-window, exact deploy-receipt functions, allowlist, wrapper linters and both real-tree completeness tests. The review then added independent input-blindness incident/recovery: 96 affected tests passed on those final three changed files. These overlapping profiles are not added together and are not full-project CI. Twelve source checks passed; registry/contracts/allowlist/authority file hashes were unchanged. See `source-verification.json` for tested file hashes and private receipt pointers. Native installation, operator admission, remote required checks and live delivery remain pending.
