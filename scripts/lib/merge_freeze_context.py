"""The merge-freeze status context name, and the one helper every reader of ``main``'s required checks uses.

``train-merge-freeze`` is a commit status posted by ``.github/workflows/train-merge-freeze.yml``
(``scripts/release_train_freeze.py ci``). Once the operator adds it to ``main``'s required status checks it blocks a
merge to ``main`` while the Release Train v2 merge freeze is active (AGENTS.md §25.3;
``docs/ops/RELEASE_TRAIN_MERGE_FREEZE.md``).

It is a timing gate, not a code-quality check, so the readers that treat "every required check is success" as
"this commit is green" drop it:

* the PR-hygiene census (``scripts/pr_hygiene_audit.py``): during a freeze every open PR would read ``PENDING`` and
  the train, which is exempt from the freeze, would select nothing;
* tree-attested promote (``scripts/lib/tree_attested_promote.py``): it reads required contexts as check runs on the
  PR head; a commit status is never a check run, so every promote would refuse ``check_missing``;
* the agent claim lifecycle and the Work pipeline (``agent_claim_lifecycle``, ``work_pipeline``,
  ``work_pipeline_tier2``): they read check runs only; the Tier 2 merge asks the freeze itself instead.

Stdlib only, no imports, no environment read (it sits in several import closures). MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

from typing import Iterable

FREEZE_CONTEXT = "train-merge-freeze"


def without_freeze_context(names: Iterable[str]) -> list[str]:
    """``names`` without the merge-freeze context, order kept."""
    return [n for n in names if n != FREEZE_CONTEXT]
