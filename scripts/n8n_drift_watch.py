#!/usr/bin/env python3
"""n8n_drift_watch.py — the host-scheduled n8n workflow-drift check that pages P1 (FW-P3). Dry run by default.

Why: AGENTS.md §23.23 "Workflow governance" (2) — any git-vs-live drift pages **P1** — and §23.24 Logging (5) — the
drift check runs on a schedule outside n8n. The checker exists (``scripts/check_n8n_workflow_drift.py``, producer of
``N8nWorkflowDriftReceipt@v1``) but nothing ran it: the framework scorecard measured "no receipt, no timer"
(N8N_FRAMEWORK_SCORECARD_20261015 FW-P3; PROGRAM_TRACKER row 40). Its fan-in findings are P2 and the fan-in is an
n8n-fired lane, so it can neither page P1 nor page when n8n is the thing that drifted.

What one run does (reusing the drift checker, not copying it):

1. reads every workflow body from the n8n DB (one SELECT, ``scripts/lib/n8n_live_inventory.py``) and evaluates it
   against the reviewed git copy (``check_n8n_workflow_drift.evaluate`` / ``build_receipt``);
2. live: writes the drift receipt to its canonical path (``data/runtime/n8n_workflow_drift_last.json``, the file
   the fan-in already reads) atomically;
3. DRIFT or MISSING_IN_GIT → **P1** through the host SYSTEM ops transport (``scripts/lib/host_p1_pager.py``):
   one page per drift signature after 1 bad run (drift is not a blip), a reminder every 6 h while it stays, one
   recovery message when the live set matches git again. The page names the workflow ids and the runbook.
4. writes ``data/runtime/n8n_drift_watch_last.json`` (``N8nDriftWatch@v1``) — the receipt
   ``scripts/probe_n8n_platform_facts.py`` reads for FW-P3 — and the pager state beside it.

CANNOT RUN (n8n DB unreadable) is not drift and pages nothing here: the drift receipt is not rewritten, the watch
receipt says ``CANNOT_RUN`` and the platform probe reports FW-P3 FAIL; n8n being down is the host dead-man's page
(``scripts/n8n_host_deadman.py``, FW-P6).

    python3 scripts/n8n_drift_watch.py              # dry run: live SELECT, verdicts + the page it WOULD send; writes nothing
    python3 scripts/n8n_drift_watch.py --live       # what the timer runs (operator-installed unit, packet FW-P3)
    python3 scripts/n8n_drift_watch.py --workflows-json F   # offline (tests)

Exit: 0 clean, 1 drift, 2 cannot run (dry run and live alike).
AUTHORITY: OPERATOR_NOTIFY_SYSTEM_OPS. One SELECT; no n8n write, no relay, no broker. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import check_n8n_workflow_drift as D  # noqa: E402
from scripts.lib import host_p1_pager as PG  # noqa: E402
from scripts.lib import n8n_live_inventory as inv  # noqa: E402
from scripts.lib.atomic_json_store import atomic_write_json  # noqa: E402

SCHEDULED_ENTRYPOINT = (
    "systemd --user tradeai-n8n-drift-watch.timer (every 15 min; PROPOSED, operator-installed: "
    "docs/ops/packets/n8n-platform-hardening-20261022/units/)"
)
SCHEMA = "N8nDriftWatch@v1"
RECEIPT_REL = Path("data") / "runtime" / "n8n_drift_watch_last.json"
STATE_REL = Path("data") / "runtime" / "n8n_drift_watch_state.json"
RUNBOOK = "docs/ops/packets/n8n-platform-hardening-20261022/README.md#fw-p3"
PAGE_PREFIX = "n8n-drift"
CADENCE_MIN = 15


def drift_signature(rows: list[dict]) -> str:
    """Stable key of WHAT drifted: a different drift set is a new onset (a new page), the same one is not."""
    bad = sorted((r["id"], r["status"], tuple(r.get("diffs") or ())) for r in rows if r["status"] in D.FINDING_STATUSES)
    return hashlib.sha256(json.dumps(bad).encode()).hexdigest()[:16] if bad else "clean"


def page_text(rows: list[dict], action: dict) -> str:
    bad = [r for r in rows if r["status"] in D.FINDING_STATUSES]
    if action["kind"] == PG.RECOVER:
        return (
            "TRADE AI SYSTEM NOTICE — n8n workflow drift CLEARED\n"
            f"Every active n8n workflow matches its reviewed git copy again (drift since {action.get('onset')}).\n"
            f"Runbook: {RUNBOOK}"
        )
    lines = [
        "TRADE AI SYSTEM ALERT — P1 n8n workflow DRIFT (AGENTS §23.23: workflows are never edited in the UI)",
        f"{len(bad)} active workflow(s) differ from git:",
    ]
    for r in bad[:8]:
        lines.append(f"• {r['id']} {r['status']} {', '.join(r.get('diffs') or [])[:120]}")
    if len(bad) > 8:
        lines.append(f"• … and {len(bad) - 8} more (receipt data/runtime/n8n_workflow_drift_last.json)")
    lines.append(f"Since {action.get('onset')}. Re-import from git under a grant, or archive. Runbook: {RUNBOOK}")
    if action["kind"] == PG.REMIND:
        lines.append("(reminder — still drifted)")
    return "\n".join(lines)


def _load(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def run_once(
    *,
    live: bool,
    root: Path,
    workflows: Optional[list[dict]] = None,
    reader: Optional[Callable[[], list[dict]]] = None,
    now: Optional[datetime] = None,
    sender: Optional[PG.Sender] = None,
    previewer: Optional[PG.Previewer] = None,
    generated_dir: Optional[Path] = None,
    generic_dir: Optional[Path] = None,
    index_path: Optional[Path] = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "as_of": now.replace(microsecond=0).isoformat(),
        "mode": "live" if live else "dry_run",
        "authority": "OPERATOR_NOTIFY_SYSTEM_OPS",
        "cadence_min": CADENCE_MIN,
        "p1_path": PG.P1_PATH,
        "runbook": RUNBOOK,
        "drift_receipt": str(D.RECEIPT_REL),
    }
    try:
        if workflows is None:
            workflows = (reader or inv.read_workflow_bodies)()
            source = f"docker exec {inv.DB_CONTAINER} psql (SELECT workflow_entity)"
        else:
            source = "injected workflows"
        index = inv.load_generated_index(index_path)
        git = D.git_reviewed_set(generated_dir, generic_dir)
    except Exception as exc:  # noqa: BLE001 — cannot run != clean, and != drift
        receipt.update(verdict="CANNOT_RUN", error=f"{type(exc).__name__}: {str(exc)[:200]}", page={"action": PG.NONE})
        if live:
            atomic_write_json(root / RECEIPT_REL, receipt)
        return receipt
    placeholder = str(index.get("relay_url_placeholder") or D.DEFAULT_PLACEHOLDER)
    rows = D.evaluate(workflows, git=git, placeholder=placeholder)
    drift = D.build_receipt(rows, source=source, now=now)
    sig = drift_signature(rows)
    state_path = root / STATE_REL
    state, action = PG.decide(
        _load(state_path), bad=drift["verdict"] != "CLEAN", key=sig, now=now, prefix=PAGE_PREFIX, threshold=1
    )
    state, page = PG.run_action(
        state, action, page_text(rows, action), live=live, now=now, kind="n8n_workflow_drift",
        sender=sender, previewer=previewer,
    )
    receipt.update(
        verdict=drift["verdict"],
        counts=drift["counts"],
        evaluated_count=drift["evaluated_count"],
        drift_signature=sig,
        findings=[{"id": r["id"], "status": r["status"], "diffs": r.get("diffs") or []} for r in rows if r["status"] in D.FINDING_STATUSES],
        severity="P1" if drift["verdict"] != "CLEAN" else None,
        page=page,
    )
    if live:
        atomic_write_json(root / D.RECEIPT_REL, drift)
        atomic_write_json(state_path, state)
        atomic_write_json(root / RECEIPT_REL, receipt)
    return receipt


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--live", action="store_true", help="write receipts and page (default: dry run, writes nothing)")
    ap.add_argument("--workflows-json", default=None, help="offline workflow rows instead of the live n8n DB")
    ap.add_argument("--state-root", default=None, help="default $TRADEAI_STATE_ROOT or ~/trade-ai-releases/persistent-state")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.state_root) if a.state_root else D._state_root()
    workflows = json.loads(Path(a.workflows_json).read_text(encoding="utf-8")) if a.workflows_json else None
    receipt = run_once(live=a.live, root=root, workflows=workflows)
    if a.json:
        print(json.dumps(receipt, indent=1, default=str))
    else:
        c = receipt.get("counts") or {}
        print(
            f"n8n drift watch ({receipt['mode']}): verdict {receipt['verdict']}"
            + (f"  OK={c.get('OK')} DRIFT={c.get('DRIFT')} MISSING_IN_GIT={c.get('MISSING_IN_GIT')}" if c else "")
            + f"  page {receipt['page'].get('action')}"
            + (f" {receipt['page'].get('identity')}" if receipt["page"].get("identity") else "")
            + ("" if a.live else "  (dry run, nothing written or sent)")
        )
        for f in receipt.get("findings") or []:
            print(f"    P1 {f['status']} {f['id']}: {', '.join(f['diffs'])[:160]}")
        if receipt.get("error"):
            print(f"    CANNOT RUN: {receipt['error']}")
    return {"CLEAN": 0, "DRIFT": 1}.get(receipt["verdict"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
