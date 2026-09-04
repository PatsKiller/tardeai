#!/usr/bin/env python3
"""Phase 9: package the campaign's evidence, then prove the package.

Building an archive is easy. The part that matters is the part after: reopen it, verify
every hash it claims, and prove the patch it carries really is the base-to-final diff.
An archive nobody reopened is a claim, not evidence.

    python3 scripts/package_campaign_evidence.py \
        --campaign-dir /home/johnclaw/trade-ai-campaigns/cc-whole-site-residual-v1-20260903 \
        --base <base_sha> --final <final_sha> --label v7-reconciled
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "CampaignEvidencePackage@v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True).stdout


def build(campaign: Path, base: str, final: str, label: str, extra: list[Path]) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stage = Path(tempfile.mkdtemp(prefix="cc-evidence-")) / f"{label}-{stamp}"
    for sub in ("evidence", "reports", "git", "logs"):
        (stage / sub).mkdir(parents=True, exist_ok=True)

    # Evidence produced by the campaign's own tooling.
    src = ROOT / "evidence" / "whole_site"
    if src.is_dir():
        shutil.copytree(src, stage / "evidence" / "whole_site", dirs_exist_ok=True)

    # Written reports.
    for d in sorted((campaign / "outputs").glob("implementation-v*")):
        for md in d.glob("*.md"):
            shutil.copy2(md, stage / "reports" / f"{d.name}__{md.name}")

    # Git identity: the diff, the ledger, the lineage.
    (stage / "git" / "patch.diff").write_text(git("diff", f"{base}..{final}"))
    (stage / "git" / "changed_files.txt").write_text(git("diff", "--name-status", f"{base}..{final}"))
    (stage / "git" / "lineage.txt").write_text(git("log", "--format=%H %P %s", f"{base}..{final}"))
    (stage / "git" / "commit_info.txt").write_text(git("log", "-1", "--format=%H%n%P%n%an%n%cd%n%s", final))
    (stage / "git" / "base_final.txt").write_text(f"base={base}\nfinal={final}\n")

    for p in extra:
        if p.is_file():
            shutil.copy2(p, stage / "logs" / p.name)

    # Hash every artifact.
    rows: dict[str, str] = {}
    for p in sorted(stage.rglob("*")):
        if p.is_file() and p.name != "ARTIFACT_HASHES.json":
            rows[str(p.relative_to(stage))] = sha256_file(p)
    (stage / "ARTIFACT_HASHES.json").write_text(
        json.dumps({"schema": SCHEMA, "artifact_count": len(rows), "artifact_hashes": rows}, indent=2, sort_keys=True)
        + "\n"
    )

    exports = campaign / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    archive = exports / f"{label}-{stamp}-evidence.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(stage, arcname=stage.name, filter=_deterministic)
    digest = sha256_file(archive)
    (exports / f"{archive.name}.sha256").write_text(f"{digest}  {archive.name}\n")
    shutil.rmtree(stage.parent, ignore_errors=True)
    return {"archive": str(archive), "sha256": digest, "artifact_count": len(rows), "stamp": stamp}


def _deterministic(ti: tarfile.TarInfo) -> tarfile.TarInfo:
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    ti.mtime = 1788480000
    return ti


def verify(archive: Path, base: str, final: str) -> dict[str, Any]:
    """Reopen the archive and check every claim it makes about itself."""
    out: dict[str, Any] = {"archive": str(archive), "sha256": sha256_file(archive)}
    area = Path(tempfile.mkdtemp(prefix="cc-evidence-verify-"))
    try:
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(area, filter="data")
        root = next(area.iterdir())
        manifest = json.loads((root / "ARTIFACT_HASHES.json").read_text())
        claimed = manifest["artifact_hashes"]

        mismatched, missing = [], []
        for rel, want in claimed.items():
            p = root / rel
            if not p.is_file():
                missing.append(rel)
            elif sha256_file(p) != want:
                mismatched.append(rel)
        present = {
            str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p.name != "ARTIFACT_HASHES.json"
        }
        unlisted = sorted(present - set(claimed))

        # The patch must BE the base-to-final diff, not merely resemble one.
        packaged = (root / "git" / "patch.diff").read_text()
        live = git("diff", f"{base}..{final}")
        out["patch_matches_git"] = packaged == live
        out["patch_bytes"] = len(packaged)

        out.update(
            {
                "artifact_count_claimed": manifest["artifact_count"],
                "artifact_count_found": len(present),
                "mismatched": mismatched,
                "missing": missing,
                "unlisted": unlisted,
                "all_hashes_verified": not (mismatched or missing or unlisted),
            }
        )
        out["ok"] = bool(out["all_hashes_verified"] and out["patch_matches_git"])
    finally:
        shutil.rmtree(area, ignore_errors=True)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campaign-dir", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--final", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--include", nargs="*", default=[])
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    campaign = Path(args.campaign_dir)
    built = build(campaign, args.base, args.final, args.label, [Path(p) for p in args.include])
    print(f"archive : {built['archive']}")
    print(f"sha256  : {built['sha256']}")
    print(f"artifacts: {built['artifact_count']}")

    checked = verify(Path(built["archive"]), args.base, args.final)
    print(
        f"reopened: hashes verified={checked['all_hashes_verified']} patch matches git={checked['patch_matches_git']}"
    )
    if not checked["ok"]:
        for k in ("mismatched", "missing", "unlisted"):
            if checked.get(k):
                print(f"  {k}: {checked[k][:5]}", file=sys.stderr)

    receipt = {"schema": SCHEMA, "generated_at_utc": _now(), "build": built, "verification": checked}
    if args.out:
        Path(args.out).write_text(json.dumps(receipt, indent=1, default=str) + "\n")
        print(f"receipt : {args.out}")
    return 0 if checked["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
