"""What is the operator asking ABOUT? One resolver, registry-first.

WHY
---
2026-09-13 18:50: "Is now a good time to get back into schg" resolved no symbol,
because only UPPER-CASE tokens counted as tickers, and the desk answered with the
whole re-entry book. The base fix matched any-case tokens against a known set. This
module makes subject resolution one measurable function instead of three regexes
spread through the desk loop.

ORDER, AND WHY EACH STEP IS WHERE IT IS
---------------------------------------
(a) tickers. A token binds in ANY case only when it is in the operator's BOOK
    (holdings + re-entry desk: `cio_operator_desk_loop._known_symbols`). Registry
    symbols bind only when written UPPER-CASE or as a $cashtag. Measured
    2026-09-13: 514 of the registry's 5,391 alphabetic symbols are English words
    (BACK, INTO, CASH, TECH, CHEAP, NOW, GOING, ...), so any-case matching against
    the registry would attach "get back into" to three issuers. The book is small
    and the operator's own; the registry is not.
(b) company / fund names, through `company_name_index.resolve_name` -- the broker
    instrument feed, never a hand-written map (AGENTS.md "Company names and
    CUSIPs"). A generic word never binds an issuer on its own
    (`inbound_identity_tagger.GENERIC_NAME_TERMS`, the REFR incident). A name the
    feed does not carry is returned as `kind: company, symbol: None`: it is a real
    subject that Trade-AI cannot price, and saying so is the honest answer.
(c) sector / theme words, mapped onto the sector names the CIO snapshot's
    `sectors` domain carries (Yahoo vocabulary: "Technology", "Financial
    Services", "Consumer Defensive", ...).
(d) topics (seasonality, election cycle, options, earnings, ...). When nothing at
    all resolved, one `topic: general` subject, so a caller never has to ask
    whether an empty list means "about nothing" or "not resolved".

GUIDS ARE READ, NEVER MINTED
----------------------------
Every symbol carries `guid` = the registry's subject GUID (security > issuer >
ticker alias, `identity_registry.subject_guid_of`). A symbol the registry does not
hold keeps `guid: None` and a lowered `confidence`. Nothing here writes.

AUTHORITY: READ_ONLY_ADVISORY. No model runs here.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

SCHEMA = "OperatorSubject@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

KINDS = ("ticker", "company", "etf", "sector", "topic")

#: Upper-case tokens that are English, desk vocabulary or finance acronyms.
#: Union of the desk loop's historic list and the inbound tagger's list, plus the
#: acronyms an operator actually types in a question.
_STOP = frozenset({
    "I", "A", "THE", "AND", "OR", "TO", "FOR", "ON", "IN", "OF", "IS", "IT", "AN", "AT", "BY", "BE",
    "WHAT", "CAN", "NOW", "ETC", "DAY", "SMA", "RSI", "CIO", "READ", "ONLY", "USD", "READY", "NEAR",
    "ZONE", "STOP", "ALEX", "LLM", "YOU", "HOW", "WHICH", "USING", "MODEL", "FLASH", "PRO", "AI", "WHY",
    "GOOD", "TIME", "GET", "BACK", "INTO", "BUY", "SELL", "HOLD", "MY", "ME", "WE", "US", "DO", "DOES",
    "ARE", "WAS", "ALL", "ANY", "NOT", "NO", "YES", "OK", "SO", "IF", "AS", "UP", "OUT", "NEW", "OLD",
    "GO", "AM", "BUT", "HAS", "SEE", "CEO", "CFO", "ETF", "ETFS", "IPO", "EPS", "PE", "ATR", "PM", "EST",
    "EDT", "UTC", "YTD", "QTD", "MTD", "EOD", "EOY", "ATH", "GDP", "CPI", "FED", "FOMC", "SEC", "IRA",
    "ROTH", "TLDR", "FYI", "ASAP", "PT", "SR", "MACD", "VIX", "DCA",
})

#: Holdings rows that are not instruments.
_PSEUDO = frozenset({"CASH", "MMF", "SWEEP", "PENDING", "TOTAL"})

#: Book symbols that are also everyday words. Lower-case they are the word.
_LOWER_REFUSE = frozenset({
    "div", "hold", "buy", "well", "key", "low", "cost", "big", "fun", "life", "love", "safe", "gain",
    "gold", "play", "next", "best", "open", "real", "free", "hope", "home", "run", "fly", "eat", "tech",
    "data", "cloud", "cash", "bah", "bond", "fund", "cat", "dog", "man", "car", "job", "net", "win",
    # Desk vocabulary that is also a registry symbol (CHEAP, PRICE, LOOK, VIA, TERM, ...).
    "cheap", "price", "look", "looks", "via", "term", "going", "right", "doing", "today", "here", "there",
    "stock", "share", "trade", "level", "month", "year", "week", "quote", "chart", "sales", "deal",
    "calls", "puts", "split", "gains", "rally", "surge", "drop", "drops", "move", "moves", "news", "ideas",
})

_MONTHS = frozenset({
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "Q1", "Q2", "Q3", "Q4",
})

_UPPER_TOKEN = re.compile(r"(?<![A-Za-z0-9_$])([A-Z]{1,5})(?![A-Za-z0-9_])")
_ANYCASE_TOKEN = re.compile(r"(?<![A-Za-z0-9_$])([A-Za-z]{2,5})(?![A-Za-z0-9_])")
_CASHTAG = re.compile(r"\$([A-Za-z]{1,5})\b")
#: A ticker spelled letter by letter, as voice dictation writes it: "a x t i",
#: "A.X.T.I", "a-x-t-i". Three to five single letters, one separator between.
_SPELLED = re.compile(r"(?<![A-Za-z0-9])((?:[A-Za-z][ .\-]){2,4}[A-Za-z])\.?(?![A-Za-z0-9])")

#: Sector vocabulary -> the name the CIO snapshot `sectors` domain uses.
#: A vocabulary, not a symbol map: no issuer is named here.
_SECTOR_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Technology", re.compile(r"\b(?:tech|technology|semis|semiconductors?|chips?\s+stocks?|software)\b", re.I)),
    ("Financial Services", re.compile(r"\b(?:financials|financial\s+services|banks|banking)\b", re.I)),
    ("Healthcare", re.compile(r"\b(?:health\s*care|biotech|pharma(?:ceuticals)?)\b", re.I)),
    ("Energy", re.compile(r"\b(?:energy|oil\s+(?:and|&)\s+gas|oil\s+stocks)\b", re.I)),
    ("Industrials", re.compile(r"\b(?:industrials|defen[cs]e\s+(?:stocks|names|sector)|aerospace)\b", re.I)),
    ("Basic Materials", re.compile(r"\b(?:basic\s+materials|materials|mining|miners|metals)\b", re.I)),
    ("Consumer Defensive", re.compile(r"\b(?:consumer\s+staples|staples|consumer\s+defensive)\b", re.I)),
    ("Consumer Cyclical", re.compile(r"\b(?:consumer\s+discretionary|discretionary|consumer\s+cyclical)\b", re.I)),
    ("Utilities", re.compile(r"\butilities\b", re.I)),
    ("Real Estate", re.compile(r"\b(?:real\s+estate|reits?)\b", re.I)),
    ("Communication Services", re.compile(r"\b(?:communication\s+services|telecoms?)\b", re.I)),
)

_TOPIC_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("seasonality", re.compile(r"\b(?:january|february|march|april|june|july|august|september|october|"
                               r"november|december|seasonal(?:ity)?|santa\s+rally)\b", re.I)),
    ("election_cycle", re.compile(r"\b(?:election|mid[\s-]?terms?|mid[\s-]?cycle|presidential\s+cycle)\b", re.I)),
    ("quarter_outlook", re.compile(r"\b(?:(?:first|second|third|fourth|next)\s+quarter|q[1-4])\b", re.I)),
    ("sector_allocation", re.compile(r"\b(?:sectors?|rotat(?:e|ing|ion)|over[\s-]?weight|under[\s-]?weight|"
                                     r"concentrat(?:e|ed|ion))\b", re.I)),
    ("options", re.compile(r"\b(?:options?|covered\s+calls?|puts?|calls|strikes?|expir(?:y|ation|ing))\b", re.I)),
    ("earnings", re.compile(r"\b(?:earnings|guidance|user\s+growth|revenue)\b", re.I)),
    ("analyst_view", re.compile(r"\b(?:analysts?|anaylsts?|analists?|price\s+target|consensus|rating)\b", re.I)),
    ("price_performance", re.compile(r"\b(?:performance|perform(?:ed|ing)?|price\s+today|outlook)\b", re.I)),
    ("dividends", re.compile(r"\b(?:dividends?|yield|income)\b", re.I)),
    ("market", re.compile(r"\bmarket\b", re.I)),
)


def _registry_doc(registry: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    if registry is not None:
        return registry
    try:
        from scripts.lib import identity_registry as R  # noqa: PLC0415
        return R.load_cached()
    except Exception:
        return {}


def _identity(doc: Mapping[str, Any], symbol: str) -> dict[str, Any]:
    """Registry lookup for one symbol. Never mints."""
    try:
        from scripts.lib import identity_registry as R  # noqa: PLC0415
        row = R.lookup_symbol(doc, symbol)
        if not row:
            return {}
        guid = R.subject_guid_of(row, symbol)
    except Exception:
        return {}
    if not guid:
        return {}
    return {"guid": guid, "issuer_guid": row.get("issuer_guid"),
            "identity_status": row.get("identity_status")}


def _is_template_chrome(token: str) -> bool:
    """Delegate to the ONE chrome list -- `inbound_identity_tagger`.

    Deliberately NOT a copy. This module's `_STOP` and the tagger's
    `_TEMPLATE_CHROME` were two hand-written lists for the same job, and the
    2026-09-22 "ALERT in Command Center" message is what their drift looks like
    in front of the operator.

    Fails OPEN (returns False) when the tagger cannot be imported: suppressing a
    genuine ticker is worse than letting one chrome word through, and the tests
    assert the guard directly so a silent no-op cannot pass for a fix.
    """
    try:
        from scripts.lib.inbound_identity_tagger import is_template_chrome  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - SCRIPTS_ONLY callers
        try:
            from lib.inbound_identity_tagger import is_template_chrome  # type: ignore  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            return False
    try:
        return is_template_chrome(token)
    except Exception:  # noqa: BLE001
        return False


def _book_symbols() -> frozenset[str]:
    try:
        from scripts.lib import cio_operator_desk_loop as desk  # noqa: PLC0415
        return frozenset(str(s).upper() for s in desk._known_symbols())
    except Exception:
        return frozenset()


def _subject(kind: str, symbol: Optional[str], matched: str, confidence: float, source: str,
             ident: Optional[Mapping[str, Any]] = None, **extra: Any) -> dict[str, Any]:
    ident = ident or {}
    guid = ident.get("guid")
    if symbol and not guid:
        # A symbol the registry does not hold is a weaker claim than one it does.
        confidence = max(0.1, confidence - 0.3)
    row = {
        "symbol": symbol,
        "guid": guid,
        "kind": kind,
        "matched": matched,
        "confidence": round(confidence, 2),
        "source": source,
    }
    if ident.get("identity_status"):
        row["identity_status"] = ident["identity_status"]
    if ident.get("issuer_guid"):
        row["issuer_guid"] = ident["issuer_guid"]
    row.update(extra)
    return row


def _kind_for(symbol: str, description: Any = None) -> str:
    return "etf" if re.search(r"\bETF\b|\bFUND\b|\bTRUST\b", str(description or ""), re.I) else "ticker"


def _tickers(text: str, book: frozenset[str], doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(sym: str, matched: str, how: str) -> None:
        if sym in seen or sym in _PSEUDO:
            return
        ident = _identity(doc, sym)
        in_book = sym in book
        if how == "cashtag":
            conf = 0.95
        elif in_book:
            conf = 0.95
        elif ident:
            conf = 0.9
        else:
            conf = 0.65      # upper-case, unknown to book and registry: the old rule, kept weak
        seen.add(sym)
        out.append(_subject("ticker", sym, matched, conf,
                            "book" if in_book else ("registry" if ident else how), ident))

    # 2026-09-14 08:23 "What is a x t i price right now ...": dictation spelled
    # AXTI and nothing resolved, so the desk answered without the price and
    # levels it held. Bind a spelled ticker only when the book or the registry
    # holds it -- joined single letters are otherwise a guess. A run may carry a
    # stray letter ("A X T I a buy"), so the longest held window wins; letters
    # inside a bound spelling are not tickers of their own.
    covered: list[tuple[int, int]] = []
    for m in _SPELLED.finditer(text):
        letters = [(m.start(1) + i, ch) for i, ch in enumerate(m.group(1)) if ch.isalpha()]
        bound = False
        for size in range(len(letters), 2, -1):
            for start in range(0, len(letters) - size + 1):
                win = letters[start:start + size]
                up = "".join(ch for _, ch in win).upper()
                if up in _STOP or up in _PSEUDO or not (up in book or _identity(doc, up)):
                    continue
                lo, hi = win[0][0], win[-1][0] + 1
                add(up, text[lo:hi], "spelled")
                covered.append((lo, hi))
                bound = True
                break
            if bound:
                break

    def inside(pos: int) -> bool:
        return any(lo <= pos < hi for lo, hi in covered)

    for m in _CASHTAG.finditer(text):
        add(m.group(1).upper(), m.group(0), "cashtag")
    for m in _UPPER_TOKEN.finditer(text):
        tok = m.group(1)
        if tok in _STOP or inside(m.start(1)):
            continue
        # Machine-template CHROME (ALERT, ET, QUOTE, EOD, FIX, NONE, ...) is
        # boilerplate this system prints about itself, not an instrument. One
        # shared list with the inbound tagger; see `_is_template_chrome`.
        #
        # Fails OPEN twice, so a real ticker is never suppressed to kill chrome:
        #   * a chrome word the operator actually HOLDS still binds (book), and
        #   * an explicit $cashtag never reaches here -- the cashtag loop above
        #     already bound it, which is how "$ET" still resolves to Energy
        #     Transfer while "13:02 ET" does not.
        if _is_template_chrome(tok) and tok not in book:
            continue
        add(tok, tok, "uppercase")
    if book:
        for m in _ANYCASE_TOKEN.finditer(text):
            tok = m.group(1)
            up = tok.upper()
            if tok == up or up in _STOP or tok.lower() in _LOWER_REFUSE:
                continue
            if up in book:
                add(up, tok, "book")
    # Order of appearance in the question, not order of discovery.
    out.sort(key=lambda s: _position(text, s["matched"]))
    return out


def _position(text: str, needle: str) -> int:
    i = text.find(needle)
    return i if i >= 0 else len(text)


def _companies(text: str, taken: set[str], doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        from scripts.lib import inbound_identity_tagger as T  # noqa: PLC0415
        from scripts.lib import company_name_index as C  # noqa: PLC0415
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for name in T.extract_name_mentions(text):
        words = [w for w in name.split() if w not in _MONTHS]
        if not words:
            continue
        name = " ".join(words)
        up = name.upper()
        if up in taken or up in _STOP or up in _PSEUDO:
            continue                     # already a ticker ("SCHD", "ADBE"), or not a name
        if T._is_generic_term(name):     # "Research" must never bind REFR
            continue
        hit = None
        try:
            hit = C.resolve_name(name)
        except Exception:
            hit = None
        if hit and hit.get("symbol"):
            sym = str(hit["symbol"]).upper()
            if sym in taken:
                continue
            taken.add(sym)
            conf = 0.85 if hit.get("matched_on") == "exact" else 0.7
            kind = "etf" if _kind_for(sym, hit.get("description")) == "etf" else "company"
            out.append(_subject(kind, sym, name, conf, "company_name_index", _identity(doc, sym),
                                description=hit.get("description"), matched_on=hit.get("matched_on")))
            continue
        # Unresolved. A lone capitalised word opening the sentence ("Continue",
        # "Thoughts", "Approved") is not evidence of a company; a mid-sentence
        # capital or a multi-word run ("SpaceX", "Nonesuch Holdings") is.
        start = text.find(name)
        if len(words) == 1 and (start < 0 or T._is_sentence_initial(text, start)):
            continue
        out.append(_subject("company", None, name, 0.3, "unresolved_name",
                            reason="name_not_in_instrument_feed_or_ambiguous"))
    return out


def resolve_subjects(text: str, *, book: Optional[Iterable[str]] = None,
                     registry: Optional[Mapping[str, Any]] = None) -> list[dict[str, Any]]:
    """Every subject the question names, in resolution order a -> d.

    Each row: {symbol, guid, kind, matched, confidence, source, ...}. `symbol` is
    None for sectors, topics and names the instrument feed does not carry.
    """
    t = text or ""
    if not t.strip():
        return []
    book_set = frozenset(str(s).upper() for s in book) if book is not None else _book_symbols()
    doc = _registry_doc(registry)

    subjects = _tickers(t, book_set, doc)
    taken = {s["symbol"] for s in subjects if s["symbol"]}
    subjects += _companies(t, taken, doc)

    for sector, rx in _SECTOR_WORDS:
        m = rx.search(t)
        if m:
            subjects.append(_subject("sector", None, m.group(0), 0.7, "sector_vocabulary", sector=sector))

    for topic, rx in _TOPIC_WORDS:
        m = rx.search(t)
        if m:
            subjects.append(_subject("topic", None, m.group(0), 0.5, "topic_vocabulary", topic=topic))

    if not subjects:
        subjects.append(_subject("topic", None, t.strip()[:80], 0.2, "fallback", topic="general"))
    return subjects


def ticker_candidates(text: str, *, book: Optional[Iterable[str]] = None,
                      registry: Optional[Mapping[str, Any]] = None) -> list[str]:
    """Lower-case tokens the registry holds as symbols -- CANDIDATES, never bound.

    "is nvda cheap here" binds nothing (lower-case NVDA is indistinguishable from
    the 514 registry symbols that are English words). Refusing it silently would be
    unhelpful; binding it would be a guess. A caller may name the candidates and
    ask the operator to write the ticker in capitals.
    """
    book_set = frozenset(str(s).upper() for s in book) if book is not None else _book_symbols()
    by_symbol = (_registry_doc(registry).get("by_symbol") or {})
    out: list[str] = []
    for m in _ANYCASE_TOKEN.finditer(text or ""):
        tok = m.group(1)
        up = tok.upper()
        if (tok == up or up in _STOP or up in _PSEUDO or tok.lower() in _LOWER_REFUSE
                or up in book_set or up not in by_symbol or up in out):
            continue
        out.append(up)
    return out[:5]


def verify_added_symbol(symbol: Any, *, book: Optional[Iterable[str]] = None,
                        registry: Optional[Mapping[str, Any]] = None,
                        source: str = "flash") -> Optional[dict[str, Any]]:
    """A symbol proposed by a model, as a subject -- or None when nothing vouches for it.

    A model may ADD a symbol the heuristic missed, but only one the identity
    registry or the operator's book already holds. "SPACEX" from a model is a
    six-letter guess, and accepting it would turn an unanswerable question into
    a pending that can never complete.
    """
    sym = str(symbol or "").strip().lstrip("$").upper()
    if not (sym.isalpha() and 1 <= len(sym) <= 5) or sym in _STOP or sym in _PSEUDO:
        return None
    book_set = frozenset(str(s).upper() for s in book) if book is not None else _book_symbols()
    ident = _identity(_registry_doc(registry), sym)
    if not ident and sym not in book_set:
        return None
    return _subject("ticker", sym, sym, 0.6, source, ident)


def symbols_of(subjects: Iterable[Mapping[str, Any]], limit: int = 12) -> list[str]:
    """The flat symbol list every existing caller of `intent["symbols"]` reads."""
    out: list[str] = []
    for s in subjects:
        sym = s.get("symbol")
        if sym and sym not in out:
            out.append(str(sym))
    return out[:limit]


def name_spans(subjects: Iterable[Mapping[str, Any]]) -> list[str]:
    """Matched text of company subjects, so intent regexes do not read a name as a word.

    "Nonesuch Holdings" is a company, not a request for the operator's holdings.
    """
    return [str(s["matched"]) for s in subjects if s.get("kind") in ("company", "etf") and s.get("matched")]


__all__ = ["SCHEMA", "AUTHORITY", "KINDS", "resolve_subjects", "ticker_candidates", "verify_added_symbol",
           "symbols_of", "name_spans"]
