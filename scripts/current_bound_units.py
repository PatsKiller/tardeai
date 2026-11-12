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
    # TRADEAI_TEST_HARNESS_FORCE is set only by tests; the deploy strips the other three before calling verify.
    for var in ("TRADEAI_TEST_HARNESS_FORCE", "TRADE_AI_CI", "TRADEAI_TEST_HARNESS"):
        if os.environ.get(var, "").strip().lower() in TRUTHY:
            return var
    if os.environ.get("PYTEST_CURRENT_TEST", "").strip():
        return "PYTEST_CURRENT_TEST"
    return None


def is_test_double(fn) -> bool:
    """Only a callable that explicitly declares ``_tradeai_test_double = True`` counts (Mock auto-attributes,
    wrappers, partials and re-exports of the real sender do not). Never mark a wrapper of the real sender as
    ``_tradeai_test_double``: the marker asserts the callable cannot reach Telegram."""
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


def render_page(
    event: str,
    day: str,
    failed: list[str],
    restart_failed: list[str],
    stale_page_only: list[dict],
    deferred_intentional: list[dict] | None = None,
) -> str:
    """Stable per unit set per day: no release name, no pid, no time — so the router's body dedupe holds."""
    what = "rollback" if event == "rollback" else "promote"
    lines = [f"🚨 *RELEASE NOT REACHED after {what}* — {day}"]
    for name in restart_failed:
        lines.append(f"• *{name}*: restart FAILED — still on the previous release")
    for name in failed:
        if name not in restart_failed:
            lines.append(f"• *{name}*: restarted but not running the new release")
    for u in stale_page_only:
        when = u.get("restart_command") or f"systemctl --user restart {u['name']}"
        lines.append(
            f"• *{u['name']}*: on an old release, not restarted by the deploy ({u['reason']}) — when safe: `{when}`"
        )
    for u in deferred_intentional or ():
        when = u.get("restart_command") or f"systemctl --user restart {u['name']}"
        if u.get("category") == "market_hours":
            lines.append(
                f"• *{u['name']}*: held on the old release by the market-hours guard ({u['reason']}) — "
                f"after the US session closes (20:00 ET): `{when}`"
            )
        else:
            lines.append(
                f"• *{u['name']}*: on the old release, intentionally deferred by the deploy ({u['reason']}) — "
                f"operator action: `{when}`"
            )
    lines.append(f"These services run older code until restarted (Ops → Releases). Receipt: {RECEIPT_REL}")
    return "\n".join(lines)


