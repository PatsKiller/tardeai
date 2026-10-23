# Ops → Controls: one operator surface, one governed host applier

```
Status:      DRAFT (branch feat/ops-controls-20261022). Built INERT: refuses every change until AGENTS.md 19.0.0 is
             ACTIVE and the operator has applied the migration, installed the applier and enrolled a passkey.
as_of:       2026-10-22T22:30:00-04:00 (§9 Data approvals readiness added; previous 2026-10-22T22:00:00-04:00)
Measured at: hermetic tests only (tests/test_ops_controls_20261022.py, tests/test_ops_controls_pg_webauthn_20261022.py);
             nothing ran against the live server, database, crontab, live list or guard ledger
Owner:       platform
Authority:   OPERATOR_ONLY · MBI_BEHAVIOR = 0
Policy:      AGENTS.md 19.0.0 §27.2–§27.4 (PROPOSED; package built 2026-10-22, operator applies and commits it)
Operator decisions (2026-10-22): all ops configuration editable from a CC Ops page ("hands-on keyboard for nothing
             that has to edit files"); settings in a Postgres operator_settings table with history that overrides repo
             defaults; one governed host applier (backup, audit, undo) for crontab, n8n live list, settings and grants;
             agents may never call these endpoints; safe direction one click; risky direction a WebAuthn passkey
             (several named devices, revocable, add/remove needs an existing passkey) plus a typed phrase; TOTP
             recovery only; Telegram notification only.
API contract: docs/ops/OPS_CONTROLS_API.md
```

## 1. What it is

The Command Center page **System → Ops Controls** (`/v3/system/ops-controls`) shows six tabs from the mockup — Jobs &
schedules, n8n lanes, Flags & thresholds, Data approvals, Grants, Audit & undo — plus a Passkeys panel. Every row is
read from the real source (lane registry + `crontab -l`, the relay live-list file, `operator_settings`, `bin/guard
show`, `config/data_source_authority.json` proposed rows, the release-train control state, the append-only audit).

Every change goes through three steps: **(1) preview** (the server's dry run: exact before/after, warnings, the
target-state digest), **(2) authenticate** (risky direction only: passkey with user verification + the typed phrase
the server shows), **(3) apply** (the host applier re-plans, refuses if the target moved, backs up, applies, verifies,
audits and offers an undo). The safe direction (release-train STOP or pause, kill-switch engage) is one click.

## 2. Components

| Part | File | Role |
|---|---|---|
| Policy gate, change kinds, preview/apply/undo | `scripts/lib/ops_controls_core.py` | `policy_state()` reads `AGENTS.md` at call time: ACTIVE only if the 19.0.0 history row is ACTIVE and §27.3 exists. No env override. |
| Routes | `scripts/lib/ops_controls_api.py`, wired in `scripts/api_v2.py` | Records and authorises requests. Applies no host change itself (except the release-train STOP/pause writers and the passkey store). |
| Factors | `scripts/lib/ops_controls_auth.py` | py_webauthn (`webauthn`) registration and assertion, `userVerification: required`, RP id `ms01-openclaw.tail163d14.ts.net`; pyotp TOTP (recovery only); step-up tokens; approval HMAC. |
| Stores | `scripts/lib/ops_controls_store.py` | `PgStore` (production) and `MemoryStore` (tests), one interface. |
| Migration | `migrations/2026_10_22_ops_controls.sql` (+ `.down.sql`) | 7 tables, refuse-delete triggers, append-only `ops_audit` and `operator_settings_history`. Not applied. |
| Plan tool | `scripts/ops/ops_controls_migration_plan.py` | Dry run of the migration (`--probe`: read-only existence check). |
| Host applier | `scripts/ops/operator_controls_applier.py` | The only writer of host state: `serve`, `preview`, `status`, `init-hmac-key`, `totp-enroll`. |
| Unit | `config/systemd/user/tradeai-ops-applier.service` | Not installed (§17). |
| Config | `config/ops_controls.json` | RP id and origin, TTLs, file paths (secrets by path only), live-list units, guard path, settings catalog. |
| Page | `apps/command-center-v3/src/pages/OpsControls.tsx`, `src/lib/opsControls.ts` | The surface; disables every action while policy is not ACTIVE. |

