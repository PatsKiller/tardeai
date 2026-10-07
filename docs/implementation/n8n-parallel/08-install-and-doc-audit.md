# n8n lab install and documentation audit

Measured 2026-10-07T02:09Z through 2026-10-07T02:14Z (2026-10-06 22:09–22:14 ET). This file is an OBSERVED_LAB record of the localhost n8n bench and a documentation inventory. It is not a deployment receipt. Cron, systemd, and flock still own live Trade AI and DOF jobs. n8n is not the production orchestrator.

## Pins at this read

| Item | Observed |
| --- | --- |
| Served Trade AI | `18a27ff288894c4e428151d5f385e68522ecd47b`, UI `3.14+mux8d5sp`, built `2026-10-06T22:08:40.117Z`, label `main-exact-phase2` |
| origin/main | same SHA |
| Local Trade AI | branch `wt/n8n-parallel-20261007`, worktree `/home/johnclaw/tradeai-wt-n8n-parallel-20261007`, three commits ahead of origin/main, not pushed |
| Local tip when this file was added | parent `761bdbd7b0fdfdde67acf8a6000f91c877070d29`; the commit that adds this file is the next local commit |
| DOF served master | `/home/johnclaw/nyc-dof-auction` clean at `1f3186d563076da62c38c4294321b0c65086be50` |
| DOF policy branch | `/home/johnclaw/dof-wt-n8n-policy-20261007` clean at `47f1749b8ed9369d918b5eba76aba30ed9b205c8`, not pushed |
| Grants | every listed scope still expired at 2026-10-07T02:13Z. No approval code is recorded here. Push was not attempted |

## Containers

| Item | Value |
| --- | --- |
| Compose project | `m8m-n8n`, file `/home/johnclaw/m8m-bakeoff-lab/docker-compose.n8n.yml` |
| App container | `m8m-n8n`, image `n8nio/n8n:2.43.0`, image id `sha256:c6a3a0461d1d3ffc16d849adf57606c2b028667ade70cce2faa2ff094734873c`, image created `2026-10-06T07:15:11Z` |
| Database container | `m8m-n8n-db`, image `postgres:16.15-alpine`, database `n8n`, healthy |
| Restart | `unless-stopped` on both |
| Network | `m8m-n8n_lab` |
| UI publish | `127.0.0.1:5678` to container port 5678 |
| Database publish | none. Postgres listens only on the Docker network |
| Volumes | `m8m-n8n_n8n-data` mounted at `/home/node/.n8n`; Postgres data volume `n8n-pg` |
| Limits | n8n memory 768m and 256 pids; database memory 256m and 128 pids; `no-new-privileges` on both |
| Health | `GET http://127.0.0.1:5678/healthz` returned `{"status":"ok"}` |

The image tag is the community `n8nio/n8n` image. The unauthenticated settings body on the earlier corrective read did not include a license or plan field. This pass did not re-read that field. Do not treat the image tag as a fresh license query.

Inside the container, `N8N_LISTEN_ADDRESS` is `0.0.0.0`. The Docker port binding is still loopback only. `WEBHOOK_URL` is `http://127.0.0.1:5678/`.

## Environment that is safe to record

These values were read from the running container. Password, encryption-key, and database-user secret values are present in the container environment and are omitted here.

| Key | Value |
| --- | --- |
| `DB_TYPE` | `postgresdb` |
| `DB_POSTGRESDB_HOST` | `n8n-db` |
| `DB_POSTGRESDB_PORT` | `5432` |
| `DB_POSTGRESDB_DATABASE` | `n8n` |
| `GENERIC_TIMEZONE` | `America/New_York` |
| `N8N_HOST` / `N8N_PORT` / `N8N_PROTOCOL` | `127.0.0.1` / `5678` / `http` |
| `N8N_COMMUNITY_PACKAGES_ENABLED` | `false` |
| `N8N_PYTHON_ENABLED` | `false` |
| `N8N_BLOCK_ENV_ACCESS_IN_NODE` | `true` |
| `N8N_DIAGNOSTICS_ENABLED` | `false` |
| `N8N_TEMPLATES_ENABLED` | `false` |
| `N8N_PERSONALIZATION_ENABLED` | `false` |
| `N8N_HIRING_BANNER_ENABLED` | `false` |
| `N8N_VERSION_NOTIFICATIONS_ENABLED` | `false` |
| `N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS` | `true` |
| `EXECUTIONS_DATA_SAVE_ON_SUCCESS` | `all` |
| `EXECUTIONS_DATA_SAVE_ON_ERROR` | `all` |
| `NODE_ENV` | `production` |
| `N8N_RELEASE_TYPE` | `stable` |
| `NODE_VERSION` | `26.7.0-r0` |

