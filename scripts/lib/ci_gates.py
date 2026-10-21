"""The CIO hardening gate registry: one JSON file per gate under ``config/ci_gates/``.

Why (operator-approved process plan, 2026-10-21): the gates used to be one Python list
(``GATES`` in scripts/run_cio_hardening_ci.py, 533 tuples). Every PR that registered a test
appended to it, so any two parallel PRs collided in the same hunk. One file per gate means two
PRs that each add a gate add two different files: git merges them with no conflict.

File format (``config/ci_gates/<name>.json``, schema ``CiGate@v1``)::

    {
      "schema": "CiGate@v1",
      "name": "<name>",                 # must equal the file stem
      "files": ["tests/test_x.py"],     # pytest files, repo-relative, in run order
      "anchor": "X_20261021",           # optional: the ANCHOR id from the comment
      "comment": ["ANCHOR: X_20261021 — why this gate exists ..."]   # optional, free text
    }

Order: gates load sorted by name (the file stem). The runner never depended on the old list
order for WHAT runs -- the fast/pr pools re-sort by duration, the shard plan sorts by path --
only for the serial ``full`` profile's sequence and for which gate labels a file registered
twice. Sorting by name is deterministic and independent of merge order.

Fail closed: an unreadable or malformed gate file raises ``GateRegistryError``; it never
silently drops a gate (a dropped gate would be a test CI stopped running).

Stdlib only. AUTHORITY: READ_ONLY_ADVISORY (CI tooling; no broker, no Telegram, no DB).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA = "CiGate@v1"
GATES_DIR_REL = "config/ci_gates"
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
ANCHOR_RE = re.compile(r"ANCHOR:\s*([A-Za-z0-9_]+)")
_KEYS = ("schema", "name", "files", "anchor", "comment")


class GateRegistryError(ValueError):
    """A gate file is missing, unreadable or malformed. Never a pass."""


def gates_dir(root: Path) -> Path:
    return Path(root) / GATES_DIR_REL


def gate_path(root: Path, name: str) -> Path:
    return gates_dir(root) / f"{name}.json"


def validate(doc: object, *, stem: str | None = None) -> dict:
    """Return ``doc`` if it is a valid CiGate@v1 record, else raise GateRegistryError."""
    where = f"{GATES_DIR_REL}/{stem}.json" if stem else "gate"
    if not isinstance(doc, dict):
        raise GateRegistryError(f"{where}: not a JSON object")
    extra = sorted(set(doc) - set(_KEYS))
    if extra:
        raise GateRegistryError(f"{where}: unknown keys {extra}")
    if doc.get("schema") != SCHEMA:
        raise GateRegistryError(f"{where}: schema must be {SCHEMA!r}")
    name = doc.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise GateRegistryError(f"{where}: bad name {name!r}")
    if stem is not None and name != stem:
        raise GateRegistryError(f"{where}: name {name!r} must equal the file stem {stem!r}")
    files = doc.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(p, str) and p for p in files):
        raise GateRegistryError(f"{where}: files must be a non-empty list of paths")
    if len(set(files)) != len(files):
        raise GateRegistryError(f"{where}: duplicate path in files")
    if "anchor" in doc and not isinstance(doc["anchor"], str):
        raise GateRegistryError(f"{where}: anchor must be a string")
    comment = doc.get("comment", [])
    if not isinstance(comment, list) or not all(isinstance(s, str) for s in comment):
        raise GateRegistryError(f"{where}: comment must be a list of strings")
    return doc


def make_record(name: str, files: list[str], comment: list[str] | None = None) -> dict:
    """A CiGate@v1 record in canonical key order; ``anchor`` is derived from the comment."""
    doc: dict = {"schema": SCHEMA, "name": name, "files": list(files)}
    comment = [s for s in (comment or [])]
    m = next((ANCHOR_RE.search(s) for s in comment if ANCHOR_RE.search(s)), None)
    if m:
        doc["anchor"] = m.group(1)
    if comment:
        doc["comment"] = comment
    return validate(doc, stem=name)


def render(doc: dict) -> str:
    """Canonical file text (stable bytes, so re-running the migration is a no-op)."""
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def load_records(root: Path) -> list[dict]:
    """Every gate record, sorted by name. Raises GateRegistryError on any bad file."""
    d = gates_dir(root)
    if not d.is_dir():
        raise GateRegistryError(f"{GATES_DIR_REL}/ is missing")
    out: list[dict] = []
    for p in sorted(d.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GateRegistryError(f"{GATES_DIR_REL}/{p.name}: unreadable ({exc})") from exc
        out.append(validate(doc, stem=p.stem))
    if not out:
        raise GateRegistryError(f"{GATES_DIR_REL}/ holds no gates")
    out.sort(key=lambda r: r["name"])
    return out


def load_gates(root: Path) -> list[tuple[str, list[str]]]:
    """``[(name, [files])]`` sorted by name -- the shape GATES always had."""
    return [(r["name"], list(r["files"])) for r in load_records(root)]


def registry_text(root: Path) -> str:
    """Raw text of every gate file, concatenated in name order.

    For tests that assert "my test file is registered" by substring: they used to grep the
    runner's source for ``"tests/test_x.py"``; the same substring is in the gate file.
    """
    return "".join(p.read_text(encoding="utf-8") for p in sorted(gates_dir(root).glob("*.json")))