## 3. Threat model and the controls that answer it

- **An agent calls the endpoints.** The actor is server-derived: only `tailnet:<login>` on the `serve_proxy` listener
  with the login in `config/cc_auth.yaml` `allowed_logins` is answered. The service token (`service-token`: cron,
  agents, n8n) is refused on every route (`AGENT_CALLER_REFUSED`, audited). A body field never names the actor.
- **A forged browser request (CSRF).** `config/cc_auth.yaml` lists `/api/v2/ops/controls(/.*)?` as a hard CSRF route,
  and the handler re-checks same-origin itself (`cc_auth.command_csrf_check`) whatever `report_only` says.
- **An agent with database access writes an APPROVED row.** The applier applies only rows whose approval carries an
  HMAC-SHA256 signature made with a key in a 0600 file outside the repository (`~/.config/tradeai/
  ops_controls_hmac.key`, read only by the Command Center process and the applier; §24.7 forbids agents reading it).
  Editing the params of a signed row breaks the signature (`SIGNATURE_INVALID`, audited).
- **A replayed or stale authentication.** WebAuthn challenges are single use, bound to one request and purpose, and
  expire in 120 s; the passkey sign counter is compare-and-set; the step-up token is single use, bound to its request
  and expires in 120 s; the applier refuses an approval older than 120 s.
- **The target moved between preview and apply.** The preview stores a digest of the target (whole crontab text,
  live-list file, setting value, grant id); the applier re-plans and refuses `STATE_CHANGED` on any difference.
- **A bad change.** Every applied change keeps a backup (crontab copy and live-list `*.bak-<UTC>-ops-<request>` at 0600,
  the guard ledger copy, the settings history row) and an undo request that goes through the same factors as any
  change in its direction. Nothing auto-remediates (§0 rule 5).
- **Losing every passkey.** TOTP (Google Authenticator) may register a passkey only when none is active; it is never
  a factor for a risky act. Its secret is a 0600 file, not a database column.

## 4. Change kinds

See the table in `docs/ops/OPS_CONTROLS_API.md` §5. Safe: `release_train.stop`, `release_train.pause`,
`kill_switch.engage`. Risky: every crontab, live-list, setting, grant and passkey change.

**Not supported, with the reason shown on the page:**

- **`kill_switch.clear`:** its path is broker-execution code (`scripts/brokers/kill_switches.py --disable`). Calling or
  testing it from the applier needs an `execution-engineering` grant (§0 rule 2, §27.4). Engage only runs the existing
  CLI as a subprocess. Neither path's code is modified by the applier.
  *2026-10-22 (execution-engineering grant e88bf21e, `KILL_SWITCH_DISABLE_AUDIT_20261022`):* the operator CLI's
  `--disable` raised `TypeError` on every correctly-confirmed phrase (`_audit()` keyword mismatch, present since
  2026-06-26) and is fixed. Enable and disable now write the state row and the audit row in one transaction that
  rolls back on any failure, and the CLI exits 1 when a change is refused or fails, so an engage that did not apply
  reports `FAILED`, not `APPLIED`.
- **`release_train.resume` / `.arm` / `.change_scope` / `.revoke`:** `release_control.OPERATOR_KINDS` is pinned to
  the D3 host-CLI and Telegram proofs by `tests/test_agents_policy_17_0_0_release_train.py`. Adding a passkey proof
  kind is its own reviewed PR after 19.0.0 is ACTIVE. Until then the host CLI is the path
  (`scripts/release_control_cli.py`).
- **Data approvals (registry rows):** these are a reviewed PR to `config/data_source_authority.json` (§26.6). The tab
  is read-only. It shows each row's readiness for that decision (§9); it never approves one.

