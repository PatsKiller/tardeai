# SOP 1.2.0 · Evidence architecture

**Status:** authoritative for this tranche
**control_surface_digest:** computed at HEAD by the validator and recorded in Layer 2 (not committed since 2026-09-25)

## Why exact-head must not live inside the commit it attests

If a committed evidence blob embeds `HEAD=<sha-of-this-commit>`, the blob's
content is part of the commit hash. Changing the SHA field changes the commit,
so the evidence always names its **parent** (or forces endless amend cycles).
That is an impossible self-reference, not a verification signal.

Therefore this tranche uses **two layers**:

### Layer 1 — In-repository reproducible evidence (tracked)

- Declares a sorted **control-surface manifest**
  (`config/sop_120_control_surface.manifest.json`).
- The deterministic **control_surface_digest** over that manifest is computed at
  HEAD by the validator (it fails closed if any manifest path is missing) and is
  recorded in Layer 2. **It is not embedded in the tracked evidence files** since
  2026-09-25: the manifest includes `scripts/run_cio_hardening_ci.py`, which
  almost every PR edits to register a test, so a committed digest was rewritten
  (by `sed`, with nothing re-run) on every PR and made every pair of concurrent
  PRs conflict. The four files that used to carry it
  (`FULL_TEST_MATRIX.txt`, `RUFF_SHELLCHECK.txt`, `CONTROL7_WORKFLOW_PROOF.txt`,
  `CONTROL7_LOCAL_EQUIVALENT.txt`) now say `control_surface_digest=AT_HEAD`, and the
  validator refuses a concrete digest there (`EVIDENCE_EMBEDS_VOLATILE_DIGEST`).
- What still binds tracked evidence to the control surface, and so changes only
  when the surface does: the governance workflow's blob hash, line count, triggers,
  absence of path filters and pinned Ruff install (`CONTROL7_WORKFLOW_PROOF.txt`,
  checked against the live file), and the recorded exit semantics.
- Excludes volatile evidence outputs and `docs/INDEX.md` from the digest.
- Records commands, required tool versions, expected exit semantics, and the
  expected **120** core pytest total.
- Validated by `python3 scripts/validate_sop_evidence_integrity.py`.

### Layer 2 — Runtime exact-head attestation (untracked / CI artifact)

- Generated **after** checkout/commit by local verification or CI.
- Names `git rev-parse HEAD` or `GITHUB_SHA`.
- Contains live command results, exit codes, docs-index fingerprint, tool
  versions, clean-state, and authority non-regression.
- Written only under `artifacts/sop-attestations/` (gitignored) or uploaded as
  a CI artifact — **never** into tracked `docs/`.
- Emitter: `python3 scripts/emit_sop_runtime_attestation.py`.

## Historical evidence

Files marked `STATUS: SUPERSEDED_NON_AUTHORITATIVE` are audit history only.
They must not be cited as PASS subjects in the maturity scorecard.
