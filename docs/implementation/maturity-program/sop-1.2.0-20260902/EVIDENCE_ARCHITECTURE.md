# SOP 1.2.0 · Evidence architecture

**Status:** authoritative for this tranche
**control_surface_digest binding:** see CURRENT evidence files (recomputed by validator)

## Why exact-head must not live inside the commit it attests

If a committed evidence blob embeds `HEAD=<sha-of-this-commit>`, the blob's
content is part of the commit hash. Changing the SHA field changes the commit,
so the evidence always names its **parent** (or forces endless amend cycles).
That is an impossible self-reference, not a verification signal.

Therefore this tranche uses **two layers**:

### Layer 1 — In-repository reproducible evidence (tracked)

- Declares a sorted **control-surface manifest**
  (`config/sop_120_control_surface.manifest.json`).
- Binds to a deterministic **control_surface_digest** over that manifest.
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
