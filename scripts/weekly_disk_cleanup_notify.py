#!/usr/bin/env python3
"""weekly_disk_cleanup_notify.py — Sunday disk report bundle with Telegram summary.

REMOVES NOTHING since 2026-10-27 (AGENTS.md §24.12, §0 rule 6). §24.12 makes
`scripts/disk_hygiene.py` (n8n lane `disk-hygiene`, or the operator CLI) the only automated
removal of release directories and puts backups out of scope. So an --apply request (the
weekly timer's) runs the PLAN of each step and reports REFUSED_OUTSIDE_24_12 with what the
plan lists; a --dry-run is unchanged.

Steps:
  1. disk_hygiene_enforcer --dry-run, always (never --apply): releases keep-N + stale backup
     *files* -- reported, not removed
  2. stale ~/backups/deploy-tree-preclean-* dirs -- listed, never removed (backups)
  (3-4 removed 2026-10-21, OPERATOR_DECISION D6: librarian + db_retention row purges
   are owned by the CURRENT release's nightly timers, never by this dev-tree job)

Always sends one Telegram summary (operator request 2026-09-18): disk free
before/after, bytes/rows reclaimed, per-step ok/fail.

Usage:
  .venv/bin/python scripts/weekly_disk_cleanup_notify.py --dry-run
  .venv/bin/python scripts/weekly_disk_cleanup_notify.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

NO_CONSUMER_REASON = (
    "Sunday weekly cleanup entrypoint; Telegram summary + logs/weekly_disk_cleanup.log "
    "are the consumers (timer-invoked, not imported)"
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

LOG = ROOT / "logs" / "weekly_disk_cleanup.log"
PRECLEAN_MAX_AGE_DAYS = 7
#: Same status disk_hygiene_enforcer.py reports for a refused --apply.
REFUSED_STATUS = "REFUSED_OUTSIDE_24_12"
REMOVAL_LINE = (
    "Removal: none — AGENTS.md §24.12 (the disk-hygiene lane owns release reclaim; deleting a backup is an "
    "operator decision)"
)


try:
    from lib.live_project_root import venv_python  # noqa: E402  (release dirs ship no .venv)
except ImportError:  # imported with scripts/lib, not scripts/, on sys.path
    from live_project_root import venv_python  # noqa: E402


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()}  {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _disk() -> dict:
    u = shutil.disk_usage("/")
    free_pct = 100.0 * u.free / u.total if u.total else 0.0
    return {
        "free_gb": round(u.free / (1024**3), 2),
        "used_pct": round(100.0 * u.used / u.total, 2) if u.total else 0.0,
        "free_pct": round(free_pct, 2),
        "level": "critical" if free_pct < 10 else ("warn" if free_pct < 15 else "ok"),
    }


def _run_json(argv: list[str], *, timeout: int = 3600) -> tuple[bool, dict | str]:
    try:
        p = subprocess.run(
            argv,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    # Prefer last JSON object in stdout
    payload: dict | str = out[-4000:] if out else err[:4000]
    if out:
        try:
            # find outermost JSON
            i = out.find("{")
            j = out.rfind("}")
            if i >= 0 and j > i:
                payload = json.loads(out[i : j + 1])
        except json.JSONDecodeError:
            payload = out[-2000:]
    ok = p.returncode == 0
    if not ok and isinstance(payload, str) and err:
        payload = (payload + "\n" + err)[:4000]
    return ok, payload


def _clean_preclean_dirs(*, dry_run: bool) -> dict:
    """List stale ~/backups/deploy-tree-preclean-* dirs. ``dry_run=False`` is REFUSED: they are backups, never in
    AGENTS.md §24.12's scope, so they are reported and kept (2026-10-27)."""
    base = Path.home() / "backups"
    now = time.time()
    cutoff = now - PRECLEAN_MAX_AGE_DAYS * 86400
    deleted: list[dict] = []
    errors: list[str] = []
    bytes_est = 0
    if not base.is_dir():
        return {"ok": True, "deleted": [], "bytes_reclaimed_est": 0, "skipped": "no_backups_dir"}
    for p in sorted(base.glob("deploy-tree-preclean-*")):
        if not p.is_dir() or p.is_symlink():
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError as e:
            errors.append(f"{p}: {e}")
            continue
        if mtime >= cutoff:
            continue
        # rough size
        size = 0
        try:
            for root, _dirs, files in os.walk(p):
                for f in files:
                    try:
                        size += (Path(root) / f).stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
        deleted.append({"path": str(p), "bytes": size, "action": "would_delete"})
        bytes_est += size
    if not dry_run:
        return {
            "ok": not errors,
            "refused": True,
            "status": REFUSED_STATUS,
            "deleted": [],
            "refused_items": [{**d, "action": "refused"} for d in deleted],
            "listed_bytes_est": bytes_est,
            "bytes_reclaimed_est": 0,
            "errors": errors,
            "max_age_days": PRECLEAN_MAX_AGE_DAYS,
        }
    return {
        "ok": not errors,
        "deleted": deleted,
        "bytes_reclaimed_est": bytes_est,
        "errors": errors,
        "max_age_days": PRECLEAN_MAX_AGE_DAYS,
    }


