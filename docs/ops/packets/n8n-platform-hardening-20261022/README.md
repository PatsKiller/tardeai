# n8n platform hardening packet — FW-P1..P6 for the §23.24 import gate (operator-applied)

```
Status:      DRAFT, operator runbook. Every apply step is an operator act (AGENTS §17 / §0 rule 9); the agent ran
             only the read-only dry runs quoted below, and a FW-P2 rehearsal on throwaway containers.
as_of:       2026-10-22T13:50:00Z
Measured at: origin/main df3ebab50 (branch feat/n8n-platform-hardening-20261022); host ms01-openclaw;
             live n8n m8m-n8n running n8nio/n8n:2.43.0 = sha256:c6a3a0461d1d…873c; compose
             /home/johnclaw/m8m-bakeoff-lab/docker-compose.n8n.yml sha256 5d6210de…a54c (mtime 2026-10-09 21:57 EDT)
Authority:   MBI_BEHAVIOR = 0. No broker, order or credential path. No secret value was read or printed: the probe
             reads only allowlisted, non-secret container env keys; the role script writes the new password to a
             mode-600 file and sends Postgres only its SCRAM verifier.
Blocks:      tradeai-fabric-release-train import (release-train arming step F) — framework_pending_evidence.json
             platform_blocking FW-P1..P6 (docs/ops/packets/release-train-arming-20261021/).
```

## What this clears, and how it is checked now

The §23.24 activation gate (`scripts/check_n8n_import_ready.py` → `check_n8n_workflow_framework.py --gate activation`)
refuses every workflow while any platform element is not PASS. Until this packet those six were read from a
hand-cited file (`docs/implementation/n8n-maturity/data/n8n_platform_facts_20261015.json`) that nothing re-measured.

Now:

- **`scripts/probe_n8n_platform_facts.py`** measures FW-P1..P6 on this host, read-only, and emits
  `N8nPlatformFacts@v1` with `source_kind: host_probe` (`--write` stores it at
  `$STATE_ROOT/data/runtime/n8n_platform_facts_last.json`).
- **The checker lets an element PASS only from a fresh host probe** (≤ 24 h). A cited or stale file caps every
  element at PARTIAL ("PASS withheld"), so an edited JSON file can no longer clear the gate.
- **`check_n8n_import_ready.py --probe-host`** runs the probe in-process and prints each element with its status,
  evidence and source; `--platform-facts F` (or `$N8N_PLATFORM_FACTS`) reads a probe file. With neither, it reads
  the committed 2026-10-15 measurement, so nothing that runs today changes.

| Element | What the probe reads | PASS needs |
|---|---|---|
| FW-P1 | n8n container env (allowlisted keys only) | `EXECUTIONS_DATA_SAVE_ON_SUCCESS=all`, `EXECUTIONS_DATA_PRUNE=true`, `EXECUTIONS_DATA_MAX_AGE>0` |
| FW-P2 | `pg_roles` row of `DB_POSTGRESDB_USER` (one SELECT, read-only transaction) | `rolsuper=f` and none of createrole/createdb/replication/bypassrls |
| FW-P3 | `systemctl --user` state of `tradeai-n8n-drift-watch.timer`; `N8nDriftWatch@v1` + `N8nWorkflowDriftReceipt@v1` | timer enabled+active; live receipts ≤ 45 min old; verdict CLEAN or DRIFT; host P1 path |
| FW-P4 | `ss -ltn`; `docker network inspect m8m-n8n_lab`; an operator ufw capture (root-only) ≤ 7 days old | relay bound to the lab gateway only; ufw active, default deny; ALLOW lab subnet on lab bridge **before** a DENY to the relay port; no other allow in front |
| FW-P5 | `.Config.Image` and `.Image` of `m8m-n8n`; env | image ref carries `@sha256:` equal to the running image; env access blocked; community packages off |
| FW-P6 | `systemctl --user` state of `tradeai-n8n-host-deadman.timer`; `N8nHostDeadman@v1` | timer enabled+active; live receipt ≤ 15 min old; `runs_inside_n8n: false`; host alert path |

Measured on this host, 2026-10-22T13:48:59Z (`python3 scripts/probe_n8n_platform_facts.py`, dry run):

