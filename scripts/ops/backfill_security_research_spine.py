#!/usr/bin/env python3
"""Backfill SecurityResearchSpine from Hermes (+ optional theses) to ≥80% coverage.

Writes one spine tip per researched symbol using the latest COMPLETED Hermes
result that resolves to a registry GUID. Tags each contribution with
``hermes`` + ``backfill`` so organic forward writes remain distinguishable.

Usage:
  CROSS_ASSET_SPINE=1 python3 scripts/ops/backfill_security_research_spine.py --dry-run
  CROSS_ASSET_SPINE=1 python3 scripts/ops/backfill_security_research_spine.py --apply
"""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "ops CLI; operator/agent invokes for researched→spine coverage catch-up; "
    "not imported by runtime producers"
)

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _latest_hermes_by_symbol(path: Path) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    if not path.exists():
        return latest
    with path.open(encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if row.get("event") != "HERMES_RESEARCH_COMPLETED":
                continue
            sym = str(row.get("symbol") or "").upper().strip()
            if not sym:
                continue
            latest[sym] = row
    return latest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--include-theses", action="store_true")
    ap.add_argument("--target-pct", type=float, default=80.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    apply = bool(args.apply)
    if apply:
        os.environ.setdefault("CROSS_ASSET_SPINE", "1")

    from scripts.lib.cross_asset.security_research_spine import (
        load_latest,
        upsert_from_hermes,
        upsert_research_memory,
    )
    from scripts.lib.identity_carriage import is_registry_guid, resolve_security_identity

    root = args.root
    hermes_path = root / "data" / "cio" / "hermes_research_results.jsonl"
    by_sym = _latest_hermes_by_symbol(hermes_path)

    report = {
        "schema": "SecurityResearchSpineBackfill@v1",
        "as_of": _now(),
        "apply": apply,
        "researched": len(by_sym),
        "already": 0,
        "upserted": 0,
        "skipped_unresolved": 0,
        "errors": 0,
        "samples": [],
    }

    for sym, row in sorted(by_sym.items()):
        existing = load_latest(sym, root=root)
        if existing and (existing.get("thesis") or {}).get("summary"):
            report["already"] += 1
            continue
        env = resolve_security_identity(sym, root=root)
        if not is_registry_guid(env.get("subject_guid")):
            report["skipped_unresolved"] += 1
            if len(report["samples"]) < 8:
                report["samples"].append({"symbol": sym, "status": "unresolved"})
            continue
        if not apply:
            report["upserted"] += 1
            continue
        # Force write path even if env was unset before setdefault.
        os.environ["CROSS_ASSET_SPINE"] = "1"
        out = upsert_from_hermes(
            sym,
            {**row, "subject_guid": env["subject_guid"], "issuer_guid": env.get("issuer_guid")},
            root=root,
            tags=["hermes", "backfill", "lifecycle"],
        )
        if out.get("ok"):
            report["upserted"] += 1
        else:
            report["errors"] += 1
            if len(report["samples"]) < 8:
                report["samples"].append({"symbol": sym, "status": "error", "error": out.get("error")})

    if args.include_theses and apply:
        theses = root / "data" / "cio" / "cio_theses.jsonl"
        if theses.exists():
            latest_thesis: dict[str, dict] = {}
            with theses.open(encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = row.get("payload") if isinstance(row, dict) else None
                    if not isinstance(payload, dict):
                        continue
                    for sym in payload.get("linked_symbols") or []:
                        su = str(sym).upper()
                        if su:
                            latest_thesis[su] = payload
            report["thesis_symbols"] = len(latest_thesis)
            for sym, payload in latest_thesis.items():
                if load_latest(sym, root=root) and (load_latest(sym, root=root).get("thesis") or {}).get("summary"):
                    continue
                env = resolve_security_identity(sym, root=root)
                if not is_registry_guid(env.get("subject_guid")):
                    continue
                upsert_research_memory(
                    sym,
                    silo="cio",
                    kind="thesis_backfill",
                    summary=str(payload.get("summary") or "")[:800] or None,
                    artifact_id=str(payload.get("thesis_version") or payload.get("thesis_id") or ""),
                    tags=["thesis", "backfill", "lifecycle"],
                    thesis_patch={
                        "stance": payload.get("stance"),
                        "summary": str(payload.get("summary") or "")[:1200] or None,
                        "state": "POPULATED" if payload.get("summary") else "INSUFFICIENT_DATA",
                    },
                    subject_guid=env.get("subject_guid"),
                    issuer_guid=env.get("issuer_guid"),
                    root=root,
                )

    researched = max(report["researched"], 1)
    covered = report["already"] + report["upserted"]
    # after apply, recount from disk for honesty
    if apply:
        from scripts.ops.spine_coverage_metric import main as _cov  # type: ignore  # noqa: F401
        spine_syms = set()
        sp = root / "data" / "cio" / "security_research_spine.jsonl"
        if sp.exists():
            latest = {}
            with sp.open(encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict) and row.get("symbol"):
                        latest[str(row["symbol"]).upper()] = row
            spine_syms = set(latest)
        covered = len(set(by_sym) & spine_syms)
    pct = round(100.0 * covered / researched, 1)
    report["covered"] = covered
    report["pct_researched_with_spine"] = pct
    report["target_pct"] = args.target_pct
    report["meets_target"] = pct >= args.target_pct

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        mode = "APPLY" if apply else "DRY"
        print(
            f"[{mode}] researched={report['researched']} covered≈{covered} "
            f"pct={pct}% (target {args.target_pct}%) upserted={report['upserted']} "
            f"unresolved={report['skipped_unresolved']} errors={report['errors']}"
        )
    return 0 if (not apply or report["meets_target"] or report["upserted"] > 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