def _fmt_bytes(n: int | float) -> str:
    n = float(n or 0)
    if n >= 1e9:
        return f"{n / 1e9:.2f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.1f} MB"
    return f"{int(n)} B"


def _step_line(name: str, ok: bool, detail: str) -> str:
    mark = "OK" if ok else "FAIL"
    return f"• {name}: {mark} — {detail}"


def build_telegram(summary: dict) -> str:
    before = summary["disk_before"]
    after = summary["disk_after"]
    lines = [
        "🧹 *Weekly disk cleanup*",
        f"Host `{os.uname().nodename}` · {summary['ts'][:16]}Z",
        "",
        f"Disk `/`: {before['free_gb']}G → *{after['free_gb']}G* free "
        f"({before['used_pct']}% → {after['used_pct']}%) · level *{after['level']}*",
        "",
    ]
    for s in summary["steps"]:
        lines.append(_step_line(s["name"], s["ok"], s["detail"]))
    lines.append("")
    lines.append(f"Total reclaim (est): *{_fmt_bytes(summary.get('bytes_reclaimed_est') or 0)}*")
    if summary.get("apply"):
        lines.append(REMOVAL_LINE)
    lines.append("DB row retention: owned by the nightly CURRENT timers (not this job, D6)")
    if not summary.get("ok"):
        lines.append("")
        lines.append("⚠️ One or more steps failed — check logs/weekly_disk_cleanup.log")
    return "\n".join(lines)


