# Target Drive Structure — 2026-05-30

## Proposed Structure

The goal is to consolidate the canonical `Trade_AI_Docs_v2` root into a clean hierarchy. The sync script continues to manage `docs/` and `config/` automatically.

```
Trade_AI_Docs_v2/
├── config/                          # Synced: strategy YAML configs
│   └── strategies/
├── docs/                            # Synced: canonical docs tree (ONE folder, not two)
│   ├── hermes/                      # Hermes v4 design package
│   ├── project/                     # Session summaries, runbooks, memory notes
│   ├── atm_lifecycle_v1_2026_05_29/ # Latest ATM lifecycle docs
│   ├── llm_fleet/                   # LLM fleet phase docs
│   ├── execution_safety/            # Execution safety phases
│   ├── governance/                  # Governance docs
│   ├── _archive/                    # Archived session docs
│   └── ...                          # Other synced subdirectories
├── ui_redesign/                     # UI redesign workspace
├── atm_audit_2026_05_26/            # ATM audit handoff (manually uploaded)
├── 20_ARTIFACT_PACKAGES/            # NEW: all .tgz handoff packages
│   ├── session_packages/            # Session drop packages
│   ├── playwright_archives/         # Playwright crawl archives
│   ├── phase_packages/              # Phase-specific packages
│   └── backup_archives/             # Split backup parts
├── 40_ARCHIVE/                      # NEW: superseded/duplicate content
│   ├── duplicate_docs_folder/       # Contents of stale second docs/ folder
│   ├── superseded_packages/         # Older playwright_1421, etc.
│   └── loose_root_files/            # Root-level MDs moved here
└── 90_REVIEW_BEFORE_DELETE/         # NEW: needs operator review
    ├── root_files/                  # Unclassified root files
    └── unclassified/                # Other uncertain files
```

## Migration Rules

1. Sync script continues managing `docs/` and `config/` — no changes to sync behavior
2. Stale second `docs/` folder contents move to `40_ARCHIVE/duplicate_docs_folder/`
3. Root-level .tgz packages move to `20_ARTIFACT_PACKAGES/`
4. Root-level duplicate .md files move to `40_ARCHIVE/loose_root_files/`
5. Split backup parts move to `20_ARTIFACT_PACKAGES/backup_archives/`
6. Unknown/unclassified files move to `90_REVIEW_BEFORE_DELETE/`
7. Nothing is deleted until operator approves

## Sync Script Fix

After cleanup, patch `scripts/sync-docs-to-drive.sh` to use `--max=1000` in `gog drive ls` calls to prevent future duplicate folder creation.
