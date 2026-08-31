# Night Three Wave 6 — Structure proofs (G1 / G4 / G3)

```
Status:      ACTIVE
as_of:       2026-09-01
Measured at: 2026-08-31T14:20:24Z · served CURRENT
             373a82078-main-exact-phase2-20260831-101330
             (= origin/main @ 373a82078)
Authority:   READ_ONLY_ADVISORY · MBI=0
Branch:      docs/overnight-w6-structure-proofs
Hub:         /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
Worktree:    /home/johnclaw/worktrees/overnight-w6-structure-proofs
```

**Rails:** AGENTS.md §0.6 (archive tripwire) · §9.4 (resolution layer, never
auto-remediate two authoritative copies) · AI_WORK_POLICY (no cron install,
no merge of divergent stores, no archive of real material this tranche).

**Store set:** none mutated. SCRATCH archive proof restored to empty.
**Deploy:** none. **Cron:** not installed / not edited.

---

## Contract

Prove three overnight structure ships against **live CURRENT** (not a stale
checkout assumption):

| ID | Claim to prove | Pass criterion |
|----|----------------|----------------|
| **6a** | G1 five checkout-relative instances | Per-instance: fixed+verified on served release **or** remaining named honestly. Fix only at resolution layer if still broken. Never change cron cwd as the fix. |
| **6b** | G4 archive tripwire | Archive a **SCRATCH** file only → live read → finding raised → restore. Archive nothing real. |
| **6c** | G3 `docs/INDEX.md` | Report **MISSING HEADER** count (honest debt). Confirm CI drift check exists. Mutation: change a doc → regenerated index differs / check red → restore → green. |

---

## 6a — G1 resolution layer (five instances)

