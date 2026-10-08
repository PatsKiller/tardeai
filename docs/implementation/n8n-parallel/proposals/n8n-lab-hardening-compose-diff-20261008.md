# Proposal — n8n lab hardening: compose diff, SM key names, firewall (2026-10-08)

```
Status:      DRAFT — PROPOSAL ONLY. Nothing here is applied. The operator applies the compose change,
             creates the SM keys, turns on MFA, recreates the DB role and writes the firewall rule.
as_of:       2026-10-08T12:00:00-04:00
Measured at: /home/johnclaw/m8m-bakeoff-lab/docker-compose.n8n.yml as read 2026-10-08 (not a git repo,
             operator-owned); repo origin/main e6eee00a2. Firewall state NOT VERIFIED (sudo).
Policy:      AGENTS.md §23.5 (PROPOSED 2.0.0); ADR docs/architecture/n8n/ADR_COORDINATION_SECRETS.md (ACCEPTED 2026-10-08)
Relay:       tradeai-n8n-run-relay.service binding 172.19.0.1:18092 is PENDING OPERATOR PERMISSION.
             Steps 5 and 6 below are moot until that permission is given.
```

This is the minimal diff that satisfies ADR precondition 1 (non-retention). The broader hardened compose
(`docker-compose.n8n.hardened.yml` in this directory: container healthcheck, `N8N_WEBHOOK_URL`,
`N8N_PUBLIC_API_DISABLED`, PG17 on recreate, `n8n_app` role) remains the fuller target and is unchanged by
this proposal; apply this diff first, the rest with the recreate.

## 1. Compose diff (unified, against the running file)

```diff
--- /home/johnclaw/m8m-bakeoff-lab/docker-compose.n8n.yml	(running, as read 2026-10-08)
+++ /home/johnclaw/m8m-bakeoff-lab/docker-compose.n8n.yml	(proposed)
@@ -58,8 +58,12 @@
       GENERIC_TIMEZONE: America/New_York
       # JSON array. A comma-separated string fails JSON.parse and becomes an empty exclude list.
       NODES_EXCLUDE: '["n8n-nodes-base.executeCommand","n8n-nodes-base.executeCommandTool","n8n-nodes-base.ssh","n8n-nodes-base.ftp","n8n-nodes-base.emailSend","n8n-nodes-base.emailSendTool","n8n-nodes-base.emailSendHitlTool","n8n-nodes-base.localFileTrigger"]'
-      EXECUTIONS_DATA_SAVE_ON_SUCCESS: all
+      # ADR precondition 1 (AGENTS.md §23.5): no successful execution input is retained, so the one
+      # credential n8n holds is never copied into an execution record. Errors are kept 168 h for triage.
+      EXECUTIONS_DATA_SAVE_ON_SUCCESS: none
       EXECUTIONS_DATA_SAVE_ON_ERROR: all
+      EXECUTIONS_DATA_PRUNE: "true"
+      EXECUTIONS_DATA_MAX_AGE: "168"
       N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS: "true"
     volumes:
       - n8n-data:/home/node/.n8n
```

**`NODES_EXCLUDE` — measured, not changed.** The plan asked for `n8n-nodes-base.executeCommand`,
`n8n-nodes-base.ssh` and `n8n-nodes-base.ftp` to be added. All three are already present in the running
file (along with `executeCommandTool`, the three `emailSend*` nodes and `localFileTrigger`), so the diff
leaves the line byte-identical. Do not re-type it: the value is a JSON array and a comma-separated string
parses as an empty list that also drops the image defaults (lab `docs/AGENTS.md`).

Apply (operator): edit the file, then recreate **only** the `n8n` service (container `m8m-n8n`) — `docker compose -f
/home/johnclaw/m8m-bakeoff-lab/docker-compose.n8n.yml up -d n8n`. Do not recreate `m8m-n8n-db` for an env
change (lab change-control rule). Verify: `docker exec m8m-n8n env | grep -E '^EXECUTIONS_DATA_'` shows the
four values; an execution of `n8n-monitor-trade-ai` after the restart shows no stored data on success.

## 2. Owner MFA (operator, n8n UI)

Account `bakeoff-n8n@m8m.lab` is the single `global:owner` and had MFA off on 2026-10-07. In the n8n UI:
Settings → Personal → Two-factor authentication → Enable; store the recovery codes in Bitwarden SM (not in
the lab `.env`, not in a doc). Verify: `docker exec m8m-n8n-db psql -U n8n -d n8n -c "select email,
\"mfaEnabled\" from \"user\";"` reports `t` (column name as of n8n 2.x; if the column differs, the UI banner
is the evidence). This is ADR precondition 2.

## 3. Non-superuser database role on recreate (operator)

