"""LLM curation of a market-risk card — the model may only CHOOSE phrases for ONE sentence, never write it.

Template mode (review of #2383 round 2, B3; operator 2026-10-31 "we got to get it working correctly"): the model
returns a JSON choice of phrase ids from ``why_template.phrase_bank`` in ``config/market_risk_curation.yaml`` plus which
displayed contributors fill the slots. ``render_choice`` builds the sentence from the engine's own names and displayed
figures; free text is never sent. The checks below still run on every rendered sentence (defence in depth).

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

import json
import math
import re
import threading
import unicodedata
from typing import Any, Callable, Optional

try:
    from scripts.lib.market_risk.curation_config import CONFIG_PATH, PROJECT_ROOT, load_config  # noqa: F401
except ImportError:  # pragma: no cover — cron path with scripts/ on sys.path
    from lib.market_risk.curation_config import CONFIG_PATH, PROJECT_ROOT, load_config  # type: ignore  # noqa: F401

SCHEMA = "MarketRiskCurationResult@v1"
# The only tiers whose "why" may ever be curated. Code, not config: ORANGE, RED, NONE, an empty or unknown tier are
# refused before the config is read (review #2406 F2).
CURATABLE = frozenset({"BLUE", "YELLOW", "GREEN"})


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
        v = _finite(assessment.get(k))
        if v is not None:
            parts.append(str(round(v)))
    n, of = _confirming(assessment)
    for v in (n, of):
        if v is not None:
            parts.append(str(v))
    obs = [o for o in assessment.get("observations") or [] if isinstance(o, dict)]
    if obs:
        parts.append(str(sum(1 for o in obs if str(o.get("state") or "").upper() == "UNKNOWN")))
    for c in (assessment.get("contributors") or [])[:5]:
        if not isinstance(c, dict):
            continue
        if _finite(c.get("points")) is not None:
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
    for phrase in ((cfg.get("why_template") or {}).get("phrase_bank") or {}).values():
        for w in _WORD.findall(re.sub(r"\{[a-z0-9_]+\}", " ", str(phrase))):
            words.add(w.lower())
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
    return sorted({w for w in _WORD.findall(text) if not _in_vocab(w.lower(), vocab)})


def _in_vocab(w: str, vocab: set[str]) -> bool:
    """Exact plural rule: the word itself, or a possessive / plural of a listed word of 3+ letters. Never ``rstrip``
    (review #2383 round 3: ``"ass".rstrip("'s")`` is ``"a"``, which let "Ass." through)."""
    if w in vocab:
        return True

    def ok(base: str) -> bool:
        return len(base) >= 3 and base in vocab

    if w.endswith("'s") and ok(w[:-2]):
        return True
    if w.endswith("ies") and ok(w[:-3] + "y"):
        return True
    if w.endswith("es") and w[:-2].endswith(("s", "x", "z", "ch", "sh")) and ok(w[:-2]):
        return True
    return w.endswith("s") and not w.endswith("ss") and ok(w[:-1])


class ChoiceRejected(ValueError):
    """The model's answer is not a valid phrase choice."""


def _contributors(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in (assessment.get("contributors") or [])[:5] if isinstance(c, dict)]


def _display_name(c: dict[str, Any]) -> str:
    raw = str(c.get("name") or c.get("category") or "").replace("_", " ").strip()
    return raw[:1].upper() + raw[1:] if raw else ""


def _confirming(assessment: dict[str, Any]) -> tuple[Optional[int], Optional[int]]:
    v = assessment.get("confirming")
    if isinstance(v, dict):
        n, of = v.get("n"), v.get("of")
        fn, fo = _finite(n), _finite(of)
        return (int(fn) if fn is not None else None, int(fo) if fo is not None else None)
    if _finite(v) is not None:
        obs = [o for o in assessment.get("observations") or [] if isinstance(o, dict)]
        return int(v), (len(obs) or None)
    return None, None


def _finite(v: Any) -> Optional[float]:
    """A finite int/float, never a bool, NaN or inf (review #2406 F6)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        return None
    return float(v)


def _points(c: dict[str, Any]) -> float:
    v = _finite(c.get("points"))
    if v is None and "points" in c:
        raise ChoiceRejected(f"contributor points are not a finite number: {type(c.get('points')).__name__}")
    return v if v is not None else 0.0


def unmeasured_clause(n: int) -> str:
    """F8: '1 category is unmeasured', '2 categories are unmeasured'."""
    return f"{n} category is unmeasured" if n == 1 else f"{n} categories are unmeasured"


def slot_values(assessment: dict[str, Any], picks: list[int]) -> dict[str, str]:
    """Slot text from the assessment only. ``picks`` are 1-based positions of displayed contributors for c1, c2."""
    cons = _contributors(assessment)
    vals: dict[str, str] = {}
    for slot, pos in zip(("c1", "c2"), picks):
        c = cons[pos - 1]
        vals[slot] = _display_name(c)
        if "points" in c:
            vals[f"{slot}_points"] = str(round(_points(c)))
        detail = str(c.get("headline") or c.get("detail") or "").strip().rstrip(".")
        if detail:
            vals[f"{slot}_detail"] = detail
    score = _finite(assessment.get("score"))
    if score is not None:
        vals["score"] = str(round(score))
    n, of = _confirming(assessment)
    if n is not None and of is not None:
        vals["confirming"], vals["of"] = str(n), str(of)
    obs = [o for o in assessment.get("observations") or [] if isinstance(o, dict)]
    if obs:
        vals["unmeasured_clause"] = unmeasured_clause(
            sum(1 for o in obs if str(o.get("state") or "").upper() == "UNKNOWN")
        )
    return vals


_SLOT = re.compile(r"\{([a-z0-9_]+)\}")


def parse_choice(answer: str, assessment: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Strictly parse ``{"phrases": [{"id": <bank id>, "c": [i, j]}, ...]}``. Anything else raises ChoiceRejected."""
    text = str(answer or "").strip()
    if text.startswith("```"):  # a fenced JSON block is the only wrapper tolerated
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    if not text.startswith("{"):
        raise ChoiceRejected("answer is not a JSON phrase choice")
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise ChoiceRejected(f"answer is not valid JSON ({type(exc).__name__})") from exc
    if not isinstance(doc, dict) or set(doc) != {"phrases"} or not isinstance(doc["phrases"], list):
        raise ChoiceRejected('answer must be exactly {"phrases": [...]}')
    tpl = cfg.get("why_template") or {}
    bank = tpl.get("phrase_bank") or {}
    max_n = int(tpl.get("max_phrases") or 3)
    items = doc["phrases"]
    if not 1 <= len(items) <= max_n:
        raise ChoiceRejected(f"choose 1 to {max_n} phrases")
    n_cons = len(_contributors(assessment))
    if n_cons == 0:
        raise ChoiceRejected("the card shows no contributors to describe")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict) or not set(it) <= {"id", "c"} or not isinstance(it.get("id"), str):
            raise ChoiceRejected('each phrase is {"id": <bank id>, "c": [positions]}')
        pid = it["id"]
        if pid not in bank:
            raise ChoiceRejected(f"unknown phrase id {pid[:40]!r}")
        if pid in seen:
            raise ChoiceRejected(f"phrase {pid!r} chosen twice")
        seen.add(pid)
        picks = it.get("c", list(range(1, min(2, n_cons) + 1)))
        if (
            not isinstance(picks, list)
            or len(picks) > 2
            or not all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= n_cons for x in picks)
            or len(set(picks)) != len(picks)
        ):
            raise ChoiceRejected("contributor positions out of range")
        out.append({"id": pid, "c": picks or [1]})
    return out


