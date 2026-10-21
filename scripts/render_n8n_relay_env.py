#!/usr/bin/env python3
"""Render the n8n run relay's dedicated EnvironmentFile from the full secrets env. Names only on stdout.

ExecStartPre of config/systemd/user/tradeai-n8n-run-relay.service (B2-D2, 2026-10-09):

    render_n8n_relay_env.py --source %t/tradeai/env --out %t/tradeai/n8n-relay-secrets.env

systemd reads EnvironmentFile= for ExecStart after ExecStartPre has finished, so every (re)start, including
the restart a weekly bearer / HMAC rotation asks for, picks up the values render_env.py just wrote. The out
file is written atomically with mode 0600 and holds only scripts/lib/n8n_relay_env.py RELAY_SECRET_NAMES.
Exit 0 written; 2 refused (source unreadable, a required name missing, or an unsupported value), nothing
written. Never prints a value.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_relay_env import render_relay_env  # noqa: E402

SCHEDULED_ENTRYPOINT = "systemd: ExecStartPre of tradeai-n8n-run-relay.service (every relay start)"
SCHEMA = "N8nRelayEnvRender@v1"


def _runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "tradeai"


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)


def render(source: Path, out: Path) -> dict:
    try:
        source_text = source.read_text(encoding="utf-8")
    except OSError as exc:
        return {"schema": SCHEMA, "ok": False, "reason": "source_unreadable", "error": type(exc).__name__}
    try:
        text, names, missing = render_relay_env(source_text)
    except ValueError as exc:
        return {"schema": SCHEMA, "ok": False, "reason": "unsupported_value", "error": str(exc)}
    if missing:
        return {"schema": SCHEMA, "ok": False, "reason": "required_name_missing", "missing": missing}
    write_private(out, text)
    return {"schema": SCHEMA, "ok": True, "out": str(out), "names": names, "mode": "0600"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=_runtime_dir() / "env")
    parser.add_argument("--out", type=Path, default=_runtime_dir() / "n8n-relay-secrets.env")
    args = parser.parse_args(argv)
    report = render(args.source, args.out)
    print(json.dumps(report, separators=(",", ":")), flush=True)
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
