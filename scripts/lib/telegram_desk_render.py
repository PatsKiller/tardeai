"""telegram_desk_render.py — a desk answer as a person reads it on a phone.

WHY
---
2026-09-14. The AXTI answer (4,571 characters) was refused by Telegram and re-sent by hand in two cuts.
Part 2 was the bookkeeping tail: raw store names (`ticker_prices`, `yahoo_analyst_targets_history`,
`sector_momentum_latest.json`), a "Went outside" line and the authority token.

The operator: "Gibberish." Then: "If it needs to be broken up across three or four messages, then do so."

WHAT
----
`render_desk_reply(text)` turns the stored desk answer into Telegram HTML parts:
- the colour-key legend line is dropped (the footer says the same thing in fewer words);
- the answer body keeps its structure, with `*bold*` and `code` rendered and everything else escaped;
- one plain footer line on the last part says how many Trade-AI sources were read, whether an AI model
  wrote any wording, and that the answer is advisory only;
- the full provenance (sources in plain names, the model's role, anything looked up outside) is folded
  into an expandable quote, one tap away;
- a long answer is split at paragraph breaks into "Part 1 of N" messages, each within Telegram's
  4,096 UTF-16 limit.

The stored answer is unchanged. The machine provenance stays in operator_conversation_turns, and the
answer-quality monitor still reads it.

READ_ONLY_ADVISORY. Formatting only.
"""
from __future__ import annotations

import html
import re
from typing import Optional

try:
    from lib.comms_editor import markdown_to_html
    from lib.reply_provenance import _parse_sources_line, _split_provenance_lines
except ImportError:  # pragma: no cover
    from scripts.lib.comms_editor import markdown_to_html  # type: ignore
    from scripts.lib.reply_provenance import _parse_sources_line, _split_provenance_lines  # type: ignore

TELEGRAM_TEXT_LIMIT = 4096
PART_BUDGET = 3800  # UTF-16 units per part, leaving room for the part label

#: store label fragment (lower case) -> what a person calls it
PLAIN_NAMES: tuple[tuple[str, str], ...] = (
    ("cio snapshot", "portfolio snapshot"),
    ("ticker_prices", "Trade-AI daily prices"),
    ("re-entry desk", "re-entry desk"),
    ("symbol_profiles", "company profiles"),
    ("catalyst_events", "catalysts and news"),
    ("yahoo_analyst", "analyst targets (Yahoo)"),
    ("sector_momentum", "sector momentum"),
    ("industry_momentum", "industry groups (Finviz)"),
    ("hermes_research", "Hermes research"),
    ("symbol thesis", "house thesis"),
    ("holdings.json", "your holdings"),
    ("conversation memory", "this conversation"),
    ("operator_conversation_turns", "this conversation"),
    ("options_iv", "options volatility"),
    ("office situation scan", "office situation scan"),
)


def utf16_len(text: str) -> int:
    return len((text or "").encode("utf-16-le")) // 2


def plain_source(label: str) -> str:
    low = (label or "").lower()
    for key, name in PLAIN_NAMES:
        if key in low:
            return name
    base = re.split(r" · | \(| — ", label or "", maxsplit=1)[0]
    base = re.sub(r"\.(json|jsonl|csv)$", "", base.strip())
    return base.replace("_", " ").strip() or (label or "")


def _model_phrase(model_label: Optional[str]) -> Optional[str]:
    if not model_label:
        return None
    low = model_label.lower()
    if "intent classification only" in low and "general knowledge" not in low and "wording" not in low:
        return None  # the model only read the question; it wrote nothing the operator sees
    role = "general knowledge where labelled" if "general knowledge" in low else "wording only"
    return f"DeepSeek ({role})"


def _footer(stores: list[str], model_label: Optional[str], outside: Optional[str]) -> str:
    names: list[str] = []
    for s in stores:
        n = plain_source(s)
        if n not in names:
            names.append(n)
    model = _model_phrase(model_label)
    # Entries are "<what> — <why>" joined by "; ", and a why can itself contain "; " ("intent classification
    # only; no facts"). Split only where a new "<name> —" entry starts, so a fragment is never read as a lookup.
    payload = (outside or "")[len("Went outside:"):].strip()
    outside_items = [o.strip() for o in re.split(r";\s*(?=[\w.-]+ — )", payload) if o.strip()]
    outside_items = [o for o in outside_items if "deepseek" not in o.lower()]
    summary = [f"🟢 {len(names)} Trade-AI source{'s' if len(names) != 1 else ''}"]
    if outside_items:
        summary.append("🔵 looked up outside Trade-AI")
    if model:
        summary.append(f"🟣 {model}")
    summary.append("advisory only — no orders")
    detail = [f"Sources: {', '.join(names) if names else 'none'}"]
    if model:
        detail.append(f"AI model: {model}")
    if outside_items:
        detail.append(f"Looked up outside Trade-AI: {'; '.join(outside_items)}")
    return (f"<i>{html.escape(' · '.join(summary), quote=False)}</i>\n"
            f"<blockquote expandable>{html.escape(chr(10).join(detail), quote=False)}</blockquote>")


def _chunks(body_html: str, budget: int) -> list[str]:
    """Split at blank lines, then single lines; inline tags never span a line, so no tag is cut."""
    parts: list[str] = []
    current = ""
    for para in re.split(r"\n{2,}", body_html):
        pieces = [para] if utf16_len(para) <= budget else para.split("\n")
        for piece in pieces:
            joiner = "\n\n" if para is piece else "\n"
            candidate = f"{current}{joiner if current else ''}{piece}"
            if current and utf16_len(candidate) > budget:
                parts.append(current)
                current = piece
            else:
                current = candidate
    if current:
        parts.append(current)
    return parts


def render_desk_reply(text: str) -> list[str]:
    """Telegram HTML parts for one stored desk answer. Pure."""
    body_lines, sources_line, outside_line, _tail = _split_provenance_lines(text or "")
    body_lines = [ln for ln in body_lines if not ln.strip().startswith("Key:")]
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    stores, model_label = _parse_sources_line(sources_line) if sources_line else ([], None)
    footer = _footer(stores, model_label, outside_line)
    body_html = markdown_to_html("\n".join(body_lines))
    chunks = _chunks(body_html, PART_BUDGET)
    if not chunks:
        chunks = [""]
    if utf16_len(chunks[-1]) + utf16_len(footer) + 2 > PART_BUDGET:
        chunks.append(footer)
    else:
        chunks[-1] = f"{chunks[-1]}\n\n{footer}" if chunks[-1] else footer
    n = len(chunks)
    return [f"<i>Part {i + 1} of {n}</i>\n{c}" if n > 1 else c for i, c in enumerate(chunks)]


__all__ = ["PLAIN_NAMES", "plain_source", "render_desk_reply", "utf16_len"]