def run(*, apply: bool, notify: bool) -> dict:
    dry = not apply
    py = venv_python(ROOT)
    if not Path(py).is_file():
        py = sys.executable

    disk_before = _disk()
    steps: list[dict] = []
    bytes_reclaimed = 0
    db_rows = 0
    librarian_affected = 0

    # 1) Disk hygiene -- the enforcer's PLAN, always (--dry-run, never --apply; AGENTS.md §24.12, 2026-10-27)
    argv = [py, str(ROOT / "scripts" / "disk_hygiene_enforcer.py"), "--dry-run", "--json"]
    ok, payload = _run_json(argv, timeout=7200)
    detail = "no result"
    if isinstance(payload, dict):
        rr = payload.get("releases_result") or {}
        br = payload.get("backups_result") or {}
        b = int(rr.get("bytes_reclaimed_est") or 0) + int(br.get("bytes_reclaimed_est") or 0)
        n_rel = len(rr.get("deleted") or [])
        n_bak = len(br.get("deleted") or [])
        if apply:
            # Removal refused: nothing is reclaimed, so nothing is added to bytes_reclaimed. The step is judged on
            # planning errors only -- the enforcer's dry run exits 1 at the critical floor, which is its alarm.
            errs = list(rr.get("errors") or []) + list(br.get("errors") or [])
            ok = not errs
            detail = (
                f"{REFUSED_STATUS}: removed nothing; plan lists releases={n_rel} backups_files={n_bak} "
                f"(~{_fmt_bytes(b)}) — reclaim is the disk-hygiene lane's job"
            )
        else:
            bytes_reclaimed += b
            detail = f"releases={n_rel} backups_files={n_bak} reclaim={_fmt_bytes(b)}"
            ok = ok and bool(payload.get("ok", True))
    else:
        detail = str(payload)[:180]
        ok = False
    steps.append(
        {"name": "disk_hygiene", "ok": ok, "detail": detail, "raw": payload if isinstance(payload, dict) else None}
    )

    # 2) deploy-tree-preclean dirs
    preclean = _clean_preclean_dirs(dry_run=dry)
    b = int(preclean.get("bytes_reclaimed_est") or 0)
    bytes_reclaimed += b
    if preclean.get("refused"):
        pre_detail = (
            f"{REFUSED_STATUS}: removed nothing; dirs listed={len(preclean.get('refused_items') or [])} "
            f"(~{_fmt_bytes(preclean.get('listed_bytes_est') or 0)}) — backups are out of scope"
        )
    else:
        pre_detail = f"dirs={len(preclean.get('deleted') or [])} reclaim={_fmt_bytes(b)}"
    steps.append(
        {
            "name": "backup_preclean_dirs",
            "ok": bool(preclean.get("ok")),
            "detail": pre_detail,
            "raw": preclean,
        }
    )

    # Steps 3-4 (Hermes librarian retention + db_retention.py) were REMOVED 2026-10-21
    # (OPERATOR_DECISION D6). This timer's cwd is the DEV tree, so it ran the dev tree's
    # registry and purge code against the live DB on Sundays: a second, unreleased
    # retention owner. Row retention is owned only by tradeai-platform-maintenance-nightly
    # (CURRENT) and hermes-librarian-retention.timer. Do not re-add a DB purge here; the
    # D6 gate (tests/test_retention_priority_20261021.py) fails if run() invokes either.
    # db_rows_deleted / librarian_affected stay 0 for receipt-schema stability.

    disk_after = _disk()
    summary = {
        "ok": all(s["ok"] for s in steps),
        "apply": apply,
        "ts": datetime.now(timezone.utc).isoformat(),
        "disk_before": disk_before,
        "disk_after": disk_after,
        "steps": [{"name": s["name"], "ok": s["ok"], "detail": s["detail"]} for s in steps],
        "bytes_reclaimed_est": bytes_reclaimed,
        "db_rows_deleted": db_rows,
        "librarian_affected": librarian_affected,
        "authority": "READ_ONLY_ADVISORY",
        "schema": "WeeklyDiskCleanup@v1",
    }
    if apply:
        summary["removal"] = f"none — {REFUSED_STATUS} (AGENTS.md §24.12)"

    # durable receipt
    receipt = ROOT / "logs" / "weekly_disk_cleanup_receipts.jsonl"
    try:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        with receipt.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(summary, default=str) + "\n")
    except OSError as e:
        _log(f"receipt write failed: {e}")

    if notify:
        msg = build_telegram(summary)
        try:
            from telegram_alert import send_telegram

            sent = send_telegram(msg, message_class="operator_alert", priority="P2", producer="weekly_disk_cleanup")
            summary["telegram"] = "accepted" if sent else "send_returned_false"
        except Exception as e:
            summary["telegram"] = f"error:{type(e).__name__}:{e}"
            _log(f"telegram failed: {e}")

    _log(
        json.dumps(
            {
                k: summary[k]
                for k in ("ok", "apply", "bytes_reclaimed_est", "db_rows_deleted", "librarian_affected", "telegram")
                if k in summary
            }
        )
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Plan only (no deletes)")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="the weekly timer's mode: runs every step's plan; removal is REFUSED (AGENTS.md §24.12)",
    )
    ap.add_argument("--no-notify", action="store_true", help="Skip Telegram")
    ap.add_argument("--json", action="store_true", help="Print full summary JSON")
    args = ap.parse_args()
    if not args.apply and not args.dry_run:
        args.dry_run = True  # safe default for manual runs
    summary = run(apply=bool(args.apply), notify=not args.no_notify)
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(build_telegram(summary))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
