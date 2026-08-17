# A1A Documentation Protocol (Authoritative)

**Created:** 2026-05-12
**Status:** Active — Non-negotiable
**Enforced by:** Every Claude session that touches docs, code, schemas, or pipelines

---

## Purpose

This file defines the non-negotiable process for keeping all Trade AI v12
documentation accurate, current, and internally consistent. No partial updates.
No appendix band-aids. No stale docs rotting in the index.

---

## Trigger: When A1A Must Run

Run this process after ANY of:
- Documentation updates (any file in `/docs`)
- Backup or restore operations
- Schema changes (new tables, altered columns, migrations)
- Execution/approval/risk logic changes
- Alpaca integration or paper trading changes
- Trade journal or analytics changes
- Agent, LLM, memory, or RAG changes
- Orchestration, cron, or pipeline changes
- Strategy engine or incubator changes
- Frontend page additions or removals
- Notification or alerting changes

**If you changed behavior, you changed documentation. Act accordingly.**

---

## A1A Process (Required Steps)

### Step 1 — Inventory

List every doc in `/docs` (and subfolders) that references the behavior you changed.
Include the doc index (`docs/project/PROJECT_DOC_INDEX.md`).

### Step 2 — Audit

Go through **every affected document**, section by section.
Validate each claim against the system as it exists right now.
If something is wrong, fix it in place. Do not add a footnote.

### Step 3 — Rewrite (not patch)

If a section is inaccurate, **rewrite it**. Do not:
- Add a correction below the wrong text
- Append a note saying "see also new doc"
- Leave contradictions for the reader to resolve

### Step 4 — Remove or Archive obsolete material

If something is no longer true:
- Remove it from the active document
- If historical context is needed, rely on git history or Google Drive (the in-repo `docs/_archive/` was purged 2026-08-16)
- Update the index to reflect the removal

Do not hide stale content in appendices.

### Step 5 — Update the index

Update `docs/project/PROJECT_DOC_INDEX.md` so it reflects:
- New docs added
- Docs removed or archived
- What is currently authoritative
- What changed since the last update
- The date of this update

### Step 6 — Ownership mapping

Any doc describing system behavior must identify:
- Which files/modules implement it
- Which component owns the behavior

If it cannot be mapped to code ownership, it must not be documented as truth.

### Step 7 — Consistency check

After updating, scan for contradictions across documents. Two docs must not
disagree about how the same system works.

### Step 8 — If unsure, ask

If you do not know:
- Which doc set is authoritative
- Where a behavior is implemented
- Which index governs the docs
- What should be archived

You must **ask the operator** rather than guessing or leaving partial updates.

---

## Output Requirements

After A1A runs:
- Active docs reflect only current behavior
- The index lists only current authoritative docs
- Obsolete docs are archived and removed from the index
- No undocumented "assumed behavior" exists
- No contradictions exist across the doc set

---

## Doc Organization

| Location | Purpose |
|----------|---------|
| `docs/` | Active top-level docs (master docs, operational guides, audits) |
| `docs/project/` | Project-specific docs (strategies, agents, skills, architecture) |
| *(removed 2026-08-16)* | `docs/_archive/`, `docs/archive/`, `docs/backups/`, `docs/v4_1_discovery/` were purged — superseded/backup content now lives in git history + Google Drive |
| `docs/DOCUMENTATION_INDEX.md` | **The index** — single source of truth for what is current (supersedes `docs/project/PROJECT_DOC_INDEX.md`) |
| `docs/A1A.md` | **This file** — the protocol governing all doc changes |

---

## Enforcement

Every Claude session that modifies documentation must:
1. Read `docs/A1A.md` before making changes
2. Follow the full A1A process
3. Update the index as part of the same commit
4. Not claim "documentation updated" without completing all steps

**Any documentation change must follow /docs/A1A.md protocol.**
