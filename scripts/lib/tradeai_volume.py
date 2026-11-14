"""One mount guard and one map of heavy-write locations (LQ-20261113-3151).

Why this exists
---------------
The host has a 468 GB root filesystem (``/``, ``/dev/nvme0n1p2``, 88 % full on 2026-11-13) and a 1.8 TB verified
volume (``/data``, ``/dev/nvme1n1p1``, ext4, UUID ``e5711aef-…f0f0``). Heavy writes — agent working copies, temp
files, test output, disposable databases, dumps, browser and node caches — belong on ``/data``.

The trap this module closes: ``~/.cache/agent-tmp`` is an fstab **bind** of ``/data/agent-tmp``, and the
fstab line carries ``nofail``. When ``/data`` is missing, the bind simply does not happen; the directory that remains
is an ordinary directory **on root**, and every ``TMPDIR`` write lands there silently. A mount check by path is not
enough either — ``/data`` existing as an empty directory on root looks exactly like a mounted volume to ``ls``.

So the guard proves four independent things before anything heavy writes:

1. ``/data`` is a *mount point* — it appears in ``/proc/self/mountinfo`` as a mount target, not a plain directory.
2. That mount's source device is the volume with the expected filesystem UUID (``/dev/disk/by-uuid/<uuid>``).
3. The sentinel file ``/data/.tradeai-volume`` is present and readable (an independent, human-auditable marker; a
   stale empty mountpoint cannot have it).
4. ``st_dev(/data) != st_dev(/)``, and every path handed to :func:`check` resolves to the same device as ``/data``.
   Check 4 alone is what catches the broken bind: the bind target is on ``/``'s device when ``/data`` is absent.

Every launcher (``~/bin/claude-deepseek``, the governor's ``ds_start``/``ds_start_one``, ``relaunch_workers.py``,
``scripts/new-worktree.sh``) runs :file:`scripts/lib/tradeai_volume.py check` and exits non-zero with this module's
message rather than starting a process that would quietly fill root.

Usage
-----
    python3 scripts/lib/tradeai_volume.py check [--path PATH ...] [--root /data] [--json]
    python3 scripts/lib/tradeai_volume.py paths [--json]

``check`` exits 0 when every check passes, and 78 (``EX_CONFIG``) when any fails; the message names every failed
check, not just the first. ``TRADEAI_VOLUME_ROOT`` and ``TRADEAI_VOLUME_EXPECT_UUID`` redirect the guard at another
volume; they do not relax any check — a different root still has to be a mount of the expected UUID with the
sentinel, on a different device from ``/``.

Stdlib only, no network, no writes. Tests exercise the checks with injected mountinfo and stat results (synthetic
temp roots only); the CLI itself is proven on this host against a same-device directory (refused) and ``/data``
(accepted).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: The verified 2 TB volume (``findmnt -T /data``: /dev/nvme1n1p1, ext4, 2026-11-13).
EXPECTED_UUID = "e5711aef-7b7b-4e07-ba94-1c9d0dfa50f0"
#: Where the volume is mounted unless TRADEAI_VOLUME_ROOT says otherwise.
DEFAULT_ROOT = "/data"
#: Written once on the volume; its presence is check 3 and it names the UUID it vouches for.
SENTINEL = ".tradeai-volume"
#: Exit code for a refused volume (EX_CONFIG), distinct from usage errors (2).
REFUSED = 78
#: A check that never ran (the earlier proof already failed) reports this, never ``ok``: unknown beats wrong.
SKIPPED = "skipped"
#: The filesystem the guard exists to keep heavy writes off.
ROOT_FS = "/"

_CHECK_NAMES = ("mountpoint", "uuid", "sentinel", "device")


@dataclass
class Report:
    """The outcome of every check, so a refusal can name all of them and a test can pin each one."""

    root: str
    uuid_expected: str
    checks: dict[str, str | None] = field(default_factory=dict)  # name -> failure reason, or None when it passed
    paths: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (not any(v for v in self.checks.values() if v not in (None, SKIPPED))
                and not any(p["reason"] for p in self.paths))

    def reason(self) -> str:
        parts = [f"{name}: {why}" for name, why in self.checks.items() if why and why != SKIPPED]
        parts += [f"path {p['path']}: {p['reason']}" for p in self.paths if p["reason"]]
        return "; ".join(parts) if parts else "volume verified"

    def as_dict(self) -> dict:
        return {"ok": self.ok, "root": self.root, "uuid_expected": self.uuid_expected,
                "checks": {k: (v or "ok") for k, v in self.checks.items()}, "paths": self.paths,
                "reason": self.reason()}


def _unescape(field_value: str) -> str:
    """mountinfo escapes space, tab and newline as \\040, \\011, \\012."""
    for esc, ch in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        field_value = field_value.replace(esc, ch)
    return field_value


def parse_mountinfo(text: str) -> list[dict]:
    """The mount targets and sources from a ``/proc/self/mountinfo`` body, longest-target order preserved."""
    mounts = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 10 or "-" not in parts:
            continue
        sep = parts.index("-")
        # 0 id, 1 parent, 2 major:minor, 3 root, 4 mount point, 5 options, 6.. optional, sep fstype, sep+1 source
        mounts.append({"major_minor": parts[2], "mount_point": _unescape(parts[4]),
                       "fstype": parts[sep + 1], "source": _unescape(parts[sep + 2] if len(parts) > sep + 2 else "")})
    return mounts


def _mounts_for(path: str, mounts: list[dict]) -> dict | None:
    """The mount whose target is the longest prefix of ``path`` (path boundary respected), or None."""
    best = None
    for m in mounts:
        mp = m["mount_point"].rstrip("/") or "/"
        if path == mp or path.startswith(mp.rstrip("/") + "/") or mp == "/":
            if best is None or len(mp) > len(best["mount_point"]):
                best = m
    return best


def _nearest_existing(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return path.anchor and Path(path.anchor) or path


def check(root: str | os.PathLike = DEFAULT_ROOT, *, expect_uuid: str = EXPECTED_UUID,
          paths: list[str | os.PathLike] | None = None, sentinel: str = SENTINEL,
          mountinfo: str | None = None, by_uuid_dir: str | os.PathLike = "/dev/disk/by-uuid",
          stat=os.stat, resolve=os.path.realpath) -> Report:
    """Prove that ``root`` is the verified volume and every ``paths`` entry lives on it.

    ``mountinfo``, ``by_uuid_dir`` and ``stat`` are injection points for the tests (synthetic temp roots only);
    the CLI never passes them, so a caller cannot soften the guard from the command line.
    """
    rep = Report(root=str(root), uuid_expected=expect_uuid)
    for name in _CHECK_NAMES:
        rep.checks[name] = None

    real_root = resolve(str(root))
    root_path = Path(real_root)
    if not root_path.is_dir():
        rep.checks["mountpoint"] = f"{root} is not a directory (the volume is not mounted there)"
        for name in ("uuid", "sentinel", "device"):
            rep.checks[name] = SKIPPED
        return rep

    # 1. a mount target, not a plain directory that happens to exist on root
    text = mountinfo if mountinfo is not None else Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    mounts = parse_mountinfo(text)
    entry = next((m for m in mounts if m["mount_point"].rstrip("/") == real_root.rstrip("/")), None)
    if entry is None:
        where = (_mounts_for(real_root, mounts) or {}).get("mount_point", "?")
        rep.checks["mountpoint"] = (f"{real_root} is a plain directory on the {where} mount, not a mount point "
                                    f"(the volume is not mounted — a bind with nofail fails silently)")
        rep.checks["uuid"] = SKIPPED  # there is no mount source to compare the UUID against
    else:
        # 2. the expected filesystem UUID resolves to the device mounted here
        link = Path(by_uuid_dir) / expect_uuid
        if not link.exists():
            rep.checks["uuid"] = f"no {link}: the expected volume UUID is not attached"
        elif resolve(str(link)) != resolve(entry["source"]):
            rep.checks["uuid"] = (f"{real_root} is {entry['source']}, but UUID {expect_uuid} is "
                                  f"{resolve(str(link))}")

    # 3. the human-auditable sentinel
    marker = root_path / sentinel
    if not marker.is_file():
        rep.checks["sentinel"] = f"{marker} is missing (write it once on the verified volume)"
    else:
        try:
            body = marker.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            rep.checks["sentinel"] = f"{marker} is unreadable: {exc}"
        else:
            if "uuid=" in body and expect_uuid not in body:
                rep.checks["sentinel"] = f"{marker} names a different UUID than {expect_uuid}"

    # 4. a different device from /, and every path on that same device
    try:
        root_dev = stat(real_root).st_dev
        slash_dev = stat(ROOT_FS).st_dev
    except OSError as exc:
        rep.checks["device"] = f"cannot stat {real_root} or /: {exc}"
        return rep
    if root_dev == slash_dev:
        rep.checks["device"] = f"{real_root} and / are the same device ({root_dev}): writes would land on root"
    for given in paths or []:
        target = Path(resolve(str(given)))
        probe = _nearest_existing(target)
        try:
            dev = stat(str(probe)).st_dev
        except OSError as exc:
            rep.paths.append({"path": str(given), "resolved": str(probe), "reason": f"cannot stat: {exc}"})
            continue
        why = None
        if dev == slash_dev:
            why = f"resolves to the root device ({dev}) — the bind to {real_root} is not in effect"
        elif dev != root_dev:
            why = f"is on device {dev}, not the volume's device {root_dev}"
        rep.paths.append({"path": str(given), "resolved": str(probe), "reason": why})
    return rep


def layout(env: dict[str, str] | None = None) -> dict:
    """Every heavy-write location, derived from one root, so no script hardcodes a second one."""
    env = os.environ if env is None else env
    root = env.get("TRADEAI_VOLUME_ROOT", DEFAULT_ROOT).rstrip("/") or "/"
    return {
        "volume": root,
        "sentinel": f"{root}/{SENTINEL}",
        "worktrees": env.get("TRADEAI_WORKTREE_ROOT", f"{root}/worktrees"),
        "agent_tmp": f"{root}/agent-tmp",
        "cc_tmp": f"{root}/cc-tmp",
        "test_db": f"{root}/test-db",
        "dumps": f"{root}/db_backups",
        "build": f"{root}/build",
        "caches": {"npm": f"{root}/caches/npm", "puppeteer": f"{root}/caches/puppeteer",
                   "ms-playwright": f"{root}/caches/ms-playwright", "tradeai-quality": f"{root}/caches/tradeai-quality"},
        "compat_links": {"~/.cache/agent-tmp": f"{root}/agent-tmp", "~/cc-tmp": f"{root}/cc-tmp"},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prove that a path is on the verified Trade AI data volume.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="verify the volume and any paths handed to it")
    c.add_argument("--root", default=os.environ.get("TRADEAI_VOLUME_ROOT", DEFAULT_ROOT))
    c.add_argument("--expect-uuid", default=os.environ.get("TRADEAI_VOLUME_EXPECT_UUID", EXPECTED_UUID))
    c.add_argument("--path", action="append", default=[], help="a path that must live on the volume (repeatable)")
    c.add_argument("--json", action="store_true")
    c.add_argument("--quiet", action="store_true", help="print nothing on success")
    p = sub.add_parser("paths", help="print every routed heavy-write location")
    p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "paths":
        print(json.dumps(layout(), indent=2, sort_keys=True) if args.json else
              "\n".join(f"{k:12s} {v}" for k, v in layout().items() if isinstance(v, str)))
        return 0

    rep = check(args.root, expect_uuid=args.expect_uuid, paths=args.path)
    if args.json:
        print(json.dumps(rep.as_dict(), indent=2))
    elif not rep.ok:
        print(f"TRADEAI_VOLUME_GUARD: refusing: {rep.reason()}", file=sys.stderr)
        print(f"TRADEAI_VOLUME_GUARD: heavy writes must fail here, not land on {ROOT_FS}. "
              f"Mount the verified volume at {rep.root} (UUID {rep.uuid_expected}) and retry; "
              f"a nofail bind that did not happen is the usual cause.", file=sys.stderr)
    elif not args.quiet:
        print(f"TRADEAI_VOLUME_GUARD: ok {rep.root} (UUID {rep.uuid_expected})"
              + (f"; paths on volume: {', '.join(str(p) for p in args.path)}" if args.path else ""))
    return 0 if rep.ok else REFUSED


if __name__ == "__main__":
    sys.exit(main())
