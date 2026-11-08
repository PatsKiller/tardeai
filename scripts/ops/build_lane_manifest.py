#!/usr/bin/env python3
"""build_lane_manifest.py — build the one lane manifest (LaneManifest@v1) from today's sources and list every
disagreement between them instead of guessing (LQ-20261107-1003, Fable audit LQ-984 Q6 #2 + #14).

Sources (all read-only):
  config/lane_registry.json, config/n8n_run_allowlist.json, config/n8n_health_contracts.json  (the repo tree --root)
  crontab snapshot: --crontab-file FILE, else `crontab -l`; --no-crontab skips it (reported NOT_MEASURED)
  n8n DB active workflows: scripts/lib/n8n_live_inventory (single SELECT via docker exec psql); --n8n-snapshot FILE
  reads a saved list instead; --no-n8n skips it (NOT_MEASURED)

Default is a dry run: a summary goes to stdout and nothing is written. --out writes the manifest, --report writes
the disagreement report, --render-registry writes the LaneRegistry@v1 view rendered from the manifest (the shim).
--check MANIFEST exits 1 when that manifest's registry view no longer equals config/lane_registry.json (drift
between the candidate and the live registry until the cutover makes the registry a rendered file).

No crontab, systemd, n8n, DB or registry write, ever. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import lane_manifest as lm  # noqa: E402

REGISTRY_REL = Path("config/lane_registry.json")
ALLOWLIST_REL = Path("config/n8n_run_allowlist.json")
CONTRACTS_REL = Path("config/n8n_health_contracts.json")


def _read(root: Path, rel: Path) -> tuple[Any, dict[str, Any]]:
    text = (root / rel).read_text(encoding="utf-8")
    doc = json.loads(text)
    rows = doc.get("lanes") or doc.get("contracts") or []
    return doc, {"status": "ok", "path": str(rel), "sha256": lm.sha256_text(text), "rows_read": len(rows)}


def read_crontab(path: Optional[str], skip: bool) -> tuple[Optional[list[str]], dict[str, Any]]:
    if skip:
        return None, {"status": "skipped", "rows_read": 0, "note": "--no-crontab: cron rules NOT_MEASURED"}
    try:
        if path:
            text = Path(path).read_text(encoding="utf-8")
            origin = "file"
        else:
            p = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=20, check=False)
            if p.returncode != 0:
                return None, {"status": "unavailable", "rows_read": 0, "note": f"crontab -l rc {p.returncode}"}
            text, origin = p.stdout, "crontab -l"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, {"status": "unavailable", "rows_read": 0, "note": type(exc).__name__}
    lines = lm.active_cron_lines(text)
    return lines, {"status": "ok", "origin": origin, "sha256": lm.sha256_text(text), "rows_read": len(lines),
                   "note": "active lines; line text is never written to the report (lines are cron:<sha12>)"}


def read_n8n(snapshot: Optional[str], skip: bool) -> tuple[Optional[list[dict]], dict[str, Any]]:
    if skip:
        return None, {"status": "skipped", "rows_read": 0, "note": "--no-n8n: n8n rules NOT_MEASURED"}
    try:
        if snapshot:
            doc = json.loads(Path(snapshot).read_text(encoding="utf-8"))
            rows = doc.get("workflows") if isinstance(doc, dict) else doc
            origin = "snapshot"
        else:
            from scripts.lib import n8n_live_inventory as inv

            rows, origin = inv.read_active_workflows(), "n8n DB (read-only SELECT)"
    except Exception as exc:  # noqa: BLE001 -- an unreadable n8n DB is NOT_MEASURED, never clean
        return None, {"status": "unavailable", "rows_read": 0, "note": type(exc).__name__}
    rows = [r for r in rows or [] if r.get("active", True)]
    return rows, {"status": "ok", "origin": origin, "rows_read": len(rows)}


def build(root: Path, *, crontab_file: Optional[str] = None, no_crontab: bool = False,
          n8n_snapshot: Optional[str] = None, no_n8n: bool = False, now: Optional[str] = None,
          ledger: Optional[dict[str, Any]] = None, ledger_source: Optional[dict[str, Any]] = None,
          window_hours: float = 168.0) -> tuple[dict[str, Any], dict[str, Any]]:
    """Manifest + report. ``ledger``/``ledger_source`` come from scripts/ops/lane_truth.py; the generator alone does
    not read the ledger, and then no ledger source is listed at all."""
    registry, s_reg = _read(root, REGISTRY_REL)
    allowlist, s_allow = _read(root, ALLOWLIST_REL)
    contracts, s_con = _read(root, CONTRACTS_REL)
    cron, s_cron = read_crontab(crontab_file, no_crontab)
    n8n, s_n8n = read_n8n(n8n_snapshot, no_n8n)
    generated_at = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    sources = {"registry": s_reg, "allowlist": s_allow, "contracts": s_con, "crontab": s_cron, "n8n_db": s_n8n}
    if ledger_source is not None:
        sources["ledger"] = ledger_source
    manifest = lm.build_manifest(registry, allowlist, contracts, generated_at=generated_at, sources=sources)
    errors = lm.validate(manifest)
    findings = lm.disagreements(manifest, allowlist=allowlist, contracts=contracts, cron_lines=cron, n8n_active=n8n,
                                ledger=ledger, window_hours=window_hours)
    view_equal = lm.registry_view(manifest) == registry and \
        json.dumps(lm.registry_view(manifest)) == json.dumps(registry)
    report = {
        "schema": "LaneManifestBuildReport@v1",
        "generated_at": generated_at,
        "sources": sources,
        "not_measured": sorted(k for k, v in sources.items() if v["status"] != "ok"),
        "lanes": len(manifest["lanes"]),
        "schema_errors": errors,
        "registry_view_identical": view_equal,
        "counts_by_code": lm.counts_by_code(findings),
        "fingerprint": lm.fingerprint(findings),
        "disagreements": findings,
    }
    return manifest, report


def summary(report: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    states: dict[str, int] = {}
    runners: dict[str, int] = {}
    for lane in manifest["lanes"]:
        states[lane["state"]] = states.get(lane["state"], 0) + 1
        runners[lane["schedule"]["runner"]] = runners.get(lane["schedule"]["runner"], 0) + 1
    return {k: report[k] for k in ("generated_at", "lanes", "not_measured", "registry_view_identical",
                                   "counts_by_code", "fingerprint")} | {
        "schema_errors": len(report["schema_errors"]),
        "rows_read": {k: v.get("rows_read") for k, v in report["sources"].items()},
        "states": dict(sorted(states.items())), "runners": dict(sorted(runners.items())),
        "armed": sum(1 for l in manifest["lanes"] if l["armed"]),
        "manifest_bytes": len(json.dumps(manifest, ensure_ascii=False)),
    }


def _write(path: str, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)


def check(root: Path, manifest_path: str) -> int:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    errors = lm.validate(manifest)
    registry = json.loads((root / REGISTRY_REL).read_text(encoding="utf-8"))
    view = lm.registry_view(manifest)
    same = json.dumps(view) == json.dumps(registry)
    drift = sorted({str(l.get("lane_id")) for l in registry.get("lanes") or []} ^
                   {str(l.get("lane_id")) for l in view.get("lanes") or []})
    changed = sorted(str(a.get("lane_id")) for a, b in zip(registry.get("lanes") or [], view.get("lanes") or [])
                     if json.dumps(a) != json.dumps(b))
    print(json.dumps({"schema_errors": errors[:20], "identical": same, "ids_added_or_removed": drift[:50],
                      "rows_changed": changed[:50]}, indent=2))
    return 0 if same and not errors else 1


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT), help="repo tree to read config/ from (default: this tree)")
    ap.add_argument("--crontab-file", help="crontab snapshot to read instead of `crontab -l`")
    ap.add_argument("--no-crontab", action="store_true")
    ap.add_argument("--n8n-snapshot", help="JSON list (or {workflows:[...]}) of active workflows instead of the DB")
    ap.add_argument("--no-n8n", action="store_true")
    ap.add_argument("--now", help="fixed generated_at (tests)")
    ap.add_argument("--out", help="write the manifest here")
    ap.add_argument("--report", help="write the full disagreement report here")
    ap.add_argument("--render-registry", help="write the LaneRegistry@v1 view rendered from the manifest here")
    ap.add_argument("--check", metavar="MANIFEST", help="exit 1 if MANIFEST's registry view != the registry")
    a = ap.parse_args(argv)
    root = Path(a.root)
    if a.check:
        return check(root, a.check)
    manifest, report = build(root, crontab_file=a.crontab_file, no_crontab=a.no_crontab,
                             n8n_snapshot=a.n8n_snapshot, no_n8n=a.no_n8n, now=a.now)
    wrote = []
    if a.out:
        _write(a.out, json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
        wrote.append(a.out)
    if a.report:
        _write(a.report, json.dumps(report, indent=1, ensure_ascii=False) + "\n")
        wrote.append(a.report)
    if a.render_registry:
        _write(a.render_registry, lm.render_registry(manifest))
        wrote.append(a.render_registry)
    out = summary(report, manifest)
    out["mode"] = "write" if wrote else "dry-run (nothing written)"
    out["wrote"] = wrote
    print(json.dumps(out, indent=2))
    return 1 if report["schema_errors"] or not report["registry_view_identical"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