The official Postgres image makes `POSTGRES_USER` (`n8n`) a superuser. ADR precondition 3 is the `n8n_app`
role from `proposals/init/01-n8n-app-role.sh`, which only runs on a **fresh** volume. It therefore lands with
the PG17 recreate in `docker-compose.n8n.hardened.yml` (dump → new volume → restore, using
`scripts/n8n_lab_backup.sh` and the restore drill), not with the env change in step 1. Until then the
precondition is unmet and the credential is not created. Verify after recreate: `docker exec m8m-n8n-db psql
-U n8n -d n8n -c "select rolname, rolsuper from pg_roles where rolname in ('n8n','n8n_app');"` shows
`n8n_app | f` and `DB_POSTGRESDB_USER=n8n_app` in the container env.

## 4. Bitwarden SM keys to add (operator; names only, never values here)

Project `trade-ai-prod`. `scripts/secrets/render_env.py` already delivers every shell-exportable SM key to
`/run/user/1000/tradeai/env` (0600, tmpfs, every 4 h) and writes hashes only to
`/run/user/1000/tradeai/env.manifest.json` — no second render path, no hand-written env file.

| SM key name | consumer | scope |
|---|---|---|
| `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N` | `tradeai-n8n-run-relay.service` (host) and the gateway's `CALLER_KEYS[n8n-relay]` | signs `coordination_run` claims; never enters n8n |
| `TRADEAI_N8N_RELAY_BEARER` | the relay (host) verifies it; n8n holds it as its one Header-Auth credential | valid only at `172.19.0.1:18092` |

Rotation pairs (`*_PREVIOUS`) are added at the first rotation, not now. After `render_env.py --now`, verify
with `python3 -c "import json;m=json.load(open('/run/user/1000/tradeai/env.manifest.json'));print(sorted(k for k in m['hashes'] if 'N8N' in k))"`
— both names appear; no value is printed.

`config/secret_registry.yaml` entries (land in workstream B's PR with the relay, or a follow-up; names only):

```yaml
  TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N:
    class: self_minted
    max_age_days: 7
    restart_targets: [tradeai-n8n-run-relay, tradeai-n8n-coordination-gateway]
    verify_probe: null
    notes: "n8n-relay caller key; weekly; _PREVIOUS overlap; never an n8n credential"
  TRADEAI_N8N_RELAY_BEARER:
    class: self_minted
    max_age_days: 7
    restart_targets: [tradeai-n8n-run-relay]
    verify_probe: null
    notes: "the ONE n8n credential (Header-Auth); operator updates the n8n credential after SM+render"
```

`rotation_daemon.py` reads these once it is scheduled (unscheduled today — a separate `cron` grant).

## 5. Firewall rule proposal — 172.19.0.0/16 may reach the host only on 18092 (operator, sudo)

Firewall state is NOT VERIFIED (sudo requires a password; `09-live-audit` §). Traffic from a container to
the bridge address `172.19.0.1` enters the host's INPUT chain, which ufw governs (the DOCKER-USER chain only
governs forwarded traffic). Find the bridge interface first: `docker network inspect m8m-n8n_lab --format
'{{.Id}}'` → the interface is `br-<first 12 chars>`; confirm with `ip -br addr | grep 172.19.0.1`.

```
# 1. allow the relay port only, from the lab subnet, on the lab bridge interface
sudo ufw allow in on br-<id> from 172.19.0.0/16 to 172.19.0.1 port 18092 proto tcp comment 'n8n relay (AGENTS.md 23.3)'
# 2. refuse everything else from the lab subnet to the host
sudo ufw deny  in on br-<id> from 172.19.0.0/16 to any comment 'n8n lab: host reach limited to 18092'
sudo ufw status numbered   # the allow must sort before the deny
```

Consequence to accept first: the two lab monitors `n8n-monitor-trade-ai` (`172.19.0.1:7777`) and
`n8n-monitor-dof` (`172.19.0.1:7776`) go red the moment rule 2 lands. Repoint them to the relay's
`GET /status` (or accept red) in the same window. Rollback: `sudo ufw delete <n>` for the two rules.
Nothing here touches `127.0.0.1:18091` (loopback, `guard_bind`) or any other listener.

## 6. The relay itself — PENDING OPERATOR PERMISSION

`tradeai-n8n-run-relay.service` (workstream B) binds `172.19.0.1:18092`, which is the first Trade AI listener
off loopback since `guard_bind` was introduced. It is not installed, not enabled, and its unit is not added to
`config/dev_tree_units_baseline.txt` / `expected_services.json` until the operator says so in a
`config-write` grant that names it. Until then n8n has no trigger path and holds no credential.

## Order of operations

1. Compose diff (step 1) → verify retention envs. 2. MFA (step 2). 3. SM keys (step 4) → `render_env.py
--now` → manifest shows both names. 4. Relay permission + `config-write` grant (step 6) → units installed.
5. Firewall (step 5) in the same window as the monitor repoint. 6. Only then: the one n8n credential is
created by the operator in the n8n UI; the DB role (step 3) follows with the PG17 recreate and is a
precondition for keeping the credential, measured and reported.
