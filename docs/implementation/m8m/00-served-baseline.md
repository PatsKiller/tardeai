# 00 — Served baseline

Status: Phase 0 evidence. No workflow was installed, no cron or timer was changed, no message was sent, no broker call was made, and no release was promoted.

| Field | Value |
|---|---|
| Host | `ms01-openclaw` |
| Time zone | `America/New_York` (EDT, -0400). NTP active. |
| Observation | 2026-10-06T15:00:04Z through the file write on the same pin. Recheck immediately before this file: `CURRENT` still the path below. |
| Freeze pin | `/home/johnclaw/trade-ai-releases/portfolio-server/65fbeecf3-main-exact-phase2-20261006-105201` |

A second release directory exists, `65fbeecf3-main-exact-phase2-20261006-111058`, with the same SHA prefix and a later prepare clock. It is not `CURRENT`. This baseline does not blend the two directories.

## Trade AI served process

| Check | Result |
|---|---|
| `CURRENT` realpath | `65fbeecf3-main-exact-phase2-20261006-105201` |
| `/v3/build-meta.json` `git_sha` | `65fbeecf31161e0b51790d5761f7d3fc20c9ea7c` |
| `built_at` | `2026-10-06T14:53:00.051Z` |
| `ui_version` | `3.14+muwssvh7` |
| `origin/main` and rebuild HEAD | same full SHA, detached checkout |
| Policy on that pin | `AGENTS.md` Policy-Version **1.4.0**, Status **ACTIVE**. `AI_WORK_POLICY.md` Status **MANDATORY**. |
| portfolio-server | active, MainPID 311922 at observation, cwd and merged `WorkingDirectory` are the freeze pin. `ExecStart` is the venv Python plus that release's `scripts/portfolio_server.py`. |
| Listen | `0.0.0.0:7777` |
| Prior pin this session | `2d5e761f5-main-exact-phase2-20261005-221314` (AGENTS 1.3.0). Kept as a prior observation. Not the freeze. |

### Served file hashes (sha256)

| Path | Bytes | sha256 |
|---|---:|---|
| `AGENTS.md` | 272213 | `6e484bf0c5cf26da3f70748930a3ea6248a410eee4087e62188b432a85a5f47a` |
| `AI_WORK_POLICY.md` | 13847 | `d024b817f42fa736d788ff2dd8fcde511c55e1a30a306b259b664bacc1289fdf` |
| `scripts/portfolio_server.py` | 133953 | `41e119ce7fb99ba929dde9f9ac8742cd3ed06e324e36baa28fe7b1ab8111adb9` |
| `scripts/api_v2.py` | 2971146 | `c62e94ff26c3358dcd24ed0c6ea3c9de18ea9817c321b7d13fe11070b9f9b273` |
| `docs/architecture/ARCHITECTURE_INDEX.md` | 5332 | `3af8b36899d6271adc2ec4fa2a15b8ef712d9bb5c2c3699fbea7108bb75d2d8b` |

Drop-in chain for `portfolio-server.service` is the user unit plus the `service.d` directory observed at 15:00Z, including `20-exact-sha-release.conf` and `zz-restart-always.conf`. The base unit file's own `WorkingDirectory` still names the rebuild tree. The merged unit, the process cwd, and `/proc/pid/cwd` name the freeze pin.

HTTP GET, same pin:

| Route | Result |
|---|---|
| `/api/health` | 200, `ok=true`, `version=2.0`, `port=7777` |
| `/api/v2/health` | 200, `data.status=healthy`, `overall_score=86`, `mode=advisory`, `captured_at=2026-10-06T15:01:34.920097+00:00` |
| `/v3/cio` | 200, HTML, 977 bytes |

## DOF served process

| Check | Result |
|---|---|
| Repo | `PatsKiller/nyc-dof-auction`, default branch `master` |
| Git HEAD | `5d3c39e3da9ca9f33b168504f5ce2b73cd8fc83d` |
| Process | user unit `dof-dashboard.service`, active, MainPID 3642, cwd `/home/johnclaw/nyc-dof-auction` |
| Exec | `.venv/bin/python3 dof_server.py` |
| Listen | `0.0.0.0:7776` HTTP 200, `content-type` HTML, body sha256 `1253e62df9a564033c9c07b113e7b707894f0157a87bf069565df08aff2a5d41`, title `NYC DOF Auction Intelligence` |
| On-disk `dof_server.py` sha256 | `10caca4d5bac3b37ae8403fe88fe278ece960c951461bb2479d90c8d125e40a4` (69477 bytes, mtime 2026-07-13T22:17:14Z) |
| Commit `5d3c39e` copy sha256 | `499092af9506acdd2b3d60b44a8ce84de1919367228ad23a3047eb7e1be03c49` (58117 bytes) |

The running dashboard is the dirty checkout, not commit `5d3c39e`. That checkout also has uncommitted edits in `scripts/price_refresh.py`, `scripts/pricing_aggregator.py`, `scripts/stage1_fetch_pdfs.py`, `scripts/stage5_score.py`, and `static/index.html`, plus untracked files. Those files were not stashed, discarded, or committed.

## Governance copies

`docs/governance/NEW_AGENT_STARTS_HERE.md`, `docs/governance/ENGINEERING_STANDARD.md`, and `docs/architecture/ARCHITECTURE_INDEX.md` are present on the freeze pin. The DOF commit has no `AGENTS.md` and no `AI_WORK_POLICY.md`. Trade AI policy does not become DOF policy by sharing a host.

## First two natural windows on this pin

| Window | Clock | Lane |
|---|---|---|
| 1 | 2026-10-06 18:00 America/New_York | DOF `rescan_tickets.py` (`0 18 * * *`) |
| 2 | 2026-10-07 02:30 America/New_York | `tradeai-portfolio-backup-cadence.timer` |

If `CURRENT` or the DOF process cwd changes before either window, recompute. Do not blend pins.
