#!/usr/bin/env python3
"""n8n_cutover_checklist.py — the operator's per-lane / per-tranche cutover checklist, from receipts.

Renders the shadow → canary → cutover → rollback ladder of the 2026-10-08 plan
(streamed-humming-wolf, "Rollback triggers" and "Verification") as Markdown checkboxes and
ticks each box only when evidence for it exists on disk. Every input is optional; a missing
file is an unticked box with the path named, never an error.

Evidence read (all under the state root, default `TRADEAI_STATE_ROOT` or the repo):

    data/runtime/n8n_runs/*.json                RunReceipt@v1 (executor) — dry_run / live per lane
    data/runtime/n8n_cutover/*.json             CutoverReceipt@v1 (cutover tool) — cutover / rollback
    config/lane_registry.json                   scheduler.kind == "n8n" after the flip
    data/runtime/n8n_lane_readiness_last.json   readiness verdict per lane
    data/runtime/n8n_migration_board_last.json  board row per lane (phase, rollback_ready)
    docs/implementation/n8n-parallel/workflows/generated/INDEX.json   workflow files exist

    python3 scripts/n8n_cutover_checklist.py --lane n8n-lab-watchdog
    python3 scripts/n8n_cutover_checklist.py --tranche N1 --write

`--write` stores `data/runtime/n8n_cutover_checklist_<lane|tranche>.md` under the state root.

AUTHORITY: READ_ONLY_ADVISORY. Reads receipts; writes only the rendered checklist with --write.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from n8n_workflow_templates import LANES, TRANCHES  # noqa: E402

SCHEMA = "N8nCutoverChecklist@v1"
NO_CONSUMER_REASON = (
    "Operator-run renderer; the Markdown it writes is read by the operator before each cron-write "
    "grant. No lane or job imports it (plan 2026-10-08, workstream H)."
)

RUNS_DIR = Path("data/runtime/n8n_runs")
CUTOVER_DIR = Path("data/runtime/n8n_cutover")
READINESS_FILE = Path("data/runtime/n8n_lane_readiness_last.json")
BOARD_FILE = Path("data/runtime/n8n_migration_board_last.json")
REGISTRY_FILE = Path("config/lane_registry.json")
WORKFLOW_INDEX = Path("docs/implementation/n8n-parallel/workflows/generated/INDEX.json")
OUT_DIR = Path("data/runtime")

DONE_STATES = {"RUN_DONE", "DONE", "SUCCESS", "OK"}


# ---------------------------------------------------------------------------
# tolerant readers
# ---------------------------------------------------------------------------
def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _iter_json_files(directory: Path):
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.json")):
        obj = _load_json(path)
        if isinstance(obj, dict):
            yield path, obj
        elif isinstance(obj, list):
            for row in obj:
                if isinstance(row, dict):
                    yield path, row


def _run_ok(receipt: dict) -> bool:
    state = str(receipt.get("state") or receipt.get("status") or "").upper()
    if state in DONE_STATES:
        return True
    exit_code = receipt.get("exit_code", receipt.get("exit"))
    return exit_code == 0 and state not in {"RUN_FAILED", "RUN_REFUSED", "RUN_SKIPPED_LOCK", "FAILED"}


def run_receipts(state_root: Path, lane_id: str) -> dict[str, list[dict]]:
    """{mode: [receipt, ...]} for the lane; modes seen in the files, not assumed."""
    out: dict[str, list[dict]] = {}
    for path, obj in _iter_json_files(state_root / RUNS_DIR):
        if obj.get("lane_id") != lane_id:
            continue
        mode = str(obj.get("mode") or "unknown")
        row = dict(obj)
        row["_file"] = path.name
        out.setdefault(mode, []).append(row)
    return out


def cutover_receipts(state_root: Path, lane_id: str) -> list[dict]:
    rows = []
    for path, obj in _iter_json_files(state_root / CUTOVER_DIR):
        if obj.get("lane_id") != lane_id:
            continue
        row = dict(obj)
        row["_file"] = path.name
        rows.append(row)
    return rows


def _is_dry(receipt: dict) -> bool:
    if "dry_run" in receipt:
        return bool(receipt["dry_run"])
    if "apply" in receipt:
        return not bool(receipt["apply"])
    return str(receipt.get("mode", "")).lower() in {"dry_run", "dry-run"}


def _action(receipt: dict) -> str:
    return str(receipt.get("action") or receipt.get("operation") or receipt.get("kind") or "").lower()


def registry_kind(state_root: Path, lane_id: str) -> str | None:
    obj = _load_json(state_root / REGISTRY_FILE)
    rows = obj.get("lanes") if isinstance(obj, dict) else obj
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and row.get("lane_id") == lane_id:
            sched = row.get("scheduler") or {}
            return str(sched.get("kind")) if isinstance(sched, dict) else None
    return None


def _lane_row(obj, lane_id: str) -> dict | None:
    """Find a per-lane row in a verdict/board file of unknown exact shape."""
    if not isinstance(obj, dict):
        return None
    for key in ("lanes", "rows", "verdicts", "board"):
        rows = obj.get(key)
        if isinstance(rows, dict) and isinstance(rows.get(lane_id), dict):
            return rows[lane_id]
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("lane_id") == lane_id:
                    return row
    if isinstance(obj.get(lane_id), dict):
        return obj[lane_id]
    return None


def readiness_verdict(state_root: Path, lane_id: str) -> str | None:
    row = _lane_row(_load_json(state_root / READINESS_FILE), lane_id)
    if not row:
        return None
    return str(row.get("verdict") or row.get("readiness") or row.get("status") or "") or None


def board_row(state_root: Path, lane_id: str) -> dict | None:
    return _lane_row(_load_json(state_root / BOARD_FILE), lane_id)


def workflow_files_present(repo_root: Path, lane_id: str) -> tuple[bool, str]:
    idx = _load_json(repo_root / WORKFLOW_INDEX)
    if not isinstance(idx, dict):
        return False, f"{WORKFLOW_INDEX} absent"
    for row in idx.get("lanes") or []:
        if row.get("lane_id") == lane_id:
            base = (repo_root / WORKFLOW_INDEX).parent
            both = (base / row["shadow_file"]).exists() and (base / row["live_file"]).exists()
            return both, f"{row['shadow_file']} + {row['live_file']}"
    return False, "lane not in INDEX.json"


# ---------------------------------------------------------------------------
# checklist
# ---------------------------------------------------------------------------
def lane_items(state_root: Path, repo_root: Path, lane: dict) -> list[dict]:
    lane_id = lane["lane_id"]
    runs = run_receipts(state_root, lane_id)
    dry = [r for r in runs.get("dry_run", []) if _run_ok(r)]
    live = [r for r in runs.get("live", []) if _run_ok(r)]
    failed_live = [r for r in runs.get("live", []) if not _run_ok(r)]
    cuts = cutover_receipts(state_root, lane_id)
    cut_dry = [r for r in cuts if _action(r) in {"cutover", ""} and _is_dry(r)]
    cut_apply = [r for r in cuts if _action(r) in {"cutover", ""} and not _is_dry(r)]
    rb_dry = [r for r in cuts if _action(r) == "rollback" and _is_dry(r)]
    rb_apply = [r for r in cuts if _action(r) == "rollback" and not _is_dry(r)]
    kind = registry_kind(state_root, lane_id)
    verdict = readiness_verdict(state_root, lane_id)
    board = board_row(state_root, lane_id)
    wf_ok, wf_detail = workflow_files_present(repo_root, lane_id)
    phase = str((board or {}).get("phase") or "").upper()
    rollback_ready = bool((board or {}).get("rollback_ready")) if board else False

    def ev(rows: list[dict]) -> str:
        return ", ".join(sorted({r["_file"] for r in rows})[:3]) if rows else "none"

    return [
        {
            "step": "workflows",
            "label": "Workflow JSON generated (shadow + live) and committed",
            "done": wf_ok,
            "evidence": wf_detail,
        },
        {
            "step": "registry_row",
            "label": "Lane registry row exists (kind cron/systemd before the flip)",
            "done": kind is not None,
            "evidence": f"scheduler.kind={kind}" if kind else f"no row in {REGISTRY_FILE}",
        },
        {
            "step": "shadow",
            "label": "Shadow: n8n fired mode=dry_run, RunReceipt RUN_DONE (cron line still live)",
            "done": bool(dry),
            "evidence": f"{len(dry)} dry_run receipt(s): {ev(dry)}" if dry else f"none in {RUNS_DIR}",
        },
        {
            "step": "canary",
            "label": "Canary: n8n fired mode=live, RunReceipt RUN_DONE, no RUN_SKIPPED_LOCK (flock proves no double-run)",
            "done": bool(live) and not failed_live,
            "evidence": (
                f"{len(live)} live ok, {len(failed_live)} not ok: {ev(live + failed_live)}"
                if live or failed_live
                else f"none in {RUNS_DIR}"
            ),
        },
        {
            "step": "readiness",
            "label": "Readiness verdict READY (n8n_lane_readiness_last.json)",
            "done": (verdict or "").upper() in {"READY", "GO", "GREEN", "PASS"},
            "evidence": f"verdict={verdict}" if verdict else f"{READINESS_FILE} absent or no row",
        },
        {
            "step": "cutover_dry",
            "label": "Cutover dry-run receipt (_cutover.py --lane <id>, default dry-run)",
            "done": bool(cut_dry),
            "evidence": ev(cut_dry) if cut_dry else f"none in {CUTOVER_DIR}",
        },
        {
            "step": "cutover_apply",
            "label": "Cutover applied under a cron-write grant (line commented `# RETIRED <date> n8n-cutover <lane>` / timer disabled)",
            "done": bool(cut_apply),
            "evidence": ev(cut_apply) if cut_apply else f"none in {CUTOVER_DIR}",
        },
        {
            "step": "registry_n8n",
            "label": "Registry row flipped to scheduler.kind=n8n; check_lane_registry --fail-on-new --state-drift clean",
            "done": kind == "n8n",
            "evidence": f"scheduler.kind={kind}",
        },
        {
            "step": "rollback_dry",
            "label": "Rollback proven in dry-run (_cutover.py rollback --lane <id>)",
            "done": bool(rb_dry),
            "evidence": ev(rb_dry) if rb_dry else f"none in {CUTOVER_DIR}",
        },
        {
            "step": "rollback_real",
            "label": "Rollback executed for real once (first lane of each tranche) and re-cut",
            "done": bool(rb_apply),
            "evidence": ev(rb_apply) if rb_apply else "none (required for the first lane of the tranche only)",
        },
        {
            "step": "board",
            "label": "Migration board row green: phase CUTOVER, rollback_ready true",
            "done": phase in {"CUTOVER", "DONE", "LIVE"} and rollback_ready,
            "evidence": f"phase={phase or '-'} rollback_ready={rollback_ready}"
            if board
            else f"{BOARD_FILE} absent or no row",
        },
        {
            "step": "natural_fire",
            "label": "Post-cutover natural fire: output_signal fresher than the lane cadence (acceptance evidence)",
            "done": bool((board or {}).get("output_signal_fresh")) if board else False,
            "evidence": f"output_signal_age={(board or {}).get('output_signal_age_h', '-')}h"
            if board
            else "board absent",
        },
    ]


def render(state_root: Path, repo_root: Path, lanes: list[dict], title: str) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        f"# n8n cutover checklist — {title}",
        "",
        f"Rendered {now} by `scripts/n8n_cutover_checklist.py` from receipts under `{state_root}`.",
        "A ticked box is backed by a file named on the line; an unticked box names what is missing.",
        "Ticks are evidence, not approval: the cron-write grant and the activation clicks stay with the operator.",
        "",
    ]
    totals = [0, 0]
    for lane in lanes:
        items = lane_items(state_root, repo_root, lane)
        done = sum(1 for i in items if i["done"])
        totals[0] += done
        totals[1] += len(items)
        lines.append(f"## {lane['lane_id']}  ({lane['tranche']}, {done}/{len(items)})")
        lines.append("")
        lines.append(f"- schedule: `{' | '.join(lane['cron'])}` — {lane['fidelity']} — {lane['source']}")
        if lane.get("note"):
            lines.append(f"- note: {lane['note']}")
        lines.append("")
        for item in items:
            box = "x" if item["done"] else " "
            lines.append(f"- [{box}] {item['label']}  \n      evidence: {item['evidence']}")
        lines.append("")
    lines.append(f"**Total: {totals[0]}/{totals[1]} boxes ticked across {len(lanes)} lane(s).**")
    lines.append("")
    lines.append(
        "Rollback triggers (plan 2026-10-08): RUN_FAILED where the last 3 cron runs succeeded; output_signal "
        "older than 2x cadence after cutover; CRON_PRESENT_WHILE_SCHEDULER_N8N; relay bearer failures; "
        "n8n healthz down > 10 min; any REFUSED run row. Rollback = `_cutover.py rollback --lane <id> --apply` "
        "+ deactivate the workflow; target < 5 min."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--lane", help="one lane id from the generator table")
    g.add_argument("--tranche", choices=TRANCHES)
    ap.add_argument("--state-root", default=os.environ.get("TRADEAI_STATE_ROOT") or str(ROOT))
    ap.add_argument("--repo-root", default=str(ROOT))
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if a.lane:
        lanes = [lane for lane in LANES if lane["lane_id"] == a.lane]
        if not lanes:
            print(f"unknown lane {a.lane!r}; known: {[lane['lane_id'] for lane in LANES]}", file=sys.stderr)
            return 2
        title, slug = a.lane, a.lane
    else:
        lanes = [lane for lane in LANES if lane["tranche"] == a.tranche]
        title, slug = f"tranche {a.tranche}", a.tranche
    text = render(Path(a.state_root), Path(a.repo_root), lanes, title)
    if a.write:
        out = Path(a.state_root) / OUT_DIR / f"n8n_cutover_checklist_{slug}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(json.dumps({"schema": SCHEMA, "wrote": str(out), "lanes": len(lanes)}))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
