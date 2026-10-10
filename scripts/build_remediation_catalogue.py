#!/usr/bin/env python3
"""build_remediation_catalogue.py — generate config/n8n_remediation_catalogue.json from the verified inventory.

REMEDIATION_PLAN §6 R2 / operator decision 4 (2026-10-09 23:38 ET): the remediation catalogue is generated from the
inventory and shown to the operator before activation. Logic: scripts/lib/n8n_remediation_catalogue.py.

    python3 scripts/build_remediation_catalogue.py --dry-run            # summary + per-lane table, writes nothing
    python3 scripts/build_remediation_catalogue.py --write              # (re)writes config/n8n_remediation_catalogue.json
    python3 scripts/build_remediation_catalogue.py --check              # exit 1 when the file differs from a rebuild

Inputs (read-only): <inventory-dir>/inventory_base.csv, enrich_S*.csv, refactor_wave1.json,
analysis/critical_paths.csv; config/lane_registry.json; config/n8n_run_allowlist.json.
The output is config (reviewed by PR), never runtime state. No network, no DB, no send.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import n8n_remediation_catalogue as C  # noqa: E402
from scripts.n8n_selftest_fail import PROPOSED_ALLOWLIST_ENTRY  # noqa: E402

NO_CONSUMER_REASON = "config generator; its output is read by scripts/n8n_failure_diagnosis.py; no scheduled lane"
DEFAULT_INVENTORY = Path(os.environ.get("TRADEAI_CRON_INVENTORY_DIR")
                         or (Path.home() / "n8n-maturity-verification" / "cron-inventory"))
OUT = ROOT / "config" / "n8n_remediation_catalogue.json"


def build(inventory_dir: Path, as_of: str) -> dict:
    registry = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    allowlist = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
    return C.build_catalogue(inventory_dir=inventory_dir, registry=registry, allowlist=allowlist, as_of=as_of,
                             selftest_entry=PROPOSED_ALLOWLIST_ENTRY)


def _render(doc: dict) -> str:
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def _table(doc: dict) -> str:
    lines = [f"{'lane':44} {'sev':8} {'actions (auto*)':52} reason"]
    for e in doc["lanes"]:
        acts = ",".join(a["action_id"] + ("*" if a["auto"] else "") for a in e["actions"]) or C.SUGGEST_ONLY
        lines.append(f"{e['lane_id'][:44]:44} {e['severity']:8} {acts[:52]:52} {(e['suggest_only_reason'] or '')[:70]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    ap.add_argument("--inventory-dir", default=str(DEFAULT_INVENTORY))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--as-of", default=None, help="pin as_of (default: today UTC; --check reuses the file's)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    as_of = args.as_of
    if args.check and as_of is None:
        try:
            as_of = json.loads(out.read_text(encoding="utf-8")).get("as_of")
        except (OSError, ValueError):
            as_of = None
    as_of = as_of or datetime.now(timezone.utc).date().isoformat()
    doc = build(Path(args.inventory_dir), as_of)
    errs = C.validate_catalogue(doc)
    if errs:
        print(json.dumps({"ok": False, "errors": errs[:20]}), file=sys.stderr)
        return 1
    if args.dry_run:
        print(_table(doc))
        print(json.dumps({"mode": "dry-run", "would_write": str(out), "summary": doc["summary"]}))
        return 0
    if args.check:
        try:
            same = out.read_text(encoding="utf-8") == _render(doc)
        except OSError:
            same = False
        print(json.dumps({"mode": "check", "up_to_date": same, "summary": doc["summary"]}))
        return 0 if same else 1
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(_render(doc), encoding="utf-8")
    os.replace(tmp, out)
    print(json.dumps({"mode": "write", "wrote": str(out), "summary": doc["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
