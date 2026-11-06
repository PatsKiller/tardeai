#!/usr/bin/env python3
"""Render the Command Center v3 token stylesheet from design/system/tokens.json.

    python3 scripts/gen_design_tokens.py            # write apps/command-center-v3/src/styles/tokens.css
    python3 scripts/gen_design_tokens.py --check    # exit 1 when the committed CSS differs from the render

design/system/tokens.json is the source (AGENTS.md §28.13, design/README.md). Every value lives once in
``themes.<theme>.<name>``; ``layout`` is the stylesheet line by line, where ``{theme.name}`` renders as
``name: value;``. The render refuses an unknown placeholder and a value that no line uses, so a token
cannot be added to one side only. Output is UTF-8 with LF endings and a final newline, byte-identical to
the stylesheet the app has shipped since PR1 (2026-09-27).

AUTHORITY: READ_ONLY_ADVISORY in --check mode; otherwise writes exactly one repo file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "design/system/tokens.json"
PLACEHOLDER = re.compile(r"\{([a-z_]+)\.((?:--[a-z0-9-]+)|color-scheme)\}")


class TokenError(ValueError):
    pass


def render(doc: dict) -> str:
    if doc.get("schema") != "DesignTokens@v1":
        raise TokenError("schema must be DesignTokens@v1")
    themes, layout = doc.get("themes"), doc.get("layout")
    if not isinstance(themes, dict) or not isinstance(layout, list) or not all(isinstance(x, str) for x in layout):
        raise TokenError("themes must be an object and layout a list of strings")
    used: set[tuple[str, str]] = set()

    def sub(match: re.Match) -> str:
        theme, name = match.group(1), match.group(2)
        value = (themes.get(theme) or {}).get(name)
        if not isinstance(value, str) or not value or any(c in value for c in ";{}\n"):
            raise TokenError(f"unresolved or invalid placeholder {{{theme}.{name}}}")
        used.add((theme, name))
        return f"{name}: {value};"

    lines = []
    for line in layout:
        if "\n" in line or "\r" in line:
            raise TokenError("layout lines must not contain line breaks")
        lines.append(PLACEHOLDER.sub(sub, line))
    unused = sorted(f"{t}.{n}" for t, values in themes.items() for n in values if (t, n) not in used)
    if unused:
        raise TokenError("values not used by any layout line: " + ", ".join(unused))
    return "\n".join(lines) + "\n"


def target(doc: dict) -> Path:
    rel = doc.get("generated_css") or "apps/command-center-v3/src/styles/tokens.css"
    path = (ROOT / rel).resolve()
    if ROOT not in path.parents:
        raise TokenError("generated_css must stay inside the repository")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="compare only; never write")
    ap.add_argument("--source", type=Path, default=SOURCE)
    args = ap.parse_args(argv)
    try:
        doc = json.loads(args.source.read_text(encoding="utf-8"))
        css = render(doc)
        out = target(doc)
    except (OSError, ValueError) as exc:
        print(f"gen_design_tokens: {exc}", file=sys.stderr)
        return 2
    data = css.encode("utf-8")
    if args.check:
        current = out.read_bytes() if out.is_file() else b""
        if current != data:
            print(f"gen_design_tokens: {out.relative_to(ROOT)} differs from design/system/tokens.json; "
                  "run python3 scripts/gen_design_tokens.py and commit both", file=sys.stderr)
            return 1
        print(f"gen_design_tokens: {out.relative_to(ROOT)} matches design/system/tokens.json")
        return 0
    if not out.is_file() or out.read_bytes() != data:
        out.write_bytes(data)
        print(f"gen_design_tokens: wrote {out.relative_to(ROOT)}")
    else:
        print(f"gen_design_tokens: {out.relative_to(ROOT)} already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