The settings catalog (`config/ops_controls.json` `settings_catalog`) starts with two keys, both `wired: false`: the
value is stored and shown, but no consumer reads `operator_settings` yet. Wiring each consumer is its own PR.

## 5. Data dictionary coordination

The AGENTS 19.0.0 package proposes the §26 registry row `operator_settings` (writer target
`scripts/ops/operator_controls_applier.py`, the file this branch ships). This branch does **not** edit
`config/data_source_authority.json` or `docs/architecture/DATA_DICTIONARY.md`. The package's digest check requires
those files to be byte-identical to its base, so editing them here would force a rebuild of the package. The other
six tables (`operator_settings_history`, `ops_audit`, `ops_applier_requests`, `ops_webauthn_challenges`,
`webauthn_credentials`, `totp_recovery`) are the same store's history, audit and auth state. They are named in the
migration and covered by the same §17 grant. If the operator wants separate rows, they are a follow-up PR after the
package merges.

## 6. Activation (operator only, in order)

Nothing below is done by an agent. Each step that writes durable state has its dry run first (§0 rule 7).

1. **Ratify AGENTS.md 19.0.0** (package `agents-19/`: `apply19-operator.sh`, then the approval token, then
   `ratify19-operator.sh`) and merge it. Until the served release's `AGENTS.md` carries the 19.0.0 row as ACTIVE,
   every POST answers `POLICY_NOT_ACTIVE`.
2. **Merge and promote this branch** through the release train or the manual path.
3. **Install the libraries** into the serving venv: `webauthn==2.7.0` and `pyotp==2.9.0`. Under a `deps` grant, pin
   them in `requirements.txt`/`requirements.lock.txt` in a follow-up PR. Until then the passkey and TOTP routes answer
   `DEPENDENCY_MISSING`.
4. **Migration:**
   - Dry run: `.venv/bin/python scripts/ops/ops_controls_migration_plan.py --probe`.
   - Apply: `psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_22_ops_controls.sql`.
   - Verify: `GET /api/v2/ops/controls/state` shows `store.state = "OK"`.
5. **Approval key:** run `scripts/ops/operator_controls_applier.py init-hmac-key` at a TTY. It creates
   `~/.config/tradeai/ops_controls_hmac.key` at 0600. Then restart `portfolio-server`.
6. **Applier unit:**
   - Dry run: `scripts/ops/operator_controls_applier.py status` and
     `scripts/ops/operator_controls_applier.py preview --kind n8n_live_list.add --params '{"lane_id":"<lane>"}'`.
   - Install: follow the header of `config/systemd/user/tradeai-ops-applier.service` (`install -m 0644 …`,
     `daemon-reload`, `enable --now`).
   - Verify: the page's applier banner reads OK (heartbeat under 60 s).
7. **TOTP recovery:** run `scripts/ops/operator_controls_applier.py totp-enroll --label "Pixel"` at a TTY. Scan the
   printed `otpauth://` URI into Google Authenticator. It is shown once.
8. **First passkey:** on the page, Passkeys → Add passkey → name it. Authenticate with the TOTP code and the typed
   phrase, then create the passkey on the device. Add further devices (laptop, phone) the same way, each
   authenticated with an existing passkey.
9. **Smoke test:**
   - Safe: one-click release-train **Pause**. Check the audit row and the Telegram digest notice.
   - Risky: a `setting.set` on a `wired: false` key, then its undo.

**Rollback:** stop and disable `tradeai-ops-applier.service`. Run `migrations/2026_10_22_ops_controls.down.sql`; it
archives by rename and never drops. Revert the PR. Applied host changes are restored from their backups (paths in the
request results and the audit).

## 7. Telegram

The applier and the handler queue one host comms intent per change (`config/host_comms_intent_routes.json`: domain
`host`, kind `ops_controls_change`, producer `ops_controls`, tier DIGEST). That is a notification and nothing else.
No Telegram button confirms anything. A failed notification is recorded in the audit row and never blocks or fakes
an action.

