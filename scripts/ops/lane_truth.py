#!/usr/bin/env python3
"""lane_truth.py — reconcile the lane manifest against what the host actually runs, and write one machine verdict
(LaneTruth@v1). LQ-20261107-1003 step 3 (Fable audit LQ-984 Q6 #2 + #14, REBUILD-SPEC registry-runtime-truth).

Five sources, all read-only:
  registry + allowlist + contracts  config/ under --root (in production: CURRENT, the served release)
  crontab                           `crontab -l`, or --crontab-file; --no-crontab = NOT_MEASURED
  n8n DB                            active workflows via scripts/lib/n8n_live_inventory (one SELECT); --n8n-snapshot
  ledger                            <state-root>/data/governance/n8n_coordination_ledger.sqlite, mode=ro + query_only
The manifest is built from the first three (scripts/ops/build_lane_manifest.py) and every disagreement with the
other two is a coded finding (scripts/lib/lane_manifest.py CODES). Cron lines are attributed by effect-claim key,
both directions: a host line no lane claims is UNDECLARED_CRON_LINE.

Verdict:
  FAIL          at least one error-severity finding (even when a source was not measured)
  NOT_MEASURED  no error finding, but a source could not be read — never reported as clean
  PASS          every source read, no error finding; `empty_reason` says why the error list is empty

Default is a dry run: the verdict goes to stdout and nothing is written. --apply writes
<state-root>/data/runtime/lane_truth/latest.json (atomic) and appends one counts-only line to history.jsonl there.
Exit 0 when a verdict was produced (PASS or FAIL — the verdict is the output, not the exit code), 2 on NOT_MEASURED,
and with --strict also 1 on FAIL.

No crontab, systemd, n8n, DB, registry or ledger write, ever. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_registry_runtime_truth as rrt  # noqa: E402
from scripts.lib import lane_manifest as lm  # noqa: E402
from scripts.ops import build_lane_manifest as blm  # noqa: E402

SCHEMA = "LaneTruth@v1"
LANE_ID = "lane-truth"
OUT_REL = Path("data") / "runtime" / "lane_truth"
DEFAULT_WINDOW_HOURS = 168.0
WARN_IDS_CAP = 60


def read_ledger(state_root: Path, now: datetime, window_hours: float, skip: bool
                ) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    if skip:
        return None, {"status": "skipped", "rows_read": 0, "note": "--no-ledger: ledger rules NOT_MEASURED"}
    path = state_root / rrt.LEDGER_REL
    status, data, note = rrt.read_ledger(path, now - timedelta(hours=window_hours))
    if status != rrt.SOURCE_OK:
        return None, {"status": "unavailable", "rows_read": 0, "note": note}
    live = data.get("live_runs") or {}
    return data, {"status": "ok", "path": str(rrt.LEDGER_REL), "rows_read": sum(v["count"] for v in live.values()),
                  "lanes_with_live_runs": len(live), "window_hours": window_hours}


def verdict_of(findings: list[dict[str, Any]], not_measured: list[str]) -> tuple[str, str]:
    errors = [f for f in findings if f["severity"] == "error"]
    if errors:
        codes = lm.counts_by_code(errors)
        return "FAIL", "error findings: " + ", ".join(f"{k}={v}" for k, v in codes.items())
    if not_measured:
        return "NOT_MEASURED", "no error finding, but not read: " + ", ".join(not_measured)
    return "PASS", ""


def reconcile(root: Path, state_root: Path, *, now: Optional[datetime] = None, crontab_file: Optional[str] = None,
              no_crontab: bool = False, n8n_snapshot: Optional[str] = None, no_n8n: bool = False,
              no_ledger: bool = False, window_hours: float = DEFAULT_WINDOW_HOURS) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    ledger, s_ledger = read_ledger(state_root, now, window_hours, no_ledger)
    manifest, report = blm.build(root, crontab_file=crontab_file, no_crontab=no_crontab, n8n_snapshot=n8n_snapshot,
                                 no_n8n=no_n8n, now=stamp, ledger=ledger, ledger_source=s_ledger,
                                 window_hours=window_hours)
    sources = report["sources"]
    findings = report["disagreements"]
    not_measured = sorted(k for k, v in sources.items() if v["status"] != "ok")
    if report["schema_errors"]:
        not_measured.append("manifest_schema")
    verdict, reason = verdict_of(findings, not_measured)
    errors = [f for f in findings if f["severity"] == "error"]
    warns: dict[str, list[str]] = {}
    for f in findings:
        if f["severity"] == "warn":
            warns.setdefault(f["code"], []).append(str(f.get("lane_id") or f["evidence"].get("line")
                                                        or f["evidence"].get("workflow_name") or ""))
    return {
        "schema": SCHEMA,
        "lane_id": LANE_ID,
        "generated_at": stamp,
        "verdict": verdict,
        "reason": reason,
        "empty_reason": ("every source read; no lane disagrees with the crontab, n8n DB or ledger at error severity"
                         if verdict == "PASS" else None),
        "sources": sources,
        "rows_read": {k: v.get("rows_read", 0) for k, v in sources.items()},
        "not_measured": not_measured,
        "lanes": report["lanes"],
        "schema_errors": report["schema_errors"][:20],
        "registry_view_identical": report["registry_view_identical"],
        "counts_by_code": lm.counts_by_code(findings),
        "errors": len(errors),
        "warns": sum(len(v) for v in warns.values()),
        "fingerprint": lm.fingerprint(findings),
        "error_findings": errors,
        "warn_ids": {k: v[:WARN_IDS_CAP] for k, v in sorted(warns.items())},
    }


def write(state_root: Path, verdict: dict[str, Any]) -> list[str]:
    out = state_root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    latest = out / "latest.json"
    tmp = latest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(verdict, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(latest)
    line = {k: verdict[k] for k in ("generated_at", "verdict", "rows_read", "not_measured", "counts_by_code",
                                    "errors", "warns", "fingerprint")}
    with (out / "history.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, separators=(",", ":")) + "\n")
    return [str(latest), str(out / "history.jsonl")]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT), help="tree to read config/ from (production: CURRENT)")
    ap.add_argument("--state-root", default=str(rrt.DEFAULT_STATE_ROOT))
    ap.add_argument("--crontab-file")
    ap.add_argument("--no-crontab", action="store_true")
    ap.add_argument("--n8n-snapshot")
    ap.add_argument("--no-n8n", action="store_true")
    ap.add_argument("--no-ledger", action="store_true")
    ap.add_argument("--window-hours", type=float, default=DEFAULT_WINDOW_HOURS)
    ap.add_argument("--now", help="fixed ISO time (tests)")
    ap.add_argument("--apply", action="store_true", help="write latest.json + history.jsonl under the state root")
    ap.add_argument("--strict", action="store_true", help="exit 1 on FAIL")
    ap.add_argument("--full", action="store_true", help="print the whole verdict, not the summary")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now) if a.now else None
    state_root = Path(a.state_root)
    v = reconcile(Path(a.root), state_root, now=now, crontab_file=a.crontab_file, no_crontab=a.no_crontab,
                  n8n_snapshot=a.n8n_snapshot, no_n8n=a.no_n8n, no_ledger=a.no_ledger, window_hours=a.window_hours)
    wrote = write(state_root, v) if a.apply else []
    shown = v if a.full else {k: v[k] for k in ("generated_at", "verdict", "reason", "empty_reason", "rows_read",
                                                "not_measured", "counts_by_code", "errors", "warns", "fingerprint")}
    shown = dict(shown) | {"mode": "apply" if a.apply else "dry-run (nothing written)", "wrote": wrote}
    print(json.dumps(shown, indent=2))
    if v["verdict"] == "NOT_MEASURED":
        return 2
    return 1 if a.strict and v["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
