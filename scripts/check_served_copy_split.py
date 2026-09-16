#!/usr/bin/env python3
"""Report when the tree the site SERVES and the tree the producers WRITE are two
different directories. Read-only.

WHY
---
On 2026-08-27 CURRENT/data/{portfolios/state,runtime} were linked to
persistent-state so a promote could not orphan the served state again. The dev
tree -- the one 344 cron producers `cd` into -- was never linked. From that day
every producer wrote a copy nothing served, and the served copy aged in place.

Measured 2026-09-13: 294 files differed between the two trees, 40 of the 192
state files the API reads were served 18 days stale while a fresh copy sat
next door, and 79 append-only ledgers had grown on BOTH sides -- so by then no
"newest wins" could heal it without destroying rows. The health agent scored 75
and said nothing, because it read the age of whichever copy it was pointed at.

A state directory that exists twice is the defect. Not the age of any one file:
the age is the symptom, and an age check on one tree is exactly what missed
this. This gate asks one question per directory -- do the two paths resolve to
the same inode? -- and, when they do not, counts how far apart the copies are so
the alert says what is at stake.

STATES
------
    LINKED      dev and served resolve to one physical directory  (the only OK)
    SPLIT       two directories; N files differ, M exist on one side only
    MISSING     one side does not exist at all
    TRIPPED     something live references the Phase 1 reconcile archive

USAGE
-----
    python scripts/check_served_copy_split.py            # human-readable
    python scripts/check_served_copy_split.py --json
    python scripts/check_served_copy_split.py --alert    # notify on change

EXIT CODES
----------
    0  every declared directory is one physical directory
    1  at least one directory is SPLIT or MISSING
    2  could not run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
STATE_PATH = Path.home() / ".local/state/tradeai/served_copy_split_last_alert.json"

sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
from alert_transition import (  # noqa: E402
    TYPE_SYSTEM_HEALTH,
    evaluate,
    fingerprint_state,
    previous_fingerprint,
)

#: Durable identity for this condition in the shared alert state machine.
CONDITION_KEY = "platform_availability:served_copy_split"

SCHEMA = "ServedCopySplitReport@v1"
RECEIPT_NAME = "served_copy_split_last_run.json"

NO_CONSUMER_REASON = (
    "this IS an availability gate; a scheduled run invokes it and the operator reads "
    "the report, nothing imports it. Same shape as check_expected_services.py."
)

#: The state directories the Command Center reads. Each must be ONE physical
#: directory whichever tree a process happens to run from. Add a directory here
#: when a new served store is introduced; remove one in the same change that
#: retires it.
SPLIT_DIRS = ("audit", "cio", "health", "paper_trading", "portfolios/state", "runtime", "state")

#: Where Phase 1 of the One Source of Truth plan parked the dev tree's former data
#: directories and the overwritten served copies. Nothing may read from here. Any
#: reference from live code, the crontab or a unit file is a defect — the tripwire.
ARCHIVE_ROOT = "/home/johnclaw/trade-ai-releases/archive/served_copy_split_20260913"

#: mtimes closer than this are the same write (filesystems round differently).
MTIME_TOLERANCE_S = 2.0


def resolve_dir(root: Path, sub: str) -> Path | None:
    """Physical directory `root/data/sub` resolves to, or None when absent."""
    p = root / "data" / sub
    if not p.exists():
        return None
    return Path(os.path.realpath(p))


def diff_trees(a: Path, b: Path) -> dict:
    """Count how far two copies of one directory have drifted. Pure over paths.

    Byte-identity is inferred from size + mtime, not content: this runs hourly
    over ~40k files and a wrong-side stale copy shows up in mtime first.
    """
    def walk(root: Path) -> dict[str, tuple[float, int]]:
        out: dict[str, tuple[float, int]] = {}
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                p = Path(dp) / f
                if p.is_symlink() or not p.is_file():
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                out[str(p.relative_to(root))] = (st.st_mtime, st.st_size)
        return out

    fa, fb = walk(a), walk(b)
    differ: list[tuple[str, float]] = []
    for rel in fa.keys() & fb.keys():
        (ma, sa), (mb, sb) = fa[rel], fb[rel]
        if sa != sb or abs(ma - mb) > MTIME_TOLERANCE_S:
            differ.append((rel, round(abs(ma - mb) / 3600.0, 1)))
    differ.sort(key=lambda t: -t[1])
    return {
        "in_both": len(fa.keys() & fb.keys()),
        "differ": len(differ),
        "only_a": len(fa.keys() - fb.keys()),
        "only_b": len(fb.keys() - fa.keys()),
        "worst": [{"file": rel, "gap_hours": gap} for rel, gap in differ[:5]],
        "ledgers_diverged": sum(1 for rel, _ in differ if rel.endswith(".jsonl")),
    }


def check_dir(sub: str, dev_root: Path, served_root: Path, *, count: bool = True) -> dict:
    """One finding per declared directory. LINKED is the only OK."""
    dev, served = resolve_dir(dev_root, sub), resolve_dir(served_root, sub)
    row = {"dir": sub, "dev": str(dev) if dev else None, "served": str(served) if served else None}
    if dev is None or served is None:
        row["status"] = "MISSING"
        row["detail"] = f"{'dev' if dev is None else 'served'} side has no data/{sub}"
        return row
    if dev == served:
        row["status"] = "LINKED"
        return row
    row["status"] = "SPLIT"
    if count:
        d = diff_trees(dev, served)
        row.update(d)
        row["detail"] = (
            f"{d['differ']} files differ ({d['ledgers_diverged']} append-only ledgers grew on both sides), "
            f"{d['only_a']} only in dev, {d['only_b']} only in served"
        )
    return row


def archive_tripwire(archive_root: str = ARCHIVE_ROOT, *, repo: Path | None = None,
                     crontab_text: str | None = None, unit_dir: Path | None = None) -> list[dict]:
    """Every live place that names the archive path. Empty list is the only OK.

    Scans the repo's scripts/ and config/, the user crontab, and the user systemd
    unit files. The archive itself and this file are excluded.
    """
    repo = repo or PROJECT_ROOT
    hits: list[dict] = []
    needle = archive_root.rstrip("/")
    for sub in ("scripts", "config", "linux_launchers"):
        base = repo / sub
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in (".py", ".sh", ".json", ".yaml", ".yml", ".env", ".service", ".timer") or "__pycache__" in p.parts:
                continue
            if p.resolve() == Path(__file__).resolve():
                continue
            try:
                if needle in p.read_text(encoding="utf-8", errors="replace"):
                    hits.append({"where": "repo", "ref": str(p.relative_to(repo))})
            except OSError:
                continue
    if crontab_text is None:
        try:
            import subprocess
            crontab_text = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10).stdout
        except Exception:  # noqa: BLE001
            crontab_text = ""
    for i, line in enumerate(crontab_text.splitlines(), 1):
        if needle in line:
            hits.append({"where": "crontab", "ref": f"line {i}"})
    unit_dir = unit_dir or (Path.home() / ".config/systemd/user")
    if unit_dir.is_dir():
        for u in unit_dir.glob("*.service"):
            try:
                if needle in u.read_text(encoding="utf-8", errors="replace"):
                    hits.append({"where": "systemd", "ref": u.name})
            except OSError:
                continue
    return hits


def _write_run_receipt(findings: list[dict]) -> None:
    """Prove this ran, every run, findings or not (lane_registry output_signal)."""
    path = PROJECT_ROOT / "data" / "runtime" / RECEIPT_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "checked": len(findings),
                    "split": sum(1 for f in findings if f["status"] != "LINKED"),
                    "split_items": [f"{f['status']}:{f['dir']}" for f in findings if f["status"] != "LINKED"],
                    "findings": findings,
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
    except OSError as exc:
        print(f"  receipt: could not write {path} ({exc})", file=sys.stderr)


def _alert(findings: list[dict]) -> None:
    """Notify on CHANGE of the split-set, with a recovery message when it clears.

    Suppression, escalation and the 6-hour heartbeat are the shared state
    machine's decision (scripts/lib/alert_transition.py), not this file's. This
    used to be eleven lines of fingerprint comparison written here and in six
    other monitors, and a split that never healed was announced exactly once.
    """
    bad = [f for f in findings if f["status"] != "LINKED"]
    fingerprint = {f["dir"]: f["status"] for f in bad}
    # Named `transition`, not `t`: the body builder below binds `t` as its
    # per-trip loop variable, and reusing the name silently replaced the
    # transition with a trip dict on the archive-tripwire path.
    transition = evaluate(
        CONDITION_KEY,
        fingerprint_state(fingerprint),
        alertable=bool(fingerprint),
        path=STATE_PATH,
    )
    if not transition.notify:
        print(f"  alert: {transition.quiet_reason()}")
        return
    previous = previous_fingerprint(transition.previous)
    if not fingerprint:
        body = (
            "[PLATFORM_AVAILABILITY] ✅ Served-copy split cleared: every state directory "
            "resolves to one physical path from both trees."
        )
    else:
        lines = ["[PLATFORM_AVAILABILITY] 🚨 STATE TREE SPLIT — the site serves one copy, the producers write another"]
        if all(f["status"] == "TRIPPED" for f in bad):
            lines = ["[PLATFORM_AVAILABILITY] 🚨 ARCHIVE TRIPWIRE — something live references the served-copy reconcile archive"]
        for f in bad:
            lines.append((f"• {f['dir']}: {f['status']}" if f["dir"] == "archive_tripwire" else f"• data/{f['dir']}: {f['status']}") + (f" — {f['detail']}" if f.get("detail") else ""))
            for t in (f.get("trips") or [])[:5]:
                lines.append(f"    {t['where']}: {t['ref']}")
            for w in (f.get("worst") or [])[:3]:
                lines.append(f"    {w['gap_hours']}h apart  {w['file']}")
        lines.append("")
        lines.append(
            "Every value read from the affected directories may be stale while a fresh copy exists. "
            "Do NOT reconcile by hand: run the audit, then follow the One Source of Truth plan Phase 1."
        )
        recovered = [k for k in previous if k not in fingerprint]
        if recovered:
            lines.append(f"Recovered: {', '.join(recovered)}")
        body = "\n".join(lines)
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        import telegram_alert as _ta
        ok = _ta.send_telegram(body, message_class="operator_alert")
        message_id = getattr(_ta, "last_message_id", lambda: None)()
    except Exception as exc:  # noqa: BLE001
        transition.rollback()
        print(f"  alert: send failed ({exc}); state not advanced", file=sys.stderr)
        return
    if not ok:
        transition.rollback()
        print("  alert: transport returned falsy; state not advanced", file=sys.stderr)
        return
    rec = transition.commit(
        body=body,
        alert_type=TYPE_SYSTEM_HEALTH,
        source_script="check_served_copy_split.py",
        telegram_message_id=message_id,
        payload={"split_dirs": sorted(fingerprint)},
    )
    print(f"  alert: {transition.action} sent (message_id={message_id}, "
          f"alert_event={rec['alert_event_id']}, resolved={rec['resolved_rows']})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alert", action="store_true", help="notify the operator when the split-set changes")
    ap.add_argument("--dev-root", default=str(PROJECT_ROOT), help="tree the producers run from")
    ap.add_argument("--served-root", default=str(DEFAULT_CURRENT), help="tree the site serves")
    ap.add_argument("--no-count", action="store_true", help="link check only, skip the file diff")
    args = ap.parse_args()

    dev_root, served_root = Path(args.dev_root), Path(args.served_root)
    if not served_root.exists():
        print(f"ERROR: served root {served_root} does not exist — refusing to report every dir MISSING", file=sys.stderr)
        return 2

    findings = [check_dir(sub, dev_root, served_root, count=not args.no_count) for sub in SPLIT_DIRS]
    trips = archive_tripwire()
    if trips:
        findings.append({"dir": "archive_tripwire", "status": "TRIPPED",
                         "detail": f"{len(trips)} live reference(s) to the reconcile archive", "trips": trips})
    bad = [f for f in findings if f["status"] != "LINKED"]

    if args.json:
        print(json.dumps({"schema": SCHEMA, "dev_root": str(dev_root), "served_root": str(served_root), "findings": findings}, indent=2))
    else:
        print("Served-copy split — one physical directory per served store?")
        print("=" * 74)
        for f in findings:
            print(f"  [{f['status']:<7}] data/{f['dir']}")
            if f["status"] == "TRIPPED":
                for t in f["trips"]:
                    print(f"            {t['where']}: {t['ref']}")
                continue
            if f["status"] != "LINKED":
                print(f"            dev    → {f['dev']}")
                print(f"            served → {f['served']}")
                if f.get("detail"):
                    print(f"            {f['detail']}")
                for w in f.get("worst") or []:
                    print(f"            {w['gap_hours']:>8}h  {w['file']}")
        print("-" * 74)
        print(f"  checked={len(findings)}  split={len(bad)}")

    _write_run_receipt(findings)
    if args.alert:
        _alert(findings)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
