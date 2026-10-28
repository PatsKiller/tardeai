# n8n_app least-privilege packet 2026-10-27: n8n stops connecting to its database as a superuser (AGENTS §23.10 P13)

```
Status:      PREPARED, operator-run. Nothing here has run against the host. Every --apply is an operator act
             (AGENTS.md §0 rule 9, §17). P13 stays OPEN until 04_verify.sh PASSES on the host and its receipt is quoted.
as_of:       2026-10-27 (repo origin/main 274e531f5, AGENTS.md Policy-Version 25.0.1)
Request:     operator, 2026-10-27, verbatim: "I want all of your recommendations done" — including "the n8n superuser
             role" as its own small PR.
Policy:      AGENTS.md §23.5 ("the non-superuser n8n_app role remains a precondition for the bridge token (§23.10
             P13)"; "No further n8n credential is created until P13 has a receipt"), §23.10 P13, §23.23 governance (7),
             §23.24 Logging (3). ADR docs/architecture/n8n/ADR_COORDINATION_SECRETS.md precondition 3.
Authority:   MBI_BEHAVIOR = 0. No broker, order or trading path. No secret value is read, printed or logged: the
             n8n_app password lives in a mode-600 file and Postgres receives only its SCRAM verifier; the
             superuser's password never leaves the db container.
```

## The finding

The n8n container (`m8m-n8n`, compose project `m8m-n8n`) connects to its Postgres (`m8m-n8n-db`, database `n8n`) as
`n8n`, the Postgres image's bootstrap role: `rolsuper`, `rolcreaterole`, `rolcreatedb`, `rolreplication` and
`rolbypassrls` are all true (measured 2026-10-09, audit E C1/D7, and again 2026-10-22, `probe_n8n_platform_facts.py`
FW-P2 FAIL). That breaches the §23.5 precondition, and the breach has been open since the relay credential was created on
2026-10-08T16:45:48Z. A compromised n8n (a bad workflow, a node exploit) can then read any file the database server can,
create roles, and rewrite any table, including the credential table and the audit trail it is supposed to leave.

## What this packet changes, and what it does not

| Changes | Does not change |
|---|---|
| A new role `n8n_app` (`LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 40`) owns n8n's schema objects | the role `n8n` (kept; it stays the bootstrap superuser the db container's own tools use) |
| The n8n service connects as `n8n_app`, password by file (`DB_POSTGRESDB_PASSWORD_FILE` + compose secret `n8n_app_pg_password`) | the db service, its volume, its `POSTGRES_PASSWORD`; the image; any workflow; any credential in n8n |
| The n8n container no longer holds the superuser's password (`DB_POSTGRESDB_PASSWORD` removed from the n8n service) | execution-data settings (FW-P1 is **not** in this packet, see "Relation to the hardening packet") |
| Optional, later (step 05): the superuser can no longer log in over the network | local-socket logins inside the db container (nightly `pg_dump`, restore drill, governance reads) |

Nothing is deleted. Old files are renamed or kept: compose backups, the dump, evidence. No role is dropped.

## Reuse (AGENTS §13.5): this is the P13 slice of FW-P2, packaged with preflight, backup, verify and rollback

- **The role DDL** is `scripts/ops/n8n_db_app_role.py` (packet `n8n-platform-hardening-20261022`, FW-P2). It was
  rehearsed 2026-10-22 against the live n8n schema in throwaway containers, with n8n 2.43.0 starting as `n8n_app`
  (healthz ok after 5 s). Step 02 calls it; it is not re-implemented.
- **The compose change** is that packet's reviewed diff `compose/fw-p2-n8n-app-role.compose.diff.proposed`. Step 03
  applies it alone. Rebuilt from the committed proposal, the pre-patch live file has sha256 `5d6210de…a54c`, the same
  value the hardening packet measured on the host 2026-10-22. The FW-P2 diff applies to it with offsets and no fuzz
  (hermetic test `tests/test_n8n_app_role_packet_20261027.py`).
