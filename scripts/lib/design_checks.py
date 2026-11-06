"""PR design checks (AGENTS.md §28.13 proposed, design/README.md): design-reference line and removal guard.

Pure functions over a PR body, a changed-file list and a unified diff, plus reads of design/ in the repo.

- A PR that changes UI under apps/command-center-v3/src must carry ``Design: <page>/vNNN`` (that version APPROVED or
  IMPLEMENTING) or ``Design: none``.
- Removal guard: a nav item, route, tab or panel heading that the diff removes (and does not re-add anywhere in the
  same diff) or newly hides must be listed in the cited version's SPEC.md "Removals, hides and moves" section.
  ``Design: none`` carries no removals, so any removal fails.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.lib import design_pages as dp

UI_PREFIX = "apps/command-center-v3/src/"
UI_SUFFIXES = (".tsx", ".ts", ".css")
NOT_UI = (re.compile(r"\.test\.(ts|tsx|mjs)$"), re.compile(r"^apps/command-center-v3/src/fixtures/"))
BUILDABLE_STATES = ("APPROVED", "IMPLEMENTING")
REF = re.compile(r"^[ \t>*_-]*Design:\s*(?:`)?(none|([a-z0-9][a-z0-9-]*)/(v\d{3}))(?:`)?\s*\.?\s*$", re.I | re.M)

# What counts as an operator surface element, by the label it shows.
PATTERNS = (
    ("nav", re.compile(r"\{\s*to:\s*['\"]([^'\"]+)['\"]\s*,\s*label:\s*['\"]([^'\"]+)['\"]"), 2),
    ("route", re.compile(r"<Route\s+(?:index\s+)?path=\"([^\"]+)\""), 1),
    ("tab", re.compile(r"\{\s*id:\s*['\"]([^'\"]+)['\"]\s*,\s*label:\s*['\"]([^'\"]+)['\"]"), 2),
    ("panel", re.compile(r"<h2[^>]*>\s*([^<{}]+?)\s*</h2>"), 1),
    ("panel", re.compile(r"<section[^>]*\baria-label=\"([^\"]+)\""), 1),
)
HIDE = re.compile(r"display:\s*['\"]none['\"]|\bhidden(?:\s*[:=]\s*(?:\{\s*)?true|\b(?!\s*[:=]))|\bfalse\s*&&|visibility:\s*['\"]hidden['\"]")


def is_ui_file(path: str) -> bool:
    return path.startswith(UI_PREFIX) and path.endswith(UI_SUFFIXES) and not any(rx.search(path) for rx in NOT_UI)


def design_refs(body: str | None) -> list[str]:
    """Every Design: line in the body, normalised: 'none' or '<page>/vNNN'."""
    out = []
    for m in REF.finditer(body or ""):
        out.append("none" if m.group(1).lower() == "none" else f"{m.group(2).lower()}/{m.group(3).lower()}")
    return out


def _status(root: Path, page: str, version: str) -> dict | None:
    p = dp.design_dir(root) / "pages" / page / "versions" / version / "status.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def check_reference(body: str | None, changed: list[str], root: Path = dp.ROOT) -> tuple[list[str], list[str]]:
    """(errors, cited versions). No UI file changed → nothing required."""
    ui = [f for f in changed if is_ui_file(f)]
    refs = design_refs(body)
    if not ui:
        return [], [r for r in refs if r != "none"]
    if not refs:
        return [f"{len(ui)} UI file(s) changed ({', '.join(ui[:5])}{' …' if len(ui) > 5 else ''}) but the PR body has no "
                "'Design: <page>/vNNN' or 'Design: none' line (design/README.md, AGENTS.md §28.13)."], []
    if "none" in refs and len(refs) > 1:
        return ["The PR body cites both 'Design: none' and a design version; cite one or the other."], []
    if refs == ["none"]:
        return [], []
    pages = {p["id"] for p in dp.load_registry(root).get("pages") or []}
    errors, cited = [], []
    for ref in refs:
        page, version = ref.split("/")
        if page not in pages:
            errors.append(f"Design: {ref} — page '{page}' is not in design/registry.json.")
            continue
        status = _status(root, page, version)
        if status is None:
            errors.append(f"Design: {ref} — design/pages/{page}/versions/{version}/status.json does not exist.")
            continue
        if status.get("state") not in BUILDABLE_STATES:
            errors.append(f"Design: {ref} is {status.get('state')}; only an APPROVED or IMPLEMENTING version may be built.")
            continue
        cited.append(ref)
    return errors, cited


def parse_diff(diff: str) -> dict[str, dict[str, list[str]]]:
    """{file: {'-': removed lines, '+': added lines}} from a unified diff."""
    files: dict[str, dict[str, list[str]]] = {}
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:].strip()
            current = name[2:] if name.startswith("b/") else (None if name == "/dev/null" else name)
            if current:
                files.setdefault(current, {"-": [], "+": []})
            continue
        if line.startswith("--- "):
            name = line[4:].strip()
            if name != "/dev/null":
                current = name[2:] if name.startswith("a/") else name
                files.setdefault(current, {"-": [], "+": []})
            continue
        if current is None or line.startswith(("diff ", "index ", "@@")):
            continue
        if line.startswith("-"):
            files[current]["-"].append(line[1:])
        elif line.startswith("+"):
            files[current]["+"].append(line[1:])
    return files


def _labels(line: str) -> list[tuple[str, str]]:
    out = []
    for kind, rx, group in PATTERNS:
        for m in rx.finditer(line):
            out.append((kind, m.group(group).strip()))
    return out


def surface_changes(diff: str) -> list[dict]:
    """Removed or hidden operator-surface elements. A label re-added anywhere in the diff (moved) is not removed."""
    files = {f: v for f, v in parse_diff(diff).items() if is_ui_file(f)}
    removed, added, hidden = {}, set(), {}
    for f, sides in files.items():
        for line in sides["-"]:
            for kind, label in _labels(line):
                removed.setdefault((kind, label.lower()), {"kind": kind, "label": label, "file": f, "change": "removed"})
        for line in sides["+"]:
            labels = _labels(line)
            for kind, label in labels:
                added.add((kind, label.lower()))
            if labels and HIDE.search(line):
                for kind, label in labels:
                    hidden.setdefault((kind, label.lower()), {"kind": kind, "label": label, "file": f, "change": "hidden"})
    out = [v for k, v in removed.items() if k not in added]
    out += [v for k, v in hidden.items()]
    return sorted(out, key=lambda r: (r["file"], r["kind"], r["label"].lower()))


def allowed_labels(cited: list[str], root: Path = dp.ROOT) -> set[str]:
    labels = set()
    for ref in cited:
        page, version = ref.split("/")
        spec = dp.design_dir(root) / "pages" / page / "versions" / version / "SPEC.md"
        if spec.is_file():
            labels |= {r["label"].lower() for r in dp.parse_removals(spec.read_text(encoding="utf-8"))}
    return labels


def check_removals(diff: str, cited: list[str], root: Path = dp.ROOT) -> list[str]:
    allowed = allowed_labels(cited, root)
    errors = []
    for change in surface_changes(diff):
        if change["label"].lower() in allowed:
            continue
        where = f"cited version(s) {', '.join(cited)}" if cited else "'Design: none' (which allows no removal)"
        errors.append(f"{change['file']}: {change['kind']} \"{change['label']}\" is {change['change']} but not listed in the "
                      f"Removals section of {where}. Propose a design version that lists it, or keep it (§28.9 change control).")
    return errors
