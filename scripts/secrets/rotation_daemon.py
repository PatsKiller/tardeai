#!/usr/bin/env python3
"""Daily rotation nag/daemon (05:30 ET cron — UNSCHEDULED today; see
docs/implementation/n8n-parallel/proposals/key-rotation-schedule-20261008.md).

self_minted overdue → NAG only ("run rotate.py --generate"); this daemon never mints, writes SM or
                      restarts anything by itself (safety: no auto-rotate without an explicit operator step)
vendor_manual / oauth_managed overdue → Telegram nag with vendor_url every 3 days
Never prints values. Rotation age is read from data/runtime/rotation_daemon_state.json
(`<name>.last_rotated_at`); a key with no entry is treated as never rotated (age 999 d) and is due.

    rotation_daemon.py                       # live: state read+written, Telegram nag
    rotation_daemon.py --dry-run             # select + print what it would do; no state write, no send
    rotation_daemon.py --dry-run --registry /tmp/copy.yaml --state /tmp/state.json --now 2026-10-16T09:30:00Z
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))

REGISTRY = ROOT / "config" / "secret_registry.yaml"
STATE = ROOT / "data" / "runtime" / "rotation_daemon_state.json"
NAG_EVERY_DAYS = 3
NEVER_ROTATED_AGE_DAYS = 999
ACTION_NAG_VENDOR = "nag_telegram_vendor_url"
ACTION_NAG_SELF_MINTED = "nag_self_minted_run_rotate_py_generate"


def _parse_ts(value: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def load_registry(path: Path = REGISTRY) -> dict[str, Any]:
    import yaml

    reg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return reg.get("secrets") or {}


def load_state(path: Path = STATE) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def age_days(entry_state: dict[str, Any], now: datetime) -> int:
    last = _parse_ts((entry_state or {}).get("last_rotated_at"))
    return (now - last).days if last else NEVER_ROTATED_AGE_DAYS


def select_due(secrets: dict[str, Any], state: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Every registry key whose age reached max_age_days, with the action this daemon would take.

    Pure: reads nothing but its arguments, prints nothing, never a value. BWS_* keys are skipped by
    design (Rule 1). `nag_suppressed` marks a vendor key nagged within NAG_EVERY_DAYS.
    """
    due: list[dict[str, Any]] = []
    for name, entry in (secrets or {}).items():
        if name.upper().startswith("BWS_"):
            continue
        entry = entry or {}
        cls = str(entry.get("class") or "vendor_manual")
        max_age = int(entry.get("max_age_days") or 90)
        age = age_days(state.get(name) or {}, now)
        if age < max_age:
            continue
        row = {
            "name": name,
            "class": cls,
            "max_age_days": max_age,
            "age_days": age,
            "restart_targets": list(entry.get("restart_targets") or []),
        }
        if cls == "self_minted":
            row["action"] = ACTION_NAG_SELF_MINTED
            row["command"] = f"scripts/secrets/rotate.py {name} --generate"
        else:
            row["action"] = ACTION_NAG_VENDOR
            row["vendor_url"] = str(entry.get("vendor_url") or "")
            last_nag = _parse_ts((state.get(name) or {}).get("last_nag_at"))
            row["nag_suppressed"] = bool(last_nag and (now - last_nag).days < NAG_EVERY_DAYS)
        due.append(row)
    return due


def nag_lines(due: list[dict[str, Any]]) -> list[str]:
    out = []
    for row in due:
        if row["action"] == ACTION_NAG_SELF_MINTED:
            out.append(f"• `{row['name']}` self_minted overdue — run rotate.py --generate when window allows")
        elif not row.get("nag_suppressed"):
            out.append(f"• `{row['name']}` age≥{row['max_age_days']}d {row.get('vendor_url', '')}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", type=Path, default=REGISTRY, help="secret registry yaml (names only; no values)")
    ap.add_argument("--state", type=Path, default=STATE, help="rotation state json (last_rotated_at / last_nag_at)")
    ap.add_argument(
        "--dry-run", action="store_true", help="print the due selection as JSON; no state write, no Telegram"
    )
    ap.add_argument("--now", default=None, help="ISO timestamp override (tests / dry-run)")
    args = ap.parse_args(argv)
    try:
        secrets = load_registry(args.registry)
    except ImportError:
        print("pyyaml required", file=sys.stderr)
        return 1
    st = load_state(args.state)
    now = _parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print(f"--now is not an ISO timestamp: {args.now}", file=sys.stderr)
        return 2
    due = select_due(secrets, st, now)
    nags = nag_lines(due)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "registry": str(args.registry),
                    "state": str(args.state),
                    "now": now.isoformat(),
                    "considered": len([k for k in secrets if not k.upper().startswith("BWS_")]),
                    "due": due,
                    "would_send_telegram": bool(nags),
                    "nag_lines": nags,
                    "state_written": False,
                },
                indent=2,
            )
        )
        return 0
    for row in due:
        if row["action"] == ACTION_NAG_VENDOR and not row.get("nag_suppressed"):
            st.setdefault(row["name"], {})["last_nag_at"] = now.isoformat()
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps(st, indent=2))
    if nags:
        msg = "🔐 Rotation due:\n" + "\n".join(nags[:20])
        try:
            from telegram_alert import send_telegram

            send_telegram(msg, bypass_router=True)
        except Exception as e:
            print("telegram", e)
        print(f"nagged={len(nags)}")
    else:
        print("nothing_due")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
