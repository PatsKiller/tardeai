# OPERATOR_FORCED_GO_LIVE — promote + pin truth

```
Status: ACTIVE
as_of: 2026-09-20T22:26:00-04:00
Measured at: build-meta.json source_commit=0e5b9a4dc…; origin/main=a40601f01… (#1161); force close via #1157
Canonical repo path: docs/ops/OPERATOR_FORCED_GO_LIVE_PROMOTE_2026-09-20.md
Authority: operator FORCE 2026-09-20T21:01 ET; PROMOTE OK 2026-09-20T21:39 ET; AGENTS.md §8 honesty
Supersedes: none (pairs with docs/ops/STANCE_ORGANIC_PARK_2026-09-20.md SUPERSEDED)
See also: docs/audits/DARK_PARTIAL_CLOSURE_LEDGER_2026-09-19.md; LOG wave 21:03 / 21:39 / 22:26
```

## One-sentence

Forced go-live closed the stance gate and promoted `#1157` onto CURRENT; that is **not** unattended Mon–Fri organic OBSERVED, and live is now **behind** main tip `#1161` until a separate release-write promote.

## Pin identity `[VERIFIED]` 2026-09-20T22:26 ET

| surface | value |
|---|---|
| Live `source_commit` / `git_sha` (`/v3/build-meta.json`) | `0e5b9a4dc6d718883ddc83f8f15db2b65000c051` |
| Live release label | `main-exact-phase2` (built_at `2026-09-21T01:39:23.261Z`) |
| Promote receipt (peer) | `0e5b9a4dc-main-exact-phase2-20260920-212949` · PROMOTE OK |
| `origin/main` tip | `a40601f01f1532a7f5ba8e482c5bb72a5b5d4eea` · Merge #1161 |
| Live vs main | **behind** — 2 commits (`897ffbb54` stance LIVE impl + merge) |

Release-dir `readlink`/`cat` on `CURRENT` is blocked without `release-write`; pin resolved from served `build-meta.json` (and peer WD / env when granted).

## Honesty (binding)

| claim | status |
|---|---|
| `PARTIAL-telegram-CIO-stance` CLOSED · OPERATOR_FORCED_GO_LIVE | **YES** (#1157) |
| Mechanical organic holds ≥1 (AEMD+LSTA) | **YES** (4 rows; producer provenance retained) |
| Unattended Mon–Fri schedule OBSERVED | **NO** |
| Hermetic / controlled_canary as organic | **NO** |
| Invented hold rows | **NO** |
| §17 bitemporal / relationship | **CONTINUE-PARK (DEFER)** — settled, not open |

## What remains for live tip alignment

Promoting `a40601f01…` (#1161) onto CURRENT is a separate operator `release-write` ceremony. Peer agent requested grant `addc2b8ed58a48c2` at 22:24 ET — no prepare/promote until approved. Docs sync does not authorize deploy.
