#!/usr/bin/env python3
"""CLI wrapper for Maria Stage 2 specialist-honesty scrub.

Install target (needs openclaw grant): copy this directory to
``~/.openclaw/skills/tradeai-parity/scripts/`` (see
``docs/ops/openclaw_stage2_soul_patch_20260923.md``).

Reads reply body on stdin (or --text-file PATH), prints scrubbed body on
stdout. Exit 0 always for text work; stderr carries a one-line JSON decision.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_CANDIDATES = [
    Path(__file__).resolve().parents[2],  # .../tradeai/scripts/openclaw_maria_hooks
    Path.home() / "tradeai-wt-parity-stage2-20260923",
    Path.home() / "tradeai-wt-cc-lean-20260915",
]


def _ensure_repo_path() -> None:
    for root in _REPO_CANDIDATES:
        if (root / "scripts" / "lib" / "specialist_attribution.py").is_file():
            sys.path.insert(0, str(root))
            return


def main(argv: list[str] | None = None) -> int:
    _ensure_repo_path()
    from scripts.lib.maria_parity_hook import scrub_maria_outbound
    from scripts.lib.specialist_attribution import evidence_from_dicts

    p = argparse.ArgumentParser(description="Scrub fake Iris/Alex/CIO labels (Stage 2).")
    p.add_argument("--a2a", choices=("on", "off"), default="off")
    p.add_argument("--text-file", default="-", help="Reply body path, or - for stdin")
    p.add_argument(
        "--evidence-json",
        default="",
        help="Optional JSON list of SpecialistRunEvidence dicts",
    )
    args = p.parse_args(argv)

    if args.text_file == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.text_file).read_text(encoding="utf-8")

    evidence = []
    if args.evidence_json:
        evidence = evidence_from_dicts(json.loads(args.evidence_json))

    scrubbed, decision = scrub_maria_outbound(
        text, a2a_enabled=(args.a2a == "on"), evidence=evidence
    )
    sys.stdout.write(scrubbed)
    if not scrubbed.endswith("\n"):
        sys.stdout.write("\n")
    print(json.dumps(decision.to_dict(), ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