## 8. Reading the Jobs & schedules tab (UI, 2026-10-22)

Operator feedback 2026-10-22 on build `f7c1e96cb`: "I have no idea how to interpret this. Is this cron jobs that's
been retired, active? Is this actually N8N? There are no tooltips." The tab was reworked on branch
`feat/ops-controls-jobs-readability-20261022`. The rules live in `apps/command-center-v3/src/lib/opsControlsJobs.ts`
and are tested by `src/lib/opsControlsJobs.test.ts`, which runs in `npm run build`.

**What a row is.** Each row is one registry lane with `scheduler.kind == "cron"` (`config/lane_registry.json`), matched
to the live host crontab (`crontab -l`) by the registry's `scheduler.match` text (`jobs_view` in
`scripts/lib/ops_controls_api.py`). Lanes that n8n schedules are on the **n8n lanes** tab. A cron lane whose line was
removed at cut-over (crontab ABSENT, registry `dispatch.mode == "live"`) reads **"Runs on n8n (no crontab line)"**.

**Status column.** This column puts two facts into words: the live crontab state and the registry state. The raw
badges are still shown, with tooltips, in the **Crontab · registry** column.

| Crontab | Registry | Status shown | Needs attention |
|---|---|---|---|
| ACTIVE | ACTIVE | Running (adds "· n8n also dispatches it (live)" for a canary lane) | no |
| ACTIVE | RETIRED / PAUSED / NEVER_SCHEDULED | Running — but registry says it is … | **yes** |
| PAUSED | PAUSED | Paused since `<date>` (`<note>`) | no |
| PAUSED | ACTIVE | Paused since … — but registry says it should run | **yes** |
| PAUSED | RETIRED / NEVER_SCHEDULED | Retired — paused line still kept | no |
| ABSENT | RETIRED | Retired (off on purpose); collapsed by default | no |
| ABSENT | NEVER_SCHEDULED | Never scheduled (no line expected); collapsed by default | no |
| ABSENT | PAUSED | Paused in the registry (no crontab line at all) | no |
| ABSENT | ACTIVE, dispatch live | Runs on n8n (no crontab line) | no |
| ABSENT | ACTIVE, otherwise | Off — but registry says it should run | **yes** |
| AMBIGUOUS | any | read through `match_counts` as running or paused, with "· N matching cron lines"; the same agreement rules apply; no action is offered | as above |

Rows that need attention are pinned in a **Needs attention** box at the top of the tab, each with a one-line reason.
The tab has these filter chips, each with a count: All · Needs attention · Running · Paused · Retired · Broker jobs.
It also has a search box on the job name. Under All, retired and never-scheduled rows with no line are folded behind
a "Show N retired" button.

**Row detail.** Click a job name to open its row. The row shows the registry state, its date and reason, the n8n
dispatch mode, the matching-line counts, the paused date and reason, the broker tokens and the registry note. It also
shows the crontab line, with secrets redacted.

**Schedule.** The cron expression is shown in words beside the raw expression; for example, `7,22,37,52 9-16 * * 1-5`
reads "weekdays 09:07–16:52 every 15 min". Times are host time (ET). If an expression cannot be read with confidence,
only the raw form is shown.

**Action.** The server treats both `crontab.pause` and `crontab.resume` as **risky**. Each needs a dry-run preview,
then a passkey and the typed phrase `PAUSE CRON <job> <date>` or `RESUME CRON <job> <date>`. Then the applier backs
up the crontab, applies the change and offers an undo. The button label comes from the server's direction, so it reads
"Pause (passkey)". Pausing is the lower-risk direction, but it is not one click. The release train's Pause is a
different control, and that one is one click.

**"Host terminal"** means the page will not act on the row. That happens in three cases:

- Several lines match (AMBIGUOUS).
- There is no line.
- The paused line's note is more than one word.

