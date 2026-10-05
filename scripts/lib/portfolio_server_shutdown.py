"""Record why portfolio-server stopped.

The live unit is outside the repo:
``~/.config/systemd/user/portfolio-server.service``.
``StandardOutput`` and ``StandardError`` append to ``logs/portfolio_server.log``,
so a print is not a journal line. ``syslog`` is what journald already captures
for this process. The in-repo unit ``config/systemd/portfolio-server.service``
has the same append redirect; this module does not install a drop-in.

SIGKILL (MemoryMax) cannot be caught. SIGTERM and SIGINT can, and the exit
code is ``128 + signal``.
"""

from __future__ import annotations

import signal
import sys


def shutdown_record(*, signum: int | None, exit_code: int | None) -> str:
    """One line: signal name, signal number, and process exit code."""
    if signum is None:
        sig = "none"
    else:
        number = int(signum)
        try:
            name = signal.Signals(number).name
        except ValueError:
            name = f"SIG{number}"
        sig = f"{name}({number})"
    code = "none" if exit_code is None else str(int(exit_code))
    return f"portfolio-server shutdown signal={sig} exit_code={code}"


def log_shutdown(
    signum: int | None,
    exit_code: int | None,
    *,
    sink=None,
    syslog_fn=None,
) -> str:
    """Write the shutdown record to stderr and to syslog (the journal)."""
    line = shutdown_record(signum=signum, exit_code=exit_code)
    print(line, file=sink if sink is not None else sys.stderr, flush=True)
    emit = syslog_fn if syslog_fn is not None else _syslog_warn
    try:
        emit(line)
    except Exception:
        pass
    return line


def _syslog_warn(line: str) -> None:
    import syslog

    syslog.syslog(syslog.LOG_WARNING, line)


def install_shutdown_logging(log_fn=None):
    """Catch SIGTERM and SIGINT, log the exit, then raise SystemExit(128+sig)."""
    emit = log_fn or log_shutdown

    def _handler(signum, _frame):
        code = 128 + int(signum)
        emit(signum, code)
        if signum == signal.SIGINT:
            print("\nServer stopped.", flush=True)
        raise SystemExit(code)

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
    return _handler