_CALM_WORDS = re.compile(r"\b(calm|quiet|steady|low|lower|easing|eased|fading|normal|benign|safe)\b", re.IGNORECASE)
_ELEVATED = {"YELLOW", "ORANGE", "RED"}


def _phrase_allowed(pid: str, assessment: dict[str, Any], tpl: dict[str, Any]) -> Optional[str]:
    """A phrase's precondition; returns the refusal reason or None. ``calm_rest`` claims the other categories are
    calm, so it needs every observation outside the displayed contributors to be CALM and a tier below YELLOW."""
    req = ((tpl.get("requires") or {}).get(pid)) or {}
    tier = str(assessment.get("tier") or "").upper()
    allowed_tiers = req.get("tiers")
    if allowed_tiers and tier not in {str(t).upper() for t in allowed_tiers}:
        return f"phrase {pid!r} is not allowed at tier {tier or 'unknown'}"
    if req.get("others_calm"):
        shown = {str(c.get("category") or "") for c in _contributors(assessment)}
        others = [
            o for o in assessment.get("observations") or [] if isinstance(o, dict) and o.get("category") not in shown
        ]
        if not others or any(str(o.get("state") or "").upper() != "CALM" for o in others):
            return f"phrase {pid!r} needs every other measured category to read CALM"
    return None


