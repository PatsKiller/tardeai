#!/usr/bin/env python3
"""drive_semantic_compare.py — v1.2.3 P0-2: STRUCTURED semantic comparison for
legacy native-Google-Docs documents (raw .md canonicals use byte parity and
never touch this). Preserves everything meaning-bearing: headings+hierarchy,
list structure, code spans/blocks, URLs, table cells in order, operators and
math symbols, <placeholders>, punctuation, section order.

This is NOT byte parity and is never reported as such."""
from __future__ import annotations

import hashlib
import json
import re


def semantic_repr(text: str) -> list:
    """Ordered structural token stream. Two documents are SEMANTIC_PARITY iff
    their streams are identical."""
    out = []
    lines = text.replace("\r\n", "\n").split("\n")
    in_code = False
    code_buf = []
    for ln in lines:
        if ln.strip().startswith("```"):
            if in_code:
                out.append(("codeblock", "\n".join(code_buf)))
                code_buf = []
            in_code = not in_code
            continue
        if in_code:
            code_buf.append(ln)
            continue
        s = ln.rstrip()
        if not s.strip():
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            out.append(("heading", len(m.group(1)), _inline(m.group(2))))
            continue
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", s)
        if m:
            kind = "olist" if m.group(2)[0].isdigit() else "ulist"
            out.append((kind, len(m.group(1)) // 2, _inline(m.group(3))))
            continue
        if "|" in s and s.strip().startswith("|"):
            cells = [c.strip() for c in s.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue  # separator row carries no meaning
            out.append(("row", tuple(_inline(c) for c in cells)))
            continue
        out.append(("para", _inline(s.strip())))
    if in_code and code_buf:
        out.append(("codeblock_unclosed", "\n".join(code_buf)))
    return out


def _inline(s: str) -> tuple:
    """Inline decomposition keeping code spans, URLs, placeholders, operators,
    numbers WITH units/percent, and punctuation."""
    parts = []
    for tok in re.split(r"(`[^`]*`)", s):
        if tok.startswith("`") and tok.endswith("`") and len(tok) >= 2:
            parts.append(("code", tok[1:-1]))
        elif tok:
            for url in re.findall(r"https?://\S+", tok):
                parts.append(("url", url))
            rest = re.sub(r"https?://\S+", " ", tok)
            for ph in re.findall(r"<[^>\s]{1,40}>", rest):
                parts.append(("ph", ph))
            # text stream keeps operators/punct/symbols; collapse whitespace only
            parts.append(("t", re.sub(r"\s+", " ", rest).strip()))
    return tuple(p for p in parts if p != ("t", ""))


def semantic_hash(text: str) -> str:
    return hashlib.sha256(json.dumps(semantic_repr(text), sort_keys=False,
                                     default=str).encode()).hexdigest()[:16]


def compare(a: str, b: str) -> str:
    """SEMANTIC_PARITY | STRUCTURAL_DRIFT | CONTENT_DRIFT"""
    ra, rb = semantic_repr(a), semantic_repr(b)
    if ra == rb:
        return "SEMANTIC_PARITY"
    kinds_a = [x[0] for x in ra]
    kinds_b = [x[0] for x in rb]
    if kinds_a != kinds_b:
        return "STRUCTURAL_DRIFT"
    return "CONTENT_DRIFT"


def alnum_hash_weakness_demo() -> dict:
    """Why the old alphanumeric-only hash was unacceptable: these PAIRS differ
    in meaning yet collide under alnum-only normalization."""
    import re as _re
    def alnum(s):
        return _re.sub(r"[^0-9A-Za-z]+", "", s)
    pairs = [("risk > 5%", "risk < 5%"),
             ("gain of 1% today", "gain of 10 % t o d a y"[:16]),
             ("A && B", "A || B && "),
             ("-3.2% drawdown", "3.2% drawdown")]
    return {f"{a!r} vs {b!r}": {"alnum_collides": alnum(a) == alnum(b),
                                "semantic_detects": compare(a, b) != "SEMANTIC_PARITY"}
            for a, b in pairs}