```
FW-P1 FAIL    container env EXECUTIONS_DATA_SAVE_ON_SUCCESS=none EXECUTIONS_DATA_PRUNE=true EXECUTIONS_DATA_MAX_AGE=168h EXECUTIONS_DATA_PRUNE_MAX_COUNT=<unset> EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS=false
FW-P2 FAIL    pg_roles n8n (DB_POSTGRESDB_USER): rolsuper=t; also rolcreaterole,rolcreatedb,rolreplication,rolbypassrls
FW-P3 FAIL    tradeai-n8n-drift-watch.timer not-found/inactive; data/runtime/n8n_drift_watch_last.json absent age None min; data/runtime/n8n_workflow_drift_last.json absent age None min — timer not enabled+active; no watch receipt; drift receipt absent or stale
FW-P4 FAIL    relay binds ['172.19.0.1:18092']; lab br-fdc1921eeccb 172.19.0.0/16; ufw capture ufw_status_n8n_relay.txt — no ufw capture at /home/johnclaw/trade-ai-releases/persistent-state/data/runtime/ufw_status_n8n_relay.txt (root-only: operator runs '{ sudo ufw status verbose; sudo ufw status numbered; } > /home/johnclaw/trade-ai-releases/persistent-state/data/runtime/ufw_status_n8n_relay.txt')
FW-P5 PARTIAL container .Config.Image=n8nio/n8n:2.43.0 running=sha256:c6a3a0461d1d3ffc16d849adf57606c2b028667ade70cce2faa2ff094734873c; N8N_BLOCK_ENV_ACCESS_IN_NODE=true; N8N_COMMUNITY_PACKAGES_ENABLED=false — tag pin, not a digest
FW-P6 FAIL    tradeai-n8n-host-deadman.timer not-found/inactive; data/runtime/n8n_host_deadman_last.json absent age None min — timer not enabled+active; no dead-man receipt
(dry run, nothing written)
```

This agrees with the 2026-10-15 scorecard (`N8N_FRAMEWORK_SCORECARD_20261015.md`, "Platform elements"): five FAIL,
FW-P5 PARTIAL.

## Before you start