- **Re-checked here, on a throwaway local PostgreSQL 16.15** (no host, fake passwords):
  - the step-02 SQL from the role script applies;
  - as `n8n_app`, migration-shaped DDL works: `ALTER TABLE … ADD COLUMN`, `CREATE TABLE`, `CREATE INDEX`,
    `CREATE OR REPLACE FUNCTION`, `ALTER TYPE … ADD VALUE`, `ALTER TABLE … DISABLE TRIGGER USER`, and
    `CREATE EXTENSION IF NOT EXISTS "uuid-ossp"` (already present, so it is skipped);
  - `CREATE ROLE`, `CREATE DATABASE` and `pg_read_file` are denied, and so are `DISABLE TRIGGER ALL` and
    `SET session_replication_role` (see "Main risk");
  - step 05 and its rollback behave as described below, and the server log held no password.

**Relation to the hardening packet.** That packet's step 3 is one combined patch, FW-P1 + FW-P2 + FW-P5. FW-P1 sets
`EXECUTIONS_DATA_SAVE_ON_SUCCESS: all`, which AGENTS.md §23.5 still names as `none` ("the precondition for any credential
existing") while §23.23 governance (3) says successes are saved. That conflict is the operator's to resolve (§17), so this
packet carries **only** FW-P2. If the operator applies the hardening packet's combined patch instead, skip step 03 here: it
detects `DB_POSTGRESDB_USER: n8n_app` and exits. Steps 00, 01, 04, 05 and 09 still apply.

## Why step 05 is not `ALTER ROLE n8n NOSUPERUSER`

`n8n` is the cluster's bootstrap superuser (`POSTGRES_USER`, OID 10). PostgreSQL 16 refuses to demote it. Rehearsed on
16.15:

```
ALTER ROLE n8n NOSUPERUSER;
ERROR:  permission denied to alter role
DETAIL:  The bootstrap user must have the SUPERUSER attribute.
REASSIGN OWNED BY n8n TO probe_r;
ERROR:  cannot reassign ownership of objects owned by role n8n because they are required by the database system
```

P13 concerns the role **n8n connects as**, and steps 02 to 04 close it. Step 05 is the defence-in-depth that is possible:
`ALTER ROLE n8n PASSWORD NULL`. A role with no password cannot authenticate over the network (the image's pg_hba ends
`host all all all scram-sha-256`), so nothing on the lab network can log in as the superuser, the n8n container included,
even holding the old password. Local-socket logins inside the db container are `trust` and keep working. Rehearsed:

```
TCP login as n8n after 05      -> FATAL:  password authentication failed for user "n8n"
local socket as n8n after 05   -> socket-ok|t
05 rollback (\getenv inside)   -> restore-ok; tcp-ok-after-restore
```

It is a separate, later step because it is independent of P13 and needs a soak: first prove nothing else on the lab
network still logs in as `n8n` over TCP (04 and 05 read `pg_stat_activity`).

## Preconditions (each is checked by a script; none is assumed)

1. This PR is merged and promoted, so the packet is in `~/trade-ai-releases/portfolio-server/CURRENT`. Run every step
   from `cd ~/trade-ai-releases/portfolio-server/CURRENT/docs/ops/packets/n8n-app-role-20261027`. `PY` may point at the
   repo venv (`PY=~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python`). The scripts need only the stdlib, so
   plain `python3` also works.
2. `00_preflight.sh` exits 0, with the containers running in project `m8m-n8n` and both volumes
   (`m8m-n8n_n8n-data`, `m8m-n8n_n8n-pg`) present. Healthz must be ok, a relay `op: due` line must be no older than 15
   min, at least one workflow must be active, and the backup directory must be writable.
3. `01_backup.sh --apply` has run less than 6 h before step 02, and so has the preflight. Step 02 refuses otherwise.
4. Step 03 refuses unless step 02 is done (`n8n_app` has `rolsuper=f`, `rolcanlogin=t`) and the password file
   `~/.config/tradeai/n8n/n8n_app_pg_password` exists with mode 600 and owner you. The diff's secret path must equal it,
   the candidate must pass `docker compose … config --quiet`, the patch must apply without fuzz, and healthz must be ok
   before the change.
5. Step 05 needs a step-04 PASS at least 24 h old (`--soak-hours`), a fresh 04 PASS, no TCP session as `n8n`, and the
   network-login probe answering `LOGIN_OK` first. That proves the container's `POSTGRES_PASSWORD` equals the role's
   current password, so the 05 rollback restores a working value.

## Window

The restart convention is `N8N_CONFIGURATION.md` §1: pick a quiet minute, **hh:07 or hh:37**, clear of the
:00/:15/:30/:45 fires.

- `02 --apply` and `03 --apply` refuse outside hh:05–hh:09 and hh:35–hh:39. Step 02 takes a short ACCESS EXCLUSIVE lock
  per table inside one transaction with `lock_timeout 15s`; a busy table makes it roll back harmlessly.
- `03 --apply` also refuses while the NYSE session (repo calendar `scripts/lib/cio_market_session.py`) is PRE or RTH,
  because n8n dispatches the advisory market-data lanes then. An unknown session also refuses. Best time: a weekday
  evening after 20:00 ET, or a weekend.
- `--ignore-window` overrides both checks, and you decide.
- `09_rollback.sh` is never window-gated (a rollback is urgent); it warns instead.

Measured cost: in the FW-P2 rehearsal the same image answered healthz 5 s after start. At most one or two dispatcher
minutes are missed; the relay's `op: due` resumes on the next minute.

## Grants

The agent-guard tiers this needs if an agent runs a step for you (`bin/guard grant <tier> --for <dur> --reason
"n8n-app-role-20261027 step NN, PR #<n>"`). Put the grant id(s) in `N8N_APP_ROLE_GRANT`. Every `--apply` except 01
refuses without it, and the receipt records it.

| Step | Writes | Tier(s) |
|---|---|---|
| 00 preflight, 04 verify | evidence folder only | none (read-only) |
| 01 backup | a new dump in the n8n backup dir (the nightly timer does the same) | none by the classifier; `release-write` if your guard flags the backup path |
| 02 create role | role DDL and ownership in database `n8n` | **`db-write`** (the hook classifies psql DDL as db-write; the role script's AUTHORITY line makes it an operator DB act) |
| 03 switch compose | `~/m8m-bakeoff-lab/docker-compose.n8n.yml`, recreate of the `n8n` container | **`config-write`** + **`service`** (N8N_CONFIGURATION §1 restart/upgrade) |
| 05 close superuser login | one `ALTER ROLE` | **`db-write`** |
| 09 rollback | compose file and recreate; with `--also-role` or after 05, role changes | **`config-write`** + **`service`** (+ **`db-write`**) |

## Steps (the operator runs these; each prints its dry run first)

```
cd ~/trade-ai-releases/portfolio-server/CURRENT/docs/ops/packets/n8n-app-role-20261027
bash 00_preflight.sh                                          # read-only; snapshot + finding
bash 01_backup.sh            && bash 01_backup.sh --apply      # fresh pg_dump + roles snapshot + manifest
bash 02_create_app_role.sh                                     # PLAN + SQL (verifier redacted)
N8N_APP_ROLE_GRANT=<db-write id> bash 02_create_app_role.sh --apply          # at hh:07 / hh:37
bash 03_switch_compose.sh                                      # candidate, diff, config --quiet
N8N_APP_ROLE_GRANT="<config-write id> <service id>" bash 03_switch_compose.sh --apply   # at hh:07 / hh:37, not PRE/RTH
bash 04_verify.sh                                              # PASS = the P13 receipt
# soak >= 24 h (one nightly backup + one dispatcher day), then optionally:
bash 05_close_superuser_login.sh && N8N_APP_ROLE_GRANT=<db-write id> bash 05_close_superuser_login.sh --apply
```

### Expected outputs

Dry runs of 00 and 03, measured in this repo against the test's fake `docker`, so the values are canned. On the host,
expect the same lines with live values.

```
== 3. the role n8n connects as, and rolsuper
  DB_POSTGRESDB_USER=n8n  DB_POSTGRESDB_PASSWORD=set  DB_POSTGRESDB_PASSWORD_FILE=unset
    n8n|t|t|t|t|t|t
  n8n connects as n8n, rolsuper=t
  finding (P13): the role n8n connects as is a superuser; this packet fixes it
...
PREFLIGHT OK — next: bash 01_backup.sh (dry run), then --apply
```

```
== 1. apply the FW-P2 diff to a copy (the live file is not touched)
  patching file docker-compose.n8n.yml
  Hunk #2 succeeded at 46 (offset -3 lines).
  Hunk #3 succeeded at 271 (offset -10 lines).
== 2. validate the candidate (config --quiet; prints nothing on success)
  config --quiet: ok
== 3. the compose diff that --apply installs (variable names only; the file holds no values)
  -      DB_POSTGRESDB_USER: n8n
  -      DB_POSTGRESDB_PASSWORD: ${N8N_PG_PASSWORD}
  +      DB_POSTGRESDB_USER: n8n_app
  +      DB_POSTGRESDB_PASSWORD_FILE: /run/secrets/n8n_app_pg_password
  (+ top-level secrets: n8n_app_pg_password -> ~/.config/tradeai/n8n/n8n_app_pg_password; service secrets: entry)
DRY RUN — the live file and the container are unchanged. ...
```

Step 02 `--apply` ends `apply OK: n8n_app created; password file {… 'mode': '0o600' …}; rolsuper=f; ownership and
privileges verified`. That is the 2026-10-22 rehearsal line. On the host, the owners line afterwards shows only
`n8n_app:` kinds.

## Verify

`04_verify.sh` (read-only) PASSES only when all of these hold:

1. healthz is `{"status":"ok"}`.
2. The container has `DB_POSTGRESDB_USER=n8n_app`, `DB_POSTGRESDB_PASSWORD` unset and `DB_POSTGRESDB_PASSWORD_FILE` set.
3. `pg_roles` for the role read from the container shows `rolsuper=f` and no createrole, createdb, replication or
   bypassrls (`f|f|f|f|f`).
4. Every TCP session to `n8n` is `n8n_app`.
5. `scripts/ops/n8n_db_app_role.py --verify` gives `verify PASS: n8n_app rolsuper=f; n8n connects as n8n_app; all checks
   pass`.
6. The active workflow ids equal the step-00 snapshot.
7. A relay `{"op": "due"}` line newer than step 03's `up_at` appears within 300 s.

The receipt is `~/n8n-maturity-verification/packets/n8n-app-role-20261027/<UTC>-verify/verify.json`
(`verdict: PASS`). `probe_n8n_platform_facts.py | grep FW-P2` should then print `FW-P2 PASS`.

## Rollback

- **Compose (seconds):** `N8N_APP_ROLE_GRANT="<config-write> <service>" bash 09_rollback.sh --apply`.
  1. If step 05 was applied, it first restores the superuser's password from the db container's own `POSTGRES_PASSWORD`
     (psql `\getenv` inside the container; never on an argv, the host or a log).
  2. It renames the live compose file to `docker-compose.n8n.yml.rolledback-<UTC>`, copies the newest
     `docker-compose.n8n.yml.bak-<UTC>-pre-n8n-app-role` back, runs `config --quiet` and `up -d --no-deps n8n`.
  3. It checks healthz, `connects_as=n8n`, the active workflows and the relay `op: due`.

  The superuser still has every privilege, so n8n works whatever the owner of a table is.
- **Role (optional):** add `--also-role`, which runs `n8n_db_app_role.py --rollback --apply`. That sets `n8n_app` to
  NOLOGIN and runs `REASSIGN OWNED BY n8n_app TO n8n`. The role is never dropped. Archive the password file by rename if
  you want: `mv ~/.config/tradeai/n8n/n8n_app_pg_password{,.retired-$(date -u +%Y%m%dT%H%M%SZ)}`.
- **Step 05 alone:** `N8N_APP_ROLE_GRANT=<db-write> bash 05_close_superuser_login.sh --rollback --apply`.
- **Restore from the dump: the last resort only, by hand, never over the live database.** Use it only if the n8n
  database itself is damaged, which nothing in this packet is expected to cause. Restore into a NEW database and point n8n
  at it, so the original stays intact for inspection:

  ```
  D=~/trade-ai-releases/persistent-state/backups/n8n/n8n-pre-n8n-app-role-<UTC>.dump
  docker exec -i m8m-n8n-db psql -X -U n8n -d postgres -c "CREATE DATABASE n8n_restore_<UTC>"
  docker exec -i m8m-n8n-db pg_restore -U n8n -d n8n_restore_<UTC> --no-owner --role=n8n --exit-on-error < "$D"
  ```

  Then set `DB_POSTGRESDB_DATABASE: n8n_restore_<UTC>` in the restored compose file, and run `up -d --no-deps n8n`.
  Credentials decrypt only with the n8n encryption key, which is in the n8n volume and the Bitwarden escrow, not in the
  dump. That is the same condition the weekly restore drill proves.

## Main risk: n8n migrations under a non-superuser, and how the packet handles it

n8n runs its schema migrations at start. As owner of every object in `public`, with `USAGE, CREATE` on the schema,
`n8n_app` can run what migrations normally do. Rehearsed:

- allowed: ALTER, CREATE TABLE and INDEX, functions, enum values, user triggers, and a create-if-not-exists of the
  installed extension;
- denied: `ALTER TABLE … DISABLE TRIGGER ALL` (system FK triggers: `"RI_ConstraintTrigger_…" is a system trigger`),
  `SET session_replication_role`, a new untrusted extension, `CREATE ROLE`, `CREATE DATABASE`.

A future n8n release whose migration uses one of the denied operations would fail at start: healthz would stay down and
the container log would say `permission denied`. Mitigations:

1. **This packet changes no image**, so no migration is pending when step 03 recreates the container. Preflight records
   the image id and the `migrations` count; 04 checks healthz and ownership.
2. **Every later n8n image upgrade is rehearsed as `n8n_app` first.** Restore the newest dump into a scratch container
   with the role, and start the new image against it with `DB_POSTGRESDB_USER=n8n_app`. That is the 2026-10-22 FW-P2
   rehearsal shape (`docs/ops/packets/n8n-platform-hardening-20261022/README.md` Step 2, "Rehearsal"). Only then upgrade
   live, under N8N_CONFIGURATION §1's restart/upgrade procedure.
3. **If an upgrade needs the superuser**, run `09_rollback.sh --apply` (n8n starts as `n8n`, the migration runs), then
   `02_create_app_role.sh --apply --reuse-password-file`. That moves ownership of any new objects and re-checks the role
   (the role script ALTERs an existing role instead of creating it). Then run `03` and `04` again. The window is one
   restart each way.
4. Rollback at any point is one command and needs no database change.

Smaller risks: a TCP user of the superuser nobody knew about breaks at step 05, not before. 05 refuses while
`pg_stat_activity` shows one, and its rollback is one command. The password file must stay readable by uid 1000 (the
container's `node` user, measured; the file owner). Step 03 checks the mode and owner.

## What to record (quote in the closing PR; nothing secret in any of it)

- The evidence folder `~/n8n-maturity-verification/packets/n8n-app-role-20261027/` holds the `<UTC>-preflight/` snapshot
  (`active_workflows.txt`, roles, owners, hba, sessions, `preflight.json`), `<UTC>-backup/backup.json`,
  `<UTC>-create-app-role/`, `<UTC>-switch-compose/` (with `compose.diff`, the candidate and `switch_compose.json`),
  `<UTC>-verify/verify.json`, and, if run, `<UTC>-close-superuser-login/` and `<UTC>-rollback/`.
- The dump path, sha256 and TOC count from `01` (the manifest beside the dump).
- The grant ids used, the 03 `up_at`, and the compose sha256 before and after.
- Then update `docs/implementation/n8n-maturity/N8N_CONFIGURATION.md` (§0.4 audit trail, §1 DB role, §8 item 10) from
  OPEN to CLOSED, with the verify receipt path, and close P13 in the next AGENTS.md amendment (§23.10 checkbox, §23.5
  "does not hold today" sentence). This PR edits neither.

## Follow-ups (not in this packet)

- `config/secret_registry.yaml` has no row for the n8n_app password file. Add one (class `self_minted`, restart target
  the `m8m-n8n` container) when rotation is scheduled. Rotation is `02 --apply --reuse-password-file` after replacing the
  file, then `03`'s recreate.
- A read-only `n8n_reader` role for the governance reads that use the superuser through `docker exec` (hardening packet
  finding 3).
- P15: the owner password is still in the lab `.env` (V8 F6).

## Test

`tests/test_n8n_app_role_packet_20261027.py` is hermetic: a tmp HOME, a fake `docker` and `curl`, and the compose file
rebuilt from the committed proposal. It proves:

- the scripts exist, are executable and parse;
- every mutating script defaults to a dry run that runs no `up`/`down`/`restart`, no `pg_dump`, no writable SQL, leaves
  the compose file byte-identical and creates no password file;
- every direct psql call is a read-only transaction;
- `--apply` without `N8N_APP_ROLE_GRANT` refuses before any mutation;
- there is no `down`, no `-v`, no DROP of a role, database, table or schema, no `rm`, no literal password, no `.env`
  read, and no `config` without `--quiet`;
- step 03's candidate names `n8n_app` with the password by file.
