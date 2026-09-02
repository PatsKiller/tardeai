# Host and Runtime Inventory — ms01-openclaw — 2026-07-24

**Observation window:** 2026-07-24T17:23:52Z – 2026-07-24T17:41Z (local 13:23–13:41 EDT, UTC−04:00)
**Method:** read-only commands only. No `sudo`, no service state changes, no writes to production data.
**Sanitisation:** no tokens, passwords, cookies, OAuth material, webhook URLs, private keys, DSNs or
environment *values* appear in this document. Variable and file *names* only.

Status vocabulary: **VERIFIED** (directly observed), **PARTIAL** (observed but incomplete or
inconsistent), **BLOCKED** (not obtainable without privilege escalation or a prohibited action).

---

## 1. Deployed repository state

| Fact | Observed value | Evidence | Status |
|---|---|---|---|
| Deployed path | `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` | `git rev-parse --show-toplevel` | VERIFIED |
| Branch | `main` (attached, not detached) | `git branch --show-current` | VERIFIED |
| HEAD SHA | `d72f85086aa79f76fb4c985089145416f99830a4` | `git rev-parse HEAD` | VERIFIED |
| Describe | `d72f8508-dirty` | `git describe --always --dirty --tags` | VERIFIED |
| Origin | `https://github.com/PatsKiller/tardeai` (no embedded credentials observed) | `git remote -v` | VERIFIED |
| Clean/dirty | **DIRTY** — 74 changed paths (70 modified, 1 staged, 3 untracked) | `git status --porcelain=v1` | VERIFIED |
| Position vs `origin/main` | **3 behind, 0 ahead** — HEAD is a clean ancestor of `origin/main` | `git rev-list --left-right --count` | VERIFIED |
| Corresponds to | `main` lineage only — **not** PR #166 and **not** PR #168 | `git branch -a --contains` | VERIFIED |

`origin/main` = `3964936a1fcba6db6e7cd0354964dada79031918`.
PR #166 head (`agent/defense-sectors-institutional-polish`) = `5651b7da…`.
PR #168 head (`agent/defense-data-quality-v1`) = `d5c8f0b7…`.

**Discrepancy D-1.** The live tree is 3 commits behind `origin/main` and carries 74 uncommitted
paths. The staged path is `apps/command-center-v3/src/lib/supportResistance.tsx`; untracked paths are
`components/IndustryAnalystLeaders.tsx`, `components/SectorEntryIdeas.tsx` and
`e2e/screenshots/alpaca-live-read/`. These are unrelated in-flight operator/session work.
**Not staged, reset, cleaned or stashed by this inventory.** All inventory work was done in a
separate worktree.

**Next action:** land or park the in-flight tree changes before any deployment, so the deployed SHA
becomes reproducible. Today it is not.

---

## 2. OpenClaw inventory

| Fact | Observed value | Evidence | Status |
|---|---|---|---|
| Installed version | **2026.6.11** | `npm ls -g --depth=0`; `/usr/lib/node_modules/openclaw/package.json` | VERIFIED |
| Provenance | npm global package (`openclaw`), not a git checkout | `npm ls -g`; no `.git` in package dir | VERIFIED |
| Package manager | npm 10.9.8 on Node v22.23.1 | `npm --version`, `node --version` | VERIFIED |
| Executable | `/usr/bin/openclaw` → `/usr/lib/node_modules/openclaw/dist/index.js` | `command -v`, unit `ExecStart` | VERIFIED |
| Install mtime | 2026-07-04T11:37:06 | `stat` on `package.json` | VERIFIED |
| Runtime home | `/home/johnclaw/.openclaw` (mode `drwx------`, `johnclaw:johnclaw`) | `stat` | VERIFIED |
| Service user/group | `johnclaw` (systemd **user** unit) | `systemctl --user show` | VERIFIED |
| WorkingDirectory | `/home/johnclaw` | unit property | VERIFIED |
| Port | **18789**, bound `0.0.0.0` (all interfaces) | `ss -ltnup`, `ExecStart … gateway --port 18789` | VERIFIED |
| EnvironmentFile | `/home/johnclaw/.openclaw/credentials/gog.env` (path only; contents not read) | unit `EnvironmentFiles` | VERIFIED |
| Drop-in | `…/openclaw-gateway.service.d/gog-keyring.conf` | unit `DropInPaths` | VERIFIED |
| Unit state | `active/running`, `enabled`, `Restart=always`, `NRestarts=0`, `Result=success` | `systemctl --user show` | VERIFIED |
| Git SHA | N/A — installed from npm, not source | — | VERIFIED |
| Latest available | **2026.7.1-2** | `npm view openclaw version` (read-only registry query) | VERIFIED |

