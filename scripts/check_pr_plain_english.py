#!/usr/bin/env python3
"""Every PR explains itself in plain English before any technical detail (AGENTS.md §28.12, 26.0.0).

The operator approves merges from a Telegram digest and from GitHub. He is not a GitHub expert and approves what he
can read, so a PR's title is a plain-English sentence and its description opens with:

    ## In plain English
    **What changes:** …
    **Why:** …
    **Who / what it affects:** …
    **When it takes effect:** …
    **Approval:** …
    **Risk and fallback:** …

Each label must carry real text (not empty, not an unfilled `<placeholder>`), and the block must come before
`## Technical detail` when that heading is present. A draft PR is a claim, not a request to merge (AGENTS.md §0 rule
11), so it passes with a notice; the check binds when the PR is marked ready. Bot-authored PRs are exempt.

Inputs: ``--event`` (a GitHub pull_request event JSON; default ``$GITHUB_EVENT_PATH``) or ``--title`` with
``--body-file``. Exit 1 lists what is missing. Read-only; no network.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HEADING = "## In plain English"
LABELS = (
    "What changes",
    "Why",
    "Who / what it affects",
    "When it takes effect",
    "Approval",
    "Risk and fallback",
)
BOTS = {"dependabot[bot]", "mergify[bot]", "github-actions[bot]", "renovate[bot]"}
MIN_TITLE_WORDS = 4


def _block(body: str) -> str | None:
    lines = body.replace("\r\n", "\n").split("\n")
    for i, ln in enumerate(lines):
        if ln.strip() == HEADING:
            out = []
            for nxt in lines[i + 1:]:
                if nxt.startswith("## "):
                    break
                out.append(nxt)
            return "\n".join(out)
    return None


def _field_match(block: str, label: str, *, heading: bool = False):
    prefix = r"^[ \t]*(?:[-*+]\s+)?" if heading else ""
    following = r"\n[ \t]*(?:[-*+]\s+)?\*\*[^*\n]+:\*\*" if heading else r"\n\*\*[^*\n]+:\*\*"
    return re.search(prefix + r"\*\*" + re.escape(label) + r":\*\*(.*?)(?=" + following + r"|\Z)", block, re.S | re.M)


def fields(body: str) -> dict[str, str]:
    """Extract the six answers, including bodies using Markdown list bullets.

    Validation retains its original acceptance rules. Structured extraction
    matches actual heading lines, not a literal label mentioned inside an answer.
    """
    block = _block(body or "")
    if block is None:
        return {}
    out = {}
    for label in LABELS:
        match = _field_match(block, label, heading=True)
        if match:
            out[label] = " ".join(match.group(1).split())
    return out


def check(title: str, body: str) -> list[str]:
    errors: list[str] = []
    words = re.sub(r"^(\s*\[[^\]]*\]\s*)+", "", title or "").split()
    if len(words) < MIN_TITLE_WORDS:
        errors.append(f"title {title!r}: write a plain-English sentence (at least {MIN_TITLE_WORDS} words); "
                      "the operator's digest shows only the title")
    body = body or ""
    block = _block(body)
    if block is None:
        errors.append(f"description has no '{HEADING}' section (see .github/pull_request_template.md)")
        return errors
    tech = body.find("## Technical detail")
    if tech != -1 and tech < body.find(HEADING):
        errors.append(f"'{HEADING}' must come before '## Technical detail'")
    for label in LABELS:
        m = _field_match(block, label)
        if not m:
            errors.append(f"missing **{label}:**")
            continue
        text = " ".join(m.group(1).split())
        if not text or (text.startswith("<") and text.endswith(">")):
            errors.append(f"**{label}:** is empty or still the template placeholder")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--event", default=os.environ.get("GITHUB_EVENT_PATH"))
    ap.add_argument("--title")
    ap.add_argument("--body-file")
    args = ap.parse_args(argv)
    draft = False
    author = ""
    if args.title is not None:
        title = args.title
        body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else ""
    elif args.event and Path(args.event).is_file():
        pr = json.loads(Path(args.event).read_text(encoding="utf-8")).get("pull_request") or {}
        title, body = pr.get("title") or "", pr.get("body") or ""
        draft = bool(pr.get("draft"))
        author = ((pr.get("user") or {}).get("login")) or ""
    else:
        print("check_pr_plain_english: no PR event and no --title; nothing to check")
        return 0
    if author in BOTS:
        print(f"check_pr_plain_english: {author} is exempt")
        return 0
    errors = check(title, body)
    if errors and draft:
        print("check_pr_plain_english: draft PR — fix before marking ready:")
        for e in errors:
            print(f"  - {e}")
        return 0
    for e in errors:
        print(f"PLAIN_ENGLISH: {e}")
    if not errors:
        print("check_pr_plain_english ok: title and the six plain-English answers are present")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
