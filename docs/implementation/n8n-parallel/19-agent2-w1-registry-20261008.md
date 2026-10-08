# Agent 2 W1 — registry and safe run contracts

Status: W1 source validated; updated-main acceptance and supervisor review pending.
Owner: platform (Agent 2; Agent A reviews).
as_of: 2026-10-08.
Measured at: original W1 head `5e78c00811f8850086019d692543f0b1324c8f09`.
Measured: 2026-10-08. Base: main `72b0ce6bec79dcdae46323643209154105479c76`.
Authority: registry metadata, code, tests and PR only. No schedule cutover,
service installation, workflow import, merge, deployment or trading.

## Before and after

| Capability | Before | After this change |
|---|---|---|
| N3/N4/N5 missing lane rows | 21 | 0; observed cron expressions, source citations and output limitations recorded |
| Native N1 monitor rows | 0 | 2; exported legacy IDs recorded, not uninstalled replacement IDs |
| Repository-owned write-nothing jobs | No durable per-run receipt | Four entrypoints accept `--receipt PATH`, with a persistent-state default |
| Daily analyst report | Dated output files only | Stable per-run receipt, retaining the existing JSON-writing dry-run behaviour |
| Additional runnable allowlist contracts | 0 | 7; N3: 2, N4: 5, N5: 0 |
| Remaining N3/N4/N5 candidates | Undifferentiated pending lists | 31 individually documented blocking reasons; never-list unchanged |

The seven contracts are daily analyst digest, desk suggestions, job coverage,
catalyst calibration monitor, source attribution monitor, watch directives
monitor, and Finviz view contracts. An allowlist entry is not permission to
activate its workflow. Null dry-run arguments mean shadow mode is unavailable.

## Receipt semantics

`scripts/lib/scheduled_job_receipt.py` wraps the existing main function without
changing its argument parsing, return value or exit code. The default is
`$TRADEAI_STATE_ROOT/data/runtime/<script>_last.json`, using the canonical
persistent-state resolver when that environment variable is absent. Writes are
atomic. `--help` does not create a run receipt.

The envelope is `ScheduledJobReceipt@v1`: `as_of`, `exit`, and a bounded `summary`.
It records a completed or failed invocation, not proof of successful delivery,
investment value, or notification receipt. Exception text, stdout, credentials
and model output are excluded. Failed runs have nonzero `exit`; consumers must
inspect it, not interpret file freshness alone as success. A receipt-write error
fails the invocation and preserves the prior receipt rather than claiming proof.

Entrypoints changed: alert daily digest, desk suggestions, job coverage,
YouTube cookie health, daily analyst report. Their pre-existing sending and
database behaviour is unchanged; sender-bearing jobs remain outside the run
allowlist. Desk suggestions retains its original CRLF bytes outside the edit.

## Safety conflicts and dependencies

1. The real Ops scripts are external OpenClaw skill files:
   `~/.openclaw/skills/tradeai-health-inspect/scripts/ops_daily_digest.py` and
   `ops_weekly_learning_report.py`. They print and send; they do not produce a
   durable job receipt. No unrelated external files are copied or modified.
   Their receipt implementation needs the supervisor's external-skill owner.
2. Sender, retention, remote-delete, and Git-write jobs cannot be made runnable
   under AGENTS section 23.3 by merely listing their commands. All N5 candidates
   remain pending: Drive prune, Git backup/commit, and already-retired lab
   backup/restore need separately reviewed safe contracts or remain excluded.
3. Desk suggestions, job coverage, and Finviz view contracts have no shared
   cron/unit lock today. The executor locks are declared, but overlap equivalence
   is NOT proven. The operator must establish a shared lock or stop the legacy
   schedule before live canary. This PR does neither.
4. Calibration, attribution and watch-directive dry-runs do not append monitor
   history. Daily analyst dry-run does write report JSON. These semantics are
   preserved and cannot be described as a universal write-nothing shadow mode.
5. Ten added rows explicitly declare NO_SIGNAL: the two native monitors, both
   external Ops digests, rotation digest, dashboard crawl, missing conditions,
   generated-doc backup, memory-to-Drive, and Hermes commit. Other existing
   signal weaknesses are documented in their row notes (conditional health
   records and coarse directory mtimes). There is no invented success file.
6. Native monitor state is observed from the dated workflow export, not a new
   live n8n query. The IDs are `s57KBllvqf6Jb5xF` and `GXwhbRkwsGcYZxgn`.
   Generated replacements are `e10e7c19321c906a` and `e10087387b964e87`.
   The operator deactivates, never deletes, legacy workflows before import.
   Until a host consumer receipt exists, registration is not health proof.
7. Weekly governance activation is queued behind W1/W2 per the board. Its
   NEVER_SCHEDULED row is intentionally not flipped without a canary receipt.

## Validation evidence

Initial scoped suite: **85 passed** (before adding the native-monitor test).
The next scoped run found one obsolete schema-only test asserting there were no
n8n rows. That assertion is updated to permit exactly the two observed native
monitors, retaining the prohibition against host-scheduler cutovers.
Final original scoped suite: **86 passed in 6.92s**. Full local acceptance on
`5e78c00811f8850086019d692543f0b1324c8f09`: **exit 0**, observed 12:37 EDT,
17/17 release steps passed and all registered CIO gates passed. The initial run
stopped at release readiness (16/17 release
steps passed) because its filename-based hygiene classifier rejects an
uncommitted `youtube_cookie_health_check.py` edit as sensitive. The direct
readiness rerun confirmed no other failing validator. No gate is bypassed:
the reviewed source was committed locally and acceptance rerun before push.

- Dark contracts: zero new unexplained or uncompilable modules.
- Test coverage registration: zero new unlisted tests; `N8N_AGENT2_W1` GATES anchor.
- Test host paths: zero new violations.
- Live read-only registry gate with `--fail-on-new --state-drift`: exit 0,
  231 declared lanes, 174 ACTIVE, zero structural errors, zero NEW,
  zero conflicts; four existing NOT_MEASURED lanes remain explicit.
- Live read-only systemd commands confirmed `--alert` for expected services,
  served-copy split, data-source health, data plausibility, gap resolution and
  operator-answer quality. Finviz view contracts has no alert flag or lock.
- Tests isolate source boundaries: no real sender, provider, broker, cookie,
  or live application database is exercised.

## Handoff acceptance

Branch-update candidate, 2026-10-08: GitHub later reported this PR CONFLICTING
with main. A local merge of main `443774e2197feeff2d254d77f372304ba1035b7b`
has no unresolved code conflicts; the repository's generated-file driver keeps
the local docs index and requires regeneration. Main's changes, including its
new registry rows and GATES entries, are retained. No history rewrite or
force-push is used. The docs index is regenerated after staging this update.
Scoped and full acceptance must be rerun on the resulting committed candidate
before its one remaining corrective push. This does not merge the PR, install
a service, activate a workflow, or release the W2 registry lock.

Updated-main scoped regression: **96 passed in 15.58s**, including the newly
merged lane-monitor rendering and migration-board suites. New-file Ruff,
coverage and host-path gates pass. Our diff against main has no whitespace
errors; a whole-merge staged check reports existing generated Markdown hard
line-break whitespace from main, which is preserved rather than edited.

Supervisor review must resolve or explicitly accept the receipt, lock and
never-list limitations before activation. These are not a declaration that
every tranche is ready. W2 branches on W1 only after W1's PR is open and follows
the single-registry-PR lock. Push budget: two, including review corrections.