**Discrepancy D-2.** The unit *description* reads `OpenClaw Gateway (v2026.4.11)` while the installed
package is **2026.6.11**. The description string is stale and must not be used as a version source.
Version was taken from package metadata, per the "do not guess from a filename" rule.

**Next action:** correct the unit description at the next authorised maintenance window (requires a
unit edit + daemon-reload — **prohibited in this task**).

---

## 3. Hermes inventory

Two distinct things carry the name "Hermes" on this host. Conflating them would be an error.

### 3a. Hermes Agent CLI (external package)

| Fact | Observed value | Evidence | Status |
|---|---|---|---|
| Installed version | **v0.15.2 (build 2026.5.29.2)** | `hermes --version` | VERIFIED |
| Provenance | Python venv install; not importable as a named distribution via `importlib.metadata` | `importlib.metadata` scan returned no `hermes*` dist | PARTIAL |
| Executable | `/home/johnclaw/.local/bin/hermes` → `/home/johnclaw/.local/share/hermes-agent-venv/bin/hermes` | `ls -la`, shebang | VERIFIED |
| Python env | `/home/johnclaw/.local/share/hermes-agent-venv`, Python 3.14.4 | shebang, `--version` output | VERIFIED |
| Runtime home | `/home/johnclaw/.hermes` (mode `drwx------`) | `stat` | VERIFIED |
| Config paths | `/home/johnclaw/.hermes/config.yaml`, `/home/johnclaw/.hermes/SOUL.md` (paths only; not read) | `ls -la` | VERIFIED |
| Credential file present | `/home/johnclaw/.hermes/auth.json` — **deliberately not opened** | `ls -la` | VERIFIED |
| Update state | `.update_check` reports `behind: 1`, `rev: null` | `/home/johnclaw/.hermes/.update_check` | VERIFIED |
| Git SHA | Not applicable / not recorded by the install | — | PARTIAL |
| Ports | None owned directly; gateway unit is disabled (below) | `ss -ltnup` | VERIFIED |

**Discrepancy D-3 (significant).** `hermes-gateway.service` (user unit, `disabled`, `inactive/dead`)
has an `ExecStart` pointing at
`…/hermes_sidecar/install/.venv/bin/python` — **this path does not exist**. `hermes_sidecar/install/`
is absent entirely. The unit is therefore unrunnable as written. It is currently disabled, so this is
latent rather than active breakage, but the unit is misleading.

### 3b. Hermes in-repo agent fleet (first-party code)

Runs from the main repo venv, not the CLI venv:
`/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/hermes_*.py`.
Scheduled by user systemd timers and by ~454 active user-crontab lines.
Auto-graft / auto-promotion settings were **not** located in this pass — see §13 unverified list.

---

## 4. Service and systemd state (relevant units only)

### System units

| Unit | Active/Sub | Enabled | FragmentPath | User | ExecStart (path) | Restart | Result |
|---|---|---|---|---|---|---|---|
| `tradeai-portfolio-server.service` | active/running | enabled | `/etc/systemd/system/…` | `johnclaw` | repo `.venv/bin/python scripts/portfolio_server.py` | always | success |
| `ollama.service` | active/running | enabled | `/etc/systemd/system/…` | `ollama` | `/usr/local/bin/ollama serve` | always | success |
| `tradeai-continuous.service` | inactive/dead | disabled | — | — | — | — | — |
| `tradeai-reprice.service` | inactive/dead | static | — | — | — | — | — |

`ollama.service` carries three drop-ins:
`99-tradeai-llm-safety.conf`, `override.conf`, `zz-tradeai-llm-safety.conf`.

The live portfolio server (port 7777) has `WorkingDirectory` = the **primary repo tree**, confirming
that tree is production-live and explaining why it must not be disturbed.

