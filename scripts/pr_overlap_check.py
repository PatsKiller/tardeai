#!/usr/bin/env python3
"""pr_overlap_check.py — before building, list the open PRs that already touch your files or topic. Read-only.

Why (2026-10-21): #1906 re-did the Schwab reauth step-up fix that #1836 already carried, because nobody looked at
the 59 open PRs first. Run this before writing code; it becomes mandatory by a later AGENTS amendment
(docs/ops/PR_HYGIENE.md).

    python3 scripts/pr_overlap_check.py --files scripts/lib/cc_auth.py scripts/api_v2.py
    python3 scripts/pr_overlap_check.py --keywords "step-up" reauth
    python3 scripts/pr_overlap_check.py --files config/lane_registry.json --keywords hermes --json

A PR matches a FILE when it changes that path (or a path under it, when the argument ends with "/"). It matches a
KEYWORD (case-insensitive) in its title, body, head branch, a changed path, or a changed line of its patch. Output:
one block per matching PR with what matched. Uses scripts/pr_hygiene_audit.py's read-only gh wrapper (``gh pr
list`` / GET-only ``gh api``); it never comments, labels, merges or closes.

Exit 0 = the check ran (with or without matches); 1 = GitHub could not be read; 2 = usage.
``--fail-on-overlap`` exits 3 when anything matched (for scripted pre-build checks).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pr_hygiene_audit as PHA  # noqa: E402

PATCH_LINE_MAX = 160


def _file_hits(changed: Sequence[str], files: Sequence[str]) -> list[str]:
    hits = []
    for want in files:
        w = want.strip().removeprefix("./")
        if not w:
            continue
        for path in changed:
            if path == w or (w.endswith("/") and path.startswith(w)):
                hits.append(path)
    return sorted(set(hits))


def _keyword_hits(pr: Mapping[str, Any], patches: Mapping[str, str], keywords: Sequence[str]) -> list[dict[str, str]]:
    hits = []
    for kw in keywords:
        k = kw.lower().strip()
        if not k:
            continue
        where = None
        if k in str(pr.get("title") or "").lower():
            where = "title"
        elif k in str(pr.get("head") or "").lower():
            where = "branch"
        elif k in str(pr.get("body") or "").lower():
            where = "body"
        else:
            path = next((p for p in patches if k in p.lower()), None)
            if path:
                where = f"path {path}"
            else:
                for p, patch in patches.items():
                    line = next((ln for ln in (patch or "").splitlines()
                                 if ln[:1] in "+-" and not ln.startswith(("+++", "---")) and k in ln.lower()), None)
                    if line:
                        where = f"diff {p}: {line[:PATCH_LINE_MAX]}"
                        break
        if where:
            hits.append({"keyword": kw, "where": where})
    return hits


def check(gh: "PHA.Gh", files: Sequence[str], keywords: Sequence[str]) -> list[dict[str, Any]]:
    prs, _source = PHA.list_open_prs(gh)
    out = []
    for pr in sorted(prs, key=lambda p: p["number"]):
        rows = gh.api(f"repos/{gh.slug}/pulls/{pr['number']}/files?per_page=100", paginate=True) or []
        patches = {r.get("filename"): r.get("patch") or "" for r in rows if isinstance(r, dict) and r.get("filename")}
        fh = _file_hits(list(patches), files)
        kh = _keyword_hits(pr, patches, keywords)
        if fh or kh:
            out.append({"number": pr["number"], "title": pr["title"][:160], "url": pr["url"], "head": pr["head"],
                        "draft": pr["draft"], "updated_at": pr["updated_at"],
                        "holds": PHA.hold_markers(pr["title"], pr["body"], pr.get("labels") or []),
                        "files": fh, "keywords": kh})
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], allow_abbrev=False)
    ap.add_argument("--files", nargs="*", default=[], help="repo-relative paths (a trailing / matches a directory)")
    ap.add_argument("--keywords", nargs="*", default=[], help="case-insensitive words or phrases")
    ap.add_argument("--slug", help="owner/name (default: TRADEAI_PR_HYGIENE_SLUG, else origin's URL)")
    ap.add_argument("--repo", help="local clone used only to read origin's URL")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-overlap", action="store_true", help="exit 3 when any open PR matched")
    a = ap.parse_args(argv)
    if not a.files and not a.keywords:
        ap.error("give --files and/or --keywords")
    slug = PHA.resolve_slug(a.slug, PHA.Git(PHA.resolve_repo(a.repo)))
    if not slug:
        print("[pr-overlap] no GitHub slug (pass --slug or run inside a clone)", file=sys.stderr)
        return 2
    try:
        hits = check(PHA.Gh(slug), a.files, a.keywords)
    except PHA.AuditError as exc:
        print(f"[pr-overlap] GitHub unreadable: {exc}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(hits, indent=1))
    elif not hits:
        print("[pr-overlap] no open PR touches these files or keywords")
    else:
        print(f"[pr-overlap] {len(hits)} open PR(s) overlap — read them before building:")
        for h in hits:
            flags = " ".join(x for x in (("DRAFT" if h["draft"] else ""), "/".join(h["holds"])) if x)
            print(f"  #{h['number']} {h['title']}  {flags}".rstrip())
            print(f"     {h['url']}  (head {h['head']}, updated {h['updated_at']})")
            for f in h["files"]:
                print(f"     file: {f}")
            for k in h["keywords"]:
                print(f"     keyword {k['keyword']!r}: {k['where']}")
    return 3 if (hits and a.fail_on_overlap) else 0


if __name__ == "__main__":
    raise SystemExit(main())
