#!/usr/bin/env python3
"""nightly_cutover_cron_edit.py — the NARROW host capability that edits the crontab for the nightly cutover controller.

It does exactly two things and nothing else:

  retire    comment the planned lines of ONE lane: each line at --index must still be byte-identical to the planned
            `before` text and uncommented; it becomes `# RETIRED <date> n8n-cutover <lane> <before>` (the _cutover.py
            tag, so `_cutover.py rollback --lane` and lane_registry.n8n_cutover_tag still read it). Never deletes.
  rollback  uncomment exactly the lines this lane's rollback receipt names (each must still read `<after>`).

Every call: exclusive non-blocking flock on the controller lock (default /tmp/n8n_cutover.lock, shared with
_cutover.py), `crontab -l`, compare the crontab's sha256 with --expect-sha (the hash the controller evaluated), refuse
any difference, write a 0600 backup owned by this user, install with `crontab -`, read back and compare byte-exact,
check ownership (euid not root, backup uid = euid). Only the named indices change; every other byte is preserved.
Exit 0 = applied (JSON on stdout); 3 = lock/hash/precondition refusal (nothing written); 4 = install or read-back
failure (the backup path is in the JSON). Input is a JSON request on --request (written by the controller).

n8n never calls this; the controller (scripts/nightly_cutover_controller.py) is its only caller, and only in apply
mode under an active `cron` grant naming the controller.

AUTHORITY: crontab comment/uncomment of planned lines only. No broker, no secret, no send, no systemd.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

NO_CONSUMER_REASON = "Host capability of the nightly cutover controller; invoked only by it (subprocess)."
SCHEMA = "NightlyCutoverCronEdit@v1"
TAG = "# RETIRED {date} n8n-cutover {lane} "


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _crontab_cmd() -> str:
    return os.environ.get("CRONTAB_CMD", "crontab")


def read_crontab() -> str:
    p = subprocess.run([_crontab_cmd(), "-l"], capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError(f"crontab -l failed: {p.stderr.strip()[:160]}")
    return p.stdout


def plan_text(text: str, req: dict[str, Any]) -> tuple[str, list[str]]:
    """The candidate crontab and problems. Pure. Splits on '\\n' only and keeps the trailing-newline shape."""
    lines = text.split("\n")
    problems: list[str] = []
    op, lane = req.get("op"), str(req.get("lane_id") or "")
    if not lane or any(c.isspace() for c in lane):
        return text, ["bad lane_id"]
    edits = req.get("edits") or []
    if not edits:
        return text, ["no edits"]
    seen = set()
    for e in edits:
        i = e.get("index")
        if not isinstance(i, int) or i < 0 or i >= len(lines) or i in seen:
            problems.append(f"bad index {i}")
            continue
        seen.add(i)
        cur = lines[i]
        if op == "retire":
            before = e.get("before")
            after = TAG.format(date=req.get("date"), lane=lane) + str(before)
            if cur != before:
                problems.append(f"L{i + 1}: line changed since the plan")
            elif cur.lstrip().startswith("#"):
                problems.append(f"L{i + 1}: already commented")
            elif e.get("after") not in (None, after):
                problems.append(f"L{i + 1}: planned after-text is not the pure retire tag")
            else:
                lines[i] = after
        elif op == "rollback":
            after, before = e.get("after"), e.get("before")
            if cur != after or not str(after).startswith("# RETIRED ") or f" n8n-cutover {lane} " not in str(after) \
                    or not str(after).endswith(str(before)):
                problems.append(f"L{i + 1}: not this lane's retire tag (changed since the cutover)")
            else:
                lines[i] = before
        else:
            return text, [f"bad op {op!r}"]
    return "\n".join(lines), problems


def run(req: dict[str, Any], *, lock_path: str, backup_dir: Path) -> tuple[int, dict[str, Any]]:
    out: dict[str, Any] = {"schema": SCHEMA, "op": req.get("op"), "lane_id": req.get("lane_id"),
                           "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "applied": False,
                           "backup": None, "read_back_ok": None, "ownership_ok": None, "problems": []}
    if os.geteuid() == 0:
        out["problems"].append("refused: running as root would edit root's crontab")
        return 3, out
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError as exc:
        out["problems"].append(f"lock_unavailable: {exc}")
        return 3, out
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            out["problems"].append("lock_held: another crontab act holds " + lock_path)
            return 3, out
        try:
            text = read_crontab()
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            out["problems"].append(str(exc))
            return 3, out
        out["sha_before"] = _sha(text)
        if out["sha_before"] != req.get("expect_sha"):
            out["problems"].append("crontab_hash_changed: the crontab differs from the one evaluated; nothing written")
            return 3, out
        cand, probs = plan_text(text, req)
        if probs:
            out["problems"].extend(probs)
            return 3, out
        changed = sum(1 for a, b in zip(text.split("\n"), cand.split("\n")) if a != b)
        if changed != len(req.get("edits") or []) or len(text.split("\n")) != len(cand.split("\n")):
            out["problems"].append("candidate touches lines outside the request")
            return 3, out
        backup_dir.mkdir(parents=True, exist_ok=True)
        bk = backup_dir / f"crontab-{time.strftime('%Y%m%dT%H%M%S')}-nightly-{req.get('op')}-{req.get('lane_id')}.txt"
        fdb = os.open(bk, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        with os.fdopen(fdb, "w", encoding="utf-8") as fh:
            fh.write(text)
        out["backup"] = str(bk)
        st = bk.stat()
        if st.st_uid != os.geteuid() or (st.st_mode & 0o077):
            out["problems"].append("backup ownership/mode wrong")
            return 4, out
        p = subprocess.run([_crontab_cmd(), "-"], input=cand, capture_output=True, text=True, timeout=30)
        if p.returncode != 0:
            out["problems"].append(f"crontab - rejected: {p.stderr.strip()[:200]}")
            return 4, out
        out["applied"] = True
        try:
            back = read_crontab()
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            out["problems"].append(f"read-back failed: {exc}")
            out["read_back_ok"] = False
            return 4, out
        out["read_back_ok"] = back == cand
        out["ownership_ok"] = True       # `crontab -l` as this (non-root) euid returned what we installed
        out["sha_after"] = _sha(back)
        if not out["read_back_ok"]:
            out["problems"].append("read-back differs from the installed candidate")
            return 4, out
        return 0, out
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--request", required=True, help="JSON request {op, lane_id, date, expect_sha, edits[]}")
    ap.add_argument("--lock", default=os.environ.get("N8N_CUTOVER_LOCK", "/tmp/n8n_cutover.lock"))
    ap.add_argument("--backup-dir", default=str(Path.home() / ".local/state/tradeai/backups"))
    a = ap.parse_args(argv)
    try:
        req = json.loads(Path(a.request).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"schema": SCHEMA, "applied": False, "problems": [f"bad request: {exc}"]}))
        return 3
    rc, out = run(req, lock_path=a.lock, backup_dir=Path(a.backup_dir))
    print(json.dumps(out, sort_keys=True))
    return rc


if __name__ == "__main__":
    sys.exit(main())