def render_summary(updated: int, deferred: list[dict], stale_page_only: list[dict], failed: list[str]) -> str:
    """The operator's summary block (LQ-20261107-2082, E21): updated / intentionally deferred / action required."""
    ok = not failed and not stale_page_only
    lines = [
        "Release activated" if ok else "Release NOT fully activated",
        f"{updated} services updated",
        f"{len(deferred)} services intentionally deferred",
    ]
    if deferred:
        lines.append("Operator action required: systemctl --user restart " + " ".join(u["name"] for u in deferred))
        for u in deferred:
            if u.get("category") == "market_hours":
                lines.append(f"  {u['name']}: only after 20:00 ET on trading days")
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
    # LQ-20261107-137: units the deploy asked to drain (n8n run executor finishing in-flight runs). They restart
    # themselves when idle, so being on the old release right now is expected, not a stale unit to page.
    deferred = _split(getattr(args, "deferred", ""))
    # LQ-20261107-1685 (E): units the market-hours guard kept on the old release on purpose (a long run in
    # flight). Recorded, never paged as stale — the release waits for an off-hours promote by design.
    refused_units = _split(getattr(args, "refused", ""))
    checks = cbu.verify(args.current, restarted)
    failed = sorted({*restart_failed, *(k for k, v in checks.items() if not v["ok"])})
    # One market clock for the whole receipt: the same value decides the plan's reasons and the split below.
    market_now = cbu.market_open()
    p = cbu.plan(args.current, is_open=market_now)
    stale = [
        {"name": u.name, "cwd": u.cwd, "reason": u.reason if u.action == "page_only" else "not_in_this_deploy_list"}
        for u in p.units
        if u.stale
        and u.name not in restarted
        and u.name not in restart_failed
        and u.name not in deferred
        and u.name not in refused_units
    ]
    # LQ-20261107-2067/2082 (E21): a unit the activation policy deliberately never restarts — market-hours guard,
    # PAGE_ONLY_NAMED, or HARD_NEVER — is expected to sit on the old release. Record it with the exact restart
    # command and do NOT raise "not reached" for it; a page raised for another unit still names it. A stale unit
    # with no such policy reason stays in stale_page_only and pages.
    deferred_intentional: list[dict] = []
    stale_page_only: list[dict] = []
    for u in stale:
        u["restart_command"] = f"systemctl --user restart {u['name']}"
        category = cbu.deferral_category(u["reason"], is_market_open=market_now)
        if category:
            u["category"] = category
            deferred_intentional.append(u)
        else:
            stale_page_only.append(u)
    deferred_market_close = [u for u in deferred_intentional if u["category"] == "market_hours"]
    updated = sum(1 for v in checks.values() if v["ok"])
    now = datetime.now(timezone.utc)
    out: dict = {
        "schema": "CurrentBoundRestart@v1",
        "at": now.isoformat(timespec="seconds"),
        "event": args.event,
        "current": str(args.current),
        "restarted": restarted,
        "restart_failed": restart_failed,
        "updated_confirmed": updated,
        "deferred_draining": deferred,
        "refused_market_busy": refused_units,
        "verify": checks,
        "failed": failed,
        "stale_page_only": stale_page_only,
        # LQ-20261107-2082 (E21): every standing policy refusal, with its category, reason and restart command.
        # Never a page by itself; read by the human summary and by release_status.py's LAG lines.
        "intentionally_deferred": deferred_intentional,
        # LQ-20261107-2067: the market-hours subset, kept so the original field keeps its meaning.
        "deferred_market_close": deferred_market_close,
        "market_open_at_verify": market_now,
        "dry_run": bool(args.dry_run),
        "harness_reason": harness_reason(),
        "paged": False,
        "page_error": None,
    }
    if harness_reason() and not args.dry_run:
        print(f"current_bound_units: {harness_reason()} set — sends and production writes are refused", file=sys.stderr)
    if failed or stale_page_only:
        msg = render_page(
            args.event, now.strftime("%Y-%m-%d"), failed, restart_failed, stale_page_only, deferred_intentional
        )
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
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(render_summary(updated, deferred_intentional, stale_page_only, failed))
        print(
            f"verify[{args.event}]: {updated}/{len(checks)} on new release; failed={failed} "
            f"refused_market_busy={refused_units} "
            f"stale_page_only={[u['name'] for u in stale_page_only]} "
            f"intentionally_deferred={[u['name'] for u in deferred_intentional]} paged={out['paged']}"
        )
    refused = bool(out.get("receipt_refused")) or str(out.get("page_error") or "").startswith("refused")
    if refused and not args.dry_run:
        print(
            "current_bound_units: ERROR verify refused to page and/or write its receipt (harness guard)",
            file=sys.stderr,
        )
        return 4  # distinct: the alarm itself was suppressed
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
    b.add_argument("--deferred", default="", help="units draining in-flight work; they restart themselves when idle")
    b.add_argument(
        "--refused",
        default="",
        help="units whose activation the market-hours guard refused; recorded, never paged as stale (LQ-1685)",
    )
    b.add_argument("--state-root")
    b.add_argument("--dry-run", action="store_true", help="print the page; send nothing; write no receipt")
    b.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    return {"plan": cmd_plan, "filter": cmd_filter, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
