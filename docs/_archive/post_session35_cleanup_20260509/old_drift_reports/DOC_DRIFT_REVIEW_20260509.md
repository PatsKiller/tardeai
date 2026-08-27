# Doc Drift Review — 2026-05-09

Generated from `data/system_fact_drift.json` after hardening sprint validation.
Live values sourced from `data/system_facts.json`.

**Action required:** Update the stale values listed below in each affected doc.
Do not auto-edit — review each change manually for context accuracy.

---

## Table Count: 219 → 249

30 new tables added (hardening sprint + prior growth).

| File | Stale Claim | Live Value |
|------|-------------|------------|
| `docs/CHEAT_SHEET.md` | 219 tables | **249** |
| `docs/ARCHITECTURE_INFOGRAM.md` | 219 tables | **249** |
| `docs/ARCHITECTURE_OVERVIEW.md` | 219 tables (2 occurrences) | **249** |
| `docs/MASTER_SYSTEM_DOCUMENTATION.md` | 219 tables | **249** |
| `docs/COST_MODEL.md` | 219 tables | **249** |
| `docs/RESTORE_GUIDE.md` | 143 tables | **249** (was already stale before sprint) |

## Strategy Count: 14 → 20

| File | Stale Claim | Live Value |
|------|-------------|------------|
| `docs/MASTER_SYSTEM_DOCUMENTATION.md` | 14 strategies | **20** |

## Python Script/Package Count: 90 → 321

Note: The "90 Python packages" claim in MASTER_SYSTEM_DOCUMENTATION.md refers to
`requirements.txt` pip packages, not scripts. Verify whether `requirements.txt`
still has ~90 entries or has grown. The drift detector matched on the number "90"
in a packages context — this may be a false positive for script count drift.

| File | Stale Claim | Context | Live Script Count |
|------|-------------|---------|-------------------|
| `docs/MASTER_SYSTEM_DOCUMENTATION.md` | 90 | "90 Python packages" (pip, not scripts) | 321 scripts |

## False Positives (script count = 3)

The drift detector matched occurrences of the digit "3" in `.py` command lines
in CHEAT_SHEET.md and RESTORE_GUIDE.md. These are command examples, not script
count claims. No action needed.

---

## Recommended Actions

1. **Find-and-replace "219 tables"** → "249 tables" in the 5 affected docs.
2. **Update RESTORE_GUIDE.md** from "143 tables" → "249 tables".
3. **Update MASTER_SYSTEM_DOCUMENTATION.md** from "14 strategies" → "20 strategies".
4. **Verify requirements.txt line count** — if still ~90 packages, no change needed for that claim.
5. **Re-run `generate_system_facts.py`** after doc edits to confirm drift drops to 0 real items.
