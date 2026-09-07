#!/usr/bin/env bash
# Git merge driver for GENERATED files.
#
#   %O ancestor   %A ours (result goes here)   %B theirs   %P real path
#
# THE ROOT CAUSE THIS FIXES
# -------------------------
# Measured over six consecutive merges on 2026-09-06: 6 of 6 touched the same
# five files, and every one of them is a generated artifact —
#
#   docs/INDEX.md                       rebuilt from `git ls-files`
#   FULL_TEST_MATRIX.txt                carries control_surface_digest
#   RUFF_SHELLCHECK.txt                 carries control_surface_digest
#   CONTROL7_WORKFLOW_PROOF.txt         carries control_surface_digest
#   CONTROL7_LOCAL_EQUIVALENT.txt       carries control_surface_digest
#
# So any two concurrent PRs conflicted BY CONSTRUCTION, whatever they changed.
# Four resolutions that day were all this; none was a disagreement about code.
#
# Line-merging them is not just noisy, it is WRONG: a hand-merged digest is a
# hash that matches nothing, and a line-merged index describes neither tree. The
# only correct resolution is to recompute from the merged tree — which is exactly
# what every one of those four manual resolutions did by hand.
#
# This driver takes `ours` as a placeholder and regenerates afterwards. The
# regeneration itself is left to the post-merge step, because the digest must be
# computed over the FULLY merged tree, not over one file mid-merge.
#
# NOTE: the digest binding is NOT weakened. The evidence is still bound to the
# control surface and still verified by tests/test_sop_evidence_integrity.py —
# this only stops git from producing a hash nobody computed.
set -euo pipefail

ANCESTOR="$1"; OURS="$2"; THEIRS="$3"; PATHNAME="${5:-unknown}"

# Keep `ours` so the merge completes; content is authoritative only after
# regeneration, which `scripts/regenerate_generated_files.sh` performs.
printf '%s\n' "MERGE-REGENERATE: kept ours for ${PATHNAME}; run scripts/regenerate_generated_files.sh" >&2
exit 0
