#!/usr/bin/env python3
"""Plan, verify and receipt the post-promote restart of CURRENT-bound user units.

Used by ``scripts/cio_phase2_exact_main_deploy.sh`` (``restart_root_frozen_units``):

  # what would be restarted / paged (read-only; the default):
  python scripts/current_bound_units.py plan --current <release dir> [--json]
  # names only, for the shell loop (restartable units):
  python scripts/current_bound_units.py plan --current <dir> --names
  # after the restarts: read back each cwd, write the receipt, page P1 when any unit is still stale:
  python scripts/current_bound_units.py verify --current <dir> --restarted "a.service b.service" [--dry-run]

Nothing here restarts a unit. ``verify`` pages through ``telegram_alert.send_telegram`` (P1, dedupe 60) when a
restarted unit is not on the new release, or when a page-only unit (AGENTS.md §23.14 never-list, Active Trader) is
left on an old release; ``--dry-run`` prints the page instead of sending it and writes no receipt.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from lib import current_bound_units as cbu  # noqa: E402

PRODUCER = "deploy_current_bound_units"
RECEIPT_REL = "data/runtime/current_bound_units_last.json"
HISTORY_REL = "data/runtime/current_bound_units_history.jsonl"


def _state_root(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    from lib.persistent_state_root import good_persistent_root

    return good_persistent_root()


def _extra_never() -> list[str]:
    raw = os.environ.get("TRADEAI_CURRENT_BOUND_EXTRA_NEVER", "")
    return [t for t in raw.replace(",", " ").split() if t]


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def render_page(current: str, failed: dict[str, dict], stale_page_only: list[dict]) -> str:
    rel = Path(current).name
    lines = [f"🚨 *RELEASE NOT REACHED* — units still on an old release after promote to `{rel}`"]
    for name, v in failed.items():
        lines.append(f"• *{name}* restarted but cwd is `{Path(v.get('cwd') or '?').name or '?'}`")
    for u in stale_page_only:
        lines.append(
            f"• *{u['name']}* on `{Path(u['cwd']).name}` — not restarted by the deploy ({u['reason']}); "
            "restart it yourself when safe"
        )
    lines.append("These services run code from an older release until restarted (Ops → Releases).")
    return "\n".join(lines)


def deliver(message: str) -> tuple[bool, str | None]:
    try:
        from telegram_alert import send_telegram

        ok = send_telegram(message, priority="P1", dedupe_minutes=60, producer=PRODUCER, message_class="operator_alert")
        return bool(ok), None if ok else "send_telegram returned falsy"
    except Exception as e:  # noqa: BLE001 — recorded on the receipt and the exit code, never only logged
        return False, f"{type(e).__name__}: {e}"


def cmd_plan(args: argparse.Namespace) -> int:
    p = cbu.plan(args.current, extra_never=_extra_never())
    if args.names:
        print(" ".join(p.restart))
        return 0
    if args.json:
        print(json.dumps(p.to_dict(), indent=2))
        return 0
    print(f"CURRENT {p.current}")
    for u in p.units:
        state = "STALE" if u.stale else "current"
        why = f" ({u.reason})" if u.reason else ""
        print(f"  {u.action:9s} {u.name:45s} {state:7s} cwd={Path(u.cwd).name if u.cwd else '-'}{why}")
    print(f"restart: {len(p.restart)}  page_only: {len(p.page_only)}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    restarted = [u for u in (args.restarted or "").replace(",", " ").split() if u]
    checks = cbu.verify(args.current, restarted)
    failed = {k: v for k, v in checks.items() if not v["ok"]}
    p = cbu.plan(args.current, extra_never=_extra_never())
    stale_page_only = [
        {"name": u.name, "cwd": u.cwd, "reason": u.reason} for u in p.units if u.action == "page_only" and u.stale
    ]
    out: dict = {
        "schema": "CurrentBoundRestart@v1",
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "current": str(args.current),
        "restarted": restarted,
        "verify": checks,
        "failed": sorted(failed),
        "stale_page_only": stale_page_only,
        "dry_run": bool(args.dry_run),
        "paged": False,
        "page_error": None,
    }
    if failed or stale_page_only:
        msg = render_page(str(args.current), failed, stale_page_only)
        if args.dry_run:
            print(msg)
        else:
            ok, err = deliver(msg)
            out["paged"], out["page_error"] = ok, err
    if not args.dry_run:
        root = _state_root(args.state_root)
        _atomic_write(root / RECEIPT_REL, json.dumps(out, indent=2) + "\n")
        hist = root / HISTORY_REL
        hist.parent.mkdir(parents=True, exist_ok=True)
        with hist.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(out, sort_keys=True) + "\n")
    print(
        json.dumps(out, indent=2)
        if args.json
        else f"verify: {len(checks) - len(failed)}/{len(checks)} on new release; "
        f"failed={sorted(failed)} stale_page_only={[u['name'] for u in stale_page_only]} paged={out['paged']}"
    )
    if failed:
        return 2
    if out["page_error"]:
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("plan", help="list CURRENT-bound running units (read-only)")
    a.add_argument("--current", required=True)
    a.add_argument("--names", action="store_true", help="print restartable unit names only")
    a.add_argument("--json", action="store_true")
    b = sub.add_parser("verify", help="read back cwd after restart; receipt; page P1 when stale")
    b.add_argument("--current", required=True)
    b.add_argument("--restarted", default="")
    b.add_argument("--state-root")
    b.add_argument("--dry-run", action="store_true", help="print the page; send nothing; write no receipt")
    b.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    return cmd_plan(args) if args.cmd == "plan" else cmd_verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
