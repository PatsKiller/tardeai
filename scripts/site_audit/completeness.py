"""§6 completeness: a card must carry its evidence, and a top-list card missing it is P1.

The spec names the symbol detail card explicitly: price, RSI, MACD, 20/50/200-day averages, support/resistance 1 and
2, trend; a CIO thesis or stance with an as_of; and a *reason* for any missing field. A card in a TOP list (Best
opportunities, Home top 5) missing a technical or with no CIO thesis is P1.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

REQUIRED_SYMBOL_FIELDS = (
    "price", "rsi", "macd",
    "sma_20", "sma_50", "sma_200",
    "support_1", "support_2", "resistance_1", "resistance_2",
    "trend",
)
CIO_FIELDS = ("cio_stance", "cio_thesis")

P1 = "P1"
P2 = "P2"

#: How each required field is named in the rendered detail a crawl captures. Matching is word-bounded and
#: case-insensitive; several product surfaces spell the same field differently ("SMA50" / "SMA 50" / "50-day").
FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "price": ("price", "last price", "mark price", "current price"),
    "rsi": ("rsi",),
    "macd": ("macd",),
    "sma_20": ("sma20", "sma 20", "sma_20", "sma(20)", "20-day sma", "20d sma"),
    "sma_50": ("sma50", "sma 50", "sma_50", "sma(50)", "50-day sma", "50d sma"),
    "sma_200": ("sma200", "sma 200", "sma_200", "sma(200)", "200-day sma", "200d sma"),
    "support_1": ("support 1", "support1", "support_1"),
    "support_2": ("support 2", "support2", "support_2"),
    "resistance_1": ("resistance 1", "resistance1", "resistance_1"),
    "resistance_2": ("resistance 2", "resistance2", "resistance_2"),
    "trend": ("trend",),
}

#: Some product surfaces put several fields in ONE row, with the values slash-separated. `OpportunityModal` renders
#: ``Support 1 / 2   $12.00 / $11.00``, ``Resistance 1 / 2   …`` and ``20 / 50 / 200-day   $… / $… / $…``.
#: The per-field aliases above can only see the first value in such a row, so the second and third are parsed by
#: position here. cx-cloud CX7 on #2648: a healthy opportunity detail was graded P1 because four fields the page
#: did print were invisible to the parser.
GROUPED_FIELDS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"support\s+1\s*/\s*2\b", re.I), ("support_1", "support_2")),
    (re.compile(r"resistance\s+1\s*/\s*2\b", re.I), ("resistance_1", "resistance_2")),
    (re.compile(r"20\s*/\s*50\s*/\s*200\s*-?\s*day\b", re.I), ("sma_20", "sma_50", "sma_200")),
)

#: A value the surface itself says is absent. A bare "-" is NOT here: MACD's value is often negative.
_ABSENT = re.compile(
    r"^\s*(?:[:=·]\s*)?(?:—|–|n/?a\b|none\b|unknown\b|unavailable\b|not available\b|not served\b|"
    r"missing\b|pending\b|loading\b|no data\b)",
    re.I,
)
_CIO = re.compile(r"\b(?:cio\s+(?:stance|thesis)|stance|thesis)\b", re.I)
_AS_OF = re.compile(r"\b(?:as[_ ]of|dated)\b", re.I)


def _label_present(text: str, labels: Iterable[str]) -> bool:
    """The label appears with a value beside it (same line, or the line below a label-only cell).

    The `(… )` suffix the product prints as part of a label — `RSI (14)` — is consumed WITH the label. Leaving it
    after the match made `(14)` look like the value, so `RSI (14) —` was graded present (triage at c5af7039a).
    """
    for label in labels:
        m = re.search(rf"(?<![A-Za-z0-9]){re.escape(label)}(?:\s*\([^)\n]{{0,24}}\))?(?![A-Za-z0-9])",
                      text, re.I)
        if not m:
            continue
        rest = text[m.end():]
        line, _, tail = rest.partition("\n")
        candidate = line if line.strip() else tail.split("\n", 1)[0]
        if not candidate.strip():
            return True  # the label is present and the surface printed nothing beside it
        if _ABSENT.match(candidate):
            return False
        return True
    return False


def _grouped_present(text: str, pattern: re.Pattern[str], names: tuple[str, ...]) -> Iterable[str]:
    """The fields of one grouped row whose OWN value is printed (not "—" / "n/a").

    `Row` renders its label and value side by side, so Playwright's `inner_text` usually keeps them on one line:
    ``Support 1 / 2   $12.00 / $11.00``. A block layout that puts the value on the following line is accepted too.
    """
    for m in pattern.finditer(text):
        rest = text[m.end():]
        line, _, tail = rest.partition("\n")
        candidate = line.strip() or tail.split("\n", 1)[0].strip()
        values = [part.strip() for part in candidate.split("/")]
        if len(values) < len(names):
            continue  # not the row shape this parser knows; the per-field aliases still apply
        for name, value in zip(names, values):
            if value and not _ABSENT.match(value):
                yield name


def detail_text_to_card(text: str) -> dict[str, Any]:
    """A card dict parsed from the rendered text of an opened detail.

    The crawl captures text, not the component's props, so this reads the labels the product surfaces print.
    It is deliberately conservative about what counts as present: a label whose value is "—" / "n/a" /
    "unavailable" is a gap, and a label with no value beside it is still a stated field (the surface decided to
    print it). A text with no recognizable card label yields an empty dict, which `assess_detail_text()` refuses
    to grade rather than turning every proposal/options detail into a missing-technicals finding.
    """
    body = str(text or "")
    card: dict[str, Any] = {}
    #: A grouped row is a LABEL with several value positions. Its fields are decided only by the positional parser:
    #: the loose per-field alias ("support 1") would otherwise match the label and read the "/ 2" as a value, so
    #: `Support 1 / 2 — / $232` was graded complete (triage at c5af7039a).
    grouped: set[str] = set()
    for pattern, names in GROUPED_FIELDS:
        if pattern.search(body):
            grouped.update(names)
            for name in _grouped_present(body, pattern, names):
                card[name] = "present"
    for name, labels in FIELD_LABELS.items():
        if name in grouped:
            continue
        if _label_present(body, labels):
            card[name] = "present"
    if _CIO.search(body):
        card["cio_stance"] = "present"
        if _AS_OF.search(body):
            card["cio_as_of"] = "present"
    return card


def assess_detail_text(text: str, *, top_list: bool = False) -> dict[str, Any]:
    """Evaluate a captured detail's text with the same completeness rule as a card.

    Returns ``{"evaluated", "severity", "gaps", "card"}``. ``evaluated`` is False when the text is not
    recognizable as a symbol card, so a detail of a different kind is not graded against symbol fields.

    The check exists because cx-cloud found that the crawl recorded "opened: true" for every detail and the same
    successful record whether the detail carried its technical evidence and CIO thesis or not. The captured text is
    the input now, and the severity travels with the detail record.
    """
    card = detail_text_to_card(text)
    if not str(text or "").strip():
        # A detail that opened and rendered nothing is not "unevaluable": it is broken, whatever kind it is.
        return {"evaluated": True, "severity": P1,
                "gaps": [{"field": "detail_text", "reason": "the detail opened but rendered no text"}], "card": card}
    recognised = sum(1 for name in REQUIRED_SYMBOL_FIELDS if _present(card.get(name)))
    has_cio = any(_present(card.get(k)) for k in CIO_FIELDS)
    if recognised < 2 and not has_cio:
        return {"evaluated": False, "severity": None, "gaps": [], "card": card}
    severity, gaps = card_severity(card, top_list=top_list)
    return {"evaluated": True, "severity": severity, "gaps": gaps, "card": card}


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


def _reason(card: dict[str, Any], name: str) -> str | None:
    """The card's own explanation for a missing field, if it gives one."""
    for key in (f"{name}_reason", "missing_reason", "why_missing"):
        value = card.get(key)
        if _present(value):
            return str(value)
    reasons = card.get("missing_reasons")
    if isinstance(reasons, dict) and _present(reasons.get(name)):
        return str(reasons[name])
    return None


