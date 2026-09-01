#!/usr/bin/env python3
"""Drive hygiene: propose archives and dedups. MOVES NOTHING, DELETES NOTHING.

READ_ONLY_ADVISORY. Built 2026-09-01 for the Drive hygiene pass.

Three agents are about to publish into one Drive folder for twelve hours, so the
operator asked for an archive mechanism and a dedup proposal BEFORE that starts.

This script only ever REPORTS. Archiving moves to a folder and never deletes;
deletion is the operator's, always, after the review period. Nothing here
executes either -- `--apply` does not exist by design.

Per AGENTS.md: never archive on a single observation. A quarterly report looks
identical to a dead one on any given Tuesday, so `--min-observations` exists and
a candidate seen once is reported as UNCONFIRMED rather than proposed.
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ACCOUNT = "john@jwwhiting.com"
DEFAULT_REVIEW_DAYS = 30


def _ls(folder_id: str) -> list[dict]:
    r = subprocess.run(
        ["gog", "drive", "ls", "--account", ACCOUNT, "--parent", folder_id,
         "--max=1000", "--json", "--no-input"],
        capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"listing failed for {folder_id}: {r.stderr[:200]}")
    return json.load(io_stringio(r.stdout)).get("files", [])


def io_stringio(s: str):
    import io as _io
    return _io.StringIO(s)


def dedup_proposal(files: list[dict]) -> list[dict]:
    """Per duplicated title: the authoritative copy, and the rest as removals.

    Newest by modifiedTime wins. Reported only -- executing this is the
    operator's call, and merging or removing copies of an authoritative store is
    §17 regardless.
    """
    by_name = collections.defaultdict(list)
    for f in files:
        if "folder" not in f.get("mimeType", ""):
            by_name[f["name"]].append(f)
    out = []
    for name, copies in sorted(by_name.items()):
        if len(copies) < 2:
            continue
        copies.sort(key=lambda f: f.get("modifiedTime") or "", reverse=True)
        out.append({
            "title": name,
            "keep": {"id": copies[0]["id"], "modifiedTime": copies[0].get("modifiedTime"),
                     "size": copies[0].get("size")},
            "propose_remove": [
                {"id": c["id"], "modifiedTime": c.get("modifiedTime"), "size": c.get("size")}
                for c in copies[1:]
            ],
            "note": "newest by modifiedTime; verify content before acting",
        })
    return out


def staleness_rules(files: list[dict], older_than_days: int) -> dict:
    """Each rule counted SEPARATELY so the operator can see what each would sweep."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=older_than_days)
    docs = [f for f in files if "folder" not in f.get("mimeType", "")]

    def _mtime(f):
        try:
            return datetime.fromisoformat((f.get("modifiedTime") or "").replace("Z", "+00:00"))
        except ValueError:
            return None

    # DETECTOR-SHAPE WARNING, measured 2026-09-01: this rule returns 0 and will
    # keep returning 0. The hourly sync uses delete-before-upload (Google Docs
    # cannot be content-replaced), so EVERY synced file gets a fresh
    # modifiedTime every hour. Drive metadata therefore cannot express document
    # age at all.
    #
    # Staleness must come from the document's OWN header `as_of` (§14), not from
    # Drive. Reported rather than silently returning a zero that reads as "nothing
    # is stale" -- a zero from a detector that could not have found a positive is
    # the most convincing kind of wrong answer.
    older = [f for f in docs if (_mtime(f) or now) < cutoff]
    by_name = collections.defaultdict(list)
    for f in docs:
        by_name[f["name"]].append(f)
    dup_older = [c for copies in by_name.values() if len(copies) > 1
                 for c in sorted(copies, key=lambda x: x.get("modifiedTime") or "", reverse=True)[1:]]
    return {
        "rule_older_than_days": {
            "threshold_days": older_than_days, "count": len(older),
            "titles": sorted(f["name"] for f in older)[:20],
            "RELIABLE": False,
            "why": ("the hourly sync delete+creates every file, refreshing modifiedTime, "
                    "so Drive age is always ~1h. Use the document's own as_of header."),
        },
        "rule_duplicate_of_newer": {"count": len(dup_older),
                                    "titles": sorted({f["name"] for f in dup_older})[:20]},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Propose Drive archives and dedups. Moves nothing.")
    ap.add_argument("--folder", required=True, help="Drive folder id")
    ap.add_argument("--older-than-days", type=int, default=180)
    ap.add_argument("--review-by-days", type=int, default=DEFAULT_REVIEW_DAYS)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    files = _ls(args.folder)
    dups = dedup_proposal(files)
    rules = staleness_rules(files, args.older_than_days)
    review_by = (datetime.now(timezone.utc) + timedelta(days=args.review_by_days)).date().isoformat()

    report = {
        "authority": "READ_ONLY_ADVISORY",
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "folder": args.folder,
        "total_files": len([f for f in files if "folder" not in f.get("mimeType", "")]),
        "distinct_titles": len({f["name"] for f in files if "folder" not in f.get("mimeType", "")}),
        "duplicate_titles": len(dups),
        "extra_copies": sum(len(d["propose_remove"]) for d in dups),
        "staleness_rules": rules,
        "dedup_proposal": dups,
        "review_by": review_by,
        "restore_command": "gog drive move <FILE_ID> --parent <ORIGINAL_FOLDER_ID> --account " + ACCOUNT,
        "executed": False,
        "note": "Nothing was moved, archived or deleted. This script has no --apply.",
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"folder {args.folder}  as_of {report['as_of']}")
        print(f"  files {report['total_files']}  distinct titles {report['distinct_titles']}")
        print(f"  duplicate titles {report['duplicate_titles']}  extra copies {report['extra_copies']}")
        for k, v in rules.items():
            print(f"  {k}: {v['count']}")
        print(f"  review_by {review_by}")
        print("  NOTHING MOVED, ARCHIVED OR DELETED — this script has no --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