Prior art: `docs/audits/overnight/G1_RESOLUTION_LAYER_2026-08-31.md` (#758) +
overlay databroker hotfix (#760). Both are on `origin/main` and therefore on
served CURRENT (dir name encodes `373a82078`).

### Served-release verification

| Check | Result |
|-------|--------|
| Worktree HEAD == CURRENT release id | `373a82078` |
| `tests/test_overnight_g1_resolution.py` | **15 passed** (worktree = served SHA) |
| `OVERLAY_RELS` includes `logs` | yes (CURRENT `scripts/lib/persistent_overlay.py`) |
| `state/data_broker` in `OVERLAY_RELS` | **no** — intentional post-hotfix (fork escalate, do not overlay) |
| CURRENT `logs` / `data/portfolios/state` / `data/runtime` | symlinks → `GOOD_PERSISTENT_ROOT` |
| `resolve_durable_dir("logs", …)` from `/tmp` cwd | → persistent `logs` (cwd-independent) |
| Cron cwd changed as the fix? | **No.** Crontab still `cd` hub / `PROJ=…/trade-ai-v12-rebuild`; resolution helpers ignore process cwd. |

### Per-instance status (from served release)

| # | Instance | Resolution-layer on CURRENT | Live residual (do **not** auto-remediate) | Verdict |
|---|----------|-----------------------------|-------------------------------------------|---------|
| 1 | release-local `logs/` | **FIXED+VERIFIED** — `logs` in `OVERLAY_RELS`/`DATA_DIRS_TO_LINK`; CURRENT `logs` → persistent | Hub `logs/` remains a real dir (~4215 entries) vs persistent (~44). Named fork; not collapsed. | fixed |
| 2 | two holdings copies | **FIXED+VERIFIED** — `portfolio_state_write_targets` / dual-write path present | Hub vs persistent `holdings.json` now **identical** (`sha12=9b19da7c7cf3`, 232791 B, mtime 2026-08-31T14:15:30Z). `action=NONE`. | fixed |
| 3 | risk state | **FIXED+VERIFIED** — `_canonical_state_dir` via `good_persistent_root`; dual-write retained | **Historical divergence REMAINS:** hub `bc60b831b47a` (10541 B, 2026-08-31T10:15:02Z) vs persistent `b87c658b49a5` (10554 B, 2026-08-30T19:15:40Z). `REPORT_BOTH_ESCALATE`, `auto_remediate=False`. | fixed (residual fork reported) |
| 4 | evening packet | **FIXED+VERIFIED** — `evening_packet_write_targets` / persistent-first | **Historical divergence REMAINS:** hub `71a046be5999` (1704 B, 2026-08-26) vs persistent `586d2816f784` (6125 B, 2026-08-30T23:45:02Z). `REPORT_BOTH_ESCALATE`, `auto_remediate=False`. | fixed (residual fork reported) |
| 5 | cron → dev tree | **FIXED+VERIFIED** — `resolve_durable_dir` / write-target helpers ignore cwd | Crontab still targets hub checkout by design; **not** retargeted (changing cron cwd is forbidden as the “fix”). | fixed |

### 6a remaining count

**Resolution-layer remaining among the five: `0`.**

No code PR this tranche. Historical `risk_management.json` and
`aegis_evening_packet.json` forks are **reported**, not merged
(`auto_remediate=False` on every `report_authoritative_divergence` row).
Operator-only to collapse those copies later.

Regenerate divergence:

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
    r = report_authoritative_divergence(hub/rel, ps/rel, label=label)
    print(label, r["action"], "identical=", r["identical"], "auto_remediate=", r["auto_remediate"])
PY
```

---

## 6b — Archive tripwire (G4)

Prior art: `docs/audits/overnight/G4_ARCHIVE_MECHANISM_2026-08-31.md` (#756).
Mechanism on CURRENT; committed manifest empty.

### Proof sequence (SCRATCH only)

Measured in worktree `/home/johnclaw/worktrees/overnight-w6-structure-proofs`
at 2026-08-31T14:19Z:

| Step | Action | Result |
|------|--------|--------|
| 0 | `validate` + `tripwire` on empty manifest | `ok: true`, `trip_count: 0`, exit 0 |
| 1 | Create SCRATCH `scripts/_W6_SCRATCH_TRIPWIRE_ONLY.py` | disposable marker only |
| 2 | Place copy at `archive/w6_scratch/_W6_SCRATCH_TRIPWIRE_ONLY.py` | on-disk archived path (not a real census batch) |
| 3 | Live consumer `scripts/_W6_SCRATCH_CONSUMER_READ.py` reads archived path | FS read succeeded (`READ_OK True`) |
| 4 | `python3 scripts/cio_archive_mechanism.py tripwire` | **FIRE** — exit 1 |
| 4b | Finding | `ArchivedPathAccessFinding`: `scripts/_W6_SCRATCH_CONSUMER_READ.py -> archive/w6_scratch/_W6_SCRATCH_TRIPWIRE_ONLY.py (read)` |
| 5 | Restore: delete SCRATCH + consumer + `archive/w6_scratch/`; empty manifest | `trip_count: 0`, exit 0; `archive/` = `.gitkeep` + empty `ARCHIVE_MANIFEST.json` only |

**Tripwire: PASS** (fires on SCRATCH read; quiet after restore).
**Archived real material: none.**

Suite still green: `tests/test_overnight_g4_archive_mechanism.py` — 9 passed.

---

## 6c — `docs/INDEX.md` (G3)

Prior art: `docs/audits/overnight/G3_DOCS_INDEX_2026-08-31.md` (#754).

### MISSING HEADER (documentation debt)

A markdown file under `docs/` is **MISSING HEADER** when its first 40 lines
lack YAML front matter and lack structured metadata keys (`**Status:**`,
`**Created:**`, `**Authority:**`, `**Owner:**`, `**Updated:**` / Last updated,
`**Date:**`, `**Document version:**`, or `as_of` / `doc-version`).

| Metric | Value | Measured at |
|--------|------:|-------------|
| **MISSING HEADER** | **1034** | 2026-08-31T14:19Z (worktree = CURRENT SHA) |
| Markdown files (excl. INDEX) | 1902 | same |
| Header OK | 868 | same |
| Files under `docs/` (excl. INDEX) | 2270 | same |
| Tree fingerprint (pre this audit) | `ac574dda2032…` | committed `docs/INDEX.md` before W6 note |
| Tree fingerprint (with this audit) | see regenerated `docs/INDEX.md` | `--write-index` after adding this note |

G3 overnight reported **1033** @ 2026-08-31T05:39:28Z. Honest delta: **+1**
as later markdown landed without structured headers (debt size moved; not
remediated file-by-file this tranche). Adding this audit (header OK) does not
change the MISSING HEADER count.

**MISSING HEADER count as_of this proof: 1034.**

### CI drift check exists

`scripts/run_cio_hardening_ci.py` runs gate `docs_index_drift`:

```text
[RUN]  docs_index_drift
→ python3 scripts/report_docs_inventory.py --check-index
```

Also covered by `tests/test_overnight_g3_docs_index.py` (allowlist
`overnight_g3_docs_index`).

### Mutation test

| Step | Result |
|------|--------|
| Baseline `--check-index` | **PASS** (MISSING HEADER=1034, fingerprint `ac574dda2032…`) |
| Mutate `docs/audits/overnight/G3_DOCS_INDEX_2026-08-31.md` (append probe comment) | — |
| `--check-index` after mutation | **FAIL** / exit 1 — fingerprint → `39c409bd6cd0…`; G3 row sha12 `c84615e159f7` → `2a4199e77c05` |
| Restore G3 file | — |
| `--check-index` after restore | **PASS** / exit 0 — fingerprint back to `ac574dda2032…` |

Mutation-test: **PASS** (red on change, green on restore).

After adding **this** audit, regenerate INDEX so `docs_index_drift` stays green:

```bash
python3 scripts/report_docs_inventory.py --write-index --verbose
python3 scripts/report_docs_inventory.py --check-index
```

---

## Summary scores

| Proof | Result |
|-------|--------|
| **6a remaining (resolution-layer among five)** | **0** |
| **6a residual historical forks (reported, not merged)** | risk + evening_packet (`REPORT_BOTH_ESCALATE`) |
| **6b tripwire** | **PASS** |
| **6c MISSING HEADER** | **1034** |
| **6c CI drift check** | present + mutation red/green proven |
| **PRs this tranche** | [#773](https://github.com/PatsKiller/tardeai/pull/773) docs-only (this audit + INDEX regen); **no resolution-layer code PR** |

---

## What did not work

1. **First attempt to write a temporary SCRATCH manifest row via inline
   `import cio_archive_mechanism`** failed with `ModuleNotFoundError` (scripts/
   not on `sys.path` in that one-liner). Tripwire still fired because
   `effective_archived_paths` unions **on-disk** files under `archive/` with
   manifest items — sufficient for the SCRATCH proof. Manifest rewrite was
   retried with `sys.path` fixed; final restore returned the committed empty
   manifest via `git checkout -- archive/ARCHIVE_MANIFEST.json` after a JSON
   unicode-escape noise diff (`—` vs `\u2014`).
2. **`report_docs_inventory.py --output /tmp/…`** is ambiguous (`--output-json`
   / `--output-md`). Mutation proof relied on `--check-index`’s built-in
   regenerate+diff (which did go red) rather than a separate `--output` file.
3. **Pytest against the release tree directory** (`…/CURRENT`) was
   wall-clock-heavy / timed out in this environment; proofs were run in the
   worktree at the **same commit id** as CURRENT (`373a82078`) instead.
4. **Holdings were diverged at G1 measurement** (2026-08-31T05:37Z); by this
   proof they are identical. That is dual-write / later writers catching up —
   not an automatic merge of historical forks. Risk + evening packet did
   **not** converge; still escalate-only.
5. **Cron still `cd`s the hub checkout.** That is expected and must not be
   “fixed” by editing crontab working directories; resolution layer is the
   fix. Instance 5 is therefore fixed without a cron change.
6. **`state/data_broker` hub vs persistent still forks** (separate from the
   five G1 instances; G1 overlay hotfix deliberately keeps it out of
   `OVERLAY_RELS`). Not auto-remediated this tranche.

---

## Invariants honored

- No cron install / no crontab edit.
- No merge of divergent authoritative stores (`auto_remediate=False`).
- No archive of real material; SCRATCH only; restored.
- Never auto-remediate two authoritative copies.
- Path fixes live in `scripts/lib/persistent_*`, not cron cwd.
- Authority `READ_ONLY_ADVISORY`. MBI=0.

## Proof commands (re-run)

```bash
# 6a
python3 -m pytest -q tests/test_overnight_g1_resolution.py
# divergence snippet above

# 6b
python3 scripts/cio_archive_mechanism.py validate
python3 scripts/cio_archive_mechanism.py tripwire
python3 -m pytest -q tests/test_overnight_g4_archive_mechanism.py

# 6c
python3 scripts/report_docs_inventory.py --verbose
python3 scripts/report_docs_inventory.py --check-index
python3 -m pytest -q tests/test_overnight_g3_docs_index.py
```
