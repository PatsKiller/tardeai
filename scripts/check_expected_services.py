#!/usr/bin/env python3
"""Report services and feature flags that are OFF when they should be ON. Read-only.

WHY
---
`systemctl --failed` -- which is what health_agent.py:2858 uses -- reports units
that FAILED. A unit that was stopped or disabled has not failed. It is absent,
and absence is invisible to every "what is running" view, because a disabled
unit drops out of the very lists a monitor would enumerate.

On 2026-09-08 `tradeai-cio-telegram.service` was disabled. For five days every
reply the operator sent to a CIO alert landed in a room with no listener, and no
check anywhere could see it. The same week `CIO_REPLY_ENABLED` sat at 0 with a
comment beside it recording an operator instruction to enable it.

Three separate things were found switched off in one day, all of them built and
correct. Nothing was missing. The gap was that nothing reported OFF.

The only way to detect a missing thing is to have written down that it should be
there. config/expected_services.json is that written-down expectation; this
measures against it.

STATES
------
    OK            enabled and running (or a oneshot between scheduled runs)
    DISABLED      the unit exists but will not start on boot -- the silent one
    INACTIVE      enabled but not running now, and it is not a oneshot
    FAILED        systemd says failed
    MISSING       declared here, unknown to systemd entirely
    FLAG_OFF      a declared feature flag is not at its expected value

USAGE
-----
    python scripts/check_expected_services.py            # human-readable
    python scripts/check_expected_services.py --json
    python scripts/check_expected_services.py --alert    # notify on change

EXIT CODES
----------
    0  everything declared is on
    1  at least one declared thing is off
    2  could not run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "config" / "expected_services.json"
STATE_PATH = Path.home() / ".local/state/tradeai/expected_services_last_alert.json"

SCHEMA = "ExpectedServicesReport@v1"
RECEIPT_NAME = "expected_services_last_run.json"

NO_CONSUMER_REASON = (
    "this IS an availability gate; an operator or a scheduled run invokes it and reads "
    "the report, nothing imports it. Same shape as check_test_coverage.py."
)


def _systemctl(*args: str) -> str:
    """Run systemctl --user, returning stdout (empty on any failure).

    DBUS_SESSION_BUS_ADDRESS is set explicitly: under cron there is no login
    session and systemctl silently reports nothing, which would make every unit
    look MISSING and turn this gate into an alarm generator.
    """
    env = dict(os.environ)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{os.getuid()}/bus")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    try:
        p = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=60, env=env)
        return p.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _unit_states() -> tuple[dict[str, str], dict[str, str]]:
    """(enablement by unit, activity by unit) for every unit systemd knows."""
    enablement: dict[str, str] = {}
    for line in _systemctl("list-unit-files", "--no-legend", "--no-pager").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            enablement[parts[0]] = parts[1]

    activity: dict[str, str] = {}
    for line in _systemctl("list-units", "--all", "--plain", "--no-legend", "--no-pager").splitlines():
        parts = line.split()
        # Columns are UNIT LOAD ACTIVE SUB DESCRIPTION. ACTIVE (index 2) is the
        # one with the active/inactive/failed vocabulary. SUB (index 3) holds
        # running/waiting/dead/exited -- a waiting timer is ACTIVE=active,
        # SUB=waiting, so reading SUB reports every healthy timer as inactive.
        if len(parts) >= 3:
            activity[parts[0]] = parts[2]
    return enablement, activity


def check_unit(unit: str, enablement: dict[str, str], activity: dict[str, str]) -> str:
    """Classify one declared unit. Pure, so it is testable without systemd."""
    enabled = enablement.get(unit)
    if enabled is None and unit not in activity:
        return "MISSING"
    if enabled in {"disabled", "masked"}:
        return "DISABLED"

    active = activity.get(unit, "inactive")
    if active == "failed":
        return "FAILED"
    if active == "active":
        return "OK"

    # A .service that is neither active nor failed is only acceptable when it is
    # a oneshot driven by a timer -- it is *supposed* to be inactive between
    # runs. A .timer or .path, by contrast, must be active to be waiting at all.
    if unit.endswith((".timer", ".path")):
        return "INACTIVE"
    if f"{unit[: -len('.service')]}.timer" in enablement:
        return "OK"
    return "INACTIVE"


def _flag_value(name: str, source: str) -> str | None:
    """Read a flag from its declared source file. Values are never logged."""
    path = Path(os.path.expanduser(source))
    if not path.exists():
        return None
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        m = re.match(rf"^{re.escape(name)}=(.*)$", line)
        if m:
            return m.group(1).strip().strip("\"'")
    return None


def _write_run_receipt(checked: int, off: int, detail: dict) -> None:
    """Prove this ran, every run, whether or not it found anything.

    The alert state file only changes when findings change, so a quiet run
    leaves no trace -- and a timer that silently stopped would look exactly like
    a clean result. config/lane_registry.json requires an output_signal that is
    a durable artifact, "not its exit code, not its log file existing", and this
    is that artifact.
    """
    path = PROJECT_ROOT / "data" / "runtime" / RECEIPT_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "ran_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                    "checked": checked,
                    "off": off,
                    **detail,
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
    except OSError as exc:
        print(f"  receipt: could not write {path} ({exc})", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alert", action="store_true", help="notify the operator when the off-set changes")
    args = ap.parse_args()

    if not MANIFEST_PATH.exists():
        print(f"ERROR: no manifest at {MANIFEST_PATH}", file=sys.stderr)
        return 2
    manifest = json.loads(MANIFEST_PATH.read_text())

    enablement, activity = _unit_states()
    if not enablement:
        # Refuse to report 57 MISSING units because systemctl could not be reached.
        print(
            "ERROR: systemctl returned nothing — refusing to report every unit as "
            "MISSING. Check DBUS_SESSION_BUS_ADDRESS.",
            file=sys.stderr,
        )
        return 2

    results = []
    for entry in manifest.get("units", []):
        unit = entry["unit"]
        results.append({"kind": "unit", "name": unit, "status": check_unit(unit, enablement, activity)})

    for entry in manifest.get("flags", []):
        got = _flag_value(entry["name"], entry["source"])
        ok = got == entry["expected"]
        results.append(
            {
                "kind": "flag",
                "name": entry["name"],
                "status": "OK" if ok else "FLAG_OFF",
                "detail": (
                    "as expected"
                    if ok
                    else f"expected {entry['expected']!r}, found "
                    f"{'absent' if got is None else repr(got)} in {entry['source']}"
                ),
            }
        )

    off = [r for r in results if r["status"] != "OK"]

    if args.json:
        print(json.dumps({"schema": SCHEMA, "checked": len(results), "off": len(off), "results": results}, indent=2))
    else:
        print("Expected services — declared things that should be ON")
        print("=" * 74)
        for r in sorted(off, key=lambda x: x["name"]):
            print(f"  [{r['status']:<9}] {r['name']}")
            if r.get("detail"):
                print(f"              {r['detail']}")
        if not off:
            print(f"  all {len(results)} declared units and flags are on.")
        print("-" * 74)
        print(f"  checked={len(results)}  off={len(off)}")
        if any(r["status"] == "DISABLED" for r in off):
            print("\n  A DISABLED unit is the silent one: it never appears in")
            print("  `systemctl --failed`, so nothing else would ever report it.")

    _write_run_receipt(len(results), len(off), {"off_items": [f"{r['status']}:{r['name']}" for r in off]})

    if args.alert:
        _alert(off)

    return 1 if off else 0


def _alert(off: list[dict]) -> None:
    """Notify only when the off-set changes. Never raises."""
    fingerprint = {r["name"]: r["status"] for r in off}
    previous = {}
    try:
        previous = json.loads(STATE_PATH.read_text()).get("fingerprint", {})
    except (OSError, ValueError):
        pass

    if fingerprint == previous:
        print("\n  alert: suppressed — unchanged since the last run.")
        return

    newly = [k for k in fingerprint if k not in previous]
    if not fingerprint:
        body = "✅ Services: everything declared in expected_services.json is on."
    else:
        head = "🚨 CRITICAL — a service that should be running is OFF" if newly else "🚨 Services off"
        lines = [head, ""]
        for r in sorted(off, key=lambda x: x["name"]):
            lines.append(f"• [{r['status']}] {r['name']}")
            if r.get("detail"):
                lines.append(f"    {r['detail']}")
        if newly:
            lines += ["", "NEW since the last run: " + ", ".join(newly)]
        recovered = [k for k in previous if k not in fingerprint]
        if recovered:
            lines += ["", "Back on: " + ", ".join(recovered)]
        lines += [
            "",
            "A disabled unit never appears in `systemctl --failed`.",
            "config/expected_services.json is the declared expectation.",
        ]
        body = "\n".join(lines)

    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from telegram_alert import send_telegram

        ok = send_telegram(body, message_class="operator_alert")
        print(f"\n  alert: {'accepted' if ok else 'NOT accepted'} by the platform")
    except Exception as exc:
        print(f"\n  alert: FAILED to send ({exc}). The findings above still stand.", file=sys.stderr)
        return

    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({"fingerprint": fingerprint}, indent=2))
    except OSError as exc:
        print(f"  alert: could not record state ({exc}).", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
