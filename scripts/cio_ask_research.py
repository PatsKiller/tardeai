#!/usr/bin/env python3
"""Host executor for the n8n lane ``cio-ask-research`` (Ask the CIO, Phase 9). READ_ONLY_ADVISORY.

Researches pending AskRequest@v1 JSON files and writes one AskAnswer@v1 per request.

Inputs and outputs
------------------
* Reads pending requests from ``--queue-dir``, or env ``CIO_ASK_REQUESTS_DIR``. The questions/answers store row
  is Phase 8's, and it is pending operator approval (§26.6). This executor creates no store: with no queue it
  reports ``no_new_input``.
* Writes each answer to ``--out-dir`` (env ``CIO_ASK_ANSWERS_DIR``) as ``<request_id>.json``. An existing answer
  is never redone (idempotent).
* CIO memory: every fact and answer goes through the integrator. That is a dry run unless ``--apply-memory`` is
  set.

Dry run
-------
``--dry-run`` (the lane's SHADOW mode) resolves entities and plans the sources and the panel admission.
It touches no provider, spends nothing and writes nothing, the lane receipt included. It prints a
``DRY-RUN {...}`` line.

The executor never sizes, orders, stops or weights (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import cio_ask_research as car  # noqa: E402

LANE_ID = car.LANE_ID


def _pending(queue_dir: Path | None, out_dir: Path | None, limit: int) -> list[tuple[Path, dict]]:
    if queue_dir is None or not queue_dir.is_dir():
        return []
    out: list[tuple[Path, dict]] = []
    for p in sorted(queue_dir.glob("*.json")):
        try:
            req = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rid = str(req.get("request_id") or p.stem)
        if out_dir is not None and (out_dir / f"{rid}.json").exists():
            continue
        out.append((p, req))
        if len(out) >= limit:
            break
    return out


def _atomic_write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, default=str, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--request-file", type=Path, help="research one AskRequest JSON file")
    ap.add_argument(
        "--queue-dir",
        type=Path,
        default=Path(os.environ["CIO_ASK_REQUESTS_DIR"]) if os.environ.get("CIO_ASK_REQUESTS_DIR") else None,
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(os.environ["CIO_ASK_ANSWERS_DIR"]) if os.environ.get("CIO_ASK_ANSWERS_DIR") else None,
    )
    ap.add_argument("--max-requests", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true", help="plan only: no provider, no spend, no writes")
    ap.add_argument("--apply-memory", action="store_true", help="write CIO memory (default: integrator dry run)")
    ap.add_argument(
        "--memory-ledger",
        type=Path,
        default=None,
        help="idempotency ledger for memory appends (default <out-dir>/_memory_ledger.jsonl)",
    )
    ap.add_argument(
        "--origin", choices=("n8n", "in_process"), default="n8n" if os.environ.get("TRADEAI_RUN_ID") else "in_process"
    )
    args = ap.parse_args(argv)
    started = datetime.now(timezone.utc)

    if args.request_file:
        items = [(args.request_file, json.loads(args.request_file.read_text(encoding="utf-8")))]
    else:
        items = _pending(args.queue_dir, args.out_dir, max(1, args.max_requests))

    if args.dry_run:
        plans = []
        for path, req in items:
            try:
                plan = car.run_research(req, dry_run=True, origin=args.origin)
                plans.append(
                    {
                        "request": str(path),
                        "entities": plan["entities"],
                        "sources": len(plan["sources"]),
                        "panel": plan["panel"],
                        "governor": plan["governor"],
                    }
                )
            except Exception as exc:  # noqa: BLE001
                plans.append({"request": str(path), "error": f"{type(exc).__name__}: {exc}"})
        try:
            from scripts.lib.lane_last_receipt import dry_run_report
        except ImportError:  # pragma: no cover
            from lib.lane_last_receipt import dry_run_report  # type: ignore
        dry_run_report(
            LANE_ID,
            {
                "pending": len(items),
                "plans": plans,
                "empty_reason": None if items else "no_new_input",
                "queue_dir": str(args.queue_dir) if args.queue_dir else None,
            },
            would_write=[
                f"{args.out_dir}/<request_id>.json" if args.out_dir else "<no out-dir>",
                "CIO memory events via CIOEnvelopeIntegrator" + (" (apply)" if args.apply_memory else " (dry run)"),
            ],
        )
        return 0

    if items and args.out_dir is None:
        print(f"[{LANE_ID}] refusing a live run without --out-dir / CIO_ASK_ANSWERS_DIR", file=sys.stderr)
        return 2
    ledger = args.memory_ledger or (args.out_dir / "_memory_ledger.jsonl" if args.out_dir else None)
    memory = car.MemoryAppender(ledger_path=ledger, apply=args.apply_memory)
    produced, errors, evidence = 0, [], []
    for path, req in items:
        try:
            ans = car.run_research(req, memory=memory, origin=args.origin)
            target = args.out_dir / f"{ans['request_id']}.json"
            _atomic_write(target, ans)
            produced += 1
            evidence.append({"kind": "file_artifact", "ref": str(target)})
            print(
                f"[{LANE_ID}] answered {ans['request_id']} partial={ans['partial']} facts={len(ans['facts'])} "
                f"gaps={len(ans['gaps'])} mbi_stripped={len(ans['mbi_strip_log'])} "
                f"memory={ans.get('memory_receipt', {}).get('appended')}"
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path.name}: {type(exc).__name__}: {str(exc)[:200]}")
    ok = not errors
    try:
        from scripts.lib.lane_last_receipt import write_lane_receipt
    except ImportError:  # pragma: no cover
        from lib.lane_last_receipt import write_lane_receipt  # type: ignore
    write_lane_receipt(
        LANE_ID,
        ok=ok,
        exit_code=0 if ok else 1,
        started_at=started,
        script="scripts/cio_ask_research.py",
        summary={"pending": len(items), "answered": produced, "errors": errors[:5]},
        produced_count=produced,
        attempted_count=len(items),
        output_evidence=evidence,
        empty_reason=None if items else "no_new_input",
        error="; ".join(errors)[:500] if errors else None,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