_HEADER_CONFIRM = re.compile(r"(\d+) of (\d+) categories confirm")


def _top_position(assessment: dict[str, Any]) -> int:
    """1-based position of the displayed contributor with the most points (first on a tie)."""
    cons = _contributors(assessment)
    best = max(range(len(cons)), key=lambda i: (_points(cons[i]), -i))
    return best + 1


def render_choice(
    choice: list[dict[str, Any]], assessment: dict[str, Any], cfg: dict[str, Any], card_text: str = ""
) -> str:
    """The sentence, rendered from the bank and the assessment. A slot with no value rejects the whole choice.

    Review #2406: positions carry meaning, so ``lead`` and ``score`` always put the top-points contributor in {c1}
    (F3); ``pair`` needs its two contributors to hold at least half the displayed points (F3); ``calm_rest`` needs
    another phrase, every displayed contributor named, and every other observation CALM (F4); ``confirm`` must match
    the card header's "n of N" (F5)."""
    tpl = cfg.get("why_template") or {}
    bank = tpl.get("phrase_bank") or {}
    cons = _contributors(assessment)
    n_cons = len(cons)
    total = sum(max(_points(c), 0.0) for c in cons)
    parts: list[str] = []
    named: set[int] = set()
    for it in choice:
        why_not = _phrase_allowed(it["id"], assessment, tpl)
        if why_not:
            raise ChoiceRejected(why_not)
        picks = [p for p in it["c"] if p <= n_cons]
        if it["id"] in ("lead", "score"):
            top = _top_position(assessment)
            picks = [top] + [p for p in picks if p != top]
        if len(picks) < 2:  # c2 defaults to the next displayed contributor when one exists
            rest = [i for i in range(1, n_cons + 1) if i not in picks]
            picks = (picks + rest)[:2]
        if it["id"] == "pair":
            if len(picks) < 2 or total <= 0:
                raise ChoiceRejected("phrase 'pair' needs two contributors with points")
            share = (max(_points(cons[picks[0] - 1]), 0.0) + max(_points(cons[picks[1] - 1]), 0.0)) / total
            if share < float(tpl.get("pair_min_share", 0.5)):
                raise ChoiceRejected(f"phrase 'pair' needs at least half the points, these two hold {share:.0%}")
        if it["id"] == "confirm":
            m = _HEADER_CONFIRM.search(fold_ascii(card_text or ""))
            n, of = _confirming(assessment)
            if not m or (n, of) != (int(m.group(1)), int(m.group(2))):
                raise ChoiceRejected("phrase 'confirm' must match the card header's count")
        vals = slot_values(assessment, picks)
        phrase = str(bank[it["id"]])
        slots = _SLOT.findall(phrase)
        missing = [m for m in slots if m not in vals]
        if missing:
            raise ChoiceRejected(f"phrase {it['id']!r} needs {', '.join(missing)}, which the card does not show")
        named.update(pos for slot, pos in zip(("c1", "c2"), picks) if any(x.startswith(slot) for x in slots))
        parts.append(_SLOT.sub(lambda m: vals[m.group(1)], phrase))
    if any(it["id"] == "calm_rest" for it in choice):
        if len(choice) < 2:
            raise ChoiceRejected("phrase 'calm_rest' cannot stand alone")
        if named != set(range(1, n_cons + 1)):
            raise ChoiceRejected("phrase 'calm_rest' needs every displayed contributor named first")
        shown = {str(cons[i - 1].get("category") or "") for i in named}
        others = [
            o for o in assessment.get("observations") or [] if isinstance(o, dict) and o.get("category") not in shown
        ]
        if not others or any(str(o.get("state") or "").upper() != "CALM" for o in others):
            raise ChoiceRejected("phrase 'calm_rest' needs every other observation to read CALM")
    return " ".join(parts)


