#!/usr/bin/env python3
"""Validate in-repository SOP 1.2.0 evidence against the control-surface digest.

Exit 0 only when all checks pass. Does not embed or require the containing
commit SHA — that belongs in runtime attestation only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.sop_evidence_integrity import (  # noqa: E402
    control_surface_digest,
    validate_in_repo_evidence,
    workflow_facts,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT

    errors = validate_in_repo_evidence(root)
    try:
        digest = control_surface_digest(root)
        wf = workflow_facts(root)
    except Exception as exc:  # noqa: BLE001
        digest = {"digest": None, "error": str(exc)}
        wf = {"error": str(exc)}

    payload = {
        "ok": not errors,
        "control_surface_digest": digest.get("digest"),
        "workflow_blob_sha256": wf.get("blob_sha256"),
        "workflow_lines": wf.get("lines"),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"ok={payload['ok']} digest={payload['control_surface_digest']}")
        print(f"workflow_blob_sha256={payload['workflow_blob_sha256']} lines={payload['workflow_lines']}")
        if errors:
            print("errors:")
            for e in errors:
                print(f"  - {e}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
