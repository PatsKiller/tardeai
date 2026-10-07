# Findings corrected, and the muted coordination gateway

Remeasured 2026-10-07 about 01:10–01:22Z. Served pin was still `18a27ff288894c4e428151d5f385e68522ecd47b` (`GET /v3/build-meta.json` HTTP 200, ui `3.14+mux8d5sp`). n8n `GET /healthz` HTTP 200. DOF `/api/run-scope` HTTP 200. This file corrects the phase 0 narrative where the host and the source disagreed. It does not move a live owner.

The lane registry still declares 173 lanes: 134 ACTIVE, 15 NEVER_SCHEDULED, 13 PAUSED, 11 RETIRED. Those counts were checked again after the approval-signal edit and did not change.

## What was wrong in the census labels

| Lane | Earlier label | Remeasure | What was done |
|---|---|---|---|
| at-observation-01 and at-observation-01-closeout | ENABLED_WHILE_DECLARED_RETIRED | `UnitFileState=enabled`, `ActiveState=active`, `SubState=elapsed`, `NextElapse` empty, `Persistent=no`, `OnCalendar` 2026-07-27 06:55 and 10:12 | Classifier miss. The registry already calls them spent one-shots. Conflict cleared in the lane ledger. Timers left enabled. |
| contradiction-adjudicator | ENABLED_WHILE_DECLARED_NEVER_SCHEDULED | Timer waiting. Last trigger 2026-10-06 19:30 EDT. Next 2026-10-07 19:30 EDT. Service `Result=success`, exit status 0. `contradiction_adjudicator_latest.json` age about 1.63h. `contradiction_verdicts.jsonl` exists (206,289 bytes). The registry still says the verdict file does not exist and the state is NEVER_SCHEDULED until a closeout PR. | Real registry drift. State not flipped. Timer not disabled. Verdict text not read. No model call. |
| maturity-remeasure | CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED | Crontab `40 6 * * 1` with `--write` is active. `maturity_latest.json` mtime `2026-10-05T10:40:02Z` (Monday 06:40 ET), size 4,587. The scores file exists. | Real registry drift. State not flipped. Crontab not edited. Score contents not read. |
| approval-package-reminder | syslog versus a 189h file, cause NOT_MEASURED | See below. | Explained. A run receipt was added in this worktree. The live job was not run and was not changed. |

Host census figures from phase 0 were not rebuilt: 482 active user crontab commands, 474 on the release path, 2 DOF, 7 in `/etc`, 117 user timer unit files of which 92 are enabled, journal 19 days (2026-09-18 through 2026-10-06) and 164,687 CMD lines. Weekday bands near 9,550 and then near 10,150–10,200 are syslog volume. They are not a missed-fire rate and not a consumer receipt. No service count of 27 was found.

## Approval reminder

The live crontab line is `5 * * * *` and its flags are `--send` and `--record`. It is not a dry run. A same-day journal slice (from local midnight on 2026-10-06) had 22 CMD lines for this script, and every one of those lines carried both flags. The seven-day count of 168 was not recomputed.

`scripts/approval_package_reminder.py` appends the package ledger only when `plan()` returns actions and `--send` or `--record` is set. An empty plan prints `nothing due` and leaves `data/governance/approval_packages.jsonl` untouched. The served tree still does not have that file. The persistent-state copy was 46,368 bytes, mtime `2026-09-29T03:05:02Z`, age about 190.07h at this remeasure. No `approval_package_reminder_last.json` existed under persistent-state or CURRENT.

So the hourly command lines and the old ledger can both be true: the scheduler is invoking a job that sends only when something is due, and the ledger mtime is the last package write, not the last run. A command line is still not proof that anyone received a reminder. Whether any of the 168 runs had actions, sent, or failed was not read from stdout. Cron records the command, not the receipt.

The worktree script now writes `data/runtime/approval_package_reminder_last.json` on every run, including an empty plan. The receipt stores counts and flags, not reminder text. The lane output signal in `config/lane_registry.json` now points at that receipt. CURRENT will not write it until a later promote. This pass did not execute the script against the live ledger and did not pass `--send`.

The approval pilot contract refuses `wrong_signal` when the observation's signal is the package ledger and no run receipt is supplied. With a run receipt and no consumer receipt, the state is `ARTIFACT_WRITTEN`, not `CONSUMED`.

## Blockers

