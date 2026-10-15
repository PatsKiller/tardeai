#!/usr/bin/env python3
"""Remove (or restore) one lane on the relay live-lane list file, ~/.config/tradeai/n8n-live-lanes.env.

Packet maturity-remeasure-relay-live-removal-20261015 (CANARY_DOUBLE_EFFECT_AUDIT.md 2026-10-14, finding 1). The
file holds lane names only (no secret; operator ruling 2026-10-13), in one line
``TRADEAI_N8N_RELAY_LIVE_LANES=<lane> <lane> ...``, read as an EnvironmentFile by tradeai-n8n-run-relay and
tradeai-n8n-coordination-gateway (scripts/lib/n8n_due.parse_relay_live_lanes: whitespace-separated).

    edit_live_lanes.py --file F --remove maturity-remeasure            # dry run: prints before/after, writes nothing
    edit_live_lanes.py --file F --remove maturity-remeasure --apply    # atomic rewrite (tmp + rename, mode kept)

Refuses (exit 3) unless the file has exactly one TRADEAI_N8N_RELAY_LIVE_LANES= line and the lane is on it once.
Every other line and every other lane is kept in order. AUTHORITY: operator-run config write. No send, no broker.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

VAR = "TRADEAI_N8N_RELAY_LIVE_LANES"
LINE_RE = re.compile(rf"^{VAR}=(.*)$")
LANE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


class EditRefused(ValueError):
    pass


def lanes_of(text: str) -> list[str]:
    hits = [m for m in (LINE_RE.match(line) for line in text.splitlines()) if m]
    if len(hits) != 1:
        raise EditRefused(f"expected exactly one {VAR}= line, found {len(hits)}")
    value = hits[0].group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.split()


def remove_lane(text: str, lane: str) -> str:
    """``text`` with ``lane`` dropped from the live-lane line; the line keeps every other lane in order."""
    if not LANE_RE.fullmatch(lane):
        raise EditRefused(f"bad lane id {lane!r}")
    lanes = lanes_of(text)
    if lanes.count(lane) != 1:
        raise EditRefused(f"{lane} appears {lanes.count(lane)} times on the live list (expected 1)")
    kept = [x for x in lanes if x != lane]
    out = []
    for line in text.splitlines(keepends=True):
        if LINE_RE.match(line.rstrip("\r\n")):
            eol = line[len(line.rstrip("\r\n")) :]
            line = f"{VAR}={' '.join(kept)}{eol}"
        out.append(line)
    new = "".join(out)
    assert lanes_of(new) == kept
    return new


def add_lane(text: str, lane: str) -> str:
    """Rollback helper: ``lane`` appended to the live-lane line (refuses if already present)."""
    if not LANE_RE.fullmatch(lane):
        raise EditRefused(f"bad lane id {lane!r}")
    lanes = lanes_of(text)
    if lane in lanes:
        raise EditRefused(f"{lane} is already on the live list")
    out = []
    for line in text.splitlines(keepends=True):
        if LINE_RE.match(line.rstrip("\r\n")):
            eol = line[len(line.rstrip("\r\n")) :]
            line = f"{VAR}={' '.join(lanes + [lane])}{eol}"
        out.append(line)
    return "".join(out)


def atomic_write(path: Path, text: str) -> None:
    mode = path.stat().st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--remove", metavar="LANE")
    g.add_argument("--add", metavar="LANE", help="rollback: put LANE back on the list")
    ap.add_argument("--apply", action="store_true", help="write the change (default: dry run)")
    a = ap.parse_args(argv)
    path = Path(a.file).expanduser()
    text = path.read_text(encoding="utf-8")
    try:
        new = remove_lane(text, a.remove) if a.remove else add_lane(text, a.add)
    except EditRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    print(f"before ({len(lanes_of(text))}): {' '.join(lanes_of(text))}")
    print(f"after  ({len(lanes_of(new))}): {' '.join(lanes_of(new))}")
    if not a.apply:
        print("dry run: nothing written (add --apply)")
        return 0
    atomic_write(path, new)
    print(f"written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