`NODES_EXCLUDE` is a JSON array of `executeCommand`, `executeCommandTool`, `ssh`, `ftp`, `emailSend`, `emailSendTool`, `emailSendHitlTool`, and `localFileTrigger`.

## What is installed inside n8n

| Item | Count or state |
| --- | --- |
| Workflows | 4, listed below |
| Credentials | 0 |
| User API keys | 0 |
| Installed community packages | 0 |
| Installed nodes beyond the image | 0 |
| Variables | 0 |
| Registered webhooks | 0 rows in `webhook_entity` |
| Projects | 1 |
| Users | 1 |
| Execution rows | 100 |
| Python task runner | off |
| HMAC coordination gateway | not installed in n8n |
| Public webhook | not published. The only webhook node is on an inactive workflow |

Settings keys present, with secret-bearing LDAP fields left unread: `chat.access.enabled` false, `features.ldap` login disabled, `userManagement.authenticationMethod` email, `userManagement.isInstanceOwnerSetUp` true, `ui.banners.dismissed` contains `V1`. Enterprise SSO was false on the earlier unauthenticated settings read and was not switched on.

No custom node package is installed. The custom changes are the compose limits, the exclude list, the loopback publish, and the four workflows. Docker names stay `m8m-n8n` and `m8m-n8n-db`.

## Workflows

| Name | Id | Active | Nodes |
| --- | --- | --- | --- |
| `n8n-monitor-trade-ai` | `s57KBllvqf6Jb5xF` | yes | schedule every 5 minutes, HTTP GET `http://172.19.0.1:7777/v3/build-meta.json`, Code node requires HTTP 200 |
| `n8n-monitor-dof` | `GXwhbRkwsGcYZxgn` | yes | schedule every 5 minutes, HTTP GET `http://172.19.0.1:7776/api/run-scope`, Code node requires HTTP 200 |
| `n8n-bench-nodes` | `2yPuOGW9yYtJsoYk` | no | inactive webhook path `n8n-bench-nodes` (POST), plus HTTP, If, and Code nodes used for the bench |
| `n8n-bench-error` | `Bi002YOPSpZOQpEo` | no | inactive Error Trigger and a Code node |

Execution rows at this read: monitor Trade AI 48 success, monitor DOF 48 success, bench-nodes 2 success and 1 error, bench-error 1 success. A green n8n execution is not a consumer receipt and not a Telegram or mail delivery.

`updatedAt` stayed `2026-10-07 00:08:46Z` for three workflows and `2026-10-07 00:12:00Z` for `n8n-bench-nodes` after `n8n export:workflow --all`. The exporter printed that Postgres 16 is outside n8n's preferred range and that it acquired its migration lock. It did not change those four rows. The export JSON has no credential values. The container's copy of the export was removed after the copy to the operator host.

## Automation boundary

The two monitors read health URLs. They do not own cron, do not send, and do not replace journal, syslog, `communication_deliveries`, or `telegram_outbox`. The five coordination pilots in `04-pilot-contracts.md` remain fixture-only and `BLOCKED_POLICY`. The lab watchdog unit files in git are `PROPOSAL ONLY` and are not enabled on the host. The coordination gateway is code in this branch. It is not a running service and it does not hold a key inside n8n.

## Documentation inventory

`scripts/report_docs_inventory.py --check-index` on this worktree, before this file was added, reported PASS with markdown 2321, indexed files 2774, missing headers 102, duplicate groups 3, fingerprint `caddf5a5ec06`. The index is generated from `git ls-files`. Untracked files are invisible until `git add`.