### User units — selected

| Unit | Active/Sub | Enabled | Restart | NRestarts | Result |
|---|---|---|---|---|---|
| `openclaw-gateway.service` | active/running | enabled | always | 0 | success |
| `portfolio-server.service` | **activating/auto-restart** | enabled | on-failure | **15081** | **exit-code (status=1)** |
| `hermes-gateway.service` | inactive/dead | disabled | always | 0 | success |
| `hermes-autonomous-loop.service` | **failed** | static | no | 0 | exit-code (1) |
| `hermes-deep-research-local.service` | **failed** | — | — | — | — |
| `hermes-external-feedback.service` | **failed** | — | — | — | — |
| `tradeai-iris-taxonomy.service` | **failed** | static | no | 0 | **timeout (SIGTERM after 5min)** |
| `chatgpt-oauth-proxy.service` | active/running | — | — | — | — |
| `grok-oauth-proxy.service` | active/running | — | — | — | — |
| `heartbeat-receiver.service` | active/running | — | — | — | — |

**Discrepancy D-4 (significant).** There are **two** portfolio-server definitions with the *same*
`ExecStart` and `WorkingDirectory`: the system unit (active, owns port 7777) and a user unit that has
restarted **15,081 times** and exits `status=1` immediately (start and stop timestamps identical).
The user unit is a redundant duplicate that cannot bind the port the system unit already holds. It is
burning a restart cycle every few seconds indefinitely.

