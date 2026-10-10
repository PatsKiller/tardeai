"""restore_dump_guard.py — line guard for SQL scripts replayed by the trade_ai restore drill.

The drill (scripts/trade_ai_restore_drill.py) replays a pg_dump SQL script with psql into a throwaway
database. psql executes whatever the script says, so a script that says ``\\connect trade_ai`` or
``DROP DATABASE`` would act outside the throwaway. Three layers stop that; this module is the second:

  1. A dedicated drill role with CREATEDB and nothing else (no superuser, no CREATEROLE, not the live
     owner or a member of it). It can only touch databases it owns. Checked by the drill's preflight.
  2. This guard. Every line goes through ``DumpGuard.feed`` before psql sees it, twice: a full
     pre-scan before ``CREATE DATABASE`` (a refusal creates nothing), then again on the restore stream
     itself (so a dump swapped between the two passes is still checked line by line). A violating line
     is never forwarded.
  3. psql's own restricted mode: the drill sends ``\\restrict <random per-run key>`` as the first line,
     so psql refuses every backslash command (``\\connect``, ``\\!``, ``\\o``, ``\\copy`` ...) for the
     whole session, also mid-line ones the guard might not parse. The dump cannot know the key.

Rules (outside COPY data; COPY data rows are data to psql and are only counted):
  - backslash lines: only pg_dump's own ``\\restrict <key>`` / ``\\unrestrict <key>`` pass (they are
    dropped from the forwarded stream; layer 3 supplies the drill's key). Any other line starting with a
    backslash, and any ``\\<meta>`` token mid-line, is a violation.
  - ``CREATE|DROP|ALTER DATABASE``, ``ALTER SYSTEM``, ``CREATE|ALTER|DROP ROLE|USER|GROUP``,
    ``SET [SESSION|LOCAL] ROLE``, ``RESET ROLE``, ``SESSION AUTHORIZATION``, ``set_config('role'|...)``,
    ``GRANT``/``REVOKE`` (the dumps are --no-acl; a membership GRANT is a role change),
    ``COPY ... PROGRAM``, and any ``COPY`` statement that is not ``COPY ... FROM stdin;``.
  - A script that ends inside a COPY block is truncated: violation at ``finish()``.

Matching is deliberately broad: a function body or comment that merely contains ``DROP DATABASE`` is
refused too. A false refusal fails the drill loudly; a false pass could reach live data.

Bytes in, bytes out; no I/O. Tested by tests/test_restore_drill_guard_20261009.py (adversarial dumps).
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

ALLOWED_META = re.compile(rb"^\\(restrict|unrestrict)[ \t]+[A-Za-z0-9]+[ \t]*\r?\n?$")
_IDENT = rb'(?:"(?:[^"]|"")*"|[^\s."(]+)'
COPY_START = re.compile(
    rb"^COPY[ \t]+(" + _IDENT + rb"(?:\." + _IDENT + rb")?)[ \t].*\bFROM[ \t]+stdin;[ \t]*\r?\n?$", re.IGNORECASE
)
COPY_END = re.compile(rb"^\\\.\r?\n?$")
# psql meta-commands are a backslash followed by a letter or one of ! ? ; outside quotes. The guard
# cannot see quotes reliably in a stream, so any such token outside COPY data is refused (layer 3 is
# the backstop for anything this misses).
MID_META = re.compile(rb"\\(?:[A-Za-z]+|!|\?)")
# Tag bytes >= 0x80 cover any UTF-8 letter (over-inclusive on purpose).
DOLLAR_TAG = re.compile(rb"\$(?:[A-Za-z_\x80-\xff][A-Za-z0-9_\x80-\xff]*)?\$")

FORBIDDEN: tuple[tuple[str, re.Pattern], ...] = (
    ("create_database", re.compile(rb"\bCREATE\s+DATABASE\b", re.I)),
    ("drop_database", re.compile(rb"\bDROP\s+DATABASE\b", re.I)),
    ("alter_database", re.compile(rb"\bALTER\s+DATABASE\b", re.I)),
    ("alter_system", re.compile(rb"\bALTER\s+SYSTEM\b", re.I)),
    ("role_ddl", re.compile(rb"\b(?:CREATE|ALTER|DROP)\s+(?:ROLE|USER|GROUP)\b", re.I)),
    ("set_role", re.compile(rb"\b(?:SET|RESET)\s+(?:(?:SESSION|LOCAL)\s+)?ROLE\b", re.I)),
    ("session_authorization", re.compile(rb"\bSESSION[\s_]+AUTHORIZATION\b", re.I)),
    ("set_config_role", re.compile(rb"set_config\s*\(\s*'(?:role|session_authorization)'", re.I)),
    ("grant_revoke", re.compile(rb"^\s*(?:GRANT|REVOKE)\b", re.I)),
    ("copy_program", re.compile(rb"\bCOPY\b.*\bPROGRAM\b", re.I)),
)
COPY_ANY = re.compile(rb"^\s*COPY\b", re.I)


class DumpGuardViolation(Exception):
    def __init__(self, rule: str, line_no: int, excerpt: str):
        super().__init__(f"line {line_no}: {rule}: {excerpt}")
        self.rule, self.line_no, self.excerpt = rule, line_no, excerpt

    def as_dict(self) -> dict:
        return {"rule": self.rule, "line_no": self.line_no, "excerpt": self.excerpt}


def _excerpt(line: bytes) -> str:
    return line[:160].decode("utf-8", errors="replace").rstrip("\r\n")


class DumpGuard:
    """Stateful line checker. ``feed`` returns the line to forward (or None to drop) or raises."""

    def __init__(self) -> None:
        self.line_no = 0
        self.in_copy: Optional[str] = None
        self.dollar_tag: Optional[bytes] = None
        self.copy_rows: dict[str, int] = {}
        self.copy_blocks = 0
        self.dropped_meta = 0

    def _violation(self, rule: str, line: bytes) -> DumpGuardViolation:
        return DumpGuardViolation(rule, self.line_no, _excerpt(line))

    def _track_dollar(self, line: bytes) -> None:
        for m in DOLLAR_TAG.finditer(line):
            tag = m.group(0)
            if self.dollar_tag is None:
                self.dollar_tag = tag
            elif tag == self.dollar_tag:
                self.dollar_tag = None

    def feed(self, line: bytes) -> Optional[bytes]:
        self.line_no += 1
        if self.in_copy is not None:
            if COPY_END.match(line):
                self.in_copy = None
            else:
                self.copy_rows[self.in_copy] += 1
            return line
        if line.startswith(b"\\"):
            if ALLOWED_META.match(line):
                self.dropped_meta += 1
                return None
            raise self._violation("meta_command", line)
        if MID_META.search(line):
            raise self._violation("meta_command_inline", line)
        for rule, rx in FORBIDDEN:
            if rx.search(line):
                raise self._violation(rule, line)
        if self.dollar_tag is None and COPY_ANY.match(line):
            m = COPY_START.match(line)
            if not m:
                raise self._violation("copy_not_from_stdin", line)
            table = m.group(1).decode("utf-8", errors="replace")
            self.in_copy = table
            self.copy_rows.setdefault(table, 0)
            self.copy_blocks += 1
            return line
        self._track_dollar(line)
        return line

    def finish(self) -> dict:
        if self.in_copy is not None:
            raise DumpGuardViolation("truncated_in_copy", self.line_no, self.in_copy)
        return self.summary()

    def summary(self) -> dict:
        return {
            "lines": self.line_no,
            "copy_blocks": self.copy_blocks,
            "copy_rows_total": sum(self.copy_rows.values()),
            "dropped_meta_lines": self.dropped_meta,
        }


def scan_lines(lines: Iterable[bytes]) -> tuple[DumpGuard, Optional[DumpGuardViolation]]:
    """Feed every line; return the guard and the first violation (None = clean and complete)."""
    g = DumpGuard()
    try:
        for line in lines:
            g.feed(line)
        g.finish()
    except DumpGuardViolation as exc:
        return g, exc
    return g, None


def copy_table_key(schema: str, table: str) -> str:
    """The COPY target spelling pg_dump uses (``schema.table``, quoted only when needed)."""

    def q(s: str) -> str:
        return s if re.fullmatch(r"[a-z_][a-z0-9_$]*", s) else '"' + s.replace('"', '""') + '"'

    return f"{q(schema)}.{q(table)}"
