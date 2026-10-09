#!/usr/bin/env python3
"""check_n8n_workflow_drift.py — every active n8n workflow matches its git copy, or says how it does not.

AGENTS.md 3.0.0 §23.10 P18 (audit C G9): n8n Community has no git source control, so the generated set
under docs/implementation/n8n-parallel/workflows/generated/ is the reviewed copy and the n8n database is
only where it runs. Parity was true on 2026-10-09 by one hand measurement. This makes it a check.

For each ACTIVE workflow (by id) it compares nodes, connections and settings against the generated file
with the same id (pending/ included), after normalising:

  * the relay URL the operator substitutes at import (``http://<host>:18092``) is put back to the
    generator's placeholder (INDEX ``relay_url_placeholder``), so the install-time edit is not drift;
  * node ``position`` and ``webhookId`` are dropped (canvas layout and n8n-assigned ids are not behaviour);
  * nodes are keyed by name; keys whose value is null are dropped.

Verdicts per workflow: OK, DRIFT (with the differing fields), MISSING_IN_GIT (no generated file has the
id: a UI-built or hand-imported workflow). A workflow that still carries the unsubstituted placeholder
host is reported as ``placeholder_unsubstituted`` beside its verdict: it matches git but cannot reach the
relay, so every fire fails.

    python3 scripts/check_n8n_workflow_drift.py --dry-run            # live read, print, write nothing
    python3 scripts/check_n8n_workflow_drift.py --write              # live read, write the receipt
    python3 scripts/check_n8n_workflow_drift.py --workflows-json F   # offline (CI / fixtures)

Receipt: ``$TRADEAI_STATE_ROOT/data/runtime/n8n_workflow_drift_last.json`` (``--receipt`` overrides).
Exit codes: 0 clean (or report-only), 1 DRIFT/MISSING_IN_GIT with --fail-on-drift, 2 cannot run.

Proposed lane ``n8n-workflow-drift-check`` (registry row NEVER_SCHEDULED, allowlist entry): it is not
scheduled until the operator imports a generated workflow under a grant naming its id.

AUTHORITY: READ_ONLY_ADVISORY. One SELECT against the n8n DB; no n8n write, no send, no network.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import n8n_live_inventory as inv  # noqa: E402

SCHEDULED_ENTRYPOINT = (
    "n8n lane n8n-workflow-drift-check (config/lane_registry.json NEVER_SCHEDULED until a generated "
    "workflow is imported under a grant; config/n8n_run_allowlist.json entry, --dry-run / --write)"
)
SCHEMA = "N8nWorkflowDriftReceipt@v1"
RECEIPT_REL = Path("data") / "runtime" / "n8n_workflow_drift_last.json"

OK = "OK"
DRIFT = "DRIFT"
MISSING_IN_GIT = "MISSING_IN_GIT"
FINDING_STATUSES = (DRIFT, MISSING_IN_GIT)

DEFAULT_PLACEHOLDER = "http://RELAY_HOST:18092"
DROP_NODE_KEYS = ("position", "webhookId")


def _state_root() -> Path:
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env)
    try:
        from scripts.lib.canonical_store_registry import production_state_root

        return Path(production_state_root())
    except Exception:  # noqa: BLE001
        return Path.home() / "trade-ai-releases" / "persistent-state"


def _relay_pattern(placeholder: str) -> re.Pattern[str]:
    m = re.match(r"^(https?)://[^/:]+:(\d+)$", placeholder)
    scheme, port = (m.group(1), m.group(2)) if m else ("http", "18092")
    return re.compile(rf"{scheme}://[A-Za-z0-9_.\-]+:{port}")


def _substitute(obj: Any, pat: re.Pattern[str], placeholder: str) -> Any:
    if isinstance(obj, str):
        return pat.sub(placeholder, obj)
    if isinstance(obj, list):
        return [_substitute(x, pat, placeholder) for x in obj]
    if isinstance(obj, dict):
        return {k: _substitute(v, pat, placeholder) for k, v in obj.items()}
    return obj


def _drop_nulls(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _drop_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_drop_nulls(x) for x in obj]
    return obj


def normalise(workflow: dict, *, placeholder: str = DEFAULT_PLACEHOLDER) -> dict:
    """The behaviour-bearing part of a workflow, comparable across n8n and git."""
    pat = _relay_pattern(placeholder)
    nodes: dict[str, Any] = {}
    for node in workflow.get("nodes") or []:
        n = {k: v for k, v in node.items() if k not in DROP_NODE_KEYS}
        nodes[str(node.get("name"))] = _drop_nulls(_substitute(n, pat, placeholder))
    return {
        "nodes": nodes,
        "connections": _drop_nulls(_substitute(workflow.get("connections") or {}, pat, placeholder)),
        "settings": _drop_nulls(workflow.get("settings") or {}),
    }


def diff_fields(live: dict, git: dict) -> list[str]:
    """Names of what differs: 'settings', 'connections', 'node:<name>:<key>', 'node:<name>:missing_in_*'."""
    out: list[str] = []
    for part in ("settings", "connections"):
        if live[part] != git[part]:
            out.append(part)
    ln, gn = live["nodes"], git["nodes"]
    for name in sorted(set(ln) | set(gn)):
        if name not in gn:
            out.append(f"node:{name}:missing_in_git")
            continue
        if name not in ln:
            out.append(f"node:{name}:missing_in_live")
            continue
        for key in sorted(set(ln[name]) | set(gn[name])):
            if ln[name].get(key) != gn[name].get(key):
                out.append(f"node:{name}:{key}")
    return out


def evaluate(
    workflows: list[dict],
    *,
    git: dict[str, tuple[Path, dict]],
    placeholder: str,
    include_inactive: bool = False,
    repo_root: Path = ROOT,
) -> list[dict]:
    host_pat = re.compile(re.escape(placeholder.split("://", 1)[-1].rsplit(":", 1)[0]))
    rows: list[dict] = []
    for wf in sorted(workflows, key=lambda w: str(w.get("id"))):
        if not include_inactive and not wf.get("active"):
            continue
        wid = str(wf.get("id"))
        unsubstituted = bool(host_pat.search(json.dumps(wf.get("nodes") or [])))
        row: dict[str, Any] = {
            "id": wid,
            "name": wf.get("name"),
            "active": bool(wf.get("active")),
            "placeholder_unsubstituted": unsubstituted,
        }
        hit = git.get(wid)
        if hit is None:
            row.update(status=MISSING_IN_GIT, git_file=None, diffs=[])
        else:
            path, doc = hit
            diffs = diff_fields(normalise(wf, placeholder=placeholder), normalise(doc, placeholder=placeholder))
            try:
                rel = str(path.resolve().relative_to(repo_root.resolve()))
            except ValueError:
                rel = path.name
            row.update(status=DRIFT if diffs else OK, git_file=rel, diffs=diffs)
        rows.append(row)
    return rows


def build_receipt(rows: list[dict], *, source: str, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in (OK, DRIFT, MISSING_IN_GIT)}
    findings = [r for r in rows if r["status"] in FINDING_STATUSES]
    unsub = [r["id"] for r in rows if r.get("placeholder_unsubstituted")]
    return {
        "schema": SCHEMA,
        "as_of": now.replace(microsecond=0).isoformat(),
        "source": source,
        "authority": "READ_ONLY_ADVISORY",
        "evaluated_count": len(rows),
        "active_count": sum(1 for r in rows if r.get("active")),
        "counts": counts,
        "placeholder_unsubstituted": unsub,
        "verdict": "CLEAN" if not findings else "DRIFT",
        "workflows": rows,
        # Shaped like scripts/n8n_incident_fanin.py findings so a later fan-in source can read them
        # verbatim. NOT wired: nothing sends from here (P18 asks for the check; alerting is a separate PR).
        "fanin_findings": [
            {
                "source": "n8n_workflow_drift",
                "item": f"{r['id']}:{r['status']}",
                "severity": "P2",
                "detail": f"{r.get('name')} {','.join(r['diffs'])[:120]}",
                "artifact_rel": str(RECEIPT_REL),
                "store": "data/runtime",
            }
            for r in findings
        ],
        "fanin_wired": False,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the verdicts; write nothing (default)")
    mode.add_argument("--write", action="store_true", help="write the receipt under the state root")
    ap.add_argument(
        "--workflows-json",
        default=None,
        help="read workflow rows (id, name, active, nodes, connections, settings) from this file "
        "instead of the live n8n DB",
    )
    ap.add_argument("--container", default=inv.DB_CONTAINER)
    ap.add_argument("--generated-dir", default=None)
    ap.add_argument("--index", default=None, help="generated INDEX.json (relay placeholder)")
    ap.add_argument("--receipt", default=None, help="receipt path (default $STATE_ROOT/" + str(RECEIPT_REL) + ")")
    ap.add_argument("--include-inactive", action="store_true")
    ap.add_argument("--fail-on-drift", action="store_true", help="exit 1 on DRIFT or MISSING_IN_GIT")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    try:
        if a.workflows_json:
            workflows = json.loads(Path(a.workflows_json).read_text(encoding="utf-8"))
            source = f"file:{Path(a.workflows_json).name}"
        else:
            workflows = inv.read_workflow_bodies(container=a.container)
            source = f"docker exec {a.container} psql (SELECT workflow_entity)"
        index = inv.load_generated_index(Path(a.index) if a.index else None)
        git = inv.git_workflows(Path(a.generated_dir) if a.generated_dir else None)
    except Exception as exc:  # noqa: BLE001 — cannot run != clean
        print(f"n8n workflow drift CANNOT RUN: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    placeholder = str(index.get("relay_url_placeholder") or DEFAULT_PLACEHOLDER)
    rows = evaluate(workflows, git=git, placeholder=placeholder, include_inactive=a.include_inactive)
    receipt = build_receipt(rows, source=source)

    if a.write:
        path = Path(a.receipt) if a.receipt else _state_root() / RECEIPT_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)
        receipt["receipt_path"] = str(path)

    if a.json:
        print(json.dumps(receipt, indent=1))
    else:
        c = receipt["counts"]
        print(
            f"n8n workflow drift: {receipt['evaluated_count']} evaluated ({receipt['active_count']} active)  OK={c[OK]} DRIFT={c[DRIFT]} "
            f"MISSING_IN_GIT={c[MISSING_IN_GIT]}  placeholder_unsubstituted={len(receipt['placeholder_unsubstituted'])}"
            f"  ({'written ' + receipt['receipt_path'] if a.write else 'dry-run, nothing written'})"
        )
        for r in rows:
            if r["status"] != OK:
                print(f"    ✗ {r['status']} {r['id']} {r.get('name')}: {', '.join(r['diffs'])[:160]}")
    if a.fail_on_drift and receipt["verdict"] != "CLEAN":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
