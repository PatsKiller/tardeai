"""Run a lane script as __main__ under a CPython audit hook that RECORDS every side effect a dry run must not have.

    python tests/support/dry_run_write_recorder.py <out.json> <script> [args...]

Recorded (sys.addaudithook, PEP 578; nothing is blocked, so the script's own control flow is what is proven):
  * open / os.open with a write, append, create or truncate mode (any file: logs, state, receipts, caches);
  * os.mkdir / os.rename / os.replace / os.remove / shutil.* / os.truncate (filesystem mutation);
  * socket.connect / socket.getaddrinfo (DB, HTTP, Telegram, provider: every network reach);
  * subprocess.Popen / os.system / os.exec / os.posix_spawn (child processes);
  * sqlite3.connect (local stores).
Writes the record (exit code, the events, the importable DB / HTTP / send modules that got loaded) to <out.json>.
Used by the n8n onboarding dry-run proofs (tests/test_n8n_onboard_dryrun_proven_*_20261015.py): a dry run is
write-free only when every list is empty. Hermetic: it executes only the given script; it never connects anywhere.
"""

from __future__ import annotations

import json
import os
import runpy
import sys

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_FS_EVENTS = {
    "os.mkdir",
    "os.rename",
    "os.replace",
    "os.remove",
    "os.rmdir",
    "os.truncate",
    "shutil.copyfile",
    "shutil.move",
    "shutil.rmtree",
    "os.link",
    "os.symlink",
    "os.chmod",
    "os.utime",
}
_NET_EVENTS = {"socket.connect", "socket.getaddrinfo", "socket.sendto", "http.client.connect"}
_PROC_EVENTS = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork", "os.spawn"}
#: Modules whose import alone means the dry run reached a DB / HTTP / send path.
WATCHED_MODULES = (
    "psycopg2",
    "psycopg",
    "sqlalchemy",
    "db_adapter",
    "requests",
    "httpx",
    "urllib3",
    "telegram_alert",
    "telegram_transport",
    "smtp" + "lib",  # spelled apart: the provider-chokepoint ratchet greps the literal module name
    "dotenv",
    "llm_lane",
    "llm_router",
)


def main(argv: list[str]) -> int:
    out_path, script, *args = argv
    events: dict[str, list] = {"file_writes": [], "fs_mutations": [], "network": [], "subprocess": [], "sqlite": []}
    armed = [False]

    def hook(event: str, a: tuple) -> None:
        if not armed[0]:
            return
        if event == "open":
            path, mode, flags = (list(a) + [None, None, None])[:3]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & _WRITE_FLAGS
            )
            if writing and not str(path).startswith("/dev/"):
                events["file_writes"].append([str(path), str(mode), flags])
        elif event in _FS_EVENTS:
            events["fs_mutations"].append([event, [str(x) for x in a][:2]])
        elif event in _NET_EVENTS:
            events["network"].append([event, [str(x) for x in a][:2]])
        elif event in _PROC_EVENTS or event.startswith("os.exec") or event.startswith("os.spawn"):
            events["subprocess"].append([event, str(a)[:200]])
        elif event == "sqlite3.connect":
            events["sqlite"].append([str(x) for x in a][:1])

    sys.addaudithook(hook)
    sys.argv = [script, *args]
    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
    code = 0
    armed[0] = True
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    finally:
        armed[0] = False
    loaded = sorted(m for m in WATCHED_MODULES if m in sys.modules)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(
            {"script": script, "args": args, "exit_code": code, "events": events, "watched_modules_loaded": loaded},
            fh,
            indent=1,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