def symbol_card_gaps(card: dict[str, Any]) -> list[dict[str, str]]:
    """Every required field that is absent, with the card's stated reason when it has one."""
    out: list[dict[str, str]] = []
    for name in REQUIRED_SYMBOL_FIELDS:
        if not _present(card.get(name)):
            out.append({"field": name, "reason": _reason(card, name) or ""})
    if not any(_present(card.get(k)) for k in CIO_FIELDS):
        out.append({"field": "cio_stance_or_thesis", "reason": _reason(card, "cio") or ""})
    return out


def card_severity(card: dict[str, Any], *, top_list: bool) -> tuple[str | None, list[dict[str, str]]]:
    """(severity, gaps) for one card. None means complete.

    Severity: a top-list card missing any technical field or the CIO thesis is P1; elsewhere a missing field is P2, and
    an unexplained one is P1 because the operator cannot tell a gap from a bug.
    """
    gaps = symbol_card_gaps(card)
    # cx-openai-4 R3 on #2648: a CIO stance or thesis with no as_of is a CLAIM, not evidence — the module already
    # said so in thesis_as_of_missing(), but the function whose docstring says "None means complete" did not ask.
    # A card could therefore be graded complete by card_severity and flagged by the sibling check in the same pass.
    # The clock is part of completeness now, in the one function that decides it.
    if thesis_as_of_missing(card):
        gaps = gaps + [{"field": "cio_as_of", "reason": "the CIO stance or thesis carries no as_of"}]
    if not gaps:
        return None, []
    if top_list:
        return P1, gaps
    if any(not g["reason"] for g in gaps):
        return P1, gaps
    return P2, gaps


def thesis_as_of_missing(card: dict[str, Any]) -> bool:
    """A thesis/stance without an as_of is not evidence; it is a claim."""
    has_cio = any(_present(card.get(k)) for k in CIO_FIELDS)
    return has_cio and not _present(card.get("cio_as_of") or card.get("thesis_as_of"))
