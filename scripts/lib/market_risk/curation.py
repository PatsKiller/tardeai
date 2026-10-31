"""LLM curation of a market-risk card — the model may rephrase ONE sentence, nothing else.

Design DSN-20261031-market-risk-engine §5.10 / P3-T3. Operator 2026-10-31: "you can have normalization and alerts
curated by LLM." The deterministic card (built by the engine, never by a model) is the product. This module may hand
the model the card and the assessment and ask for a plainer "Why:" sentence. The candidate sentence is rejected, and
the deterministic card returned unchanged, when:

* it contains a number that is in neither the card nor the assessment (``agent_number_grounding.check_grounding``
  with a zero-tolerance threshold — one invented figure is enough);
* it contains behaviour wording (buy, sell, trim, share counts, a stop level, an order type, a dollar amount) —
  ``MBI_BEHAVIOR = 0``; patterns live in ``config/market_risk_curation.yaml``;
* the lane chain fails, refuses, returns nothing, or exceeds the tier's time budget (a RED card is never held for prose).

The model call goes through ``scripts/lib/llm_fallback.generate_with_fallback`` with ``allow_paid=False`` and the
registered process ``market_risk_alert_curation`` (free OAuth grok -> chatgpt; the consumption gate and caps apply on
every attempt). Tests inject ``call_model(prompt, timeout_s) -> text | (text, lane)``; nothing here opens a socket of its own. The free lanes
are not subject to the off-peak deferral (that gate covers metered DeepSeek calls only, lib/llm_deferral.py).
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import unicodedata
from typing import Any, Callable, Optional

try:
    from scripts.lib.market_risk.curation_config import CONFIG_PATH, PROJECT_ROOT, load_config  # noqa: F401
except ImportError:  # pragma: no cover — cron path with scripts/ on sys.path
    from lib.market_risk.curation_config import CONFIG_PATH, PROJECT_ROOT, load_config  # type: ignore  # noqa: F401

SCHEMA = "MarketRiskCurationResult@v1"


def _grounding():
    try:
        from scripts.lib import agent_number_grounding as g  # type: ignore
    except ImportError:  # pragma: no cover — cron path with scripts/ on sys.path
        from lib import agent_number_grounding as g  # type: ignore
    return g


def split_why(card_text: str, prefix: str) -> tuple[list[str], Optional[int]]:
    """Card lines and the index of the "Why:" line (None when the card has none)."""
    lines = card_text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith(prefix.strip()):
            return lines, i
    return lines, None


# Typographic characters a model legitimately writes, folded to ASCII before the template check.
_FOLD = {
    "\u2019": "'",
    "\u2018": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2014": "-",
    "\u2013": "-",
    "\u00b7": ";",
    "\u00d7": "x",
    "\u2026": "...",
}


def normalize(text: str) -> str:
    """NFKC-normalised text with every format character (Unicode category Cf: zero-width space, joiners, BOM, bidi
    marks) removed, so "S\u200bell" cannot hide "Sell" from the checks (review of #2383, B3)."""
    t = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(ch for ch in t if unicodedata.category(ch) != "Cf")


def fold_ascii(text: str) -> str:
    """``normalize`` plus the typographic folds in ``_FOLD``."""
    t = normalize(text)
    return "".join(_FOLD.get(ch, ch) for ch in t)


def non_ascii_chars(text: str) -> list[str]:
    """Characters left outside printable ASCII after folding. Confusables (Cyrillic "\u0405", Greek "\u039f"),
    keycaps, emoji and variation selectors all land here and are refused — the "why" is plain English."""
    return sorted({ch for ch in fold_ascii(text) if not (" " <= ch <= "~")})


def non_ascii_digits(text: str) -> list[str]:
    """Digits outside 0-9 that survive NFKC (Arabic-Indic, Devanagari, ...): invisible to grounding, so refused."""
    return sorted({ch for ch in normalize(text) if ch.isdigit() and not ("0" <= ch <= "9")})


def behaviour_hits(text: str, patterns: list[str]) -> list[str]:
    t = normalize(text)
    return [p for p in patterns if re.search(p, t, flags=re.IGNORECASE)]


def allowed_figures(assessment: dict[str, Any]) -> str:
    """The ONLY figures the model may repeat: the score, the market score, the confirming count and each displayed
    contributor's points and headline (review of #2362, B3). Dates, evidence prices and the rest of the JSON are not
    grounding material — "any number anywhere" let a stop under 712.5 through."""
    parts: list[str] = []
    for k in ("score", "market_score"):
        v = assessment.get(k)
        if isinstance(v, (int, float)):
            parts.append(str(round(float(v))))
    if isinstance(assessment.get("confirming"), (int, float)):
        parts.append(str(int(assessment["confirming"])))
    for c in (assessment.get("contributors") or [])[:5]:
        if not isinstance(c, dict):
            continue
        if isinstance(c.get("points"), (int, float)):
            parts.append(str(round(float(c["points"]))))
        for k in ("headline", "detail"):  # assessment shape and projection shape
            if c.get(k):
                parts.append(str(c[k]))
    return "\n".join(parts)


_NUM_TOKEN = re.compile(r"\d+(?:[.,]\d+)*")


def _num_key(raw: str) -> str | None:
    """Canonical form of a numeric token: "3.970" -> "3.97", "50" -> "50". A comma is never read as a decimal
    point or a thousands mark ("3,97" and "1,000" are not figures the engine displays), so it never matches."""
    if "," in raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return f"{v:.6f}".rstrip("0").rstrip(".")


def ungrounded_numbers(sentence: str, card_text: str, assessment: dict[str, Any]) -> list[str]:
    """Every numeric token in ``sentence`` that is not one of the displayed figures (``allowed_figures``). Zero
    tolerance and NO trivial-number exemption: ``agent_number_grounding`` skips integers up to 31 and 1900-2100, which
    let "QQQ could fall 25 percent" and "the S&P could drop to 2050" through (review of #2383, B3). ``card_text`` is
    accepted for signature compatibility and deliberately not used as grounding."""
    allowed = {k for k in (_num_key(m) for m in _NUM_TOKEN.findall(normalize(allowed_figures(assessment)))) if k}
    out: list[str] = []
    for m in _NUM_TOKEN.findall(normalize(sentence)):
        k = _num_key(m)
        if k is None or k not in allowed:
            out.append(m)
    return out


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9/&'-]*")


def template_vocabulary(assessment: dict[str, Any], cfg: dict[str, Any]) -> set[str]:
    """The allow-list template: the descriptive words in ``cfg['why_vocabulary']`` plus every word of the
    contributors' displayed names and headlines and the category names. Nothing else may appear in the sentence."""
    words = {str(w).lower() for w in cfg.get("why_vocabulary") or []}
    for c in (assessment.get("contributors") or [])[:5]:
        if not isinstance(c, dict):
            continue
        for k in ("category", "name", "headline", "detail"):
            for w in _WORD.findall(fold_ascii(str(c.get(k) or "").replace("_", " "))):
                words.add(w.lower())
    for o in assessment.get("observations") or []:
        if isinstance(o, dict) and o.get("category"):
            words.update(w.lower() for w in str(o["category"]).split("_"))
    return words


def off_template_words(sentence: str, assessment: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    """Words outside the template. Numbers are checked separately (``ungrounded_numbers``)."""
    vocab = template_vocabulary(assessment, cfg)
    text = _NUM_TOKEN.sub(" ", fold_ascii(sentence))
    return sorted({w for w in _WORD.findall(text) if w.lower() not in vocab and w.lower().rstrip("'s") not in vocab})


def build_prompt(card_text: str, assessment: dict[str, Any], current_why: str, cfg: dict[str, Any]) -> str:
    facts = {
        "tier": assessment.get("tier"),
        "score": assessment.get("score"),
        "confirming": assessment.get("confirming"),
        "contributors": assessment.get("contributors"),
        "deescalates_if": assessment.get("deescalates_if"),
        "as_of": assessment.get("as_of"),
    }
    return (
        "You rewrite ONE sentence of a market-risk alert for a busy investor reading on a phone.\n"
        f"Return only the sentence, at most {int(cfg.get('max_why_chars') or 280)} characters, no prefix, no quotes.\n"
        "RULES: say why risk is at this level, using only the facts below. Do not add any number that is not in the "
        "facts. Do not recommend buying, selling, trimming, hedging, a stop level, an order or a position size. "
        "Do not reassure and do not exaggerate. Use only the category names, words from the contributor lines and "
        "these words: " + ", ".join(sorted(str(w) for w in cfg.get("why_vocabulary") or [])) + ".\n\n"
        f"CURRENT SENTENCE: {current_why or '(none)'}\n\n"
        f"CARD:\n{card_text}\n\nFACTS:\n{json.dumps(facts, default=str, indent=1)}\n"
    )


def default_call_model(cfg: dict[str, Any]) -> Callable[[str, float], Any]:
    """Production model call: the governed free-lane fallback chain, never a provider client of our own."""

    def _call(prompt: str, timeout_s: float) -> str:
        try:
            from scripts.lib.llm_fallback import generate_with_fallback  # type: ignore
        except ImportError:  # pragma: no cover
            from lib.llm_fallback import generate_with_fallback  # type: ignore
        res = generate_with_fallback(
            prompt,
            lane=str(cfg.get("lane") or "grok"),
            allow_paid=bool(cfg.get("allow_paid", False)),
            process_id=str(cfg.get("process_id") or "market_risk_alert_curation"),
            timeout=float(timeout_s),
            max_tokens=int(cfg.get("max_tokens") or 200),
        )
        return str(getattr(res, "text", "") or ""), str(getattr(res, "lane", "") or "")

    return _call


def _result(text: str, *, curated: bool, lane: Optional[str], reason: str, **extra: Any) -> dict[str, Any]:
    return {"schema": SCHEMA, "text": text, "curated": curated, "lane": lane, "reason": reason, **extra}


def curate(
    card_text: str,
    assessment: dict[str, Any],
    *,
    call_model: Optional[Callable[[str, float], Any]] = None,
    cfg: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return ``{text, curated, lane, reason}``. ``text`` is always sendable; on any doubt it is ``card_text``."""
    cfg = cfg if cfg is not None else load_config()
    if not cfg.get("enabled", False):
        return _result(card_text, curated=False, lane=None, reason="curation disabled")
    tier = str(assessment.get("tier") or "").upper()
    if tier in {str(t).upper() for t in (cfg.get("skip_tiers") or [])}:
        return _result(card_text, curated=False, lane=None, reason=f"tier {tier} is never curated")
    prefix = str(cfg.get("why_prefix") or "Why: ")
    lines, idx = split_why(card_text, prefix)
    current = lines[idx].strip()[len(prefix.strip()) :].strip() if idx is not None else ""
    budgets = cfg.get("timeout_s") or {}
    timeout_s = float(budgets.get(tier, budgets.get("default", 10)))
    call = call_model or default_call_model(cfg)
    prompt = build_prompt(card_text, assessment, current, cfg)

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(call, prompt, timeout_s)
    try:
        answer = fut.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        pool.shutdown(wait=False, cancel_futures=True)
        return _result(card_text, curated=False, lane=None, reason=f"timeout after {timeout_s:g}s")
    except Exception as exc:  # noqa: BLE001 — every lane failure is a reason, and the deterministic card is sent
        pool.shutdown(wait=False, cancel_futures=True)
        return _result(card_text, curated=False, lane=None, reason=f"lane failure: {type(exc).__name__}: {exc}"[:240])
    pool.shutdown(wait=False)

    lane = str(cfg.get("lane") or "grok")
    if isinstance(answer, tuple):  # (text, lane that answered) from the fallback chain
        answer, lane = answer[0], (answer[1] or lane)
    sentence = " ".join(str(answer or "").split()).strip().strip('"').strip()
    if sentence.lower().startswith(prefix.strip().lower()):
        sentence = sentence[len(prefix.strip()) :].strip()
    if not sentence:
        return _result(card_text, curated=False, lane=lane, reason="empty answer")
    if len(sentence) > int(cfg.get("max_why_chars") or 280):
        return _result(card_text, curated=False, lane=lane, reason="answer longer than max_why_chars")
    odd = non_ascii_digits(sentence)
    if odd:
        return _result(card_text, curated=False, lane=lane, reason="non-ASCII digits rejected", rejected=odd)
    odd = non_ascii_chars(sentence)
    if odd:
        return _result(card_text, curated=False, lane=lane, reason="non-ASCII characters rejected", rejected=odd)
    sentence = fold_ascii(sentence)
    hits = behaviour_hits(sentence, list(cfg.get("behaviour_patterns") or []))
    if hits:
        return _result(card_text, curated=False, lane=lane, reason="behaviour wording rejected", rejected=hits)
    bad = ungrounded_numbers(sentence, card_text, assessment)
    if bad:
        return _result(card_text, curated=False, lane=lane, reason="ungrounded numbers rejected", rejected=bad)
    off = off_template_words(sentence, assessment, cfg)
    if off:
        return _result(card_text, curated=False, lane=lane, reason="words outside the template rejected", rejected=off)

    new_line = f"{prefix}{sentence}"
    if idx is None:
        lines = lines[:1] + [new_line] + lines[1:]
    else:
        lines[idx] = new_line
    return _result("\n".join(lines), curated=True, lane=lane, reason="grounded", original_why=current)
