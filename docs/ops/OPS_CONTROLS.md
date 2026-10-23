# Ops → Controls: one operator surface, one governed host applier

```
Status:      DRAFT (branch feat/ops-controls-20261022). Built INERT: refuses every change until AGENTS.md 19.0.0 is
             ACTIVE and the operator has applied the migration, installed the applier and enrolled a passkey.
as_of:       2026-10-22T18:30:00-04:00
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
  is read-only.

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
