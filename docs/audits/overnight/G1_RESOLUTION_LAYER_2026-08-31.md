# Overnight G1 — Checkout-relative remediation at the resolution layer

**Wave:** Overnight G1  
**Date:** 2026-08-31  
**Authority:** `READ_ONLY_ADVISORY` · no deploy · no cron install  
**Branch:** `fix/overnight-g1-resolution-layer`  
**Rails:** AGENTS.md §9.4 / §10 · AI_WORK_POLICY push/merge only  
**Store set:** none mutated by this PR (live divergent copies reported, not merged)

## Finding

Five instances of the same defect class: a writer whose path resolves from
`Path(__file__)` / cron cwd lands in the hub checkout, while the served release
reads `GOOD_PERSISTENT_ROOT` (or a symlink into it).

| # | instance | prior art | residual gap on `origin/main` @ start |
|---|---|---|---|
| 1 | release-local `logs/` | #569 deploy link | lib `OVERLAY_RELS` / `DATA_DIRS_TO_LINK` omitted `logs` (AGENTS.md still listed the gap) |
| 2 | two holdings copies | #570 gate consistency; `portfolio_state_write_targets` unused by the write gate | hub vs persistent still diverge; gate did not dual-write |
| 3 | risk state | #712 P10.B dual-write in `save_risk_state` | canonical path now bound through `good_persistent_root`; historical fork still present |
| 4 | evening packet | cron already `cd CURRENT` | `PACKET_PATH = ROOT / data/runtime/…` still checkout-relative; hub copy stale |
| 5 | cron → dev tree | C-03 / Part 1 | resolution helpers make durable dirs independent of process cwd |

## Byte snapshot (read-only) — do not auto-remediate

`as_of=2026-08-31T05:37:08+00:00`  
`CURRENT` → `51da7a4a0-main-exact-phase2-20260831-013037`

| store | hub sha256 (12) | persistent sha256 (12) | identical? | action |
|---|---|---|---|---|
| `holdings.json` | `4dac6f00e90e…` (232615 B, mtime 2026-08-31T00:30:21Z) | `91517df4f3cc…` (232477 B, mtime 2026-08-30T12:00:24Z) | **NO** | `REPORT_BOTH_ESCALATE` |
| `risk_management.json` | `e1d689e52bb0…` (10234 B, mtime 2026-08-31T00:30:22Z) | `b87c658b49a5…` (10554 B, mtime 2026-08-30T19:15:40Z) | **NO** | `REPORT_BOTH_ESCALATE` |
| `aegis_evening_packet.json` | `71a046be5999…` (1704 B, mtime 2026-08-26T00:00:17Z) | `586d2816f784…` (6125 B, mtime 2026-08-30T23:45:02Z) | **NO** | `REPORT_BOTH_ESCALATE` |
| `logs/` | hub dir, 4201 entries (not a symlink) | persistent dir, 44 entries; CURRENT → symlink | separate trees | no merge |

**`auto_remediate=false` on every row.** AGENTS.md §9.4: never merge divergent
authoritative copies. Detection must not become resolution. Future dual-writes
from one in-memory object prevent *re*-divergence; they do not reconcile these
historical forks.

Regenerate:

```bash
python3 - <<'PY'
from pathlib import Path
from scripts.lib.persistent_state_root import report_authoritative_divergence, good_persistent_root
hub = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
ps = good_persistent_root()
for label, rel in [
    ("holdings", "data/portfolios/state/holdings.json"),
    ("risk", "data/portfolios/state/risk_management.json"),
    ("evening_packet", "data/runtime/aegis_evening_packet.json"),
]:
    print(label, report_authoritative_divergence(hub/rel, ps/rel, label=label)["action"])
PY
```

## Change this tranche

| File | Change |
|------|--------|
| `scripts/lib/persistent_overlay.py` | `OVERLAY_RELS` / `DATA_DIRS_TO_LINK` gain `logs` + `state/data_broker`; logs sentinels |
| `scripts/lib/persistent_state_root.py` | `durable_write_targets`, `resolve_durable_dir`, `logs_root`, `evening_packet_*`, `report_authoritative_divergence`; `logs` in `PERSISTENT_TREES` |
| `scripts/aegis_evening_packet.py` | write via `evening_packet_write_targets` (persistent first) |
| `scripts/portfolio_stops.py` | `_canonical_state_dir` via `good_persistent_root` |
| `scripts/schwab_position_sync.py` | after a successful gate write, mirror to other `portfolio_state_write_targets` when primary is a durable target |
| `tests/test_overnight_g1_resolution.py` | five-instance suite |
| `scripts/run_cio_hardening_ci.py` | allowlist gate `overnight_g1_resolution` |
| `docs/audits/overnight/G1_RESOLUTION_LAYER_2026-08-31.md` | this note |

**Not touched:** `scripts/cio_phase2_exact_main_deploy.sh` — already links `"logs"`
(#569). Prefer lib resolution; no deploy-script gap remained.

## Per-instance status

| # | instance | status after this PR |
|---|---|---|
| 1 | release-local `logs/` | **FIXED at lib** — `OVERLAY_RELS`/`DATA_DIRS_TO_LINK` include `logs`; CURRENT already symlinked; hub cron logs remain a separate larger fork (named, not collapsed) |
| 2 | two holdings copies | **FUTURE writes dual-bound**; **historical divergence REPORTED** (not merged) |
| 3 | risk state | **Resolution bound to `good_persistent_root`**; dual-write retained; **historical divergence REPORTED** |
| 4 | evening packet | **FIXED at resolution layer** — writers hit persistent/runtime first |
| 5 | cron → dev tree | **FIXED at resolution layer** — `resolve_durable_dir` / write-target helpers ignore process cwd |

## Invariants

- Path fixes live in `scripts/lib/persistent_*`, not in crontab `cd` lines.
- Dual-write is from one payload; one destination failing cannot lose the other.
- `report_authoritative_divergence(...).auto_remediate is False` always.
- Additive only: no deletion of hub copies; no reconcile of historical forks.
- No secrets, no broker, no cron install, no deploy.

## Proof commands

```bash
python3 -m pytest -q tests/test_overnight_g1_resolution.py
python3 -m pytest -q tests/test_portfolio_state_write_targets.py tests/test_risk_state_served_copy.py
python3 scripts/check_test_coverage.py --fail-on-new
python3 scripts/run_cio_hardening_ci.py
```

## Deploy

None. Push + merge only (WAVE G1 brief: ship+merge, no deploy).