**Discrepancy D-5.** Four units are in `failed` state: three Hermes lanes plus the IRIS taxonomy agent
(which was SIGTERM'd on a 5-minute timeout at 07:00 EDT today).

**Next action for D-4/D-5:** disabling the duplicate user unit and triaging the failed units both
require `systemctl` state changes — **prohibited in this task**. Raised for operator scheduling.

A `portfolio_server_watchdog.sh` runs from cron every 2 minutes, which is likely why D-4 has gone
unnoticed: the system unit is externally supervised regardless of the user unit's state.

---

## 5. Listening ports

| Proto | Bind | Port | Process | Owning service | Exposure |
|---|---|---|---|---|---|
| tcp | `0.0.0.0` | 7777 | `python` (pid 1585131) | `tradeai-portfolio-server.service` | **all interfaces** |
| tcp | `0.0.0.0` | 7776 | `python3` (pid 3383) | secondary dashboard | **all interfaces** |
| tcp | `0.0.0.0` | 18789 | `node` (pid 3408) | `openclaw-gateway.service` | **all interfaces** |
| tcp | `*` | 11434 | — | `ollama.service` | **all interfaces** |
| tcp | `*` | 9090 | — | metrics/exporter (unattributed) | **all interfaces** |
| tcp | `127.0.0.1` | 8645 | `python3` (pid 3385) | `grok-oauth-proxy.service` | loopback only |
| tcp | `127.0.0.1` | 8646 | `python3` (pid 3378) | `chatgpt-oauth-proxy.service` | loopback only |
| tcp | `127.0.0.1` | 5432 | — | PostgreSQL | loopback only |

Other listeners observed (not project-attributed): 22, 53, 443, 631, 3389, 5433, 8443, 18798, 18888
and several ephemeral high ports.

**Observation O-1.** Ollama (11434) and the two dashboards bind all interfaces. Host reachability is
mediated by Tailscale (`tailscaled.service` active) rather than by bind address. The OAuth proxies and
PostgreSQL are correctly loopback-scoped. No process was killed or restarted.

**Next action:** confirm firewall/Tailscale ACL posture for 11434 and 9090 — an unauthenticated
Ollama endpoint on all interfaces is the highest-value item here. Not changed by this inventory.

---

## 6. Active channels

| Channel | State | Config path | Classification |
|---|---|---|---|
| OpenClaw gateway (HTTP) | enabled, running | `/home/johnclaw/.config/systemd/user/openclaw-gateway.service` | production |
| OpenClaw credentials env | referenced | `/home/johnclaw/.openclaw/credentials/gog.env` (**not read**) | production |
| Hermes gateway | **disabled/dead** | `/home/johnclaw/.config/systemd/user/hermes-gateway.service` | inert (broken path, D-3) |
| Grok OAuth lane | enabled, running | loopback `:8645` | production (free OAuth lane) |
| ChatGPT/codex OAuth lane | enabled, running | loopback `:8646` | production (free OAuth lane) |

Telegram/WhatsApp channel enablement is configured inside `/home/johnclaw/.openclaw/` and
`/home/johnclaw/.hermes/config.yaml`. Those files are credential-bearing; **they were not opened**,
so per-channel enable/disable state is **BLOCKED** for this pass rather than guessed.

No tokens, webhook URLs or account identifiers are recorded in this document.

---

## 7. Cron and timer inventory

- **User crontab:** 454 active (non-comment) lines. Project-relevant lanes observed include
  `portfolio_orchestrator.py` (07:15 Mon–Fri), `price_db_sync.py` (07:20), `portfolio_level_qa.py`
  (07:40), `hermes_coordinator.py` (*/15), `hermes_watchlist_scorer.py` (*/15),
  `hermes_directive_discovery.py` (*/30, `--apply`), `hermes_news_bridge.py` (*/10 in 04–11),
  `hermes_score_alerts.py` (:15,:45 `--send`), `portfolio_repricer.py` + `holdings_reconcile.py --apply`
  + `phase3_lookthrough_resolver.py` (16:10), and `portfolio_server_watchdog.sh` (*/2).
- **`/etc/crontab`, `/etc/cron.d`:** only `anacron` and `e2scrub_all`. No project entries.
- **User timers (17 relevant):** `trade-ai-news-monitor`, `hermes-momentum-catalyst-morning`,
  `hermes-advisory-cache-worker`, `hermes-shadow-scorer`, `tradeai-sm-render`,
  `hermes-autonomous-loop`, `tradeai-portfolio-backup-cadence`, `hermes-observation-check`,
  `hermes-deep-research-local`, `hermes-backlog-health-check`, `hermes-source-discovery-dryrun`,
  `hermes-librarian-backlog-loop`, `hermes-external-feedback`,
  `hermes-embedding-promotion-review`, `tradeai-iris-taxonomy`, `tradeai-governance-pipeline`,
  `portfolio-price-cache`.
- **System timers:** `tradeai-continuous.timer` (enabled), `tradeai-reprice.timer` (enabled).

Nothing was modified. `crontab -e` was not invoked.

---

## 8. Environment inheritance

Inheritance chains observed (names and paths only — **no values read**):

```
tradeai-portfolio-server.service (system)
  └─ WorkingDirectory: <repo root>
     └─ repo .venv/bin/python scripts/portfolio_server.py
        └─ application-level dotenv loader (repo .env)

openclaw-gateway.service (user)
  └─ EnvironmentFile: /home/johnclaw/.openclaw/credentials/gog.env
     └─ DropIn: openclaw-gateway.service.d/gog-keyring.conf
        └─ /usr/bin/node …/openclaw/dist/index.js

cron lanes
  └─ $PROJ / $PY crontab variables
     └─ scripts/safe_flock.sh | scripts/llm_priority_guard.sh (wrappers)
        └─ repo .venv python
           └─ application dotenv loader

tradeai-sm-render.service (timer, 4-hourly)
  └─ renders Bitwarden SM secrets into a tmpfs env cache  ← additional injection point
```

No system unit among those inspected declares an `EnvironmentFile` except
`openclaw-gateway.service`. Secrets therefore reach most Trade AI processes through the
**application-level dotenv loader** and the **Bitwarden SM tmpfs render**, not through systemd.

`/proc/<pid>/environ` was **not** read for any process. Required variable *names* were not
enumerated in this pass because doing so safely means parsing `.env`-shaped files, and the risk of
incidental value disclosure outweighed the value of the list — recorded as **BLOCKED by policy**
rather than attempted.

---

## 9. Runtime and package versions

| Component | Version | Evidence | Status |
|---|---|---|---|
| Python (system) | 3.14.4 | `python3 --version` | VERIFIED |
| Node | v22.23.1 | `node --version` | VERIFIED |
| npm | 10.9.8 | `npm --version` | VERIFIED |
| OpenAI Python SDK | **2.30.0** | `importlib.metadata` in repo venv | VERIFIED |
| Anthropic SDK | 0.87.0 | `importlib.metadata` | VERIFIED |
| psycopg2-binary | 2.9.12 | `importlib.metadata` | VERIFIED |
| `pgvector` (Python pkg) | **not installed** | `importlib.metadata` | VERIFIED |
| Ollama | 0.24.0 | `ollama --version` | VERIFIED |

### Ollama models

| Model | ID | Size | Modified |
|---|---|---|---|
| `gemma3:4b` | 6d0ee830bb54 | 3.3 GB | ~22 hours ago |
| `gemma3:27b` | 1dcfe4e5d67c | 17 GB | ~2 weeks ago |
| `gemma3-overnight:latest` | e2c134128354 | 17 GB | ~2 weeks ago |
| `gemma3:12b` | 7a42254767c1 | 8.1 GB | ~2 weeks ago |
| `qwen3:8b` | 500a1f067a9f | 5.2 GB | ~6 weeks ago |
| `gemma3:12b-ctx4k` | 36c01589bb98 | 8.1 GB | ~6 weeks ago |
| `qwen3-embedding:8b` | 64b933495768 | 4.7 GB | ~2 months ago |
| `nomic-embed-text:latest` | 0a109f422b47 | 274 MB | ~2 months ago |

Quantization strings are not exposed by `ollama list` output on this version — **PARTIAL**; obtaining
them needs `ollama show` per model (safe, but not run in this pass).

Model routing (local/default/critical-cloud) and embedding-model selection are configured in repo
config and the LLM safety drop-ins; the **effective merged routing table was not resolved** in this
pass — **PARTIAL**, see §13. No model was pulled or deleted.

---

## 10. PostgreSQL and pgvector

| Fact | Observed value | Status |
|---|---|---|
| PostgreSQL version | **17.10 (Ubuntu 17.10-0ubuntu0.25.10.1)** | VERIFIED |
| Project database | `trade_ai` | VERIFIED |
| Installed extensions | **`plpgsql 1.0` only** | VERIFIED |
| `pgvector` extension | **NOT INSTALLED** | VERIFIED |
| `public` schema tables | 658 | VERIFIED |
| Bind | `127.0.0.1:5432` (loopback only) | VERIFIED |

### Roles

| Role | Attributes | Can log in |
|---|---|---|
| `postgres` | super, createdb, createrole, replication | yes |
| `trade_ai` | (login only) | **yes** |
| `hermes_readonly` | none | **NO** |
| `hermes_staging_writer` | none | **NO** |

**Role memberships:** none. `pg_authid` was not queried; no password material was accessed.

### Effective privileges

| Role | Schema | Tables | Privileges | USAGE | CREATE |
|---|---|---|---|---|---|
| `hermes_readonly` | `public` | 57 | `SELECT` | yes | no |
| `hermes_staging_writer` | `public` | 18 | `INSERT, SELECT, UPDATE` | yes | no |

**Discrepancy D-6 (significant).** The read-only and isolated-writer roles exist and carry
*correctly scoped grants*, but **both have `rolcanlogin = false`**. The separation is designed but
**inert** — no process can currently connect as either role. All application traffic therefore runs
as `trade_ai`, which owns the schema objects.

**Discrepancy D-7.** Six residual schemas `crash_031c1d08`, `crash_600f8d27`, `crash_6782de26`,
`crash_7483b736`, `crash_970df40b`, `crash_f58bcaff` — 6 tables each, all owned by `trade_ai`.
These look like crash-recovery leftovers. Not touched.

**Discrepancy D-8.** `pgvector` is absent while an embedding model (`qwen3-embedding:8b`,
`nomic-embed-text`) is installed and embedding/promotion review lanes are scheduled. Either
embeddings are stored without the extension or that lane is non-functional. Not resolved here.

---

## 11. Filesystem layout

| Path | Present | Mode | Owner |
|---|---|---|---|
| `/opt/trade-ai` | **absent** | — | — |
| `/var/lib/trade-ai*` | **absent** | — | — |
| `/etc/trade-ai*` | **absent** | — | — |
| `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` | yes | `drwx------` | `johnclaw:johnclaw` |
| `/home/johnclaw/.openclaw` | yes | `drwx------` | `johnclaw:johnclaw` |
| `/home/johnclaw/.hermes` | yes | `drwx------` | `johnclaw:johnclaw` |
| `/home/johnclaw/.local/share/hermes-agent-venv` | yes | `drwxrwxr-x` | `johnclaw:johnclaw` |
| `/usr/lib/node_modules/openclaw` | yes | `drwxr-xr-x` | `root:root` |

**Observation O-2.** There is no FHS-style deployment (`/opt`, `/var/lib`, `/etc`). The entire
Trade AI runtime lives under a single user's home directory, and the production service runs from a
**git worktree that is currently dirty**. **13 git worktrees** are registered against the repo.

---

## 12. Rollback artifacts

| Artifact | Size | Date | Notes |
|---|---|---|---|
| `~/backups/2026-07-04T15-33-38.793Z-openclaw-backup.tar.gz` | 2.07 GB | 2026-07-04 | **Post-dates the 2026.6.11 install (mtime 07-04T11:37)** — covers the current version |
| `~/backup_openclaw_20260416_2113.tar.gz` | 1.18 MB | 2026-04-16 | Predates current version; not a valid rollback target |
| `~/backups/trade_ai_db_20260604_214814.sql.gz` | 1.00 GB | 2026-06-04 | **50 days old** |
| `~/backups/trade_ai_pre_hermes_phase1_20260530_094558.sql.gz` | 85 KB | 2026-05-30 | Schema-scoped, small |
| `~/backups/trade_ai_backup_20260524.zip` | 3.06 GB | 2026-05-24 | Full tree |
| `~/backups/tardeai_pre_purge_20260704_1932.bundle` | 165 MB | 2026-07-04 | Git bundle |
| `~/doc_hygiene_backup_2026-05-31.tgz` | 4.44 GB | 2026-05-31 | Docs |
| `~/ollama_upgrade_backup_20260528_174415/` | dir | 2026-05-28 | Precedent for model-stack rollback |
| `~/phase3_backup_rollback_all.sh` | 7.2 KB | 2026-04-13 | Rollback script |
| Crontab backups (≥12 files) | ~76–101 KB each | 2026-06-22 → 2026-07-06 | Well covered |
| Repo helpers | — | — | `backup_all.sh`, `backup_secrets_state.sh`, `backup_verify.py`, `full_system_backup.py`, `report_backup_readiness.py` |

SHA-256 hashing of the multi-GB archives was deliberately skipped (hours of I/O on live hardware for
marginal inventory value) — **PARTIAL**. Secret-bearing backup contents were **not opened**.

**Gap G-1.** There is **no versioned/previous release directory** for either OpenClaw or Hermes, and
**exactly one** Hermes venv (`hermes-agent-venv`) with no dated sibling. A Hermes in-place upgrade is
therefore **not reversible** today without first copying the venv.

**Gap G-2.** The newest full database dump is **2026-06-04 (50 days old)**. A daily
`tradeai-portfolio-backup-cadence.timer` exists and last ran 2026-07-24T02:30, but its output was not
located under `~/backups` — either it writes elsewhere or it is not producing full dumps. **PARTIAL.**

---

## 13. Conclusions

### Is an OpenClaw update required?
**No — but one is available.** Installed **2026.6.11**; registry latest **2026.7.1-2**. Nothing
observed is broken *because of* the version. The only version-linked defect is cosmetic (stale unit
description, D-2). This is a **discretionary** upgrade, not a required one.

### Is a Hermes update required?
**NO DECISION.** `.update_check` reports `behind: 1`, which establishes that a newer build exists but
**not** what it changes. No changelog, target version or defect-fix evidence was obtained, and the
installed build (v0.15.2 / 2026.5.29.2) has no observed version-linked failure. The three failed
Hermes units (D-5) have **not** been traced to the CLI at all — they run in-repo scripts from the
repo venv (§3b), so they are not evidence for a CLI upgrade.

### Can either be tested side-by-side?
- **OpenClaw: NO, not as installed.** It is a *global* npm package at a fixed path with a fixed
  gateway port (18789). Side-by-side requires a second prefix/port — a host change, out of scope here.
- **Hermes CLI: YES, cheaply.** It is a self-contained venv at a user-writable path. A second dated
  venv can be created and exercised without touching the running one. This is the recommended route.

### Is an in-place upgrade prohibited?
**Yes, under this task** — it needs `npm -g` installation, service restarts and daemon-reload, all of
which are explicitly forbidden here. Beyond this task: an in-place **OpenClaw** upgrade is
*acceptable* on evidence (a current-version backup exists, G-1 notwithstanding). An in-place
**Hermes** upgrade should be treated as **prohibited until a venv copy exists**, because it is
currently irreversible.

### Are rollback artifacts sufficient?
**Partially — and not uniformly.**
- OpenClaw: **sufficient** (2026-07-04 archive post-dates the installed version).
- Hermes: **INSUFFICIENT** (G-1 — single venv, no dated copy, no release dir).
- Database: **INSUFFICIENT for a same-day rollback** (G-2 — newest full dump is 50 days old).
- Crontab/config: **sufficient** (frequent recent backups).

### Is the database role layout safe enough for shadow work?
**No.** The intent is right — `hermes_readonly` (SELECT on 57 tables) and `hermes_staging_writer`
(INSERT/SELECT/UPDATE on 18) are scoped sensibly and neither can CREATE. But **both are barred from
logging in** (D-6), so today every process connects as `trade_ai`, the object owner. Shadow work run
now would execute with **full owner rights against canonical tables**, which is exactly what the role
split was built to prevent. Enabling LOGIN on those two roles (plus credential provisioning) is the
prerequisite for genuinely isolated shadow work.

### Which facts remain unverified?

1. **BLOCKED (policy):** per-channel enable/disable state for Telegram/WhatsApp — lives in
   credential-bearing config that was deliberately not opened.
2. **BLOCKED (policy):** required environment-variable *names* per service — not enumerated to avoid
   incidental value disclosure.
3. **PARTIAL:** Ollama model quantization strings (needs `ollama show` per model).
4. **PARTIAL:** effective merged LLM routing table (local / default / critical-cloud) and the
   configured embedding model.
5. **PARTIAL:** Hermes auto-graft / auto-promotion settings — not located.
6. **PARTIAL:** Hermes CLI package provenance — no `importlib.metadata` distribution is registered,
   so install method is inferred from the venv layout, not proven.
7. **PARTIAL:** SHA-256 for large rollback archives (skipped by cost).
8. **PARTIAL (G-2):** where `tradeai-portfolio-backup-cadence` actually writes, and whether it
   produces full dumps.
9. **UNRESOLVED (D-8):** how embeddings are persisted without `pgvector`.
10. **UNRESOLVED (D-5):** root cause of the four failed units — diagnosis needs journal access and,
    for a fix, service changes.

---

## Recommended next actions (none performed here)

| ID | Item | Priority | Requires |
|---|---|---|---|
| D-4 | Disable the duplicate `portfolio-server.service` user unit (15,081 restarts) | **High** | `systemctl --user disable` — prohibited here |
| D-6 | Grant LOGIN to `hermes_readonly` / `hermes_staging_writer` before any shadow work | **High** | DDL + credential provisioning |
| G-2 | Verify/repair the database backup cadence; take a fresh full dump | **High** | Backup run |
| O-1 | Confirm ACL posture for Ollama `:11434` and `:9090` on all interfaces | **High** | Firewall/Tailscale review |
| G-1 | Snapshot the Hermes venv before any upgrade | Medium | `cp -a` to a dated path |
| D-5 | Triage 4 failed units | Medium | Journal access |
| D-1 | Reconcile the dirty live tree; make the deployed SHA reproducible | Medium | Operator decision |
| D-3 | Fix or remove the broken `hermes-gateway.service` ExecStart | Low | Unit edit |
| D-2 | Correct the stale OpenClaw unit description | Low | Unit edit |
| D-7 | Review and drop six residual `crash_*` schemas | Low | DDL |

---

*Read-only inventory. No service was started, stopped, restarted, enabled or disabled; no timer,
schedule or configuration was modified; no package was installed or upgraded; no model was pulled or
deleted; no production database write was issued; no secret value was read, printed or committed.*
