#!/usr/bin/env python3
"""PROPOSED offline PR-index projection. Not an active gate or authority source.

Read committed Git blobs only; never rewrite the checkout, stage, commit, or push.
Use the existing generator/checker for index syntax, path coverage and titles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import types
from pathlib import Path


class ProjectionRefused(ValueError):
    pass


def git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    run = subprocess.run(
        ["git", "-C", str(root), *args], input=data,
        capture_output=True, timeout=60, check=False,
    )
    if run.returncode:
        raise ProjectionRefused("git read failed: " + " ".join(args[:2]))
    return run.stdout


def generator(root: Path, sha: str | None = None):
    path = root / "scripts/report_docs_inventory.py"
    source = git(root, "show", sha + ":scripts/report_docs_inventory.py") if sha else path.read_bytes()
    # Compile directly: importing the checkout file through a source loader could
    # create __pycache__ in it even though this tool promises artifact-only writes.
    mod = types.ModuleType("proposal_inventory")
    mod.__file__ = str(path)
    exec(compile(source, str(path), "exec"), mod.__dict__)
    return mod


def snapshot(root: Path, sha: str, mod) -> tuple[list[dict], str]:
    """Batch read exact tracked markdown blobs, with no filesystem fallback."""
    rows = []
    for raw in git(root, "ls-tree", "-rz", "--full-tree", sha, "--", "docs").split(b"\0"):
        if not raw:
            continue
        meta, path = raw.split(b"\t", 1)
        name = path.decode("utf-8", "strict")
        if not name.endswith(".md"):
            continue
        mode, kind, oid = meta.decode().split()
        if mode != "100644" and mode != "100755":
            raise ProjectionRefused("nonregular markdown: " + name)
        if kind != "blob":
            raise ProjectionRefused("nonblob markdown: " + name)
        rows.append((name, oid))
    if not rows:
        raise ProjectionRefused("no tracked markdown")
    raw = git(root, "cat-file", "--batch", data="".join(oid + "\n" for _, oid in rows).encode())
    pos, inventory, index = 0, [], None
    for name, oid in rows:
        end = raw.index(b"\n", pos)
        header = raw[pos:end].decode().split()
        if len(header) != 3 or header[:2] != [oid, "blob"]:
            raise ProjectionRefused("invalid blob response")
        size = int(header[2])
        blob = raw[end + 1:end + 1 + size]
        pos = end + size + 2
        if len(blob) != size or raw[pos - 1:pos] != b"\n":
            raise ProjectionRefused("truncated blob")
        text = blob.decode("utf-8", "replace")
        if name == "docs/INDEX.md":
            index = text
            continue
        inventory.append({
            "path": name, "filename": name.rsplit("/", 1)[-1], "ext": ".md",
            "title": mod.extract_title(text, name.rsplit("/", 1)[-1]),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "header_status": mod.HEADER_OK if mod.has_structured_header(text) else mod.HEADER_MISSING,
        })
    if pos != len(raw) or index is None:
        raise ProjectionRefused("missing index or unexpected blob bytes")
    return inventory, index


def build_projection(root: Path, base: str, head: str) -> tuple[str, dict]:
    root = root.resolve()
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)):
        raise ProjectionRefused("full base/head SHA required")
    if git(root, "rev-parse", "HEAD").decode().strip() != head:
        raise ProjectionRefused("head identity mismatch")
    git(root, "merge-base", "--is-ancestor", base, head)
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ProjectionRefused("dirty tracked checkout")
    if git(root, "ls-files", "--others", "--exclude-standard", "--", "docs"):
        raise ProjectionRefused("untracked docs")
    if git(root, "diff", "--name-only", base, head, "--", "docs/INDEX.md"):
        raise ProjectionRefused("PR changed committed index; batch flow only")
    mod = generator(root, head)
    baseline, index = snapshot(root, base, mod)
    problems, _ = mod.index_problems(index, baseline)
    if problems:
        raise ProjectionRefused("invalid base index: " + "; ".join(problems))
    inventory, _ = snapshot(root, head, mod)
    candidate = mod.render_index_md(inventory, {})
    problems, ordered = mod.index_problems(candidate, inventory)
    if problems or not ordered:
        raise ProjectionRefused("generated projection invalid")
    receipt = {
        "schema": "ProposedDocsIndexProjection@v1", "rollout": "PROPOSED",
        "base_sha": base, "head_sha": head,
        "head_tree": git(root, "rev-parse", head + "^{tree}").decode().strip(),
        "index_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
        "markdown_total": len(inventory),
        "missing_header": sum(e["header_status"] == mod.HEADER_MISSING for e in inventory),
        "source_digest": hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest(),
        "committed_index_current": not mod.index_problems(index, inventory)[0],
        "authority": "OFFLINE_ARTIFACT_ONLY",
    }
    if git(root, "rev-parse", "HEAD").decode().strip() != head:
        raise ProjectionRefused("head identity changed while projecting")
    return candidate, receipt


def validate_projection(root: Path, receipt: dict, candidate: str) -> None:
    """Recompute against exact current HEAD, reject a stale/tampered receipt or body."""
    expected, evidence = build_projection(root, receipt["base_sha"], receipt["head_sha"])
    if evidence != receipt or expected != candidate:
        raise ProjectionRefused("projection identity/content mismatch")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    try:
        candidate, receipt = build_projection(args.root, args.base, args.head)
        out = args.out.resolve()
        if out == args.root.resolve() or args.root.resolve() in out.parents:
            raise ProjectionRefused("output must be outside checkout")
        out.mkdir(parents=True, exist_ok=False)
        (out / "INDEX.md").write_text(candidate)
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (ProjectionRefused, OSError, ValueError) as exc:
        print("REFUSED: " + str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