`PAUSED_RE` takes one token as the note and re-installs the rest of the line verbatim. A line such as
`# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 31 9 * * 1-5 …` would therefore be re-installed as
`(incident SPCX) 31 9 …`, which is not a cron line. The page offers no Resume for such a line. This applies to all 15
paused lines on 2026-10-22.

**Additive server fields.** Each jobs row now also carries four fields, all for display only:

- `dispatch_mode`: the registry `dispatch.mode`.
- `registry_since`: the registry `state_since`.
- `registry_reason`: the registry `state_reason`, up to 200 characters.
- `match_counts`: `{active, paused}`.

An older server leaves these fields out. The page then falls back: AMBIGUOUS rows read "Several crontab lines match",
and a cut-over lane reads as "Off — but registry says it should run".

**n8n lanes tab.** Section 10 describes it. This tab has a one-line explainer and tooltips on Stage, Mode, On live
list, Workflow and Action. A lane fires for real only when its stage allows `live` and it is on the relay live list.

## 9. Reading the Data approvals tab (UI, 2026-10-22)

Operator feedback 2026-10-22: the tab listed 17 domains, all "proposed", with nothing else — "This is not a
dashboard." The tab was reworked on branch `feat/ops-controls-data-approvals-20261022`. The server is
`scripts/lib/data_domain_readiness.py`, tested hermetically by `tests/test_data_domain_readiness_20261022.py` (CI gate
`ops_controls_data_approvals_20261022`). The page model is `apps/command-center-v3/src/lib/opsControlsData.ts`, tested
by `src/lib/opsControlsData.test.ts`, which runs in `npm run build`. The first full readout is
`docs/ops/DATA_DOMAIN_APPROVAL_READINESS_2026-10-22.md`.

**What a row is.** Each row is one data-dictionary domain (`config/data_source_authority.json`): a `proposed_domains[]`
row, or an approved `domains[]` row that carries a dictionary block.

**Explainer (shown on the tab).** Proposed means the data flows today, but the one-store / one-writer rule for it is
not signed off yet. Approving a row makes the rule binding. The CI gate (`check_data_source_authority.py`) then fails
the build on a second writer, or on a page reading a copy above the ceilings measured at approval, instead of only
warning. Approval itself creates no table, moves no reader and changes no page; those are separate decisions (§26.6).
The tab does not claim more than that. The only runtime code that reads a grant today is `cio_prospect`'s dual-write
gate (`prospect_store_status()`), and the row's "What approving changes" list says so.

**Summary strip.** Four counts, each with a tooltip:

- **Approved**
- **Ready to approve**
- **Not ready**
- **Findings** — live checker results; warnings for proposed rows, failures for approved ones.

Under the strip:

- A line names any row the operator has approved whose promotion PR has not merged yet, from
  `config/data_domain_approval_notes.json`. That file is display only and no gate reads it. Today it holds
  `cio_prospect`, approval E.
- Filter chips: All · Ready to approve · Not ready · Approved · With findings.
- Rows are ordered not-ready first.

**Verdict.** The server promotes each proposed row in memory with the ceilings measured now, exactly as
`data_dictionary.promote` would, and runs the real gates on it:

- `validate`
- `check_domains`: writer, projection
- `evaluate`: second writer, non-authoritative read
- `check_readers`: gated-store readers

It also checks the §26.2 rule that a row naming one writer has no other writer. **Ready to approve** means all of
these pass. **Not ready** lists each failing check, in the gate's own words. **Approved** means the row is in
`domains[]`. A row the operator approved whose PR is pending reads "Approved by operator · PR pending", never
"Approved".

**Row detail (Details).**

- The decision asked, and the readiness checks: pass or missing, with the source of each check in its tooltip.
- Store, writer, and the files that write the store today. The list is capped at 12; the count is always whole.
- Read path (projection), the pages declared as readers, and the files that read the store.
- Reader gate and approved reader batches.
- Freshness, refresh lane, derived copies, supersedes, and the approval record.
- The live findings, and what approving changes.

