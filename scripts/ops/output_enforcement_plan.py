#!/usr/bin/env python3
"""output_enforcement_plan.py — which lanes turn red, and why, when the output proof gaps close (LQ-20261107-1004,
Fable audit LQ-984 #7, Q3.1-3.3). Read-only; the dry run is the product.

Three gaps, measured on real rows:
  declared_not_enforced  live RUN_DONE runs whose contract rule was recorded but not applied (allowlist entry without
                         ``output_receipt: v2``). After the grace deadline: RUN_FAILED ``output_not_enforced``.
  empty_uncited          live RUN_DONE runs graded ``empty_allowed`` on a self-reported ``empty_reason`` whose contract
                         names no ``upstream_count_field``. After the deadline: RUN_FAILED ``empty_upstream_uncited``.
  file_mtime             ACTIVE registry lanes whose output signal is a file mtime ("the job ran", not "it wrote").
                         A proposal per lane: the lane's receipt field (json_key ok_at), a JSON key already in the
                         file, a db_max on the store the contract names, or ``needs_owner``. Nothing turns red here.

Sources: config/n8n_health_contracts.json, config/n8n_run_allowlist.json, config/lane_registry.json,
config/n8n_output_enforcement.json under --root; the coordination ledger (sqlite mode=ro, PRAGMA query_only) and the
newest per-attempt lane receipt (data/runtime/lane_attempts/<lane>/) under --state-root.

Default prints the plan to stdout and writes nothing; --out FILE writes it there. Exit 0 with a plan, 2 when the
ledger could not be read (NOT_MEASURED, never an empty red list). No config, ledger, crontab or DB write, ever.
MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_registry_runtime_truth as rrt  # noqa: E402
from scripts.lib import n8n_output_verdict as ov  # noqa: E402

SCHEMA = "OutputEnforcementPlan@v1"
POLICY_REL = Path("config/n8n_output_enforcement.json")
CONTRACTS_REL = Path("config/n8n_health_contracts.json")
ALLOWLIST_REL = Path("config/n8n_run_allowlist.json")
REGISTRY_REL = Path("config/lane_registry.json")
ATTEMPTS_REL = Path("data/runtime/lane_attempts")
DEFAULT_WINDOW_HOURS = 168.0
#: receipt keys that name a count of input READ (not work done); candidates for ``upstream_count_field``.
_UPSTREAM_NAME = re.compile(r"(checked|seen|scanned|read|input|candidates|eligible|due|listed|polled|queue|backlog|"
                            r"tracked|universe|fetched|considered)[a-z_]*(_count|_n|s)?$")
_TS_KEYS = ("ok_at", "generated_at", "finished_at", "updated_at", "as_of", "written_at")
_STORE_RE = re.compile(r"\bPostgres\s+([a-z_][a-z0-9_]*)\b")


def _load(root: Path, rel: Path) -> Any:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def contract_rules(contracts: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(c["id"]): c for c in contracts.get("contracts") or []
            if c.get("kind") == "lane" and isinstance(c.get("expected_output"), Mapping)}


def read_live_verdicts(ledger: Path, since: datetime) -> tuple[Optional[dict[str, dict[str, Any]]], str]:
    """{lane: {runs, verdicts{v: n}, uncited_empty, last_requested_at}} over live RUN_DONE runs since ``since``."""
    if not ledger.exists():
        return None, f"{rrt.LEDGER_REL} absent"
    try:
        conn = rrt.connect_ro(ledger)
        rows = conn.execute(
            "SELECT lane_id, requested_at, receipt_json FROM runs WHERE mode='live' AND state='RUN_DONE' "
            "AND requested_at >= ?", (since.isoformat(timespec="seconds"),)).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        return None, f"ledger unreadable: {type(exc).__name__}"
    out: dict[str, dict[str, Any]] = {}
    for lane, at, raw in rows:
        try:
            ovd = (json.loads(raw or "{}") or {}).get("output_verdict") or {}
        except ValueError:
            ovd = {"verdict": "receipt_unparseable"}
        v = str(ovd.get("verdict") or "absent")
        rec = out.setdefault(str(lane), {"runs": 0, "verdicts": {}, "uncited_empty": 0, "last_requested_at": None})
        rec["runs"] += 1
        rec["verdicts"][v] = rec["verdicts"].get(v, 0) + 1
        if ov.gap_of(ovd) == "empty_uncited":
            rec["uncited_empty"] += 1
        rec["last_requested_at"] = max(filter(None, (rec["last_requested_at"], str(at))))
    return out, f"{len(rows)} live RUN_DONE rows"


def upstream_candidates(state_root: Path, lane: str) -> list[str]:
    """Int fields in the newest attempt receipt whose name says 'input seen' (top level and summary.*)."""
    d = state_root / ATTEMPTS_REL / lane
    try:
        newest = max(d.glob("*.json"), key=lambda p: p.stat().st_mtime)
        doc = json.loads(newest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = []
    for prefix, obj in (("", doc), ("summary.", doc.get("summary"))):
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                if isinstance(v, int) and not isinstance(v, bool) and _UPSTREAM_NAME.search(k) and \
                        k not in ("produced_count", "attempted_count"):
                    found.append(prefix + k)
    return sorted(found)


def red_list(verdicts: Mapping[str, Mapping[str, Any]], rules: Mapping[str, Mapping[str, Any]],
             state_root: Path, deadline: Optional[str]) -> list[dict[str, Any]]:
    rows = []
    for lane in sorted(verdicts):
        v = verdicts[lane]
        dne = v["verdicts"].get("declared_not_enforced", 0)
        if dne:
            rows.append({"lane_id": lane, "gap": "declared_not_enforced", "failing_reason": "output_not_enforced",
                         "runs_in_window": v["runs"], "gap_runs": dne, "last_requested_at": v["last_requested_at"],
                         "red_from": deadline,
                         "to_stay_green": "lane writes LaneRunReceipt@v2 produced_count AND its allowlist entry gets "
                                          "output_receipt: v2 (then the rule is graded per run)"})
        if v["uncited_empty"]:
            eo = (rules.get(lane) or {}).get("expected_output") or {}
            if eo.get("upstream_count_field"):
                continue  # cited from now on: older rows predate the field
            rows.append({"lane_id": lane, "gap": "empty_uncited", "failing_reason": "empty_upstream_uncited",
                         "runs_in_window": v["runs"], "gap_runs": v["uncited_empty"],
                         "last_requested_at": v["last_requested_at"], "red_from": deadline,
                         "upstream_candidates": upstream_candidates(state_root, lane),
                         "to_stay_green": "contract names upstream_count_field and the receipt carries it as an int"})
    return rows


def propose_signal(lane: Mapping[str, Any], *, state_root: Path, v2: bool, rule: Optional[Mapping[str, Any]]
                   ) -> dict[str, Any]:
    """One file_mtime lane -> the strongest signal its own artifacts already support."""
    lid = str(lane.get("lane_id"))
    sig = lane.get("output_signal") or {}
    path = str(sig.get("path") or "")
    receipt = f"data/runtime/{lid}_last.json"
    if v2 or (state_root / receipt).exists():
        return {"proposed": {"kind": "json_key", "path": receipt, "key": "ok_at"},
                "basis": "the lane's own LaneRunReceipt (written only on a run that finished ok)"}
    if path.endswith(".json") and not path.startswith(("/", "~")):
        try:
            doc = json.loads((state_root / path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = None
        key = next((k for k in _TS_KEYS if isinstance(doc, Mapping) and doc.get(k)), None)
        if key:
            return {"proposed": {"kind": "json_key", "path": path, "key": key},
                    "basis": f"the file already carries {key}; the lane sets it, a touch does not"}
    for e in ((rule or {}).get("expected_output") or {}).get("evidence") or []:
        m = _STORE_RE.search(str(e.get("ref") or "")) if e.get("kind") == "store_rows" else None
        if m:
            return {"proposed": {"kind": "db_max", "table": m.group(1), "column": None},
                    "basis": "the contract names the store it writes; the owner names the write-time column"}
    return {"proposed": None, "basis": "needs_owner: the only artifact is " + (
        "a log (mtime proves it ran, not that it wrote)" if path.endswith(".log") else f"{path or 'no path'}")}


def file_mtime_plan(registry: Mapping[str, Any], allowlist: Mapping[str, Any], rules: Mapping[str, Any],
                    state_root: Path) -> list[dict[str, Any]]:
    v2 = {str(e.get("lane_id")) for e in allowlist.get("lanes") or [] if e.get("output_receipt") == "v2"}
    out = []
    for lane in registry.get("lanes") or []:
        if lane.get("state") != "ACTIVE" or (lane.get("output_signal") or {}).get("kind") != "file_mtime":
            continue
        lid = str(lane.get("lane_id"))
        p = propose_signal(lane, state_root=state_root, v2=lid in v2, rule=rules.get(lid))
        out.append({"lane_id": lid, "current": {"kind": "file_mtime", "path": lane["output_signal"].get("path")}}
                   | p)
    return out


def plan(root: Path, state_root: Path, *, now: datetime, window_hours: float) -> dict[str, Any]:
    policy = _load(root, POLICY_REL)
    problems = ov.validate_enforcement_policy(policy)
    deadline = None
    if not problems:
        start = datetime.fromisoformat(policy["grace_starts_at"])
        deadline = (start + timedelta(hours=float(policy["grace_hours"]))).isoformat(timespec="seconds")
    rules = contract_rules(_load(root, CONTRACTS_REL))
    allowlist = _load(root, ALLOWLIST_REL)
    registry = _load(root, REGISTRY_REL)
    since = now - timedelta(hours=window_hours)
    verdicts, note = read_live_verdicts(state_root / rrt.LEDGER_REL, since)
    signals = file_mtime_plan(registry, allowlist, rules, state_root)
    by_kind: dict[str, int] = {}
    for s in signals:
        k = (s["proposed"] or {}).get("kind") or "needs_owner"
        by_kind[k] = by_kind.get(k, 0) + 1
    doc: dict[str, Any] = {
        "schema": SCHEMA, "generated_at": now.isoformat(timespec="seconds"), "window_hours": window_hours,
        "policy": {"grace_starts_at": policy.get("grace_starts_at"), "grace_hours": policy.get("grace_hours"),
                   "deadline": deadline, "problems": problems},
        "ledger": {"status": "ok" if verdicts is not None else "unavailable", "note": note},
        "verdict_totals": {}, "red": None, "red_counts": None,
        "file_mtime": {"active_lanes": len(signals), "proposals_by_kind": dict(sorted(by_kind.items())),
                       "lanes": signals},
    }
    if verdicts is None:
        return doc
    totals: dict[str, int] = {}
    for v in verdicts.values():
        for k, n in v["verdicts"].items():
            totals[k] = totals.get(k, 0) + n
    red = red_list(verdicts, rules, state_root, deadline)
    counts: dict[str, int] = {}
    for r in red:
        counts[r["gap"]] = counts.get(r["gap"], 0) + 1
    doc.update({"verdict_totals": dict(sorted(totals.items())), "red": red,
                "red_counts": counts | {"lanes": len({r["lane_id"] for r in red})}})
    return doc


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--state-root", default=str(rrt.DEFAULT_STATE_ROOT))
    ap.add_argument("--window-hours", type=float, default=DEFAULT_WINDOW_HOURS)
    ap.add_argument("--now", help="fixed ISO time (tests)")
    ap.add_argument("--out", help="write the full plan here (default: print a summary, write nothing)")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now) if a.now else datetime.now(timezone.utc)
    doc = plan(Path(a.root), Path(a.state_root), now=now, window_hours=a.window_hours)
    if a.out:
        p = Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    shown = {k: doc[k] for k in ("generated_at", "policy", "ledger", "verdict_totals", "red_counts")}
    shown["red_lanes"] = [f"{r['lane_id']}:{r['gap']}" for r in doc["red"] or []]
    shown["file_mtime"] = {k: doc["file_mtime"][k] for k in ("active_lanes", "proposals_by_kind")}
    shown["wrote"] = [a.out] if a.out else []
    print(json.dumps(shown, indent=2))
    return 2 if doc["red"] is None else 0


if __name__ == "__main__":
    raise SystemExit(main())
