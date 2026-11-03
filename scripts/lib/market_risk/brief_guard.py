"""Hardened checks for model prose in the Market Risk deep brief (MBI_BEHAVIOR = 0).

The round-2 review of #2383 showed the reused curation checks let paraphrased advice ("Add on weakness", "Size down",
"Halve NVDA", "Tighten your stops", "Stand aside", "Keep powder dry"), invisible or look-alike characters (zero-width
joiners, Cyrillic letters) and small invented numbers through (``agent_number_grounding`` treats integers up to 31 and
1900-2100 as trivial). The deep brief therefore uses its own, stricter gate. A sentence passes only if ALL hold:

1. **Characters.** After NFKC, every character is printable ASCII or one of a few typographic marks (curly quotes,
   dashes, bullet, ellipsis), which are then folded to ASCII. Format characters (zero-width), non-Latin letters
   (Cyrillic/Greek confusables), emoji and keycaps are refused outright rather than "cleaned".
2. **Descriptive only.** No first- or second-person words (I, we, our, you, your ...); no advice modals (should, must,
   need to, consider, recommend, suggest, makes sense, time to, wise, prudent ...); no imperative opening (a sentence
   starting with an action verb such as sell, add, size, hedge, tighten, stand, keep, wait, expect ...); and no
   behaviour wording anywhere (the curation lexicon plus a longer list of trading phrasings).
3. **No spelled-out quantities.** Number words (five, twenty, hundred, half, quarter, double, halve ...) are refused,
   so a figure cannot be smuggled past the digit check.
4. **Grounding without exemptions.** Every numeric token in the sentence (after removing citations) must appear,
   character for character, as a numeric token in the facts that sentence cites. No "trivial number" exemption.
5. **Citations.** At least one citation, every cited id exists.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

TYPO = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "•": "-", "·": "-", "…": "..."}
CITE = re.compile(r"\[([a-z]+-[a-z]+(?:\s*,\s*[a-z]+-[a-z]+)*)\]")
NUM = re.compile(r"\d+(?:[.,]\d+)*")

PERSON = re.compile(
    r"\b(i|i'm|i'd|we|we're|we'd|us|our|ours|my|me|you|you're|you'd|you'll|your|yours|yourself|"
    r"investors? (?:should|must|may want))\b",
    re.I,
)
MODAL = re.compile(
    r"\b(should|ought|must|need(?:s)? to|have to|has to|consider|recommend\w*|suggest\w*|advis\w*|makes? sense|"
    r"time to|(?:it is|it's) (?:wise|prudent|best|better)|wise|prudent|better to|best to|let's|let us|please|"
    r"don't|do not|never|avoid|be (?:a |an )?(?:seller|buyer|careful|cautious|defensive))\b",
    re.I,
)
ACTION = re.compile(
    r"\b(buy\w*|sell\w*|short\w*|cover\w*|trim\w*|reduc\w*|pare\w*|cut\w*|halv\w*|quarter the|double (?:down|up)|"
    r"add(?:s|ing)? (?:on|to|more)|accumulat\w*|load\w* up|back(?:ing)? up the truck|lock\w* in|book\w* (?:gains|profits?)|"
    r"take (?:some )?(?:chips|profits?|gains)|ring\w* the register|lighten\w*|unload\w*|dump\w*|offload\w*|shed\w*|"
    r"unwind\w*|liquidat\w*|exit\w*|clos(?:e|es|ing) (?:out|the \w+ position|positions?)|bail\w*|run for the exits|"
    r"under ?weight\w*|over ?weight\w*|go(?:es|ing)? (?:defensive|long|short|to cash)|get(?:s|ting)? (?:long|short|out)|"
    r"move\w* (?:into|to|out)|switch\w* (?:to|into)|park\w*|rotat\w*|realloc\w*|allocat\w*|rebalanc\w*|deploy\w*|"
    r"stand\w* aside|step\w* aside|sit\w* (?:on|out)|powder dry|chas\w*|wait\w* (?:before|for)|hold\w* off|"
    r"size (?:down|up)|siz(?:e|ing) (?:the|a|your)|position[- ]?siz\w*|tighten\w*|trail\w*|stops?\b|stop[- ]loss|"
    r"protect\w*|protection|collar\w*|hedg\w* with|long volatility|lessen\w*|diminish\w*|dial\w* (?:down|back)|"
    r"turn\w* down|tone\w* down|scale\w* (?:back|in|out|down)|pull\w* back|purchas\w*|raise\w* cash|cash buffer|"
    r"t-?bills?|treasur\w* (?:as|for)|safe haven|entry|entries|re-?enter\w*|opportunit\w*|bargain\w*|cheap)\b",
    re.I,
)
IMPERATIVE_START = re.compile(
    r"^(reduce|pare|sell|buy|add|size|hedge|trim|lock|go|load|tighten|trail|accumulate|back|take|book|lower|raise|move|"
    r"switch|park|ring|stay|close|bail|run|lessen|diminish|protect|get|short|stand|wait|keep|sit|be|purchase|unwind|"
    r"halve|quarter|dial|turn|tone|scale|pull|cut|exit|avoid|hold|consider|watch|monitor|review|expect|use|put|set|"
    r"place|check|look|think|act|stop|start|increase|decrease|rebalance|rotate|shift|lighten|reallocate|allocate|"
    r"deploy|liquidate|cover|enter|rebuy|average|double|plan|prepare|brace|stay|remain|note|remember|beware|"
    r"don't|do|never|let's|let|please)\b",
    re.I,
)
NUMBER_WORDS = re.compile(
    r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|"
    r"billion|half|halve|halving|quarter|third|double|triple|twice|thrice|dozen|percent)\b",
    re.I,
)


def clean(text: str) -> tuple[str, list[str]]:
    """NFKC + typographic folding. Returns the text and the list of refused characters (empty when clean)."""
    t = unicodedata.normalize("NFKC", str(text or ""))
    bad: list[str] = []
    out = []
    for ch in t:
        if ch in TYPO:
            out.append(TYPO[ch])
        elif ch == "\n" or (" " <= ch <= "~"):
            out.append(ch)
        else:
            bad.append(f"U+{ord(ch):04X}")
    return "".join(out), sorted(set(bad))


def numeric_tokens(text: str) -> list[str]:
    return [m.group(0) for m in NUM.finditer(text)]


def check_sentence(sentence: str, cited_texts: Iterable[str], extra_patterns: Iterable[str] = ()) -> list[str]:
    """Reasons this sentence is refused (empty list = it passes). ``sentence`` must already be clean()ed."""
    bare = CITE.sub("", sentence).strip()
    reasons: list[str] = []
    if PERSON.search(bare):
        reasons.append("first/second person")
    if MODAL.search(bare):
        reasons.append("advice modal")
    if IMPERATIVE_START.match(bare.lstrip("\"' -")):
        reasons.append("imperative opening")
    if ACTION.search(bare):
        reasons.append("action wording")
    for p in extra_patterns:
        if re.search(p, bare, flags=re.I):
            reasons.append("curation lexicon")
            break
    if NUMBER_WORDS.search(bare):
        reasons.append("spelled-out quantity")
    allowed = {tok for t in cited_texts for tok in numeric_tokens(clean(t)[0])}
    unsupported = [tok for tok in numeric_tokens(bare) if tok not in allowed]
    if unsupported:
        reasons.append(f"ungrounded numbers {unsupported}")
    return reasons


def check_text(text: str, facts_by_id: dict[str, dict[str, Any]], titles: set[str], extra: Iterable[str] = ()) -> dict:
    """Validate a whole draft: every non-heading line is split into sentences, each must cite and pass."""
    cleaned, bad_chars = clean(text)
    reasons: list[str] = []
    if bad_chars:
        reasons.append(f"refused characters {bad_chars[:8]}")
    seen: set[str] = set()
    n = 0
    for raw in cleaned.splitlines():
        line = raw.strip().lstrip("-*# ").strip()
        if not line:
            continue
        head = line.strip(": ").lower()
        if head in titles:
            seen.add(head)
            continue
        pieces: list[str] = []
        for s in re.split(r"(?<=[.!?\]])\s+(?=\S)", line):
            s = s.strip()
            if s and CITE.fullmatch(s.rstrip(".")) and pieces:
                pieces[-1] += " " + s  # "... sentence. [hist-a]" — the citation belongs to the sentence before it
            elif s:
                pieces.append(s)
        for s in pieces:
            n += 1
            cites = [c.strip() for m in CITE.finditer(s) for c in m.group(1).split(",")]
            if not cites:
                reasons.append(f"uncited: {s[:70]!r}")
                continue
            unknown = [c for c in cites if c not in facts_by_id]
            if unknown:
                reasons.append(f"unknown citation {unknown}")
                continue
            r = check_sentence(s, [facts_by_id[c]["text"] for c in cites], extra)
            if r:
                reasons.append(f"{'; '.join(r)}: {s[:70]!r}")
    if n == 0:
        reasons.append("empty draft")
    if titles - seen:
        reasons.append(f"missing sections {sorted(titles - seen)}")
    return {"ok": not reasons, "reasons": reasons, "sentences": n}
