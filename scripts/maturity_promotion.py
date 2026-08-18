#!/usr/bin/env python3
"""Phase 11 maturity promotion CLI.

Commands:
  preflight / sign / activate-canary / restrict / rollback / inspect

READ_ONLY_ADVISORY. No broker / order / stop / 2FA / risk mutations.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.maturity_control import promotion as pm
from scripts.lib.maturity_control.schema import ACK_TOKEN


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _sha(args: argparse.Namespace) -> str:
    if args.sha:
        return args.sha
    p = Path(args.root) / "SOURCE_COMMIT" if args.root else ROOT / "SOURCE_COMMIT"
    if p.is_file():
        return p.read_text(encoding="utf-8").strip()
    import subprocess
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(args.root or ROOT), text=True).strip()
    except Exception:
        return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 11 advisory promotion (no trading authority)")
    ap.add_argument("--root", default=None, help="project root (tests)")
    ap.add_argument("--sha", default=None, help="exact reviewed source SHA")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("draft", help="create a DRAFT promotion")
    p_new.add_argument("--capability", required=True)
    p_new.add_argument("--from-state", required=True)
    p_new.add_argument("--requested-state", required=True)
    p_new.add_argument("--agent-id")
    p_new.add_argument("--lesson-id")
    p_new.add_argument("--operator", required=True)
    p_new.add_argument("--evidence-json", default="{}")
    p_new.add_argument("--review", action="store_true")
    p_new.add_argument("--score", action="store_true")
    p_new.add_argument("--matured", type=int, default=0)
    p_new.add_argument("--shadow-n", type=int, default=0)

    for name in ("preflight", "sign", "activate-canary", "restrict", "rollback", "inspect"):
        p = sub.add_parser(name.replace("-", "_") if False else name)
        p.add_argument("promotion_id")
        if name == "sign":
            p.add_argument("--operator", required=True)
            p.add_argument("--ack", required=True)
        if name in {"restrict", "rollback"}:
            p.add_argument("--reason", default="operator")
        if name == "preflight":
            p.add_argument("--review", action="store_true")
            p.add_argument("--score", action="store_true")

    args = ap.parse_args(argv)
    root = args.root
    sha = _sha(args)
    try:
        if args.cmd == "draft":
            ev = json.loads(args.evidence_json)
            rec = pm.new_promotion(
                capability_type=args.capability,
                from_state=args.from_state,
                requested_state=args.requested_state,
                exact_source_sha=sha,
                requested_by=args.operator,
                agent_id=args.agent_id,
                lesson_id=args.lesson_id,
                evidence_bundle=ev,
                shadow_sample_size=args.shadow_n,
                matured_outcome_count=args.matured,
                quality_metrics={"has_score": bool(args.score)} if args.score else {},
                safety_metrics={"authority_violations": 0},
                root=root,
            )
            rec = pm.preflight(rec, live_sha=sha, has_review=args.review, has_score=args.score, root=root)
            _print(rec)
            return 0 if rec.get("status") == "READY_FOR_SIGNOFF" else 4
        rec = pm.load_or_raise(args.promotion_id, root=root)
        if args.cmd == "preflight":
            out = pm.preflight(rec, live_sha=sha, has_review=args.review, has_score=args.score, root=root)
        elif args.cmd == "sign":
            out = pm.sign(rec, operator=args.operator, ack=args.ack, live_sha=sha, root=root)
        elif args.cmd == "activate-canary":
            out = pm.activate_canary(rec, root=root)
        elif args.cmd == "restrict":
            out = pm.restrict(rec, reason=args.reason, root=root)
        elif args.cmd == "rollback":
            out = pm.rollback(rec, reason=args.reason, root=root)
        elif args.cmd == "inspect":
            out = pm.inspect(args.promotion_id, root=root)
        else:
            raise pm.PromotionError("unknown", args.cmd)
        _print(out)
        return 0
    except pm.PromotionError as e:
        _print(e.as_dict())
        return 2
    except json.JSONDecodeError as e:
        _print({"ok": False, "error": "bad_json", "message": str(e)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
