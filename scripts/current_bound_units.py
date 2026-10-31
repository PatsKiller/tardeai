#!/usr/bin/env python3
"""Plan, filter, verify and receipt the post-promote restart of CURRENT-bound user units (AGENTS.md 28.1.0 §25.10).

Used by ``scripts/cio_phase2_exact_main_deploy.sh`` (``restart_root_frozen_units``, promote and rollback):

  python scripts/current_bound_units.py plan --current <dir> [--json]      # read-only: restart vs page-only
  python scripts/current_bound_units.py plan --current <dir> --names       # restartable names only
  python scripts/current_bound_units.py filter --units "a.service b.service"  # fail-closed filter of ANY list
  python scripts/current_bound_units.py verify --current <dir> --event promote|rollback \\
      --restarted "..." --restart-failed "..." [--dry-run]

``verify`` is the single judge: it reads back each restarted unit's ``/proc/<pid>/cwd``, counts failed restarts,
lists stale page-only units, writes the receipt and pages P1 once per unit set per day. Nothing here restarts a unit.
"""

from __future__ import annotations

import argparse
import hashlib
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
DEDUPE_MINUTES = 1440  # one page per identical unit set per day; the body carries no release name


HARNESS_VARS = ("TRADE_AI_CI", "PYTEST_CURRENT_TEST", "TRADEAI_TEST_HARNESS")
DEFAULT_STATE_ROOT = Path.home() / "trade-ai-releases" / "persistent-state"


TRUTHY = frozenset({"1", "true"})


def harness_reason() -> str | None:
    """Non-None under a test or CI harness: no live Telegram send and no write under a production state root.

    ``TRADE_AI_CI`` / ``TRADEAI_TEST_HARNESS`` count only when "1" or "true" (any case), so a stray ``=0`` in
    production can never suppress a real P1. ``PYTEST_CURRENT_TEST`` is set only by pytest (to the test id), so any
    non-empty value counts."""
    for var in ("TRADE_AI_CI", "TRADEAI_TEST_HARNESS"):
        if os.environ.get(var, "").strip().lower() in TRUTHY:
            return var
    if os.environ.get("PYTEST_CURRENT_TEST", "").strip():
        return "PYTEST_CURRENT_TEST"
    return None


def is_test_double(fn) -> bool:
    """Only a callable that explicitly declares ``_tradeai_test_double = True`` counts (Mock auto-attributes,
    wrappers, partials and re-exports of the real sender do not)."""
    try:
        return object.__getattribute__(fn, "__dict__").get("_tradeai_test_double") is True
    except (AttributeError, TypeError):
        return False