**Freshness.** For a file store it is the file's modification time under `served_from.root`. For a table it is
`max(column)`, but only when `data_dictionary.facts` declares a time column (`*_at` or `as_of`). This runs in a
read-only transaction with a 2 s statement timeout. Where the declared column does not exist, the tab says so ("Declared
time column not found"). Freshness is evidence, not a readiness check.

**Cost and bounds.** One background scan runs at most once per 60 s. It takes about 25 s on this host, most of it the
reader-gate scan. `GET /state` never waits for it: until the first scan finishes, rows show the registry facts with
"Checking…". A failed scan reads FAILED and shows no verdict.

The dictionary scan got an exact pre-filter in `data_dictionary.writer_files` / `reader_files`. The CI gate shares that
scan, so it is faster too. On 2026-10-22 `evaluate` took 39 s before the pre-filter and 3.8 s after. The measurements
were identical, and a test checks them against the bare regex.

## 10. Reading the n8n lanes tab (dashboard, 2026-10-22)

The operator's feedback on 2026-10-22: "Why do some of these say live? Some of them say dry runs. I don't know if the
last one was success or failure. This is not a real dashboard... When is everything going live?" The tab used to show
configuration only. Each row now also carries what the lane actually did and whether it may climb the ladder.

The server function `n8n_view` adds two blocks to each row, `outcome` and `readiness`, plus a section-level `summary`.
They come from `scripts/lib/ops_controls_n8n_outcomes.py`, and the contract is in `OPS_CONTROLS_API.md`. The module
reads the following, all read-only:

- **The n8n coordination ledger.** The path is `n8n_ledger.file` in `config/ops_controls.json`. It is opened with
  sqlite `mode=ro` and `PRAGMA query_only`. Tables read: `run_outcomes`, `runs`, `dead_letters` and `breakers`.
- **The registry, the run allowlist and the health contracts.**
- **The cutover policy, the effect keys and the disposition CSV.** These are the same inputs as
  `n8n_cutover_wave.py`.
- **The relay live list and `crontab -l`.**

**Bounded reads.** Every ledger query is per lane and uses an index: `run_outcomes_lane`, `runs_lane_state`, the `runs`
primary key, or `dead_letters_lane`. Older history is walked newest-first, at most 500 rows per lane. History from
before the run-outcome callback (2026-10-15) is found by run-key prefix (`d:`, `f:` and `e:`). No query scans a whole
table: `tests/test_ops_controls_n8n_outcomes_20261022.py` checks every query's `EXPLAIN QUERY PLAN`. The result is
cached for 60 s per process. On the host on 2026-10-22 one computation took 0.23 s for 120 lanes, and the process
peaked at 40 MB RSS.

**Summary strip.** Click a tile to filter the table.

| Tile | Counts |
|---|---|
| Live & healthy | Lanes whose fires are real today (effective mode `live`) with health OK. |
| Live & failing | Live lanes with health FAILING or STALE. |
| Rehearsing (shadow) | Lanes whose fires are dry runs today: shadow lanes, and canary lanes that are not on the live list. |
| Ready to promote | Lanes with readiness READY_FOR_CANARY or READY_FOR_CUTOVER. |
| Never ran | Active lanes with no run in the ledger. |

**Stage column.** The registry stage in plain words, corrected by what a fire really does today:

| Label | Meaning |
|---|---|
| Rehearsing — not doing real work yet | Shadow. |
| Live, watched (canary) | Canary and on the live list. |
| Canary on paper — not on the live list, still a dry run | Canary, but not on the live list. |
| Fully moved to n8n | Cutover. |
| n8n-native | No stage; n8n owns the workflow outright. |
| Off — … | The lane is not dispatched. |

The tooltips state the platform rules:

- The shadow stage forces `dry_run`.
- At canary, the cron line and n8n share one lock, so only one runs per slot and the other records SKIPPED.
- At cutover, the cron line is commented as `# RETIRED … n8n-cutover` and kept as the rollback.
- A `dry_run` is write-free by contract.
- The relay refuses a live fire for a lane that is not on the live list.

**Last run.** The icon shows the outcome, followed by how long ago it ran and the mode:

- ✓ — the run succeeded.
- ✗ — the run failed or timed out. The tooltip gives the reason (for example `output_unverifiable` or
  `timeout_exit_124`) and the run id.
- ↷ — the run was skipped because the other scheduler held the shared lock. This is expected at canary; it is not a
  failure and not a live proof.
- · — the lane never ran.

**Health.**

| Verdict | Meaning |
|---|---|
| OK | The last run succeeded or was skipped. |
| FAILING | The last run FAILED, TIMED OUT or was REFUSED, or there is a dead letter newer than the last success that has not been released, or the breaker is open. |
| STALE | The registry schedule (`dispatch.cron`, else the n8n `cadence`, else a cron `expression`, in `dispatch.tz`) had a fire more than 45 min ago that has no run. A lane with no cron schedule uses 2 × `expected_cadence_hours`. |
| NEVER_RAN | The lane has no run in the ledger. |
| OFF | The registry state is not ACTIVE, or `mode: off`. |

The badge counts FAILED, TIMEOUT and REFUSED runs in the last 24 h and 7 d.

**7 days** shows the runs recorded in the last 7 days, by mode.

**Next run** is the next fire of the same schedule, in ET.

**Promotion.** The readiness verdict uses the documented ladder only.

*Shadow → canary* (`N8N_ONBOARDING_STANDARD.md` steps 3, 5, 8 and 9, rule 5 and §2 rule 4) needs all of:

- a REVIEWED health contract;
- an allowlist entry;
- an n8n `dry_run` RUN_DONE as the latest dry fire;
- for a cron row, the cron line's `flock -n` lock equal to the allowlist lock;
- a `live_arg` the cutover factory can derive from the line (`parse_lane_argv`);
- for a sender, a cron line wrapped with `effect_claim_cron.sh`.

*Canary → cutover* (AGENTS.md §23.21) needs all of:

- the latest live run is not failed;
- a clean dry run;
- at least one live RUN_DONE whose `output_signal` advanced;
- the lane is on the live list;
- the cron line is present, and its lock equals the allowlist lock (`r1_canary_lock_matches`). A RUN_SKIPPED_LOCK never
  counts.

Two §23.21 items cannot be measured here, so each verdict lists them as *owed in the PR*:

- (3) the lane's regression tests;
- the per-wave `cron` grant and the effect key.

A lane is **BLOCKED** if any of the following holds:

- the registry state is not ACTIVE;
- the lane has an operator hold;
- the lane is a held lane;
- the lane is F07 or registry_systemd;
- the lane fails `lane_dispatch.dispatch_eligible` (the never-list);
- the lane is in the allowlist's `blocked_reasons`;
- the lane has no allowlist entry;
- the health contract is missing, not REVIEWED, or has UNKNOWN fields.

The risk tier is the factory's own classifier, `cutover_lane_facts.tier_of`. Expand a row to see the missing and
blocking items, the evidence, and what is owed.

**Promotion is never applied from this tab.** It is an operator decision made by a reviewed registry PR (§23.11). The
only actions here are the existing live-list Add and Remove, unchanged: risky, with a preview, a passkey and the typed
phrase. The one-time report for 2026-10-22 is `docs/ops/N8N_PROMOTION_READINESS_2026-10-22.md`.

**Degraded states.** If the ledger cannot be read, `outcomes_state` is `UNAVAILABLE`, a banner says so, health shows
"Not measured", and readiness is at most NOT_READY. A missing ledger never reads as "never ran". If `crontab -l` fails,
lock proofs read "not measured". An older server sends no `outcome` block; the page then shows "not measured" and no
summary strip, never zeros.
