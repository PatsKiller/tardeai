#!/usr/bin/env python3
"""Edit a source file without silently rewriting its line endings.

Every incident this module exists to prevent happened while "preserving" line
endings by hand:

  * `write_text()` on a CRLF file converts the whole file to LF. Three times.
    Each produced a diff of 264 / 2451 / 1498 lines for a few real edits.
  * The obvious defence -- `if crlf: data.replace(b"\\n", b"\\r\\n")` -- is worse.
    Applied to a file that ALREADY has CRLF it turns every `\\r\\n` into
    `\\r\\r\\n`. That happened on 2026-08-27 to 783 line endings. Python parsed
    the result, the tests passed, and it was caught only because an insertion
    count looked implausible.
  * Two attempts to *measure* the damage were themselves wrong: `b'\\r\\n'`
    inside a shell heredoc counts a literal backslash, so both reported zero of
    everything.

The rule that avoids all of it: **detect the existing style, normalize to \\n for
editing, restore exactly that style, and assert the count did not change.**
Never convert conditionally; never guess.

    from scripts.lib.safe_text_edit import edit_text

    edit_text("scripts/foo.py", [(old, new)])          # exact, single-occurrence

AUTHORITY: READ_ONLY_ADVISORY. Developer tooling; touches no financial surface.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

CRLF = "crlf"
LF = "lf"
CR = "cr"
MIXED = "mixed"


class LineEndingError(RuntimeError):
    """Raised rather than writing a file whose line endings would change."""


def detect(data: bytes) -> str:
    """Classify a file's line-ending convention from its bytes."""
    crlf = data.count(b"\r\n")
    lone_cr = data.count(b"\r") - crlf
    lone_lf = data.count(b"\n") - crlf
    present = [n for n in (crlf, lone_cr, lone_lf) if n]
    if len(present) > 1:
        return MIXED
    if crlf:
        return CRLF
    if lone_cr:
        return CR
    return LF


def counts(data: bytes) -> dict[str, int]:
    crlf = data.count(b"\r\n")
    return {"crlf": crlf,
            "lone_cr": data.count(b"\r") - crlf,
            "lone_lf": data.count(b"\n") - crlf}


def apply_edits(text: str, pairs: Sequence[tuple[str, str]], *, path: str = "") -> str:
    """Apply exact single-occurrence replacements to \\n-normalized text."""
    for old, new in pairs:
        n = text.count(old)
        if n != 1:
            raise LineEndingError(
                f"{path or 'text'}: expected exactly 1 occurrence, found {n}: {old[:60]!r}")
        text = text.replace(old, new, 1)
    return text


def edit_text(path: str | Path, pairs: Iterable[tuple[str, str]],
              *, allow_mixed: bool = False) -> dict[str, int]:
    """Edit `path`, preserving its line-ending style exactly.

    `pairs` are matched against text normalized to \\n, so callers write plain
    "\\n" regardless of what the file uses. Returns the line-ending counts of the
    written file. Raises LineEndingError rather than writing a file whose style
    would change.
    """
    p = Path(path)
    raw = p.read_bytes()
    style = detect(raw)
    if style == MIXED and not allow_mixed:
        raise LineEndingError(
            f"{p}: mixed line endings {counts(raw)}; refusing to edit "
            "(fix the file first, or pass allow_mixed=True deliberately)")

    before = counts(raw)
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    text = apply_edits(text, list(pairs), path=str(p))

    if style == CRLF:
        out = text.replace("\n", "\r\n").encode("utf-8")
    elif style == CR:
        out = text.replace("\n", "\r").encode("utf-8")
    else:
        out = text.encode("utf-8")

    after = counts(out)
    # The edit may add or remove LINES; it must never change the STYLE. Assert
    # the styles match and that no foreign separator appeared.
    if detect(out) != style:
        raise LineEndingError(
            f"{p}: line-ending style would change {style} -> {detect(out)}; refusing")
    for key in ("lone_cr", "lone_lf") if style == CRLF else ():
        if after[key]:
            raise LineEndingError(f"{p}: would write {after[key]} stray {key}; refusing")

    p.write_bytes(out)
    return {"style": style, "before": before, "after": after}  # type: ignore[return-value]
