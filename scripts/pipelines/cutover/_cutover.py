#!/usr/bin/env python3
"""_cutover.py — retire a host scheduler entry in favour of its successor, never by deleting a line.

Two modes. Both back up the crontab before the single write, COMMENT rather than delete
(AGENTS.md §0 rail 6), default to --dry-run, and refuse (exit 2) when the host does not look
exactly as expected.

Tranche B stage mode (2026-10-07) — flip one pipeline stage from --dry-run to --apply and retire
the cron lines it absorbed with `# RETIRED <date> tranche-b <stage> `:

    _cutover.py cutover  <pipeline> <stage> [--dry-run|--apply] [--code-root DIR]
    _cutover.py rollback <pipeline> <stage> [--dry-run|--apply] [--backup FILE]

Lane mode (2026-10-08, n8n scheduler-of-record) — move ONE registry lane to an n8n workflow:

    _cutover.py cutover  --lane <lane_id> --workflow-id <n8n workflow id> [--cadence "<cron>"] [--apply]
    _cutover.py rollback --lane <lane_id> [--receipt FILE] [--apply]

  cron lane:    the single uncommented crontab line containing the registry `scheduler.match`
                is commented with `# RETIRED <date> n8n-cutover <lane_id> `; the registry row
                flips to {kind: n8n, expression: <workflow id>, match: <kept>, cadence: <old
                cron schedule>}. Refuses on 0 or >1 matches, an already-commented line, a row
                that is not ACTIVE, or a row that is already kind n8n.
  multi-line:   (2026-10-10, D-3) a lane with up to MAX_LANE_LINES cron slots (the dispatcher's
                `dispatch.cron` cap) retires every slot in ONE cutover, one crontab write:
                  - `scheduler.match` as a LIST: each item must hit exactly one live line, and no
                    two items the same line; or
                  - `scheduler.match` as a STRING hitting K lines, only with `--expect-lines K`
                    (an accidental broad match still refuses on the 1-line default).
                Each line gets its own `# RETIRED <date> n8n-cutover <lane_id> ` tag; every line is
                re-read after the write. `scheduler.cadence` stays one cron string (the first
                slot) and `scheduler.cadence_slots` lists every slot; a row with a `dispatch` block
                must carry exactly those slots in `dispatch.cron`. The receipt lists `lines`
                [{index, before, after, cadence}]; rollback uncomments exactly the tagged lines
                and refuses unless their count equals the receipt's.
  systemd lane: systemctl is NOT run. The receipt carries `operator_command`
                (`systemctl --user disable --now <timer>`) for the operator's config-write grant,
                and the registry row flips the same way (`--cadence` required: a timer has no
                cron expression to inherit).
  rollback:     per line — uncomments exactly the line tagged `n8n-cutover <lane_id>` (never a
                wholesale restore), flips the row back to the `scheduler_before` recorded in the
                cutover receipt, and for a systemd lane emits the matching `enable --now`.

  Every lane action takes /tmp/n8n_cutover.lock (flock, non-blocking) and writes a
  CutoverReceipt@v1 to $TRADEAI_STATE_ROOT/data/runtime/n8n_cutover/<lane_id>-<ts>.json and
  n8n_cutover_last.json (`applied: false` for a dry-run, which writes nothing else). The registry
  is rewritten atomically with the file's exact serialisation (indent=2, ensure_ascii=False,
  separators=(',', ': '), trailing newline) and refuses if that would churn any line but the row.

Env: CRONTAB_CMD (default `crontab`; tests point it at a fake), BACKUP_DIR (default
~/.local/state/tradeai/backups), CUTOVER_DATE (default today UTC), CUTOVER_CODE_ROOT,
TRADEAI_STATE_ROOT, N8N_CUTOVER_LOCK (default /tmp/n8n_cutover.lock).
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
DEFAULT_CODE_ROOT = HERE.parent.parent.parent

CUTOVER_RECEIPT_SCHEMA = "CutoverReceipt@v1"
NO_CONSUMER_REASON = (
    "CutoverReceipt@v1 is the durable proof of one lane cutover/rollback (2026-10-08 n8n program). "
    "Read by the operator, by `_cutover.py rollback --lane` (scheduler_before) and by "
    "scripts/report_n8n_lane_readiness.py; no scheduled lane consumes it — it is produced only under a cron-write grant."
)
RECEIPT_DIR_REL = Path("data") / "runtime" / "n8n_cutover"
LAST_RECEIPT_NAME = "n8n_cutover_last.json"
DEFAULT_LOCK = "/tmp/n8n_cutover.lock"
#: AGENTS §23.11: a dispatcher row's scheduler.expression; mirrors scripts/lib/lane_dispatch.DISPATCHER_EXPRESSION
#: (kept local: this tool runs standalone). The dispatcher's workflow id is refused as an expression.
DISPATCHER_EXPRESSION = "dispatcher"
DISPATCHER_WORKFLOW_ID = "tradeai-dispatcher"
#: Mirrors scripts/lib/lane_dispatch.DISPATCH_CRON_MAX_SLOTS (kept local: this tool runs standalone; a test
#: pins the two equal). One lane cutover retires at most this many crontab lines.
MAX_LANE_LINES = 8
N8N_TAG_RE = re.compile(r"^#\s*RETIRED\s+(\d{4}-\d{2}-\d{2})\s+n8n-cutover\s+(\S+)\s(.*)$")

PIPELINES = {
    "after_close": ("config/pipelines/after_close.json", "run_after_close_pipeline.sh", ""),
    "premarket": ("config/pipelines/premarket.json", "run_premarket_data_pipeline.sh", ""),
    "hermes_learning": ("config/pipelines/hermes_learning.json", "run_hermes_pipeline.sh", ""),
    "hermes_overnight": ("config/pipelines/hermes_overnight.json", "run_hermes_pipeline.sh",
                         "--manifest config/pipelines/hermes_overnight.json"),
}


def crontab_cmd() -> str:
    return os.environ.get("CRONTAB_CMD", "crontab")


def read_crontab() -> str:
    proc = subprocess.run([crontab_cmd(), "-l"], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise SystemExit(f"REFUSED: {crontab_cmd()} -l failed: {proc.stderr.strip()[:120]}")
    return proc.stdout


def write_crontab(text: str) -> None:
    proc = subprocess.run([crontab_cmd(), "-"], input=text, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise SystemExit(f"FAILED: {crontab_cmd()} - rejected the new table: {proc.stderr.strip()[:200]}")


def backup_dir() -> Path:
    d = Path(os.environ.get("BACKUP_DIR") or (Path.home() / ".local/state/tradeai/backups"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def cutover_date() -> str:
    return os.environ.get("CUTOVER_DATE") or datetime.now(timezone.utc).date().isoformat()


# ── tranche B stage mode (unchanged behaviour) ──────────────────────────────────────────────────

def stage_regex(pipeline: str, stage: str) -> re.Pattern[str]:
    _, runner, extra = PIPELINES[pipeline]
    return re.compile(r"scripts/pipelines/" + re.escape(runner) + r"\s+" + (re.escape(extra) + r"\s+" if extra else "")
                      + r"--stage\s+" + re.escape(stage) + r"\s+--(dry-run|apply)\b")


def plan(pipeline: str, stage: str, text: str, code_root: Path) -> dict:
    manifest_rel, _, _ = PIPELINES[pipeline]
    manifest = json.loads((code_root / manifest_rel).read_text(encoding="utf-8"))
    spec = manifest["stages"][stage]
    absorbed = [str(st["cron_line_verbatim"]).rstrip() for st in spec["steps"]]
    lines = text.splitlines()
    pat = stage_regex(pipeline, stage)
    stage_idx = [i for i, ln in enumerate(lines) if not ln.lstrip().startswith("#") and pat.search(ln)]
    active = {ln.rstrip(): i for i, ln in enumerate(lines) if ln.strip() and not ln.lstrip().startswith("#")}
    present = [a for a in absorbed if a in active]
    missing = [a for a in absorbed if a not in active]
    problems = []
    if len(stage_idx) != 1:
        problems.append(f"stage line found {len(stage_idx)} times (need exactly 1)")
    elif "--dry-run" not in lines[stage_idx[0]]:
        problems.append("stage line is not in --dry-run (already cut over?)")
    if missing:
        problems.append(f"{len(missing)} absorbed line(s) missing or already commented")
    return {"pipeline": pipeline, "stage": stage, "step_count": len(absorbed), "absorbed": absorbed, "present": present,
            "missing": missing, "stage_index": stage_idx[0] if len(stage_idx) == 1 else None,
            "stage_line": lines[stage_idx[0]] if len(stage_idx) == 1 else None, "problems": problems}


def apply_plan(p: dict, text: str, date: str) -> str:
    lines = text.splitlines()
    i = p["stage_index"]
    lines[i] = lines[i].replace("--dry-run", "--apply", 1)
    tag = f"# RETIRED {date} tranche-b {p['stage']} "
    absorbed = set(p["absorbed"])
    out = []
    for ln in lines:
        if ln.rstrip() in absorbed and not ln.lstrip().startswith("#"):
            out.append(tag + ln)
        else:
            out.append(ln)
    return "\n".join(out) + "\n"


def cmd_cutover(args: argparse.Namespace) -> int:
    text = read_crontab()
    p = plan(args.pipeline, args.stage, text, args.code_root)
    print(f"[cutover {p['pipeline']}/{p['stage']}] steps={p['step_count']} absorbed present={len(p['present'])} missing={len(p['missing'])}")
    for a in p["missing"]:
        print(f"  MISSING: {a[:150]}")
    if p["stage_line"]:
        print(f"  stage line: {p['stage_line'][:150]}")
    if p["problems"]:
        for q in p["problems"]:
            print(f"  REFUSED: {q}")
        return 2
    for a in p["absorbed"]:
        print(f"  would comment: {a[:140]}")
    if not args.apply:
        print("dry-run: nothing written")
        return 0
    date = cutover_date()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bk = backup_dir() / f"crontab-{ts}-pre-cutover-{args.stage}.txt"
    bk.write_text(text, encoding="utf-8")
    new = apply_plan(p, text, date)
    write_crontab(new)
    after = read_crontab()
    commented = sum(1 for ln in after.splitlines() if ln.startswith(f"# RETIRED {date} tranche-b {args.stage} "))
    print(f"applied: backup={bk} stage=--apply commented={commented} (expected {p['step_count']})")
    return 0 if commented == p["step_count"] else 1


def cmd_rollback(args: argparse.Namespace) -> int:
    bk = args.backup
    if bk is None:
        cands = sorted(backup_dir().glob(f"crontab-*-pre-cutover-{args.stage}.txt"))
        if not cands:
            print(f"REFUSED: no backup crontab-*-pre-cutover-{args.stage}.txt under {backup_dir()}")
            return 2
        bk = cands[-1]
    text = bk.read_text(encoding="utf-8")
    pat = stage_regex(args.pipeline, args.stage)
    stage_lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#") and pat.search(ln)]
    print(f"[rollback {args.pipeline}/{args.stage}] backup={bk} lines={len(text.splitlines())} stage_line_in_backup={len(stage_lines)}")
    if not args.apply:
        print("dry-run: nothing written")
        return 0
    cur = read_crontab()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (backup_dir() / f"crontab-{ts}-pre-rollback-{args.stage}.txt").write_text(cur, encoding="utf-8")
    write_crontab(text if text.endswith("\n") else text + "\n")
    print("restored")
    return 0


# ── lane mode (n8n scheduler-of-record) ─────────────────────────────────────────────────────────

def state_root_dir(args: argparse.Namespace) -> Path:
    if getattr(args, "state_root", None):
        return Path(args.state_root)
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env)
    try:
        sys.path.insert(0, str(args.code_root))
        from scripts.lib.lane_registry import state_root  # type: ignore
        return Path(state_root())
    except Exception:  # noqa: BLE001
        return Path.home() / "trade-ai-releases" / "persistent-state"


def registry_path(args: argparse.Namespace) -> Path:
    return Path(args.code_root) / "config" / "lane_registry.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _serialise_registry(doc: dict[str, Any]) -> bytes:
    # The committed file's exact shape (verified byte-for-byte 2026-10-08). Any other dumps()
    # argument rewrites 200+ rows of unrelated churn, which the line-ending guard then flags.
    return (json.dumps(doc, indent=2, ensure_ascii=False, separators=(",", ": ")) + "\n").encode("utf-8")


def load_registry_exact(path: Path) -> tuple[dict[str, Any], bytes, Optional[str]]:
    """(doc, raw bytes, problem). problem is set when re-serialising would not reproduce the file."""
    raw = path.read_bytes()
    doc = json.loads(raw.decode("utf-8"))
    if _serialise_registry(doc) != raw:
        return doc, raw, ("registry serialisation would churn lines other than the changed row "
                          "(formatting drift or CRLF); refusing to rewrite the whole file")
    return doc, raw, None


def write_registry_atomic(path: Path, doc: dict[str, Any]) -> str:
    """Unique temp + fsync + os.replace (same discipline as scripts/lib/atomic_json_store)."""
    data = _serialise_registry(doc)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.cutover.tmp")
    try:
        with tmp.open("wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return _sha256(data)


def code_sha(code_root: Path) -> str:
    try:
        r = subprocess.run(["git", "-C", str(code_root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def take_lock(path: Path):
    """Non-blocking flock; returns the open handle (kept for the process lifetime) or raises SystemExit(2)."""
    fh = open(path, "a+")  # noqa: SIM115 - the handle IS the lock
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        print(f"REFUSED: another cutover holds {path}")
        raise SystemExit(2)
    return fh


def cron_schedule_of(line: str) -> str:
    """The schedule prefix of a crontab line: five fields, or an `@reboot`-style nickname."""
    s = line.strip()
    if s.startswith("@"):
        return s.split()[0]
    parts = s.split()
    return " ".join(parts[:5]) if len(parts) >= 6 else ""


def find_lane_lines(text: str, match: str) -> tuple[list[int], list[int]]:
    """(uncommented line indexes containing match, commented line indexes containing match)."""
    live, commented = [], []
    for i, ln in enumerate(text.splitlines()):
        if match and match in ln:
            (commented if ln.lstrip().startswith("#") else live).append(i)
    return live, commented


def lane_matches(sched: dict[str, Any]) -> tuple[list[str], bool]:
    """(match strings, is_list). `scheduler.match` may be one string or a list of strings (multi-line lane)."""
    raw = sched.get("match") or sched.get("expression") or ""
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x)], True
    return ([str(raw)] if str(raw) else []), False


def find_retired_lines(text: str, lane_id: str) -> list[int]:
    out = []
    for i, ln in enumerate(text.splitlines()):
        m = N8N_TAG_RE.match(ln)
        if m and m.group(2) == lane_id:
            out.append(i)
    return out


def receipt_dir(args: argparse.Namespace) -> Path:
    return state_root_dir(args) / RECEIPT_DIR_REL


def write_receipt(args: argparse.Namespace, doc: dict[str, Any]) -> Path:
    d = receipt_dir(args)
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "" if doc["applied"] else ("-refused" if doc.get("problems") else "-dry-run")
    p = d / f"{doc['lane_id']}-{ts}-{doc['action']}{suffix}.json"
    body = json.dumps(doc, indent=2, default=str) + "\n"
    p.write_text(body, encoding="utf-8")
    (d / LAST_RECEIPT_NAME).write_text(body, encoding="utf-8")
    return p


def latest_cutover_receipt(args: argparse.Namespace, lane_id: str) -> Optional[Path]:
    d = receipt_dir(args)
    if not d.is_dir():
        return None
    cands = []
    for p in d.glob(f"{lane_id}-*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if doc.get("lane_id") == lane_id and doc.get("action") == "cutover" and doc.get("applied") is True:
            cands.append((str(doc.get("at") or ""), p))
    cands.sort()
    return cands[-1][1] if cands else None


def _row_for(doc: dict[str, Any], lane_id: str) -> Optional[dict[str, Any]]:
    for row in doc.get("lanes") or []:
        if str(row.get("lane_id") or "") == lane_id:
            return row
    return None


def _base_receipt(args: argparse.Namespace, lane_id: str, action: str, row: dict[str, Any]) -> dict[str, Any]:
    return {"schema": CUTOVER_RECEIPT_SCHEMA, "lane_id": lane_id, "action": action,
            "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "applied": bool(args.apply),
            "mode": "apply" if args.apply else "dry-run", "code_sha": code_sha(args.code_root),
            "registry_path": str(registry_path(args)), "lane_kind_before": (row.get("scheduler") or {}).get("kind"),
            "scheduler_before": None, "scheduler_after": None, "crontab_backup": None,
            "line_before": None, "line_after": None, "operator_command": None,
            "registry_sha_before": None, "registry_sha_after": None, "problems": []}


def _refuse(rc: dict[str, Any], args: argparse.Namespace, problems: list[str]) -> int:
    rc["problems"] = problems
    rc["applied"] = False
    for q in problems:
        print(f"  REFUSED: {q}")
    p = write_receipt(args, rc)
    print(f"receipt: {p}")
    return 2


def cmd_cutover_lane(args: argparse.Namespace) -> int:
    lane_id = args.lane
    lock = take_lock(Path(os.environ.get("N8N_CUTOVER_LOCK") or DEFAULT_LOCK))  # noqa: F841 - held until exit
    reg_path = registry_path(args)
    doc, raw, fmt_problem = load_registry_exact(reg_path)
    row = _row_for(doc, lane_id)
    print(f"[cutover --lane {lane_id}] registry={reg_path} workflow_id={args.workflow_id or '-'}")
    if row is None:
        rc = _base_receipt(args, lane_id, "cutover", {})
        return _refuse(rc, args, [f"no registry row for lane {lane_id!r}"])
    rc = _base_receipt(args, lane_id, "cutover", row)
    rc["registry_sha_before"] = _sha256(raw)
    sched = dict(row.get("scheduler") or {})
    kind = str(sched.get("kind") or "")
    matches, match_is_list = lane_matches(sched)
    match: Any = sched.get("match") or sched.get("expression") or ""
    if not match_is_list:
        match = str(match)
    rc["scheduler_before"] = sched
    problems: list[str] = []
    if fmt_problem:
        problems.append(fmt_problem)
    if str(row.get("state") or "") != "ACTIVE":
        problems.append(f"lane state is {row.get('state')!r}, not ACTIVE")
    if kind == "n8n":
        problems.append("lane is already kind n8n (already cut over?)")
    elif kind not in ("cron", "systemd"):
        problems.append(f"scheduler.kind {kind!r} has no host entry to retire")
    if not args.workflow_id:
        problems.append("--workflow-id is required (the n8n workflow id becomes scheduler.expression)")
    elif str(args.workflow_id) == DISPATCHER_WORKFLOW_ID:
        problems.append(f"--workflow-id {DISPATCHER_WORKFLOW_ID} is the dispatcher's workflow id, not a row expression; "
                        f"a dispatcher lane is cut over with --workflow-id {DISPATCHER_EXPRESSION} (AGENTS §23.11)")
    if not matches:
        problems.append("scheduler.match / expression is empty; nothing to find on the host")
    expect = getattr(args, "expect_lines", None)
    if expect is not None and not 1 <= expect <= MAX_LANE_LINES:
        problems.append(f"--expect-lines {expect} is outside 1..{MAX_LANE_LINES} (the dispatch.cron slot cap)")
    if match_is_list and expect is not None:
        problems.append("--expect-lines applies to a string scheduler.match; a list match retires one line per item")
    if match_is_list and len(matches) > MAX_LANE_LINES:
        problems.append(f"scheduler.match lists {len(matches)} items; at most {MAX_LANE_LINES} lines per lane")

    text = None
    line_idxs: list[int] = []
    cadence = args.cadence or ""
    cadence_slots: list[str] = []
    if kind == "cron" and not problems:
        text = read_crontab()
        retired = find_retired_lines(text, lane_id)
        if retired:
            problems.append(f"a line is already tagged `n8n-cutover {lane_id}` (line {retired[0] + 1}); rollback first")
        if match_is_list:
            for m in matches:
                live, commented = find_lane_lines(text, m)
                if len(live) != 1:
                    problems.append(f"match item {m!r} found on {len(live)} uncommented line(s) (need exactly 1)"
                                    + (f"; {len(commented)} commented line(s) also contain it" if commented else ""))
                else:
                    line_idxs.append(live[0])
            if not problems and len(set(line_idxs)) != len(line_idxs):
                problems.append("two scheduler.match items hit the same crontab line; each item must name its own line")
        else:
            live, commented = find_lane_lines(text, match)
            need = expect if expect is not None else 1
            if len(live) != need:
                problems.append(f"match {match!r} found on {len(live)} uncommented line(s) (need exactly {need}"
                                + (f", --expect-lines {expect}" if expect is not None else "") + ")"
                                + (f"; {len(commented)} commented line(s) also contain it" if commented else ""))
            elif len(live) > MAX_LANE_LINES:
                problems.append(f"match {match!r} found on {len(live)} lines; at most {MAX_LANE_LINES} per lane")
            else:
                line_idxs = list(live)
        if not problems:
            all_lines = text.splitlines()
            line_idxs.sort()
            tag = f"# RETIRED {cutover_date()} n8n-cutover {lane_id} "
            if len(line_idxs) == 1:
                line_idx = line_idxs[0]
                rc["line_before"] = all_lines[line_idx]
                cadence = cadence or cron_schedule_of(rc["line_before"])
                rc["line_after"] = tag + rc["line_before"]
                if not cadence:
                    problems.append("could not derive the cron schedule from the line; pass --cadence")
            else:
                rc["lines"] = []
                for i in line_idxs:
                    before = all_lines[i]
                    slot = cron_schedule_of(before)
                    if not slot:
                        problems.append(f"could not derive the cron schedule from line {i + 1}; a multi-line lane needs "
                                        "a schedule on every line")
                    rc["lines"].append({"index": i, "before": before, "after": tag + before, "cadence": slot})
                    if slot and slot not in cadence_slots:
                        cadence_slots.append(slot)
                cadence = cadence or (cadence_slots[0] if cadence_slots else "")
                block = row.get("dispatch") if isinstance(row.get("dispatch"), dict) else None
                if block is not None and block.get("cron") is not None:
                    dcron = block.get("cron")
                    dset = {str(x) for x in (dcron if isinstance(dcron, list) else [dcron])}
                    if dset != set(cadence_slots):
                        problems.append(f"dispatch.cron {sorted(dset)} does not equal the retired slots "
                                        f"{sorted(set(cadence_slots))}: a slot would be lost or added at cutover")
    elif kind == "systemd" and not problems:
        if not match.endswith(".timer"):
            problems.append(f"systemd lane match {match!r} is not a .timer unit")
        if not cadence:
            problems.append("--cadence is required for a systemd lane (a timer has no cron expression to inherit)")
        rc["operator_command"] = f"systemctl --user disable --now {match}"
    if problems:
        return _refuse(rc, args, problems)

    new_sched = {"kind": "n8n", "expression": str(args.workflow_id), "match": match, "cadence": cadence}
    if len(cadence_slots) > 1:
        new_sched["cadence_slots"] = cadence_slots
    if str(args.workflow_id) == DISPATCHER_EXPRESSION:
        # §23.12: a dispatcher row moves to stage cutover (a dispatcher row without a stage is clamped to dry_run
        # and refused by lane_dispatch.r1_class_admission); its wave label is kept.
        new_sched["stage"] = "cutover"
        if sched.get("wave"):
            new_sched["wave"] = sched["wave"]
    rc["scheduler_after"] = new_sched
    rc["cadence"] = cadence
    rc["workflow_id"] = str(args.workflow_id)
    print(f"  scheduler before: {json.dumps(sched, ensure_ascii=False)}")
    print(f"  scheduler after : {json.dumps(new_sched, ensure_ascii=False)}")
    if rc["line_before"] is not None:
        print(f"  would comment   : {rc['line_before'][:150]}")
        print(f"  as              : {rc['line_after'][:150]}")
    for ent in rc.get("lines") or []:
        print(f"  would comment   : L{ent['index'] + 1} {ent['before'][:150]}")
    if rc["operator_command"]:
        print(f"  operator command (NOT run here; config-write grant): {rc['operator_command']}")
    if not args.apply:
        p = write_receipt(args, rc)
        print(f"dry-run: nothing written except the receipt {p}")
        return 0

    if text is not None and line_idxs:
        edits = ([(line_idxs[0], rc["line_after"])] if rc.get("lines") is None
                 else [(e["index"], e["after"]) for e in rc["lines"]])
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bk = backup_dir() / f"crontab-{ts}-pre-cutover-lane-{lane_id}.txt"
        bk.write_text(text, encoding="utf-8")
        rc["crontab_backup"] = str(bk)
        lines = text.splitlines()
        for i, new_line in edits:
            lines[i] = new_line
        write_crontab("\n".join(lines) + "\n")
        after_lines = read_crontab().splitlines()
        missing = [i for i, new_line in edits if i >= len(after_lines) or after_lines[i] != new_line]
        if missing:
            rc["problems"] = [f"crontab write did not stick (line_after not found on re-read for {len(missing)} line(s))"]
            write_receipt(args, rc)
            print("FAILED: crontab re-read does not show the retired line")
            return 1
    row["scheduler"] = new_sched
    rc["registry_sha_after"] = write_registry_atomic(reg_path, doc)
    p = write_receipt(args, rc)
    print(f"applied: registry {rc['registry_sha_before'][:12]}→{rc['registry_sha_after'][:12]}"
          + (f" backup={rc['crontab_backup']}" if rc["crontab_backup"] else "") + f" receipt={p}")
    return 0


def cmd_rollback_lane(args: argparse.Namespace) -> int:
    lane_id = args.lane
    lock = take_lock(Path(os.environ.get("N8N_CUTOVER_LOCK") or DEFAULT_LOCK))  # noqa: F841 - held until exit
    reg_path = registry_path(args)
    doc, raw, fmt_problem = load_registry_exact(reg_path)
    row = _row_for(doc, lane_id)
    print(f"[rollback --lane {lane_id}] registry={reg_path}")
    if row is None:
        rc = _base_receipt(args, lane_id, "rollback", {})
        return _refuse(rc, args, [f"no registry row for lane {lane_id!r}"])
    rc = _base_receipt(args, lane_id, "rollback", row)
    rc["registry_sha_before"] = _sha256(raw)
    sched = dict(row.get("scheduler") or {})
    rc["scheduler_before"] = sched
    problems: list[str] = []
    if fmt_problem:
        problems.append(fmt_problem)
    if str(sched.get("kind") or "") != "n8n":
        problems.append(f"lane is kind {sched.get('kind')!r}, not n8n (nothing to roll back)")
    receipt_path = Path(args.receipt) if args.receipt else latest_cutover_receipt(args, lane_id)
    prior: dict[str, Any] = {}
    if receipt_path is None or not Path(receipt_path).is_file():
        problems.append(f"no applied cutover receipt for {lane_id} under {receipt_dir(args)} (pass --receipt)")
    else:
        try:
            prior = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"cutover receipt unreadable: {exc}")
        if prior and (prior.get("lane_id") != lane_id or prior.get("action") != "cutover"):
            problems.append(f"receipt {receipt_path} is not a cutover receipt for {lane_id}")
    restore = dict((prior.get("scheduler_before") or {})) if prior else {}
    if not problems and (not restore or restore.get("kind") not in ("cron", "systemd")):
        problems.append("cutover receipt carries no scheduler_before to restore")
    rc["cutover_receipt"] = str(receipt_path) if receipt_path else None
    rc["scheduler_after"] = restore or None

    text = None
    edits: list[tuple[int, str]] = []
    if not problems and restore.get("kind") == "cron":
        text = read_crontab()
        all_lines = text.splitlines()
        retired = find_retired_lines(text, lane_id)
        prior_lines = prior.get("lines") if isinstance(prior.get("lines"), list) else None
        need = len(prior_lines) if prior_lines else 1
        if len(retired) != need:
            problems.append(f"found {len(retired)} line(s) tagged `n8n-cutover {lane_id}` (need exactly {need})")
        elif need == 1:
            line_idx = retired[0]
            before = all_lines[line_idx]
            m = N8N_TAG_RE.match(before)
            rc["line_before"] = before
            rc["line_after"] = m.group(3) if m else before
            edits.append((line_idx, rc["line_after"]))
            if prior.get("line_before") and prior["line_before"] != rc["line_after"]:
                print("  NOTE: uncommented text differs from the receipt's line_before; restoring what is on the host")
                rc["note"] = "line text differs from cutover receipt line_before"
        else:
            rc["lines"] = []
            prior_before = {str(e.get("before")) for e in prior_lines or []}
            for i in retired:
                m = N8N_TAG_RE.match(all_lines[i])
                restored = m.group(3) if m else all_lines[i]
                rc["lines"].append({"index": i, "before": all_lines[i], "after": restored})
                edits.append((i, restored))
                if restored not in prior_before:
                    rc["note"] = "line text differs from cutover receipt lines[].before"
            if rc.get("note"):
                print("  NOTE: uncommented text differs from the receipt's lines; restoring what is on the host")
        if not problems:
            for m_ in lane_matches(restore)[0]:
                live, _ = find_lane_lines(text, m_)
                if live:
                    problems.append(f"match {m_!r} is already live on line {live[0] + 1}; uncommenting would double-schedule")
                    break
    elif not problems and restore.get("kind") == "systemd":
        unit = str(restore.get("match") or restore.get("expression") or "")
        rc["operator_command"] = f"systemctl --user enable --now {unit}"
    if problems:
        return _refuse(rc, args, problems)

    print(f"  scheduler before: {json.dumps(sched, ensure_ascii=False)}")
    print(f"  scheduler after : {json.dumps(restore, ensure_ascii=False)}")
    if rc["line_before"] is not None:
        print(f"  would uncomment : {rc['line_before'][:150]}")
        print(f"  as              : {rc['line_after'][:150]}")
    for ent in rc.get("lines") or []:
        print(f"  would uncomment : L{ent['index'] + 1} {ent['after'][:150]}")
    if rc["operator_command"]:
        print(f"  operator command (NOT run here; config-write grant): {rc['operator_command']}")
    if not args.apply:
        p = write_receipt(args, rc)
        print(f"dry-run: nothing written except the receipt {p}")
        return 0

    if text is not None and edits:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bk = backup_dir() / f"crontab-{ts}-pre-rollback-lane-{lane_id}.txt"
        bk.write_text(text, encoding="utf-8")
        rc["crontab_backup"] = str(bk)
        lines = text.splitlines()
        for i, new_line in edits:
            lines[i] = new_line
        write_crontab("\n".join(lines) + "\n")
        after_lines = read_crontab().splitlines()
        if any(i >= len(after_lines) or after_lines[i] != new_line for i, new_line in edits):
            rc["problems"] = ["crontab write did not stick (line_after not found on re-read)"]
            write_receipt(args, rc)
            print("FAILED: crontab re-read does not show the restored line")
            return 1
    row["scheduler"] = restore
    rc["registry_sha_after"] = write_registry_atomic(reg_path, doc)
    p = write_receipt(args, rc)
    print(f"applied: registry {rc['registry_sha_before'][:12]}→{rc['registry_sha_after'][:12]}"
          + (f" backup={rc['crontab_backup']}" if rc["crontab_backup"] else "") + f" receipt={p}")
    return 0


# ── entry ───────────────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["cutover", "rollback"])
    ap.add_argument("pipeline", nargs="?", choices=sorted(PIPELINES))
    ap.add_argument("stage", nargs="?")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--code-root", type=Path, default=Path(os.environ.get("CUTOVER_CODE_ROOT") or DEFAULT_CODE_ROOT))
    ap.add_argument("--backup", type=Path, default=None, help="stage mode: the crontab backup to restore")
    ap.add_argument("--lane", default=None, help="lane mode: the config/lane_registry.json lane_id to move to / back from n8n")
    ap.add_argument("--workflow-id", default=None, help="lane cutover: the n8n workflow id (becomes scheduler.expression)")
    ap.add_argument("--cadence", default=None, help="lane cutover: cron expression the workflow uses (derived from the line for cron lanes)")
    ap.add_argument("--expect-lines", type=int, default=None,
                    help=f"lane cutover: a string scheduler.match must hit exactly this many live lines (1..{MAX_LANE_LINES}); "
                         "without it a string match must hit exactly 1")
    ap.add_argument("--receipt", default=None, help="lane rollback: the cutover receipt to restore scheduler_before from")
    ap.add_argument("--state-root", default=None, help="where receipts live (default $TRADEAI_STATE_ROOT / production state root)")
    args = ap.parse_args(argv)
    if args.lane:
        if args.pipeline or args.stage:
            print("REFUSED: --lane is exclusive with <pipeline> <stage>")
            return 2
        return cmd_cutover_lane(args) if args.action == "cutover" else cmd_rollback_lane(args)
    if not args.pipeline or not args.stage:
        print("REFUSED: need <pipeline> <stage> or --lane <lane_id>")
        return 2
    manifest_rel = PIPELINES[args.pipeline][0]
    stages = json.loads((args.code_root / manifest_rel).read_text(encoding="utf-8"))["stages"]
    if args.stage not in stages:
        print(f"REFUSED: unknown stage {args.stage!r} for {args.pipeline} (one of: {', '.join(stages)})")
        return 2
    return cmd_cutover(args) if args.action == "cutover" else cmd_rollback(args)


if __name__ == "__main__":
    sys.exit(main())