The three byte-identical tracked pairs are:

| Pair | Why it remains |
| --- | --- |
| `docs/architecture/PLAN_S_HOLLOW_RESEARCH_THEN_ANSWER_2026-09-22.md` and `docs/plan-s-hollow-research-then-answer.md` | Same bytes, two paths. Deleting either path is a separate review. |
| The two ActiveTrader prompt files under `docs/design/ActiveTrader_Implementation_Pack_2026-07-27_v1/documents/` | Same bytes, two filenames in the pack. |
| `docs/operations/moomoo_health/.gitkeep` and `docs/operations/promotion_intents/.gitkeep` | Both empty directory markers. |

Missing headers on the n8n-parallel notes match the neighboring notes in that directory. This file does not invent headers for the other 102. A filesystem walk that ignores git reports a much larger tree, including backups and build output. That walk is not the index.

## Phase documents and what is current

| Phase | Where the record lives | Current meaning |
| --- | --- | --- |
| M8M Phase 0 | evidence drafts, not merged | Not the served release |
| Phase 1 | repairs recorded in the phase notes | Scheduler, DOF credential, and Bronx scope repairs are done. This file does not reopen them |
| Phase 2 | stay with systemd, cron, and PostgreSQL | An external scheduler was rejected |
| Phase 3 bakeoff | incumbent stayed; Kestra lost and was uninstalled | n8n was later reinstalled as this localhost bench, not as the orchestrator |
| n8n parallel | `docs/implementation/n8n-parallel/` and `docs/architecture/n8n/ADR_COORDINATION_SECRETS.md` | Local branch only. `00-fact-reconciliation.md` through `07-release-packet.md` are the corrective record. Older `00-baseline.md` through `06-findings-and-gateway.md` keep their original measurement times |
| DOF policy | `docs/proposed/N8N_LEAST_PRIVILEGE.md` on the DOF policy branch | PROPOSED. No role was created. No production route |

Corrections applied in this commit, without rewriting the older measurement tables: `00-fact-reconciliation.md` points here for the later HEAD; `02-feature-matrix.md` records the execution count moving from 66 to 100; `07-release-packet.md` names commit `761bdbd7b`.

## Drive

The connected Drive search and list tools cannot upload. Uploads use `gog` `drive upload` as `john@jwwhiting.com`.

The hourly job `scripts/sync-docs-to-drive.sh` mirrors the served release into [Trade_AI_Docs_v2](https://drive.google.com/drive/folders/1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR). Its last receipt before this audit finished at 2026-10-07T02:05:15Z: status done, 0 uploaded, 2794 unchanged, 0 failed, source commit `18a27ff288`. That mirror does not contain this branch.

The hourly code mirror `scripts/sync_code_mirror_to_drive.sh --apply` last finished at 2026-10-07T01:35:27Z. It uploaded `hub_git_snapshot.tar.gz`, `current_production_snapshot.tar.gz`, and `CODE_MIRROR_STATUS.json` into `Trade_AI_Docs_v2/code_mirror` (`1sC3Hr_QTJVcTYChWORE4SayNmXgM7t-Q`). Both archives are the served SHA, with `.env`, credentials, data, logs, and virtualenvs excluded. `rclone` has no remotes.

Unpromoted files from this branch are uploaded to a sibling folder, not into the hourly `docs/` tree. The next hourly run sources `CURRENT` and its cleanup removes manifest paths that are absent from that release. Putting this branch into that tree would schedule those files for deletion.

Excluded from every upload in this audit: `.env`, database passwords, the n8n encryption key, grants, approval codes, chat ids, DSNs, persistent-state, virtualenvs, and the bakeoff compose file that contains those secrets.

## Still open

Push and promotion remain blocked until a grant names this branch and the commit that contains the change. A push grant would not promote, enable the watchdog, or flip a registry row. The contradiction adjudicator is still a live paid writer whose registry row says `NEVER_SCHEDULED`. The maturity Monday writer is still declared `NEVER_SCHEDULED`. Neither row was changed. Natural approval delivery is not observed because this code is not served. Missed-fire rate remains unmeasured. The n8n license field was not re-read.