def _state_root(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    env = os.environ.get("TRADEAI_PERSISTENT_STATE_ROOT")
    if env:
        return Path(env)
    from lib.persistent_state_root import good_persistent_root

    return good_persistent_root()


def protected_roots() -> list[Path]:
    """Every root a harness must never write under: the env root, the resolved production root, the default."""
    roots = [DEFAULT_STATE_ROOT]
    env = os.environ.get("TRADEAI_PERSISTENT_STATE_ROOT")
    if env:
        roots.append(Path(env))
    try:
        from lib.persistent_state_root import good_persistent_root

        roots.append(Path(good_persistent_root()))
    except Exception:  # noqa: BLE001 — the default and env roots still protect
        pass
    out = []
    for r in roots:
        try:
            out.append(r.expanduser().resolve())
        except OSError:
            out.append(r)
    return out


def write_refused(root: Path) -> str | None:
    """Why a receipt write under ``root`` is refused, or None. Only under a harness, only for protected roots."""
    why = harness_reason()
    if not why:
        return None
    root = root.expanduser()
    # Resolve the FINAL paths: a scratch root whose data/runtime is a symlink into production must be refused.
    targets = [root.resolve(), (root / RECEIPT_REL).resolve(), (root / HISTORY_REL).resolve()]
    for pr in protected_roots():
        for rr in targets:
            if rr == pr or pr in rr.parents or (rr is targets[0] and rr in pr.parents):
                return f"{why} set: refusing to write under the persistent-state root {pr}"
    return None


def _split(raw: str | None) -> list[str]:
    return [u for u in (raw or "").replace(",", " ").split() if u]


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def render_page(event: str, day: str, failed: list[str], restart_failed: list[str], stale_page_only: list[dict]) -> str:
    """Stable per unit set per day: no release name, no pid, no time — so the router's body dedupe holds."""
    what = "rollback" if event == "rollback" else "promote"
    lines = [f"🚨 *RELEASE NOT REACHED after {what}* — {day}"]
    for name in restart_failed:
        lines.append(f"• *{name}*: restart FAILED — still on the previous release")
    for name in failed:
        if name not in restart_failed:
            lines.append(f"• *{name}*: restarted but not running the new release")
    for u in stale_page_only:
        lines.append(
            f"• *{u['name']}*: on an old release, not restarted by the deploy ({u['reason']}) — restart it when safe"
        )
    lines.append(f"These services run older code until restarted (Ops → Releases). Receipt: {RECEIPT_REL}")
    return "\n".join(lines)


def deliver(message: str) -> tuple[bool, str | None]:
    try:
        from telegram_alert import send_telegram

        why = harness_reason()
        if why and not is_test_double(send_telegram):
            # A harness may exercise this path with a test double, never with the real sender.
            print(
                f"current_bound_units: {why} set — live Telegram send refused (behaving as --dry-run)", file=sys.stderr
            )
            return False, f"refused: {why} set (no live send under a test harness)"

        ok = send_telegram(
            message, priority="P1", dedupe_minutes=DEDUPE_MINUTES, producer=PRODUCER, message_class="operator_alert"
        )
        return bool(ok), None if ok else "send_telegram returned falsy"
    except Exception as e:  # noqa: BLE001 — recorded on the receipt and the exit code, never only logged
        return False, f"{type(e).__name__}: {e}"


def cmd_plan(args: argparse.Namespace) -> int:
    p = cbu.plan(args.current)
    if args.names:
        print(" ".join(p.restart))
        return 0
    if args.json:
        print(json.dumps(p.to_dict(), indent=2))
        return 0
    print(f"CURRENT {p.current}")
    for u in p.units:
        state = "STALE" if u.stale else "current"
        print(f"  {u.action:9s} {u.name:45s} {state:7s} cwd={Path(u.cwd).name if u.cwd else '-'} ({u.reason})")
    print(f"restart: {len(p.restart)}  page_only: {len(p.page_only)}")
    return 0


def cmd_filter(args: argparse.Namespace) -> int:
    keep, refused = cbu.filter_units(_split(args.units))
    for name, why in refused.items():
        print(f"refused {name}: {why}", file=sys.stderr)
    print(" ".join(keep))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    restarted = _split(args.restarted)
    restart_failed = _split(args.restart_failed)
    checks = cbu.verify(args.current, restarted)
    failed = sorted({*restart_failed, *(k for k, v in checks.items() if not v["ok"])})
    p = cbu.plan(args.current)
    stale_page_only = [
        {"name": u.name, "cwd": u.cwd, "reason": u.reason if u.action == "page_only" else "not_in_this_deploy_list"}
        for u in p.units
        if u.stale and u.name not in restarted and u.name not in restart_failed
    ]
    now = datetime.now(timezone.utc)
    out: dict = {
        "schema": "CurrentBoundRestart@v1",
        "at": now.isoformat(timespec="seconds"),
        "event": args.event,
        "current": str(args.current),
        "restarted": restarted,
        "restart_failed": restart_failed,
        "verify": checks,
        "failed": failed,
        "stale_page_only": stale_page_only,
        "dry_run": bool(args.dry_run),
        "harness_reason": harness_reason(),
        "paged": False,
        "page_error": None,
    }
    if harness_reason() and not args.dry_run:
        print(f"current_bound_units: {harness_reason()} set — sends and production writes are refused", file=sys.stderr)
    if failed or stale_page_only:
        msg = render_page(args.event, now.strftime("%Y-%m-%d"), failed, restart_failed, stale_page_only)
        out["page_key"] = hashlib.sha256(msg.encode()).hexdigest()[:16]
        if args.dry_run:
            print(msg)
        else:
            ok, err = deliver(msg)
            out["paged"], out["page_error"] = ok, err
    root = _state_root(args.state_root)
    refused_write = None if args.dry_run else write_refused(root)
    if refused_write:
        print(f"current_bound_units: {refused_write} (behaving as --dry-run)", file=sys.stderr)
        out["receipt_refused"] = refused_write
    if not args.dry_run and not refused_write:
        _atomic_write(root / RECEIPT_REL, json.dumps(out, indent=2) + "\n")
        hist = root / HISTORY_REL
        hist.parent.mkdir(parents=True, exist_ok=True)
        with hist.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(out, sort_keys=True) + "\n")
    print(
        json.dumps(out, indent=2)
        if args.json
        else f"verify[{args.event}]: {len(checks) - len([k for k, v in checks.items() if not v['ok']])}/{len(checks)} "
        f"on new release; failed={failed} stale_page_only={[u['name'] for u in stale_page_only]} paged={out['paged']}"
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
    f = sub.add_parser("filter", help="fail-closed filter of any candidate unit list (read-only)")
    f.add_argument("--units", default="")
    b = sub.add_parser("verify", help="read back cwd; receipt; page P1 when stale or a restart failed")
    b.add_argument("--current", required=True)
    b.add_argument("--event", choices=("promote", "rollback"), default="promote")
    b.add_argument("--restarted", default="")
    b.add_argument("--restart-failed", default="")
    b.add_argument("--state-root")
    b.add_argument("--dry-run", action="store_true", help="print the page; send nothing; write no receipt")
    b.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    return {"plan": cmd_plan, "filter": cmd_filter, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
