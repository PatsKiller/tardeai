#!/usr/bin/env python3
"""weekly_disk_cleanup_notify.py — Sunday cleanup bundle with Telegram summary.

Runs (apply by default when invoked from the weekly timer):
  1. disk_hygiene_enforcer --apply  (releases keep-N + stale backup *files*)
  2. Explicit cleanup of stale ~/backups/deploy-tree-preclean-* dirs (hygiene
     only deletes files, not directories — 2026-09-18 gap)
  3. Hermes librarian retention --apply
  4. db_retention.py (row purge)

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

LOG = ROOT / "logs" / "weekly_disk_cleanup.log"
PRECLEAN_MAX_AGE_DAYS = 7


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
        if dry_run:
            deleted.append({"path": str(p), "bytes": size, "action": "would_delete"})
            bytes_est += size
            continue
        try:
            shutil.rmtree(p)
            deleted.append({"path": str(p), "bytes": size, "action": "deleted"})
            bytes_est += size
        except OSError as e:
            errors.append(f"{p}: {e}")
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
    lines.append(
        f"Total reclaim (est): *{_fmt_bytes(summary.get('bytes_reclaimed_est') or 0)}* · "
        f"DB rows deleted: *{summary.get('db_rows_deleted') or 0}* · "
        f"Librarian affected: *{summary.get('librarian_affected') or 0}*"
    )
    if not summary.get("ok"):
        lines.append("")
        lines.append("⚠️ One or more steps failed — check logs/weekly_disk_cleanup.log")
    return "\n".join(lines)


def run(*, apply: bool, notify: bool) -> dict:
    dry = not apply
    py = str(ROOT / ".venv" / "bin" / "python")
    if not Path(py).is_file():
        py = sys.executable

    disk_before = _disk()
    steps: list[dict] = []
    bytes_reclaimed = 0
    db_rows = 0
    librarian_affected = 0

    # 1) Disk hygiene
    argv = [py, str(ROOT / "scripts" / "disk_hygiene_enforcer.py")]
    argv.append("--apply" if apply else "--dry-run")
    argv.append("--json")
    ok, payload = _run_json(argv, timeout=7200)
    detail = "no result"
    if isinstance(payload, dict):
        rr = payload.get("releases_result") or {}
        br = payload.get("backups_result") or {}
        b = int(rr.get("bytes_reclaimed_est") or 0) + int(br.get("bytes_reclaimed_est") or 0)
        bytes_reclaimed += b
        n_rel = len(rr.get("deleted") or [])
        n_bak = len(br.get("deleted") or [])
        detail = f"releases={n_rel} backups_files={n_bak} reclaim={_fmt_bytes(b)}"
        ok = ok and bool(payload.get("ok", True))
    else:
        detail = str(payload)[:180]
        ok = False
    steps.append({"name": "disk_hygiene", "ok": ok, "detail": detail, "raw": payload if isinstance(payload, dict) else None})

    # 2) deploy-tree-preclean dirs
    preclean = _clean_preclean_dirs(dry_run=dry)
    b = int(preclean.get("bytes_reclaimed_est") or 0)
    bytes_reclaimed += b
    steps.append({
        "name": "backup_preclean_dirs",
        "ok": bool(preclean.get("ok")),
        "detail": f"dirs={len(preclean.get('deleted') or [])} reclaim={_fmt_bytes(b)}",
        "raw": preclean,
    })

    # 3) Librarian
    argv = [py, str(ROOT / "scripts" / "run_hermes_librarian_retention.py")]
    argv.append("--apply" if apply else "--dry-run")
    ok, payload = _run_json(argv, timeout=1800)
    if isinstance(payload, dict):
        librarian_affected = int(payload.get("total_affected") or 0)
        detail = f"affected={librarian_affected}"
        # soft-ok even if total 0
        ok = ok and bool(payload.get("ok", True))
    else:
        detail = str(payload)[:180]
        ok = False
    steps.append({"name": "librarian_retention", "ok": ok, "detail": detail, "raw": payload if isinstance(payload, dict) else None})

    # 4) DB retention
    argv = [py, str(ROOT / "scripts" / "db_retention.py")]
    if dry:
        argv.append("--dry-run")
    ok, payload = _run_json(argv, timeout=3600)
    # db_retention prints a table, not JSON — parse "Total deleted:" / "Total would delete:"
    text = payload if isinstance(payload, str) else json.dumps(payload)
    import re
    m = re.search(r"Total (?:would delete|deleted):\s*([0-9,]+)\s*rows", text)
    if m:
        db_rows = int(m.group(1).replace(",", ""))
        detail = f"rows={db_rows}"
    else:
        detail = (text or "")[-160:].replace("\n", " ")
        # still ok if process exited 0
    steps.append({"name": "db_retention", "ok": ok, "detail": detail, "raw": None})

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
            sent = send_telegram(msg, bypass_router=True, message_class="operator_alert")
            summary["telegram"] = "accepted" if sent else "send_returned_false"
        except Exception as e:
            summary["telegram"] = f"error:{type(e).__name__}:{e}"
            _log(f"telegram failed: {e}")

    _log(json.dumps({k: summary[k] for k in ("ok", "apply", "bytes_reclaimed_est", "db_rows_deleted", "librarian_affected", "telegram") if k in summary}))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Plan only (no deletes)")
    ap.add_argument("--apply", action="store_true", help="Mutate disk/DB")
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
