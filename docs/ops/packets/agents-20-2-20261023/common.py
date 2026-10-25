"""Shared pure package helpers; no broker, credential, endpoint or service operations."""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent


def run(*argv: str, cwd: Path, **kwargs):
    return subprocess.run(list(argv), cwd=cwd, check=True, **kwargs)


def output(*argv: str, cwd: Path) -> str:
    return subprocess.check_output(list(argv), cwd=cwd, text=True).strip()


def metadata():
    return json.loads((HERE / "package.json").read_text())


def verify_digests():
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("invalid manifest path")
        actual = hashlib.sha256((HERE / path).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"package digest mismatch: {name}")


def verify_base(repo: Path, ref="origin/main"):
    data = metadata()
    for path, expected in data["base_digests"].items():
        p = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=repo, capture_output=True)
        actual = hashlib.sha256(p.stdout).hexdigest() if p.returncode == 0 else "ABSENT"
        if actual != expected:
            raise ValueError(f"base drift: {path}; package rebuild/review required")
    return output("git", "rev-parse", ref, cwd=repo)


def export_base(repo: Path, dest: Path):
    raw = subprocess.check_output(["git", "archive", metadata()["base_sha"]], cwd=repo)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        archive.extractall(dest, filter="data")


def apply_proposed(dest: Path):
    for name in ("agents-20.2.0-proposed.patch", "tests-20.2.0.patch"):
        run("git", "apply", "--check", str(HERE / name), cwd=dest)
        run("git", "apply", str(HERE / name), cwd=dest)


def ratify_text(text: str, *, pr: str, sha: str, comment_id: str, comment_at: str):
    if not re.fullmatch(r"[1-9][0-9]*", pr) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("full PR and SHA required")
    if not re.fullmatch(r"[1-9][0-9]*", comment_id):
        raise ValueError("comment id required")
    stamp = datetime.fromisoformat(comment_at.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("comment timestamp must be zoned")
    day = stamp.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    assert "Policy-Version:      20.2.0\n" in text
    assert "Status:              PROPOSED\nEffective-Date:      PENDING\n" in text
    text = text.replace(
        "Status:              PROPOSED\nEffective-Date:      PENDING\n",
        f"Status:              ACTIVE\nEffective-Date:      {day}\n",
        1,
    )
    text = text.replace("**20.2.0 is PROPOSED (MINOR)", "**20.2.0 is ACTIVE (MINOR)", 1)
    token = f"APPROVE_AGENTS_POLICY_20_2_0 {pr} {sha}"
    pending = "Awaiting `APPROVE_AGENTS_POLICY_20_2_0 <pr_number> <head_sha>` (§20)."
    text = text.replace(pending, f"Ratified by the operator: `{token}`, comment {comment_id} at {comment_at} (§20).", 1)
    rows = text.splitlines(keepends=True)
    for i, row in enumerate(rows):
        if row.startswith("| 20.2.0 |"):
            rows[i] = row.replace("| PROPOSED | MINOR |", "| ACTIVE | MINOR |", 1).replace(
                "**PENDING** — awaiting `APPROVE_AGENTS_POLICY_20_2_0 <pr_number> <head_sha>` (§20).",
                f"**ACTIVE** — ratified `{token}` (§20), operator comment {comment_id} at {comment_at}.",
                1,
            )
    return "".join(rows)