| Blocker | Result |
|---|---|
| Secret-bearing n8n nodes | Still blocked. Community n8n would store those secrets in its own database. External secrets are an enterprise feature and do not include Bitwarden. No credential was added. The gateway below keeps the HMAC key in the Trade AI process environment. It was not placed in n8n and the process was not installed. |
| DOF agent policy | The live checkout has none. A PROPOSED file is on branch `wt/n8n-dof-policy-20261007`, not on served `master`, and it is not binding. `dof-dashboard.service` was not restarted. |
| `dof_*` database role | Measured. Connected read-only as `trade_ai` to database `trade_ai` on `127.0.0.1:5432`. 22 tables, 22 sequences, and 37 indexes named `dof_*`, all owned by `trade_ai`. `relacl` is null (owner-default ACL). Roles whose names match `dof`: 0. No row contents. No DDL. There is no separate role, so the gateway opens no DOF SQL route. |
| Model ADR | Corrected in `docs/architecture/cio/ADR_LLM_GOVERNANCE_BOUNDARY.md`. Exact id is `deepseek-flash`. `deepseek-v4-flash` and `deepseek-v4-pro` are legacy and rejected. Lane aliases are not model ids. `FLASH_MODEL = deepseek_model_id("FAST")` was not edited. No provider call. The 2026-08-08 freeze date was not rewritten as if it had always said `deepseek-flash`. |
| Watchdog outside n8n | `scripts/n8n_lab_watchdog.py` GETs a health URL, writes a local receipt, and exits non-zero when the port is down. It does not send. The unit test used `127.0.0.1:9` (exit 2). The live lab at `2026-10-07T01:22:22Z` returned HTTP 200 with `sends: false`. n8n was not stopped. No timer was enabled, so an unattended outage is still invisible until something runs this script. |

## Gateway

`scripts/lib/n8n_coordination_gateway.py` authenticates an HMAC claim (`TRADEAI_N8N_GATEWAY_HMAC_KEY` for the optional process; tests inject a fake key). A missing or bad signature is unauthenticated even when the request says its peer is `127.0.0.1`. The claim lifetime is at most five minutes. A reused nonce is a replay. The event must match `ledgers/event-reference.schema.json`, `authority_class` must be `coordination_read`, and `origin_sha` must equal the expected served SHA or the call is `stale_origin_sha`.

Trade AI and NYC DOF stay separate: a claim for one project cannot carry the other project's event. The default lane allowlist is the five pilots. Any other lane is `unknown_lane`, which is how a DOF data lane stays out. Routes whose tokens include broker, order, grant, 2FA, promote, bid, payment, title, or send are refused before they can do work.

The receipt store is the caller's dict. `durable` is false. Nothing in the module binds a port, sends, or opens a database. `scripts/n8n_coordination_gateway.py` can serve on `127.0.0.1` only, refuses privileged and live service ports (including 5432, 5678, 7776, 7777, and 8766), and refuses to bind without a key of at least 32 bytes. It was not installed and not left running. The test started an ephemeral loopback server and shut it down.

States implemented: EXPECTED is the pre-accept name in the work order; the stored path used here is ACCEPTED, CLAIMED, STARTED, ARTIFACT_WRITTEN, CONSUMED, plus REFUSED, FAILED, DEAD_LETTER, SUPPRESSED, SUPERSEDED, CANCELLED, and EXPIRED as terminals or edges. `CONSUMED` requires a caller-supplied consumer id and receipt id. The gateway does not contact the consumer.

## Five contracts

`scripts/lib/n8n_pilot_contracts.py` is the muted body. Each one calls the gateway and then applies the lane rule. `send` is refused. Effects, outbound, and mutation stay blocked.

1. Morning brief. Syslog command lines leave the state at `ARTIFACT_WRITTEN` with reason `command_line_is_not_a_receipt`.
2. Holdings research. A shared ledger mtime without `mode=holdings` is refused. A holdings observation needs `hermes_run_id` or a typed refusal. It does not enqueue work.
3. Material-change digest. `muted` must be true, with a detector event id and a suppression mark. A live notify is refused. The detector and the notifier stay in their existing code.
4. Daily LLM spend. The caller must supply the daily amount. `provider_charge_requested` is refused. No provider is called.
5. Approval reminder. The package-ledger mtime without a run receipt is `wrong_signal`. A run receipt without a consumer receipt is not `CONSUMED`.

No n8n workflow was created or activated for these five. Cron remains the owner. A green n8n screen was not produced and would not be a consumer receipt.

## Tests

`pytest` on the five new files: 17 passed. That includes bad signature, replay, stale SHA, unknown lane, the five forbidden routes, localhost without a signature, idempotency conflict, secret material (the planted value is not echoed), project mismatch, consumer-ack refusal, bind refusal for `0.0.0.0` and port 7777, the five pilot refusals, the ADR text, the empty-plan receipt, and the closed-port watchdog.

## Effects

Performed: worktree edits, one read-only metadata query, `systemctl show` and a flag-only crontab read, one GET of n8n `/healthz`, ephemeral test servers that were shut down.

Prevented: no crontab or timer edit, no service restart, no n8n credential, no model call, no Telegram or mail, no production SQL write, no DOF row read, no gateway installed on portfolio-server, no push.

Cost: model spend caused by this pass is 0. No n8n workflow execution was added.

## Rollback

Drop branch `wt/n8n-parallel-20261007`, or revert this commit. The DOF policy branch is separate and can be deleted. No service, crontab, timer, container, or database has to be restored.
