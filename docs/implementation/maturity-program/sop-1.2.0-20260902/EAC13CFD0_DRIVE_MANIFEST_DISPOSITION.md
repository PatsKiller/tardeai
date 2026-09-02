Status:      ACTIVE
as_of:       2026-09-02T10:15:00-04:00
Canonical repo path: docs/implementation/maturity-program/sop-1.2.0-20260902/EAC13CFD0_DRIVE_MANIFEST_DISPOSITION.md
Authority:   disposition only. No Drive write. No cherry-pick into this tranche.

# eac13cfd0 Drive-manifest disposition

## Finding

Commit `eac13cfd0` on branch `docs/agents-drive-manifest-4bcba2cf` adds
`docs/ops/AGENTS_DRIVE_MIRROR_MANIFEST.json` recording BYTE_EXACT mirror of
AGENTS.md **1.1.0** at source commit `4bcba2cf7`.

That path is **absent from origin/main** (`git show origin/main:docs/ops/AGENTS_DRIVE_MIRROR_MANIFEST.json` fails).
The mirror **script** (#842) is on main; the manifest artifact itself was never merged.

## Decision

**RETAIN as historical evidence.** Do **not** cherry-pick into the 1.2.0 PROPOSED tranche:

- cherry-picking would publish a manifest claiming BYTE_EXACT for 1.1.0 bytes while this branch carries PROPOSED 1.2.0 AGENTS.md (different content hash);
- Drive write remains operator-gated (`AUTHORIZE_AGENTS_DRIVE_MIRROR …`) after ACTIVE ratification.

After 1.2.0 is ACTIVE on exact main, Checkpoint C should create/update the manifest via the stable file IDs (folder `1spBGi8…`, agents file `10vKQJa…`, manifest file `10wZMd…`) and a new reviewed commit — superseding eac13cfd0's *content*, not deleting the historical commit.