1. **This PR is merged and released**, so the scripts and this packet are in `~/trade-ai-releases/portfolio-server/CURRENT`
   (steps 3–6 call scripts from there; the units' `ExecStart` points there). Every command below starts with
   `cd ~/trade-ai-releases/portfolio-server/CURRENT` and uses the repo venv
   `~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python` (written `$PY` in prose only; each command spells it out).
2. **Step 3 recreates the n8n container once.** Do it outside ±10 min of a release-train tick
   (`scripts/ops/release_train_arm.sh` `f_quiet_now`: 06:00 06:30 07:15 08:00 09:15 16:30 18:00 19:15 22:30
   00:00 01:15 04:30 ET). n8n-scheduled lanes miss at most the recreate window (seconds: in the FW-P2 rehearsal the same
   image answered healthz 5 s after start; the live instance's own start time was not measured).
3. Order: FW-P4 (firewall, no restart) → FW-P2 role (DB, no restart) → FW-P1 + FW-P2 switch + FW-P5 (one compose
   patch, one recreate) → FW-P3 timer → FW-P6 timer → final probe and import guard. Each step has five parts:
   **Dry run** (with the output measured here), **Apply** (one line to paste), **Verify**, **Rollback**, and what it is.
   Nothing is deleted anywhere; files are archived by copy or rename (§0 rule 6).

---

## Step 1 — FW-P4: firewall the relay's docker-bridge bind <a id="fw-p4"></a>

The run relay listens on `172.19.0.1:18092`, the gateway of the n8n lab network `m8m-n8n_lab`
(`172.19.0.0/16`, bridge `br-fdc1921eeccb`). Only that network should reach it. Two ufw rules, allow first, then
deny, both inserted at the top so no existing broader allow can shadow them:

- `allow in on br-fdc1921eeccb from 172.19.0.0/16 to 172.19.0.1 port 18092 proto tcp`
- `deny in to 172.19.0.1 port 18092 proto tcp`

Measured read-only (no sudo): `ufw status` → `ERROR: You need to be root to run this script`; `/etc/ufw/ufw.conf`
`ENABLED=yes`; `/etc/ufw/user.rules` is root-only (mode 640, mtime 2026-10-15 06:21). The current rule set could not
be read, so this step inserts at position 1 instead of assuming an order. `ss -ltn`: the relay binds only
`172.19.0.1:18092` (pid of a host python process), not `0.0.0.0`.

**Dry run** (ufw's own dry run; needs sudo, so not run by the agent — `sudo: a password is required`):

```
sudo ufw --dry-run insert 1 deny in to 172.19.0.1 port 18092 proto tcp comment 'FW-P4 relay: nobody else'
```

Expected: ufw prints the `*filter` rule text it would write (lines containing `-A ufw-user-input -p tcp -d 172.19.0.1
--dport 18092 -j DROP`) and changes nothing. If it prints `ERROR: Invalid position '1'`, the IPv4 rule list is empty
and the apply line below falls back to appending.

**Apply** (one line):

```
sudo sh -c 'ufw insert 1 deny in to 172.19.0.1 port 18092 proto tcp comment "FW-P4 relay: nobody else" || ufw deny in to 172.19.0.1 port 18092 proto tcp comment "FW-P4 relay: nobody else"; ufw insert 1 allow in on br-fdc1921eeccb from 172.19.0.0/16 to 172.19.0.1 port 18092 proto tcp comment "FW-P4 n8n lab to relay"'
```

**Verify** (capture for the probe; the probe parses it and checks the bridge name against the live network):

```
{ sudo ufw status verbose; sudo ufw status numbered; } > ~/trade-ai-releases/persistent-state/data/runtime/ufw_status_n8n_relay.txt && cd ~/trade-ai-releases/portfolio-server/CURRENT && ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/probe_n8n_platform_facts.py | grep FW-P4
```

Expected: `FW-P4 PASS    relay binds ['172.19.0.1:18092']; lab br-fdc1921eeccb 172.19.0.0/16; ufw capture …`. In the
numbered list the ALLOW rule must be `[ 1]` and the DENY `[ 2]`. Functional check: n8n still reaches the relay — the
next dispatcher tick writes a fresh `data/runtime/heartbeat-watch_last.json` (`ok_at` within 5 min). Repeat the
capture after any ufw change; the probe refuses a capture older than 7 days.

**Rollback** (one line; deletes the two rules by their exact text — removing a firewall rule is the inverse of adding
it, not a data deletion):

```
sudo sh -c 'ufw delete allow in on br-fdc1921eeccb from 172.19.0.0/16 to 172.19.0.1 port 18092 proto tcp; ufw delete deny in to 172.19.0.1 port 18092 proto tcp'
```

Risk: the ALLOW is tied to the bridge name. If the lab network is ever recreated (`docker compose down`), the bridge
gets a new name and the DENY blocks n8n → every relay call fails (loud: fan-in and dead-man heartbeat). The probe
reports FW-P4 FAIL on a bridge mismatch; re-run Apply with the new name.

---

## Step 2 — FW-P2 (part 1): create the non-superuser role `n8n_app` <a id="fw-p2"></a>

n8n connects as `n8n`, the Postgres image's bootstrap superuser (measured: `rolsuper`, `rolcreaterole`,
`rolcreatedb`, `rolreplication`, `rolbypassrls` all `t`; owner of 157 tables, 374 indexes, 25 column-owned
sequences, 2 trigger functions in `public`; extensions `plpgsql`, `uuid-ossp`). Postgres needs a bootstrap
superuser, so n8n gets its own role instead: `scripts/ops/n8n_db_app_role.py` creates `n8n_app`
(`LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 40`), grants
`CONNECT, TEMPORARY` on database `n8n` and `USAGE, CREATE` on schema `public`, and transfers ownership of every
non-extension relation, sequence, function and type in `public` to it (n8n migrations ALTER their own tables, which
only the owner may do). All in one transaction. The password is generated into
`~/.config/tradeai/n8n/n8n_app_pg_password` (mode 600, directory 700, owned by you), never printed; Postgres receives
only its SCRAM-SHA-256 verifier. n8n keeps running as `n8n` until step 3 switches it.

**Dry run** (read-only; measured 2026-10-22):

```
cd ~/trade-ai-releases/portfolio-server/CURRENT && ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/ops/n8n_db_app_role.py
```

```
PLAN (read-only; nothing written, nothing executed)
  role: n8n_app
  role_exists: False
  admin_rolsuper: True
  owners_by_kind: {'n8n:r': 157, 'n8n:i': 374, 'n8n:S': 25}
  functions: {'n8n:extension': 10, 'n8n:own': 2}
  extensions: ['plpgsql', 'uuid-ossp']
  password_encryption: scram-sha-256
  server_version: 16.15
  password_file: {'path': '/home/johnclaw/.config/tradeai/n8n/n8n_app_pg_password', 'exists': False}
SQL that --apply runs in ONE transaction (the verifier is computed at apply time; shown redacted):
BEGIN;
SET LOCAL lock_timeout = '15s';
CREATE ROLE n8n_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 40 PASSWORD 'SCRAM-SHA-256$<redacted verifier>';
GRANT CONNECT, TEMPORARY ON DATABASE n8n TO n8n_app;
GRANT USAGE, CREATE ON SCHEMA public TO n8n_app;
DO $do$ … ALTER TABLE/SEQUENCE/FUNCTION/TYPE … OWNER TO n8n_app (non-extension objects in public) … $do$;
COMMIT;
```

**Rehearsal** (agent, 2026-10-22, throwaway containers only — `fwp2-rehearsal-db` = postgres:16.15-alpine with the
live n8n schema from a read-only `pg_dump --schema-only` plus the `migrations` table; `fwp2-rehearsal-n8n` = the same
n8n image digest; both `--rm`, gone after the test; nothing touched `m8m-n8n*`):

```
apply OK: n8n_app created; password file {… 'exists': True, 'mode': '0o600', 'owner_uid': 1000, 'length': 43}; rolsuper=f; ownership and privileges verified. NEXT: apply the compose patch (…) and recreate n8n.
--apply again → REFUSED: password file … exists; re-run with --reuse-password-file … (never overwritten)
n8n 2.43.0 as n8n_app via DB_POSTGRESDB_PASSWORD_FILE: healthz {"status":"ok"} after 5s; log "Editor is now accessible via: http://localhost:5690"
SET ROLE n8n_app: ALTER TABLE execution_entity ADD COLUMN …; CREATE TABLE; CREATE INDEX → ok (rolled back)
SET ROLE n8n_app: CREATE ROLE → "permission denied to create role"; pg_read_file → "permission denied for function pg_read_file"
--verify (rehearsal containers) → verify PASS: n8n_app rolsuper=f; n8n connects as n8n_app; all checks pass
--rollback --apply → rollback OK; n8n_app rolcanlogin=f; every public relation owned by n8n again (556)
```

**Apply** (one line; n8n keeps running; locks each n8n table for the length of one transaction, seconds):

```
cd ~/trade-ai-releases/portfolio-server/CURRENT && ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/ops/n8n_db_app_role.py --apply
```

**Verify** (before step 3 it reports the one expected gap, `n8n container connects as 'n8n'`):

```
docker exec m8m-n8n-db psql -X -U n8n -d n8n -tAc "select rolname, rolsuper, rolcanlogin from pg_roles where rolname = 'n8n_app'"
```

Expected `n8n_app|f|t`. Then `… scripts/ops/n8n_db_app_role.py --verify` → `verify FAIL: n8n_app rolsuper=f; n8n
connects as n8n; n8n container connects as 'n8n', not 'n8n_app' (compose switch pending)` until step 3, PASS after.

**Rollback** (one line; `NOLOGIN` + ownership back to `n8n`; the role is never dropped):

```
cd ~/trade-ai-releases/portfolio-server/CURRENT && ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/ops/n8n_db_app_role.py --rollback --apply && mv ~/.config/tradeai/n8n/n8n_app_pg_password ~/.config/tradeai/n8n/n8n_app_pg_password.retired-$(date -u +%Y%m%dT%H%M%SZ)
```

Plan only: `--rollback` without `--apply`. If step 3 is already applied, roll step 3 back first.

---

## Step 3 — FW-P1 + FW-P2 (part 2) + FW-P5: one compose patch, one recreate <a id="fw-p1"></a><a id="fw-p5"></a>

Files in `compose/` (generated from the live compose file, read-only):

| File | Change |
|---|---|
| `fw-p5-image-digest.compose.diff.proposed` | FW-P5: `image: n8nio/n8n:2.43.0@sha256:c6a3a0461d1d3ffc16d849adf57606c2b028667ade70cce2faa2ff094734873c` — the Docker Hub OCI index digest of the tag (`docker buildx imagetools inspect n8nio/n8n:2.43.0`, 2026-10-22) and the image the container runs now, so no pull and no version change. `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` and `N8N_COMMUNITY_PACKAGES_ENABLED=false` are already set (measured) and kept. |
| `fw-p1-save-success.compose.diff.proposed` | FW-P1: `EXECUTIONS_DATA_SAVE_ON_SUCCESS: all` (was `none`); adds `EXECUTIONS_DATA_PRUNE_MAX_COUNT: "20000"` beside the existing `EXECUTIONS_DATA_PRUNE: "true"`, `EXECUTIONS_DATA_MAX_AGE: "168"`. |
| `fw-p2-n8n-app-role.compose.diff.proposed` | FW-P2: `DB_POSTGRESDB_USER: n8n_app`; **removes** `DB_POSTGRESDB_PASSWORD` from the n8n service and adds `DB_POSTGRESDB_PASSWORD_FILE: /run/secrets/n8n_app_pg_password` with a compose `secrets:` entry (file `~/.config/tradeai/n8n/n8n_app_pg_password`). |
| `fw-p1-p2-p5-combined.compose.diff.proposed` | the three above as one patch (what Apply uses) |
| `docker-compose.n8n.yml.proposed` | the resulting file (sha256 `8f8d5cda…5e49`) |

Why these values, for n8n 2.43 (read from the image's `@n8n/config`, `executions.config.js` and
`decorators.js`):

- Retention: n8n prunes its own execution rows when `EXECUTIONS_DATA_PRUNE=true`, by age (`EXECUTIONS_DATA_MAX_AGE`,
  hours; default 336) and by count (`EXECUTIONS_DATA_PRUNE_MAX_COUNT`; default 10000), soft-delete then hard-delete
  after `EXECUTIONS_DATA_HARD_DELETE_BUFFER` (1 h). 168 h keeps a week; 20000 rows caps volume. Measured volume: the n8n
  DB is 39 MB, `execution_data` 18 MB for 457 saved executions (~40 KB each, mostly errors), so 20000 rows is ≈ 0.8 GB
  worst case; `/` has 116 GB free. This is n8n's own retention of its own rows; it touches nothing else.
- Redaction: n8n 2.43's execution-data redaction (workflow `settings.redactionPolicy`, the instance
  `redaction.enforcement` floor) is license-gated — `ExecutionRedactionService.resolvePolicy` returns `'none'` unless
  `licenseState.isDataRedactionLicensed()`. This instance is unlicensed, so the redaction that applies is what keeps
  secrets out of the data: manual (editor) runs are not saved (`EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS=false`, kept),
  `$env` is blocked in nodes, n8n never writes credentials into execution data, and no workflow holds a broker,
  messaging or provider credential (§23.5). Saved data is what the nodes output: run requests and relay receipts.
- `_FILE`: n8n 2.43 reads `<VAR>_FILE` only when `<VAR>` is unset (`readEnv` in `decorators.js`), so the patch removes
  `DB_POSTGRESDB_PASSWORD` rather than leaving it next to `DB_POSTGRESDB_PASSWORD_FILE`. Compose (non-swarm) bind-mounts
  the secret read-only at `/run/secrets/n8n_app_pg_password`; the container user `node` is uid 1000, the file owner
  (measured `docker exec m8m-n8n id` → `uid=1000(node)`).

**Dry run** (measured; `patch` reads, writes nothing; `config` validates the result without reading `.env`):

```
patch --dry-run -p1 -d /home/johnclaw/m8m-bakeoff-lab < ~/trade-ai-releases/portfolio-server/CURRENT/docs/ops/packets/n8n-platform-hardening-20261022/compose/fw-p1-p2-p5-combined.compose.diff.proposed
```

```
checking file docker-compose.n8n.yml
```

`docker compose -f compose/docker-compose.n8n.yml.proposed config --quiet` → exit 0 (warnings only:
`The "N8N_PG_PASSWORD" variable is not set` / `The "N8N_ENCRYPTION_KEY" variable is not set`, because it was run
outside the lab directory on purpose). Applying the three step patches in order to a copy of the live file gives a file
byte-identical to `docker-compose.n8n.yml.proposed` (`cmp` → equal; also pinned by the tests).

**Apply** (one line; needs step 2 done — the password file must exist; outside the release-train tick windows):

```
cd /home/johnclaw/m8m-bakeoff-lab && test -s ~/.config/tradeai/n8n/n8n_app_pg_password && cp -np docker-compose.n8n.yml docker-compose.n8n.yml.bak-20261022-pre-fw-p125 && patch -p1 < ~/trade-ai-releases/portfolio-server/CURRENT/docs/ops/packets/n8n-platform-hardening-20261022/compose/fw-p1-p2-p5-combined.compose.diff.proposed && docker compose -f docker-compose.n8n.yml up -d n8n
```

Only the `n8n` service changes; `n8n-db` keeps its config and is not recreated.

**Verify**:

```
cd ~/trade-ai-releases/portfolio-server/CURRENT && ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/probe_n8n_platform_facts.py | grep -E 'FW-P(1|2|5)' && ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/ops/n8n_db_app_role.py --verify
```

Expected: `FW-P1 PASS`, `FW-P2 PASS    pg_roles n8n_app (DB_POSTGRESDB_USER): rolsuper=f`, `FW-P5 PASS`, and
`verify PASS: n8n_app rolsuper=f; n8n connects as n8n_app; all checks pass`. Then curl
`http://127.0.0.1:5678/healthz` → `{"status":"ok"}`, and within an hour a saved success exists:
`docker exec m8m-n8n-db psql -X -U n8n -d n8n -tAc "select count(*) from execution_entity where status = 'success' and \"startedAt\" > now() - interval '1 hour'"`
→ a number > 0 (before the change: success rows only from `integrated`/`error` modes).

**Rollback** (one line; keeps the patched file as an archive and restores the backup):

```
cd /home/johnclaw/m8m-bakeoff-lab && mv docker-compose.n8n.yml docker-compose.n8n.yml.rolledback-$(date -u +%Y%m%dT%H%M%SZ) && cp -p docker-compose.n8n.yml.bak-20261022-pre-fw-p125 docker-compose.n8n.yml && docker compose -f docker-compose.n8n.yml up -d n8n
```

n8n then connects as `n8n` again (the superuser still has every privilege), so the step-2 role can stay or be rolled
back separately.

---

## Step 4 — FW-P3: drift check on a host timer, P1 on drift <a id="fw-p3"></a>

Reuses the existing drift checker (`scripts/check_n8n_workflow_drift.py`, the producer of
`N8nWorkflowDriftReceipt@v1`, which the incident fan-in already reads). New: `scripts/n8n_drift_watch.py` runs it,
writes that receipt to its canonical path, and on DRIFT or MISSING_IN_GIT pages **P1** through the host SYSTEM ops
transport (`scripts/lib/autonomy_watchdog/telegram_system.send_system` — the incident notifier's and the autonomy
watchdog's sender; never n8n, never the n8n-fired fan-in). One page per drift signature, a reminder every 6 h while
it stays, one "CLEARED" notice when git and live agree again. It writes `N8nDriftWatch@v1` to
`data/runtime/n8n_drift_watch_last.json`. Units: `units/tradeai-n8n-drift-watch.{service,timer}.proposed`
(every 15 min at :07/:22/:37/:52).

**Dry run** (measured; live SELECT, writes and sends nothing):

```
cd ~/trade-ai-releases/portfolio-server/CURRENT && ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/n8n_drift_watch.py
```

```
n8n drift watch (dry_run): verdict CLEAN  OK=17 DRIFT=0 MISSING_IN_GIT=0  page NONE  (dry run, nothing written or sent)
```

Unit syntax: `systemd-analyze --user verify` on the four units → exit 0 (its only messages are about other,
already-installed units). Calendar: `systemd-analyze calendar '*-*-* *:07/15:00'` → next 09:52, 10:07, 10:22 EDT.

**Apply** (one line):

```
cd ~/trade-ai-releases/portfolio-server/CURRENT/docs/ops/packets/n8n-platform-hardening-20261022/units && install -m 644 tradeai-n8n-drift-watch.service.proposed ~/.config/systemd/user/tradeai-n8n-drift-watch.service && install -m 644 tradeai-n8n-drift-watch.timer.proposed ~/.config/systemd/user/tradeai-n8n-drift-watch.timer && systemctl --user daemon-reload && systemctl --user enable --now tradeai-n8n-drift-watch.timer && systemctl --user start tradeai-n8n-drift-watch.service
```

**Verify**: `systemctl --user list-timers tradeai-n8n-drift-watch.timer` shows a next run;
`cat ~/trade-ai-releases/persistent-state/data/runtime/n8n_drift_watch_last.json` → `"schema": "N8nDriftWatch@v1"`,
`"mode": "live"`, `"verdict": "CLEAN"`; the probe → `FW-P3 PASS`. P1 path proof without touching n8n: the hermetic
tests (`tests/test_n8n_platform_hardening_20261022.py::test_drift_pages_p1_once_through_the_host_sender_then_recovers`).

**Rollback** (one line; the unit files are archived by rename, not deleted):

```
systemctl --user disable --now tradeai-n8n-drift-watch.timer && mv ~/.config/systemd/user/tradeai-n8n-drift-watch.timer ~/.config/systemd/user/tradeai-n8n-drift-watch.timer.retired-$(date -u +%Y%m%dT%H%M%SZ) && mv ~/.config/systemd/user/tradeai-n8n-drift-watch.service ~/.config/systemd/user/tradeai-n8n-drift-watch.service.retired-$(date -u +%Y%m%dT%H%M%SZ) && systemctl --user daemon-reload
```

---

## Step 5 — FW-P6: a dead-man outside n8n <a id="fw-p6"></a>

Today the only n8n heartbeat watcher (`heartbeat-watch`) is fired by n8n, and its breach rows reach you through the
fan-in, also fired by n8n (WS1-15). `scripts/n8n_host_deadman.py` runs from a host timer and checks (1) `GET
http://127.0.0.1:5678/healthz` (reusing `n8n_lab_watchdog.check`) and (2) that n8n is still scheduling — the
`heartbeat-watch` lane receipt (fired only by n8n, no cron line) has `ok_at` within 20 min. Two consecutive bad runs
page **P1** through the same host SYSTEM ops sender; reminder every 6 h; one "CLEARED" notice. It writes
`N8nHostDeadman@v1` to `data/runtime/n8n_host_deadman_last.json` (`runs_inside_n8n: false`). It restarts nothing.
Limit, stated on the receipt: it cannot see this host's total outage — `scripts/offbox_deadman.py` covers that.
Units: `units/tradeai-n8n-host-deadman.{service,timer}.proposed` (every 5 min at :02/:07/…).

**Dry run** (measured; writes and sends nothing):

```
cd ~/trade-ai-releases/portfolio-server/CURRENT && ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/n8n_host_deadman.py
```

```
n8n host dead-man (dry_run): OK  healthz ok; heartbeat ok age 1.4 min  page NONE  (dry run, nothing written or sent)
```

Forced-bad dry run (closed port, threshold 1) — the page it would send, previewed through `preview_send`, not sent:

```
… scripts/n8n_host_deadman.py --url http://127.0.0.1:9/healthz --threshold 1 --json
BAD down
"action": "PAGE", "identity": "n8n-deadman:20261022T133133Z:p1",
"p1_path": "host:scripts/lib/autonomy_watchdog/telegram_system.send_system (SYSTEM ops family; n8n not involved)",
"preview": {"would_send": true, "reason": "would_send"},
"text": "TRADE AI SYSTEM ALERT — P1 n8n DEAD-MAN (host watcher; n8n not involved)\n• healthz: FAIL (http None, connection_refused)\n• heartbeat (heartbeat-watch): ok (…)\nBad since 2026-10-22T13:31:33Z. … Runbook: docs/ops/packets/n8n-platform-hardening-20261022/README.md#fw-p6"
```

**Apply** (one line):

```
cd ~/trade-ai-releases/portfolio-server/CURRENT/docs/ops/packets/n8n-platform-hardening-20261022/units && install -m 644 tradeai-n8n-host-deadman.service.proposed ~/.config/systemd/user/tradeai-n8n-host-deadman.service && install -m 644 tradeai-n8n-host-deadman.timer.proposed ~/.config/systemd/user/tradeai-n8n-host-deadman.timer && systemctl --user daemon-reload && systemctl --user enable --now tradeai-n8n-host-deadman.timer && systemctl --user start tradeai-n8n-host-deadman.service
```

**Verify**: `cat ~/trade-ai-releases/persistent-state/data/runtime/n8n_host_deadman_last.json` → `"schema":
"N8nHostDeadman@v1"`, `"mode": "live"`, `"status": "OK"`, `"runs_inside_n8n": false`; the probe → `FW-P6 PASS`.
Optional live drill (a P1 page reaches you): with n8n otherwise idle, `docker stop m8m-n8n` for 11 minutes, expect
one "P1 n8n DEAD-MAN" message, then `docker start m8m-n8n` and one "CLEARED" (an n8n stop is an operator act; skip if
not wanted — the hermetic tests cover the state machine).

**Rollback** (one line):

```
systemctl --user disable --now tradeai-n8n-host-deadman.timer && mv ~/.config/systemd/user/tradeai-n8n-host-deadman.timer ~/.config/systemd/user/tradeai-n8n-host-deadman.timer.retired-$(date -u +%Y%m%dT%H%M%SZ) && mv ~/.config/systemd/user/tradeai-n8n-host-deadman.service ~/.config/systemd/user/tradeai-n8n-host-deadman.service.retired-$(date -u +%Y%m%dT%H%M%SZ) && systemctl --user daemon-reload
```

---

## Step 6 — record the platform facts and re-run the import gate <a id="final"></a>

**Dry run**: `… scripts/probe_n8n_platform_facts.py` (no `--write`) → expect six `PASS` lines.

**Apply** (one line; writes the host-probe receipt and runs the gate against it):

```
cd ~/trade-ai-releases/portfolio-server/CURRENT && ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/probe_n8n_platform_facts.py --write && ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/check_n8n_import_ready.py docs/implementation/n8n-maturity/workflows/fabric/tradeai-fabric-release-train.json --relay-url http://172.19.0.1:18092 --known-id tradeai-fabric-error --probe-host
```

**Verify**: the guard prints `platform facts: host_probe (as of …)` and `FW-P1 … FW-P6 PASS`. It still REFUSES the
release-train workflow until the runtime obligations have host-signed evidence (`--runtime-evidence`,
`framework_pending_evidence.json` `runtime_pending`) — this packet clears the platform half only. Measured today with
`--probe-host`:

```
REFUSED tradeai-fabric-release-train tradeai-fabric-release-train  framework_gate
platform facts: host_probe (as of 2026-10-22T13:34:08+00:00)
  FW-P1 FAIL    container env EXECUTIONS_DATA_SAVE_ON_SUCCESS=none …
  FW-P2 FAIL    pg_roles n8n (DB_POSTGRESDB_USER): rolsuper=t; also rolcreaterole,rolcreatedb,rolreplication,rolbypassrls
  FW-P3 FAIL    tradeai-n8n-drift-watch.timer not-found/inactive; …
  FW-P4 FAIL    relay binds ['172.19.0.1:18092']; lab br-fdc1921eeccb 172.19.0.0/16; … no ufw capture …
  FW-P5 PARTIAL container .Config.Image=n8nio/n8n:2.43.0 … — tag pin, not a digest
  FW-P6 FAIL    tradeai-n8n-host-deadman.timer not-found/inactive; …
1 checked, 1 refused
```

For release-train step F, export `N8N_PLATFORM_FACTS=~/trade-ai-releases/persistent-state/data/runtime/n8n_platform_facts_last.json`
before running `scripts/ops/release_train_arm.sh` so its gate reads the probe (the file must be ≤ 24 h old).

**Rollback**: none needed (read-only plus one receipt file).

---

## Pre-build check (AGENTS §13.5) and what was reused

Searched before building: open PRs (`gh pr list --search` n8n / superuser / drift / dead-man / ufw / FW-P — no
overlap; #1918 is the release-train H.0 shadow switch); `N8nWorkflowDriftReceipt@v1` producer
(`scripts/check_n8n_workflow_drift.py`, reused via import, not copied); the host P1 sender (`send_system`, as
`scripts/incident_notifier.py` uses it); the outside-n8n healthz probe (`scripts/n8n_lab_watchdog.py`, reused); the
read path (`scripts/lib/n8n_live_inventory.py`); the off-box dead-man (`scripts/offbox_deadman.py`, a different
watcher: the whole host). New contracts: `N8nDriftWatch@v1`, `N8nHostDeadman@v1`; `N8nPlatformFacts@v1` gains
`source_kind`/`probed_at` (old files stay readable, capped at PARTIAL).

## Findings for the operator

1. **The P1 path for drift was P2.** `check_n8n_workflow_drift.py` labels drift P2 in its fan-in findings ("cannot
   widen what runs"), while §23.23 (2) says drift pages P1. The drift watch pages P1 on the host path; the fan-in P2
   row is left as is (a second, batched notice). Changing the fan-in severity is a one-line follow-up if wanted.
2. **n8n also listens on the tailnet address** (`ss -ltn`: `100.66.120.124:5678` and the tailnet IPv6, besides
   `127.0.0.1:5678`), i.e. the Tailscale HTTPS front of the editor (session 2026-05-20). Not in FW-P4's scope (the
   relay bind); noted because §23.24 Security (4) says "loopback or docker-bridge binds only".
3. **The bootstrap superuser `n8n` remains** (Postgres needs one) with local-socket trust inside the db container, and
   the governance reads (`n8n_live_inventory.run_select`, the drift checker, this probe) still use it through
   `docker exec`. A read-only `n8n_reader` role for those reads is the natural next split (§23.23 "DB role split").
4. **Optional:** pin `postgres:16.15-alpine` by digest too (`postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea`,
   measured). Left out because it recreates the DB container.
5. n8n 2.43 logs `Postgres 16 is outside the supported range and receives compatibility support only` (seen in the
   rehearsal). Not a blocker today.
