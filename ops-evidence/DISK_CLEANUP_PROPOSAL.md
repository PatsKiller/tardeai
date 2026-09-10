# Disk risk diagnosis + cleanup proposal (READ-ONLY — nothing deleted)

Date (America/New_York): 2026-09-10 01:45. Campaign: Grok-closure.

## Current measurement (read-only, `df` + `du`)

- `/` = 468G total, 357G used, **88G available (81% used)**.
- Note: differs from the handoff's "98% full (11G free)" — the filesystem is
  currently at 81% with 88G free, so the crisis state has already eased (or the
  earlier reading was of a different moment). No deletion performed here.

## Largest consumers (top, by size)

| Target | Size | Owner / effect |
|---|---|---|
| `~/trade-ai-releases/` (mostly `portfolio-server/`) | **111G** | Immutable deployed releases; `CURRENT` → `87e7325d2-…` is live. Retired releases dominate. |
| `~/llama-cpp-vulkan/` | 28G | Local GPU model toolchain (not release-critical). |
| `~/trade-ai-v12-rebuild/` | 22G | Primary rebuild tree (LIVE — guard binary + grants live here). |
| `~/.hermes/` | 6.2G | Hermes model/state cache. |
| `~/trade-ai-worktrees/` | 5.9G | Agent worktrees (incl. this one). |
| `~/.cache/` | 5.8G | pip/uv/other caches. |
| `~/.cursor-server/` | 4.6G | Cursor remote server installs. |
| `~/.npm/_cacache` | 3.6G | npm cache (safe to purge). |
| `~/worktrees/` | 3.5G | Additional worktrees. |
| `~/db_backups/` | 3.1G | Database backups (retention candidates). |

## Deleted-but-open files / journal size

Not measured (would need `lsof`/`journalctl` which are read-only but slow); the
dominant reclaim is clearly retired releases, not open-fd pinning.

## Cleanup proposal (targets, sizes, owners, effects, recovery)

1. **Retired `~/trade-ai-releases/portfolio-server/<old-sha>-…` dirs** (est. ~90–100G).
   - Owner: deploy pipeline / operator.
   - Effect: single largest reclaim; keep `CURRENT` + the last 1–2 promoted SHAs for rollback.
   - Recovery: releases are reproducible from git + `prepare`; keep the immediately-previous SHA dir for one deploy.
   - **Do not touch** `87e7325d2-main-exact-phase2-20260909-234722` (CURRENT) or its `CURRENT` symlink.
2. `~/.npm/_cacache` purge (`npm cache clean --force`) — ~3.6G, fully recoverable.
3. `~/.cache/pip` + `uv` caches — ~3–5G, fully recoverable.
4. `~/llama-cpp-vulkan/` build artifacts (not the weights if in use) — ~10–20G; requires confirming no active model serving.
5. `~/db_backups/` older-than-N — 1–3G; operator retention policy.
6. Old `~/trade-ai-worktrees/` + `~/worktrees/` for closed campaigns (NOT the active `grok-closure-20260909`) — ~3–5G.

**Recovery for the critical item (#1):** the release dirs are immutable artifacts
recreated on promote; before removing any, verify `git cat-file -e <sha>` in the
served tree and keep the last promoted SHA. Do not remove the `CURRENT` symlink
target under any circumstances.

**Nothing was deleted.** This is a proposal only.
