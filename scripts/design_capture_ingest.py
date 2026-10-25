#!/usr/bin/env python3
"""Turn a design-capture manifest into committed fingerprints (design/README.md, AGENTS.md §28.13).

    python3 scripts/design_capture_ingest.py MANIFEST [--store DIR] [--dry-run]

For every captured page that rendered without a sign-in refusal it writes
design/pages/<page>/versions/<version>/status.json (state BASELINE, no approval; private_assets.files with role
"capture", the path relative to the page's private folder, sha256, bytes, width and tab), adds the version to
design/registry.json (``baseline_version``) and a line to the page's PAGE.md and CHANGELOG.md.

A page missing any manifest width (the run aborted mid-page) is ``incomplete`` and is skipped the same way.
A page whose API calls answered 401/403 is ``needs_reader``: it gets NO version folder (its screenshots show a refusal,
not the page) and registry ``baseline_pending: "needs_reader"`` until the read-only agent reader identity can capture
it. With --store, every fingerprint is re-hashed from the private store first. Only text and hashes are written; image
bytes never enter the repository (the repo is public).

AUTHORITY: READ_ONLY_ADVISORY on the private store; writes design/ text files only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import design_pages as dp  # noqa: E402

WIDTHS = (1440, 412, 390)
TAB_KEY = re.compile(r"^(default|t\d{2})$")


class IngestError(ValueError):
    pass


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_status(page: dict, manifest: dict) -> dict:
    version = manifest["version"]
    files = []
    for shot in page["shots"]:
        rel = shot["path"]
        if not rel.startswith(f"{version}/capture/") or not dp._safe_rel(rel) or not rel.endswith(".png"):
            raise IngestError(f"{page['page']}: unexpected capture path {rel!r}")
        if not dp.SHA256.fullmatch(str(shot.get("sha256", ""))) or shot.get("width") not in WIDTHS:
            raise IngestError(f"{page['page']}: {rel}: bad sha256 or width")
        tab = str(shot.get("tab") or "")
        if not TAB_KEY.fullmatch(tab) or not re.fullmatch(rf"{re.escape(version)}/capture/{re.escape(page['page'])}-{tab}-{shot['width']}\.png", rel):
            # Labels can carry tickers and counts; only the index key reaches the public repo.
            raise IngestError(f"{page['page']}: capture must be keyed default/tNN, not a label: {rel!r}")
        files.append({"path": rel, "sha256": shot["sha256"], "bytes": int(shot["bytes"]), "role": "capture",
                      "width": shot["width"], "tab": tab})
    files.sort(key=lambda f: f["path"])
    day = str(manifest.get("started_at") or "")[:10]
    mem = [m.get("bytes") for m in page.get("memory") or [] if isinstance(m.get("bytes"), int)]
    return {
        "schema": "DesignVersionStatus@v1",
        "page": page["page"],
        "version": version,
        "state": "BASELINE",
        "title": f"As built {day}: read-only live capture at {', '.join(str(w) for w in manifest['widths'])}",
        "created": day,
        "approval": None,
        "spec": None,
        "capture": {
            "base": "production (loopback)" if re.search(r"//(127\.0\.0\.1|localhost):7777", manifest.get("base", "")) else "non-production",
            "started_at": manifest.get("started_at"),
            "finished_at": manifest.get("finished_at"),
            "widths": manifest["widths"],
            "tab_count": len(page.get("tabs") or []),
            "tab_labels": "private: capture/index.json in the page's private folder",
            "reader_identity": manifest.get("reader_identity", "none"),
            "max_server_memory_bytes": max(mem) if mem else None,
            "shell_refusals": sorted(page.get("shell_refusals") or []),
            "blocked_writes": len(page.get("blocked_writes") or []),
            "errors": len(page.get("errors") or []),
        },
        "private_assets": {
            "root": f"persistent-state/data/design/pages/{page['page']}",
            "note": "Private, never committed: live screenshots show real holdings. Paths are relative to root; sha256 binds each file.",
            "files": files,
        },
        "fingerprint": dp.version_fingerprint(files),
        "prs": [],
        "verified": None,
        "history": [{"state": "BASELINE", "at": day, "by": "agent:design-capture", "note": "v000 as built: read-only capture, GET only"}],
    }


def _replace_line(lines: list[str], prefix: str, new: str, after: str | None = None) -> list[str]:
    out = [ln for ln in lines if not ln.startswith(prefix)]
    if after is not None:
        idx = next((i for i, ln in enumerate(out) if ln.startswith(after)), None)
        if idx is not None:
            out.insert(idx + 1, new)
            return out
    out.append(new)
    return out


def ingest(manifest: dict, *, root: Path = ROOT, store: Path | None = None, dry_run: bool = False) -> dict:
    if manifest.get("schema") != "DesignCaptureManifest@v1" or not dp.VERSION.fullmatch(str(manifest.get("version"))):
        raise IngestError("not a DesignCaptureManifest@v1")
    version = manifest["version"]
    reg_path = dp.design_dir(root) / "registry.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    pages = {p["id"]: p for p in reg["pages"]}
    report = {"baseline": [], "needs_reader": [], "empty": [], "shots": 0}
    writes: dict[Path, str] = {}
    for page in manifest.get("pages") or []:
        pid = page.get("page")
        if pid not in pages:
            raise IngestError(f"unknown page {pid!r}")
        reg_page = pages[pid]
        if page.get("needs_reader"):
            report["needs_reader"].append(pid)
            reg_page["baseline_pending"] = "needs_reader"
            continue
        if not page.get("shots"):
            report["empty"].append(pid)
            continue
        widths = {s.get("width") for s in page["shots"] if s.get("tab") == "default"}
        if not set(manifest["widths"]) <= widths:
            # A run that aborted mid-page (memory gate) leaves a partial page: never a baseline.
            report.setdefault("incomplete", []).append(pid)
            reg_page["baseline_pending"] = "incomplete capture"
            continue
        status = build_status(page, manifest)
        if store:
            for f in status["private_assets"]["files"]:
                p = Path(store) / "pages" / pid / f["path"]
                if not p.is_file() or _sha(p) != f["sha256"]:
                    raise IngestError(f"{pid}: {f['path']} missing or changed in the private store")
        pdir = dp.design_dir(root) / "pages" / pid
        writes[pdir / "versions" / version / "status.json"] = json.dumps(status, indent=2, ensure_ascii=False) + "\n"
        reg_page.pop("baseline_pending", None)
        reg_page["versions"] = sorted([v for v in reg_page.get("versions") or [] if v.get("version") != version] + [
            {"version": version, "state": "BASELINE", "captured_at": status["created"], "fingerprint": status["fingerprint"]}],
            key=lambda v: v["version"])
        reg_page["baseline_version"] = version
        n, day, widths = len(status["private_assets"]["files"]), status["created"], ", ".join(str(w) for w in manifest["widths"])
        page_md = (pdir / "PAGE.md").read_text(encoding="utf-8").splitlines()
        page_md = _replace_line(page_md, "- **Baseline (as built) version:**",
                                f"- **Baseline (as built) version:** {version} — captured {day}, {n} private screenshots",
                                after="- **Approved version:**")
        page_md = _replace_line(page_md, f"| {version} |", f"| {version} | BASELINE | — | as built {day}: {n} screenshots at {widths} (private) |",
                                after="|---|---|---|---|")
        writes[pdir / "PAGE.md"] = "\n".join(page_md) + "\n"
        cl = [ln for ln in (pdir / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if ln != "- (no approved version yet)"]
        cl = _replace_line(cl, f"- {day} · {version} ·", f"- {day} · {version} · BASELINE · as built: read-only live capture, {n} screenshots at {widths} · no approval (a record)")
        writes[pdir / "CHANGELOG.md"] = "\n".join(cl) + "\n"
        report["baseline"].append(pid)
        report["shots"] += n
    writes[reg_path] = json.dumps(reg, indent=2, ensure_ascii=False) + "\n"
    for blob in writes.values():
        if "\x89PNG" in blob or "base64," in blob:
            raise IngestError("refusing to write image data into the repository")
    if not dry_run:
        for path, text in writes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    report["files_written"] = 0 if dry_run else len(writes)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--store", type=Path, help="private design store: re-hash every capture before ingesting")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        report = ingest(json.loads(args.manifest.read_text(encoding="utf-8")), root=args.root, store=args.store, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        print(f"design_capture_ingest: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=1))
    errors = dp.validate(args.root) if not args.dry_run else []
    for e in errors:
        print(e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
