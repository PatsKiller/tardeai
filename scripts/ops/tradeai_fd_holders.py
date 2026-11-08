#!/usr/bin/env python3
"""tradeai-fd-holders — print the pids holding a file's inode. Read-only, root-installed.

Why this exists (LQ-20261107-501, operator route 1, 2026-11-07 20:19 ET): an unprivileged agent process
cannot read the fd tables of ``systemd --user``, ``(sd-pam)``, ``tailscaled``, ``flock``, ``gpg-agent`` or
the sandboxed ``codex`` agents on this host, so ``jsonl_archive_rotate.py`` correctly refuses to rotate
(class B: "nobody holds it" is unprovable while an unreadable process exists). Giving the rotation script
itself ``CAP_SYS_PTRACE`` or a sudoers line would be root-equivalent for every agent, because the script
lives in an agent-writable release directory. So the privileged half is this one command: it only reads
``/proc/<pid>/fd`` and ``/proc/<pid>/comm``, takes file paths as arguments, and prints what it sees.

The operator installs it root:root 0755 at ``/usr/local/sbin/tradeai-fd-holders`` and allows exactly that
path through sudoers (see ``install-tradeai-fd-holders.sh`` in the coordinator dir). The rotator calls
``sudo -n /usr/local/sbin/tradeai-fd-holders <path>`` and treats a ``complete: true`` answer as a full view.

Contract — stdout is one JSON object::

    {"schema": "tradeai_fd_holders.v1", "complete": true, "paths": [
       {"path": "<as given>", "dev": <int>, "ino": <int>,
        "holders": [{"pid": <int>, "fd": "<str>", "comm": "<str>"}],
        "unknown": [{"pid": <int>, "comm": "<str>", "reason": "<str>"}]}]}

``complete`` is true only when every process's fd table was readable, for every path. An unreadable fd
table is reported, never skipped: the caller refuses on any ``unknown`` row, which is the guarantee the
audit asked for. A path that does not exist is an error (exit 2), because "no such file" is not "no holder".

Exit status: 0 complete; 3 incomplete (capability missing or a table unreadable); 2 usage/bad path;
1 unexpected error. Nothing is opened for read or write beyond ``/proc`` metadata: no file contents, no
signals, no chmod, no network, no database (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCHEMA = "tradeai_fd_holders.v1"


def _comm(proc_root: Path, pid: str) -> str:
    try:
        return ((proc_root / pid / "comm").read_text(encoding="utf-8", errors="replace").strip() or "?")[:32]
    except OSError:
        return "?"


def scan(proc_root: Path, paths: list[Path]) -> tuple[list[dict], bool]:
    """(rows, complete). ``rows`` is one entry per path, in the order given.

    Every process whose fd table cannot be listed, or whose fd target cannot be stat'ed, is recorded as
    unknown for the paths it could not be checked against — for a 0600 store this user owns that is
    conservative (an unreadable process may hold it), and the caller's refusal on ``unknown`` is the whole
    point of the command. A process that exits mid-scan is not unknown: it is gone."""
    keys: list[tuple[int, int]] = []
    for p in paths:
        st = os.stat(p)
        keys.append((st.st_dev, st.st_ino))
    rows: list[dict] = [{"path": str(p), "dev": k[0], "ino": k[1], "holders": [], "unknown": []}
                        for p, k in zip(paths, keys)]
    me = os.getpid()
    try:
        pids = [e.name for e in os.scandir(proc_root) if e.name.isdigit()]
    except OSError as exc:
        for r in rows:
            r["unknown"].append({"pid": 0, "comm": "?", "reason": f"proc_unreadable:{exc.strerror or exc}"})
        return rows, False
    for pid in pids:
        if int(pid) == me:
            continue
        fd_dir = proc_root / pid / "fd"
        try:
            fds = os.listdir(fd_dir)
        except FileNotFoundError:
            continue
        except OSError as exc:
            for r in rows:
                r["unknown"].append({"pid": int(pid), "comm": _comm(proc_root, pid),
                                     "reason": f"fd_dir_denied:{exc.strerror or exc}"})
            continue
        for fd in fds:
            target = fd_dir / fd
            try:
                s = os.stat(target)
            except FileNotFoundError:
                continue
            except OSError as exc:
                for r in rows:
                    r["unknown"].append({"pid": int(pid), "comm": _comm(proc_root, pid),
                                         "reason": f"fd_stat_denied:{exc.strerror or exc}"})
                continue
            k = (s.st_dev, s.st_ino)
            for r in rows:
                if k == (r["dev"], r["ino"]):
                    r["holders"].append({"pid": int(pid), "fd": fd, "comm": _comm(proc_root, pid)})
    complete = not any(r["unknown"] for r in rows)
    return rows, complete


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        sys.stderr.write("usage: tradeai-fd-holders PATH [PATH ...]\n"
                         "  prints the pids holding each path's inode as one JSON object on stdout\n")
        return 2
    paths = [Path(a) for a in argv[1:]]
    rows, complete = scan(Path("/proc"), paths)
    json.dump({"schema": SCHEMA, "complete": complete, "paths": rows}, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if complete else 3


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except FileNotFoundError as exc:
        sys.stderr.write(f"tradeai-fd-holders: {exc.filename}: no such file\n")
        sys.exit(2)
    except OSError as exc:
        sys.stderr.write(f"tradeai-fd-holders: {exc}\n")
        sys.exit(1)