def imperative_openings(sentence: str, cfg: dict[str, Any]) -> list[str]:
    """Sentences that open with a verb of command ("Lower risk now.", "Hedging now ..."): refused (review #2383 r3)."""
    verbs = {str(v).lower() for v in cfg.get("imperative_openers") or []}
    out = []
    for part in re.split(r"(?<=[.;:!?])\s+", sentence.strip()):
        m = _WORD.search(part)
        if m and m.group(0).lower() in verbs:
            out.append(m.group(0))
    return out


def labelled_spans(assessment: dict[str, Any]) -> list[str]:
    """Every figure the "why" may show, WITH its own label (review #2383 round 3: grounding checked values, not
    meaning, so "Index fell 50 percent" reused the score). A number is allowed only inside one of these spans."""
    spans: list[str] = []
    if _finite(assessment.get("score")) is not None:
        spans.append(f"score reads {round(float(assessment['score']))}")
    n, of = _confirming(assessment)
    if n is not None and of is not None:
        spans.append(f"{n} of {of} categories")
    for c in _contributors(assessment):
        if _finite(c.get("points")) is not None:
            spans.append(f"{round(float(c['points']))} points")
        d = str(c.get("headline") or c.get("detail") or "").strip().rstrip(".")
        if d:
            spans.append(fold_ascii(d))
    obs = [o for o in assessment.get("observations") or [] if isinstance(o, dict)]
    if obs:
        spans.append(unmeasured_clause(sum(1 for o in obs if str(o.get("state") or "").upper() == "UNKNOWN")))
    return sorted(spans, key=len, reverse=True)


def unlabelled_numbers(sentence: str, assessment: dict[str, Any]) -> list[str]:
    """Numbers left after removing every labelled span: each one is a figure used out of its own context."""
    rest = fold_ascii(sentence)
    for sp in labelled_spans(assessment):
        rest = rest.replace(sp, " ")
    return _NUM_TOKEN.findall(rest)


def validate_sentence(
    sentence: str, card_text: str, assessment: dict[str, Any], cfg: dict[str, Any]
) -> Optional[tuple[str, list[str]]]:
    """Every check a "why" sentence must pass, rendered or not. Returns (reason, rejected) or None when it passes."""
    if len(sentence) > int(cfg.get("max_why_chars") or 280):
        return "answer longer than max_why_chars", []
    odd = non_ascii_digits(sentence)
    if odd:
        return "non-ASCII digits rejected", odd
    odd = non_ascii_chars(sentence)
    if odd:
        return "non-ASCII characters rejected", odd
    sentence = fold_ascii(sentence)
    hits = behaviour_hits(sentence, list(cfg.get("behaviour_patterns") or []))
    if hits:
        return "behaviour wording rejected", hits
    imp = imperative_openings(sentence, cfg)
    if imp:
        return "imperative wording rejected", imp
    if str(assessment.get("tier") or "").upper() in _ELEVATED and _CALM_WORDS.search(sentence):
        return "calm wording on an elevated tier rejected", sorted(
            {m.group(0).lower() for m in _CALM_WORDS.finditer(sentence)}
        )
    bad = ungrounded_numbers(sentence, card_text, assessment)
    if bad:
        return "ungrounded numbers rejected", bad
    off = off_template_words(sentence, assessment, cfg)
    if off:
        return "words outside the template rejected", off
    loose = unlabelled_numbers(sentence, assessment)
    if loose:
        return "numbers outside their own label rejected", loose
    return None


