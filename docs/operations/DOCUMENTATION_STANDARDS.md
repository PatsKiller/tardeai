# Documentation Standards — Trade AI v12

**Authority:** This file governs all documentation updates. Read before every doc session.
**Last updated:** 2026-05-14

---

## 1. Audience-Tiered Structure

| Audience | Primary Documents | Location |
|----------|------------------|----------|
| Architect | MASTER_SYSTEM_DOCUMENTATION.md, SYSTEM_ARCHITECTURE_COMPLETE.md | docs/, docs/project/ |
| Operator | CHEAT_SHEET.md, RESTORE_GUIDE.md, OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md | docs/ |
| Strategist | TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md, strategy_yaml_audit.md | docs/, docs/project/ |
| LLM/AI | LLM_FLEET_STRATEGY_v4_1_FINAL.md, LLM_DATA_DICTIONARY.md, APPENDIX_E_SCRIPT_ROUTING_MATRIX.md | docs/ |
| Deployment | v4_1_deployment_log.md, Phase reports | docs/ |
| Current state | SYSTEM_FACTS_LATEST.md | docs/project/, docs/current_state/ |

## 2. Canonical Files and Ownership

| File | Owner | Update Frequency |
|------|-------|-----------------|
| MASTER_SYSTEM_DOCUMENTATION.md | Architect | Per session if architecture changes |
| SYSTEM_ARCHITECTURE_COMPLETE.md | Architect | Per session if architecture changes |
| CHEAT_SHEET.md | Operator | When new operator commands are added |
| RESTORE_GUIDE.md | Operator | When new cron/tables/services are added |
| PROJECT_DOC_INDEX.md | All | Every session (changelog required) |
| SYSTEM_FACTS_LATEST.md | Auto-generated | Run `scripts/regenerate_system_facts.sh` |
| v4_1_deployment_log.md | Deployment | Append-only per deployment |

## 3. Update Protocol (Step by Step)

### Step A — Read this file first
Every documentation session starts by reading DOCUMENTATION_STANDARDS.md.

### Step B — Identify affected files
Determine which canonical files are affected by the change. Use the table in section 2.

### Step C — Run holdings guard
```bash
python3 -c 'import json; d=json.load(open("data/portfolios/state/holdings.json")); v=d["portfolio_totals"]["total_value"]; assert v>1000000; print(f"OK: ${v:,.0f}")'
```

### Step D — Make changes
Edit the affected files. Use live introspection for all numeric facts (never copy from memory).

### Step E — Regenerate system facts if counts changed
```bash
bash scripts/regenerate_system_facts.sh
```

### Step F — Update PROJECT_DOC_INDEX.md changelog
Every session must add a changelog entry.

### Step G — Commit
```
docs: <what changed>

Session NN — <description>

<list of files changed>
```

## 4. Forbidden Actions

- **Never delete documentation files** — always archive to `docs/_archive/`
- **Never edit `_archive/` content** — historical record is immutable
- **Never edit SYSTEM_FACTS_LATEST.md by hand** — regenerate with script
- **Never copy-paste numbers from memory** — always introspect live
- **Never skip PROJECT_DOC_INDEX.md changelog entry**
- **Never commit without running the holdings guard first**

## 5. Adding a New Document

1. Decide audience: architect / operator / strategist / LLM / deployment
2. Place in appropriate location (docs/ or docs/project/ or new subdirectory)
3. Add changelog entry to PROJECT_DOC_INDEX.md
4. Cross-reference from any related canonical file

## 6. Archiving Workflow

When superseding a document:
1. Create new doc
2. `git mv` the old doc to `docs/_archive/superseded/`
3. Add a one-line note at the top of the old doc: `> Superseded by [new doc path] on YYYY-MM-DD`
4. Commit with message: `docs: supersede [old] with [new]`

## 7. Export and Sharing

```bash
bash scripts/export_doc_backup.sh
```

Produces a timestamped zip in `backups/doc_exports/` containing all current docs (excluding _archive/) plus a manifest with live system facts.

## 8. Drift Detection

After major changes, verify documentation matches reality:
```bash
bash scripts/regenerate_system_facts.sh
```

Compare regenerated facts against claimed counts in MASTER and ARCHITECTURE docs. Any drift must be resolved before the session ends.

## 9. Cross-Reference Requirements

| Fact | Authoritative Source | Must Match |
|------|---------------------|------------|
| Table count | SYSTEM_FACTS_LATEST.md | MASTER + RESTORE_GUIDE |
| Cron count | SYSTEM_FACTS_LATEST.md | RESTORE_GUIDE + CHEAT_SHEET |
| Strategy count | strategy_yaml_audit.md | STRATEGY_PLAYBOOK |
| Endpoint count | SYSTEM_FACTS_LATEST.md | MASTER |
| Holdings value | Live introspection only | (never written to docs) |

## 10. Session Sign-Off Checklist

Before ending any documentation session:
- [ ] Holdings guard passed
- [ ] All applicable canonical files updated
- [ ] PROJECT_DOC_INDEX.md changelog entry added
- [ ] SYSTEM_FACTS_LATEST.md regenerated if counts changed
- [ ] No edits to _archive/ content
- [ ] Numeric facts verified via introspection
- [ ] `git status` clean after commit