def build_prompt(card_text: str, assessment: dict[str, Any], current_why: str, cfg: dict[str, Any]) -> str:
    """The model sees the phrase bank and the displayed contributors and returns ONLY a JSON phrase choice."""
    tpl = cfg.get("why_template") or {}
    bank = tpl.get("phrase_bank") or {}
    cons = [
        {
            "position": i,
            "name": _display_name(c),
            "points": c.get("points"),
            "detail": c.get("headline") or c.get("detail"),
        }
        for i, c in enumerate(_contributors(assessment), 1)
    ]
    return (
        "Choose how to explain ONE line of a market-risk alert. Do not write any sentence yourself.\n"
        'Return ONLY JSON: {"phrases": [{"id": "<phrase id>", "c": [<contributor position>, ...]}]} with 1 to '
        f'{int(tpl.get("max_phrases") or 3)} phrases, most important first. "c" lists which contributors fill '
        "{c1} and {c2} (default [1, 2]). Use only these phrase ids:\n"
        + "\n".join(f"- {k}: {v}" for k, v in bank.items())
        + f"\n\nCONTRIBUTORS:\n{json.dumps(cons, default=str, indent=1)}\n"
        f"TIER: {assessment.get('tier')}  SCORE: {assessment.get('score')}\n"
        f"CURRENT LINE: {current_why or '(none)'}\n"
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
    tier = fold_ascii(str(assessment.get("tier") or "")).strip().upper()
    if tier not in CURATABLE:  # code floor, checked before any config (review #2406 F2)
        return _result(card_text, curated=False, lane=None, reason=f"tier {tier or 'missing'} is never curated")
    cfg = cfg if cfg is not None else load_config()
    if not cfg.get("enabled", False):
        return _result(card_text, curated=False, lane=None, reason="curation disabled")
    if tier in {str(t).upper() for t in (cfg.get("skip_tiers") or [])}:
        return _result(card_text, curated=False, lane=None, reason=f"tier {tier} is never curated")
    prefix = str(cfg.get("why_prefix") or "Why: ")
    lines, idx = split_why(card_text, prefix)
    current = lines[idx].strip()[len(prefix.strip()) :].strip() if idx is not None else ""
    budgets = cfg.get("timeout_s") or {}
    timeout_s = float(budgets.get(tier, budgets.get("default", 10)))
    call = call_model or default_call_model(cfg)
    prompt = build_prompt(card_text, assessment, current, cfg)

    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["answer"] = call(prompt, timeout_s)
        except BaseException as exc:  # noqa: BLE001 — reported below as a lane failure
            box["error"] = exc

    # A daemon thread: a hung lane can never hold the evaluator process open (review #2406 F7).
    worker = threading.Thread(target=_run, name="market-risk-curation", daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        return _result(card_text, curated=False, lane=None, reason=f"timeout after {timeout_s:g}s")
    if "error" in box:
        exc = box["error"]
        return _result(card_text, curated=False, lane=None, reason=f"lane failure: {type(exc).__name__}: {exc}"[:240])
    answer = box.get("answer")

    lane = str(cfg.get("lane") or "grok")
    if isinstance(answer, tuple):  # (text, lane that answered) from the fallback chain
        answer, lane = answer[0], (answer[1] or lane)
    if not str(answer or "").strip():
        return _result(card_text, curated=False, lane=lane, reason="empty answer")
    try:
        choice = parse_choice(str(answer), assessment, cfg)
        sentence = render_choice(choice, assessment, cfg, card_text)
    except ChoiceRejected as exc:
        return _result(card_text, curated=False, lane=lane, reason=f"not a phrase choice: {exc}"[:240])
    bad = validate_sentence(sentence, card_text, assessment, cfg)
    if bad:
        return _result(card_text, curated=False, lane=lane, reason=bad[0], rejected=bad[1])
    sentence = fold_ascii(sentence)

    new_line = f"{prefix}{sentence}"
    if idx is None:
        lines = lines[:1] + [new_line] + lines[1:]
    else:
        lines[idx] = new_line
    return _result("\n".join(lines), curated=True, lane=lane, reason="grounded", original_why=current, choice=choice)
