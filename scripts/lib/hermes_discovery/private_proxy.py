"""White-Space Discovery — private-company / public-proxy discovery (spec Part C).

Finds notable PRIVATE companies in the EXISTING corpus (news_articles +
hermes_research_intelligence) and, when the corpus itself evidences a link to
a listed company, attaches conservative public-proxy underlyings. Everything
is emitted as PRIVATE_COMPANY_PROXY_CANDIDATE rows through
inbox.upsert_candidate — candidates only, OPERATOR_REVIEW_REQUIRED, never a
watchlist/directive/proposal write, no broker/execution imports anywhere.

Detection gates (ALL must pass):
  recurrence     entity appears in >= MIN_RECURRENCE corpus rows
  cross-source   across >= MIN_SOURCES distinct sources
  proper noun    capitalized in source text; single-word entities must appear
                 at least once mid-sentence (not only sentence-initial);
                 short ALL-CAPS single tokens are acronym-shaped and skipped
  not common     extended denylist (symbol_validation.DENYLIST + common words,
                 institutions, news wires, calendar terms, frequent figures)
  company-like   at least one mention sits within _CUE_WINDOW chars of
                 company-ish language (startup/founder/acquired/valuation/…)
                 — kills capitalized common words the denylist misses
  NOT listed     symbol_validation.validate_ticker must FAIL (VALID or
                 NEEDS_VALIDATION → the token is/behaves like a listed symbol
                 → skipped), AND the name must not prefix-match a
                 symbol_profiles company description (catches "Tesla" whose
                 uppercase form is not the ticker) — conservative extension.

Proxy resolution — NEVER INVENTED, evidence-only:
  The entity's own corpus rows are scanned for ownership/acquisition phrases
  ("acquired by X", "subsidiary of X", "owned by X", "parent company X",
  "X to acquire NAME", supplier/customer + rival/competitor phrasing). The
  public side X resolves to a ticker via (in confidence order) an exchange
  parenthetical "(NASDAQ: TEAM)" in the evidence snippet (0.8), a direct
  valid ticker token (0.7), or a UNIQUE symbol_profiles company-name prefix
  match (0.6) — ambiguous name matches resolve to nothing. Relationships map
  to parent / acquirer / supplier_customer / comparable (etf_theme is in the
  enum but this stage has no evidence source for it, so it is never emitted).
  No relationship evidence → proxy_underlyings=[] + nulls + research_only.

meta_json.private_proxy_json schema (spec Part C, exact):
  private_company, public_parent, public_parent_ticker,
  ownership_relationship, ownership_percent_if_known (null unless evidenced),
  acquisition_status, materiality_to_parent ('unknown' unless evidenced),
  direct_options_available (always false), proxy_underlyings
  [{ticker, relationship, confidence}], options_possible_on,
  no_direct_trade_reason (MUST contain NO_DIRECT_OPTIONS_SENTENCE verbatim),
  evidence_refs, recommended_action ∈ RECOMMENDED_ACTIONS.

Routing: payloads pin meta.research_domain to a lane-compatible domain
(classify_domain result when it lands in ROUTING_DOMAINS, else
DEFAULT_ROUTING_DOMAIN) — routing only, never treated as ownership evidence.

DB reads go through this module's _execute seam (db_adapter._execute, one
statement per call) so tests can monkeypatch synthetic corpora and the 120s
idle-in-transaction guard can never bite. Registers the 'private_proxy'
worker-pool lane runner (read-only: returns payloads; the pool owns writes).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from . import domains, inbox, worker_pool
from .symbol_validation import (DENYLIST as _TICKER_DENYLIST, VERDICT_VALID,
                                VERDICT_NEEDS_VALIDATION, validate_ticker)

PRODUCER = "private_company_proxy_discovery"
ACTOR = "ingestor:private_proxy"
LANE_ID = "private_proxy"

WINDOW_DAYS = 14           # corpus lookback (lane cadence is daily)
SCAN_LIMIT = 600           # max rows pulled per input stream
MIN_RECURRENCE = 2         # entity must appear in >= 2 corpus rows
MIN_SOURCES = 2            # across >= 2 distinct sources
MAX_CANDIDATES_PER_RUN = 5  # default cap (lane yaml cap wins in lane runs)
PROXY_TTL_DAYS = 30
MAX_EVIDENCE_REFS = 6
_MAX_ENTITY_EVAL = 60      # symbol-validation lookups per run, hard bound

# The literal sentence REQUIRED by spec Part C in every candidate.
NO_DIRECT_OPTIONS_SENTENCE = (
    "No direct listed options found for the private company. Research must "
    "use a public parent/proxy/comparable/ETF if appropriate.")

RECOMMENDED_ACTIONS = frozenset({
    "research_only", "proxy_analysis", "strategy_candidate", "no_action"})
RELATIONSHIPS = frozenset({
    "parent", "acquirer", "supplier_customer", "comparable", "etf_theme"})

ACQ_COMPLETED = "completed"
ACQ_ANNOUNCED = "announced"
ACQ_NONE = "none"          # relationship evidenced, but not an ownership event
ACQ_UNKNOWN = "unknown"    # no evidence at all

# Domains this lane may route into (mirrors the private_proxy lane fences).
ROUTING_DOMAINS = ("technology", "sectors", "industry_themes", "watchlist")
DEFAULT_ROUTING_DOMAIN = "industry_themes"

# ── denylist: symbol_validation.DENYLIST + common-word/proper-noun noise ─────
# Uppercased. Multi-word entries match whole cleaned entities.
COMMON_WORDS = frozenset({t.upper() for t in _TICKER_DENYLIST} | {
    # articles / pronouns / connectives / generic sentence-case words
    "THE", "A", "AN", "AND", "OR", "BUT", "IF", "AS", "AT", "BY", "FOR",
    "FROM", "IN", "INTO", "OF", "ON", "TO", "WITH", "OVER", "UNDER", "AFTER",
    "BEFORE", "ABOUT", "IT", "ITS", "THIS", "THAT", "THESE", "THOSE", "HE",
    "SHE", "THEY", "WE", "YOU", "I", "HIS", "HER", "OUR", "THEIR", "NEW",
    "MORE", "MOST", "OTHER", "WHY", "HOW", "WHAT", "WHEN", "WHERE", "WHO",
    "WHICH", "HERE", "THERE", "NOW", "TODAY", "YESTERDAY", "TOMORROW",
    "HOWEVER", "MEANWHILE", "ALSO", "ACCORDING", "DESPITE", "ALTHOUGH",
    "WHILE", "SINCE", "AMID", "AMONG", "BETWEEN", "DURING", "FINALLY",
    "FIRST", "SECOND", "THIRD", "LAST", "NEXT", "EARLIER", "LATER",
    "RECENTLY", "SOURCES", "OFFICIALS", "PRESIDENT", "SENATOR", "GOVERNOR",
    "MINISTER", "CHAIRMAN", "CHAIR", "DIRECTOR", "BOARD", "COMMITTEE",
    "DEPARTMENT", "AGENCY", "ADMINISTRATION", "OFFICE", "BUREAU",
    "COMMISSION", "INDUSTRY", "SECTOR", "ECONOMY", "INFLATION", "RECESSION",
    # headline finance vocabulary
    "SHARES", "STOCK", "STOCKS", "MARKET", "MARKETS", "INVESTORS", "INVESTOR",
    "ANALYSTS", "ANALYST", "EARNINGS", "REVENUE", "PROFIT", "REPORT",
    "REPORTS", "UPDATE", "BREAKING", "EXCLUSIVE", "WATCH", "BUY", "SELL",
    "HOLD", "STRONG", "STRONG BUY", "STRONG SELL", "REVIEW", "PART",
    "TOP", "BEST", "WORST", "BIG", "WALL", "STREET", "PRICE", "DIVIDEND",
    "DIVIDENDS", "GROWTH", "VALUE", "INCOME", "MOMENTUM", "QUALITY", "YIELD",
    "TARGET", "RATING", "UPGRADE", "DOWNGRADE", "PREMARKET", "OPTIONS",
    "FUTURES", "BONDS", "TREASURIES", "EBITDA", "GAAP", "FOMC", "PPI", "PCE",
    "ETFS", "IPOS", "M&A", "EVS", "P.M", "A.M", "CALL", "CALLS", "PUT",
    "PUTS", "OPTION", "TRADE", "TRADES", "TRADING", "TRADER", "TRADERS",
    "DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "ANNUAL", "MEDICARE",
    "MEDICAID", "SOCIAL SECURITY",
    # generic technology/theme phrases (themes, not companies)
    "QUANTUM COMPUTING", "ARTIFICIAL INTELLIGENCE", "MACHINE LEARNING",
    "GENERATIVE AI", "BIG DATA", "CLOUD COMPUTING", "CRYPTO", "BITCOIN",
    "ETHEREUM",
    # calendar (full + abbreviated)
    "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY",
    "SUNDAY", "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
    "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER", "JAN", "FEB",
    "MAR", "APR", "JUN", "JUL", "AUG", "SEP", "SEPT", "OCT", "NOV", "DEC",
    # geography / institutions (subjects, not companies)
    "US", "U.S", "U.S.", "UK", "U.K", "EU", "USA", "AMERICA", "AMERICAN",
    "EUROPE", "EUROPEAN", "ASIA", "CHINA", "CHINESE", "JAPAN", "INDIA",
    "RUSSIA", "UKRAINE", "ISRAEL", "IRAN", "TAIWAN", "KOREA", "CANADA",
    "MEXICO", "GERMANY", "FRANCE", "BRITAIN", "WASHINGTON", "LONDON",
    "BEIJING", "CONGRESS", "SENATE", "HOUSE", "PENTAGON", "TREASURY", "FED",
    "NATO", "OPEC", "ECB", "IMF", "FTC", "DOJ", "FAA", "FCC", "CDC", "NYSE",
    "NASDAQ", "DOW", "S&P", "DOW JONES", "RUSSELL", "RUSSELL 2000", "FTSE",
    "NIKKEI", "FEDERAL RESERVE", "WALL STREET", "WHITE HOUSE",
    "SUPREME COURT", "NEW YORK", "YORK", "UNITED STATES", "SILICON VALLEY",
    "FEDERAL", "RESERVE", "WHITE", "COURT", "GOVERNMENT", "STATE", "STATES",
    # news wires / attribution names (mentions are attribution, not subjects)
    "REUTERS", "BLOOMBERG", "CNBC", "AP", "AFP", "WSJ", "FORBES", "FT",
    "MARKETWATCH", "BARRONS", "AXIOS", "POLITICO", "CNN", "BBC", "FOX",
    "MSNBC", "TECHCRUNCH", "ZACKS", "TRADINGVIEW", "BARCHART", "BENZINGA",
    "TIPRANKS", "STOCKTWITS", "INVESTOPEDIA", "MARKETBEAT", "GLOBENEWSWIRE",
    "BUSINESSWIRE", "ACCESSWIRE", "NEWSFILE", "PR NEWSWIRE", "SIMPLY WALL ST",
    "ASSOCIATED PRESS", "WALL STREET JOURNAL",
    "FINANCIAL TIMES", "SEEKING ALPHA", "MOTLEY FOOL", "YAHOO FINANCE",
    "BUSINESS INSIDER", "YAHOO", "INSIDER",
    # frequently mentioned public figures (people, not companies)
    "TRUMP", "BIDEN", "HARRIS", "OBAMA", "POWELL", "YELLEN", "MUSK",
    "ALTMAN", "BUFFETT", "XI", "PUTIN", "ZELENSKY", "BESSENT",
})

# Legal-suffix tokens stripped from entity/company tails before matching.
CORP_SUFFIXES = frozenset({
    "INC", "CORP", "CORPORATION", "INCORPORATED", "CO", "LTD", "LLC", "LP",
    "PLC", "GMBH", "SA", "AG", "NV", "HOLDINGS",
})

_WORD = r"[A-Z][A-Za-z0-9&'’.\-]+"
_ENTITY_RE = re.compile(rf"\b({_WORD}(?:[ ]{_WORD}){{0,2}})")
_CO_CAPTURE = rf"({_WORD}(?:\s+{_WORD}){{0,3}})"

_EXCHANGE_TICKER_RE = re.compile(
    r"\(\s*(?:NYSE(?:\s+American|\s+Arca)?|NASDAQ|Nasdaq|AMEX|CBOE|"
    r"OTC(?:MKTS)?)\s*[:\s]\s*([A-Z][A-Z0-9.\-]{0,9})\s*\)")

# Company-context cues: at least one mention of a detected entity must sit
# near company-ish language, or the token is treated as a common word that
# slipped the denylist (precision gate — misses are fine, inventions are not).
_COMPANY_CUE_RE = re.compile(
    r"\b(?:startup|start-up|company|companies|firm|maker|manufacturer|"
    r"developer|provider|producer|owner|brand|unicorn|venture|"
    r"privately[- ]held|private\s+company|co-?founder|founder|founded|ceo|"
    r"chief\s+executive|valuation|valued\s+at|funding|series\s+[a-e]\b|"
    r"raised\s+\$|acquisition|acquired?|acquires|merger|ipo|subsidiary|"
    r"parent\s+company|owned\s+by|stake\s+in|supplier|customer|rival|"
    r"competitor)\b", re.IGNORECASE)
_CUE_WINDOW = 80  # chars around a mention searched for company cues

_OWN_PCT_RE = re.compile(
    r"(?:owns?|holds?|acquir\w+)\s+(?:an?\s+)?(\d{1,3}(?:\.\d{1,2})?)\s*%"
    r"|(\d{1,3}(?:\.\d{1,2})?)\s*%\s+(?:stake|ownership|interest|owned)")

_TRIM_CHARS = ".,;:!?'\"’”)("


# ── plumbing (monkeypatchable seams) ─────────────────────────────────────────

def _execute(sql: str, params=None, fetch: str | None = None):
    """Single monkeypatchable DB seam — delegates to db_adapter._execute
    (one statement per call, immediate commit)."""
    from db_adapter import _execute as _db_execute
    return _db_execute(sql, params, fetch=fetch)


def _rows(sql: str, params=None) -> list[dict[str, Any]]:
    return [dict(r) for r in (_execute(sql, params, fetch="all") or [])]


def _table_exists(table: str) -> bool:
    try:
        row = _execute(
            "SELECT 1 AS ok FROM information_schema.tables WHERE table_name = %s",
            (table,), fetch="one")
        return bool(row)
    except Exception:
        return False


def _ticker_verdict(sym: str) -> dict[str, Any]:
    """Monkeypatchable seam over symbol_validation.validate_ticker."""
    return validate_ticker(sym)


def _listed_symbols_for_name(name: str) -> list[str]:
    """Symbols whose symbol_profiles description starts with `name` (word
    boundary enforced). Used two ways: ANY match ⇒ the name belongs to a
    listed company (detection exclusion); EXACTLY ONE match ⇒ name→ticker
    proxy resolution. Defensive: DB errors return [] (no exclusions invented,
    no proxies invented)."""
    name = (name or "").strip()
    if len(name) < 3:
        return []
    like = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    try:
        rows = _execute(
            """SELECT upper(symbol) AS symbol, description_1s
               FROM symbol_profiles WHERE description_1s ILIKE %s LIMIT 8""",
            (like + "%",), fetch="all") or []
    except Exception:
        return []
    out: set[str] = set()
    low = name.lower()
    for r in rows:
        r = dict(r)
        desc = str(r.get("description_1s") or "").strip()
        if not desc.lower().startswith(low):
            continue
        nxt = desc[len(name):len(name) + 1]
        if nxt == "" or not nxt.isalnum():
            sym = str(r.get("symbol") or "").strip()
            if sym:
                out.add(sym)
    return sorted(out)


# ── corpus collection (EXISTING data only; missing table → note + skip) ──────

def collect_corpus(window_days: int = WINDOW_DAYS,
                   notes: list[str] | None = None) -> list[dict[str, Any]]:
    """Recent news_articles + hermes_research_intelligence rows as
    {text, source, url, ref} dicts (read-only)."""
    d = max(1, int(window_days))
    corpus: list[dict[str, Any]] = []

    if _table_exists("news_articles"):
        for r in _rows(
                f"""SELECT id, title, summary, source, source_url
                    FROM news_articles
                    WHERE created_at > now() - interval '{d} days'
                      AND COALESCE(is_duplicate, false) = false
                    ORDER BY created_at DESC LIMIT %s""", (SCAN_LIMIT,)):
            # Google-News-style titles end " - Publisher"; that attribution
            # is not subject coverage — strip it before entity extraction.
            title = re.sub(r"\s+-\s+[^-]{2,40}$", "",
                           str(r.get("title") or "").strip())
            text = ". ".join(str(x).strip() for x in (title, r.get("summary"))
                             if x and str(x).strip())
            if text:
                corpus.append({"text": text,
                               "source": str(r.get("source") or "unknown"),
                               "url": r.get("source_url"),
                               "ref": f"news_articles:{r.get('id')}"})
    elif notes is not None:
        notes.append("news_articles missing — news stream skipped")

    if _table_exists("hermes_research_intelligence"):
        for r in _rows(
                f"""SELECT id, topic, summary, thesis, source, source_urls_json
                    FROM hermes_research_intelligence
                    WHERE created_at > now() - interval '{d} days'
                    ORDER BY created_at DESC LIMIT %s""", (SCAN_LIMIT,)):
            text = ". ".join(str(x).strip() for x in
                             (r.get("topic"), r.get("summary"), r.get("thesis"))
                             if x and str(x).strip())
            if not text:
                continue
            urls = r.get("source_urls_json")
            url = urls[0] if isinstance(urls, list) and urls else None
            corpus.append({"text": text,
                           "source": str(r.get("source") or "hermes"),
                           "url": url if isinstance(url, str) else None,
                           "ref": f"hermes_research_intelligence:{r.get('id')}"})
    elif notes is not None:
        notes.append("hermes_research_intelligence missing — research stream skipped")

    return corpus


# ── entity extraction (pure) ─────────────────────────────────────────────────

def _tok_key(token: str) -> str:
    return token.strip(_TRIM_CHARS).upper()


def _clean_entity(raw: str) -> str | None:
    """Normalize an extracted span: strip possessives/punctuation, drop
    leading/trailing common words and trailing legal suffixes. None when
    nothing proper-noun-like remains."""
    tokens = []
    for tok in raw.split():
        tok = re.sub(r"(?:'s|’s)$", "", tok).strip(_TRIM_CHARS)
        if tok:
            tokens.append(tok)
    # full-span denylist FIRST: "New York" must die whole, not shed "New"
    if " ".join(_tok_key(t) for t in tokens) in COMMON_WORDS:
        return None
    while tokens and _tok_key(tokens[0]) in COMMON_WORDS:
        tokens.pop(0)
    while tokens and (_tok_key(tokens[-1]) in COMMON_WORDS
                      or _tok_key(tokens[-1]) in CORP_SUFFIXES):
        tokens.pop()
    if not tokens:
        return None
    name = " ".join(tokens)
    if name.upper() in COMMON_WORDS:
        return None
    if len(tokens) == 1 and len(tokens[0]) < 3:
        return None
    if all(_tok_key(t) in COMMON_WORDS for t in tokens):
        return None
    return name


_SENTENCE_SPLIT_RE = re.compile(r"[.!?\n]")
_ALPHA_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]+")


def _sentence_at(text: str, pos: int) -> str:
    start = 0
    for m in _SENTENCE_SPLIT_RE.finditer(text, 0, pos):
        start = m.end()
    m = _SENTENCE_SPLIT_RE.search(text, pos)
    return text[start: m.start() if m else len(text)]


def _is_title_case(segment: str) -> bool:
    """Title-Case Headlines Capitalize Every Word — capitalization carries no
    proper-noun signal there, so mid-sentence credit is withheld."""
    words = _ALPHA_WORD_RE.findall(segment)
    if len(words) < 4:
        return False
    caps = sum(1 for w in words if w[0].isupper())
    return caps / len(words) >= 0.7


def extract_entities(text: str) -> list[tuple[str, bool, bool]]:
    """Proper-noun-like spans from one text:
    [(cleaned_name, mid_sentence, company_cue)].
    mid_sentence is True when the span is NOT sentence-initial (previous
    non-space char is lowercase/digit/comma-like) AND its sentence is not
    title-case — sentence-case noise like 'Shares' only ever appears
    sentence-initial, and title-case headlines capitalize everything.
    company_cue is True when company-ish language (_COMPANY_CUE_RE) appears
    within _CUE_WINDOW chars of the mention."""
    out: list[tuple[str, bool, bool]] = []
    for m in _ENTITY_RE.finditer(text or ""):
        name = _clean_entity(m.group(1))
        if not name:
            continue
        prefix = text[:m.start()].rstrip()
        mid = bool(prefix) and (prefix[-1].islower() or prefix[-1].isdigit()
                                or prefix[-1] in ",;:)\"'")
        if mid and _is_title_case(_sentence_at(text, m.start())):
            mid = False
        window = text[max(0, m.start() - _CUE_WINDOW): m.end() + _CUE_WINDOW]
        out.append((name, mid, bool(_COMPANY_CUE_RE.search(window))))
    return out


def aggregate_entities(corpus: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate extracted entities across the corpus:
    {key: {name, recurrence, sources, mid_sentence_count, row_idxs, refs}}."""
    agg: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(corpus):
        text = str(row.get("text") or "")
        seen_in_row: set[str] = set()
        for name, mid, cue in extract_entities(text):
            key = name.lower()
            ent = agg.setdefault(key, {
                "name": name, "key": key, "recurrence": 0, "sources": set(),
                "mid_sentence_count": 0, "company_cue_count": 0,
                "row_idxs": [], "refs": []})
            if mid:
                ent["mid_sentence_count"] += 1
            if cue:
                ent["company_cue_count"] += 1
            if key in seen_in_row:
                continue
            seen_in_row.add(key)
            ent["recurrence"] += 1
            ent["sources"].add(str(row.get("source") or "unknown"))
            ent["row_idxs"].append(idx)
            if len(ent["refs"]) < MAX_EVIDENCE_REFS:
                pos = text.lower().find(key)
                snippet = text[max(0, pos - 90): pos + len(name) + 90] if pos >= 0 \
                    else text[:180]
                ent["refs"].append({
                    "source_domain": str(row.get("source") or "unknown"),
                    "url": row.get("url"),
                    "ref": row.get("ref"),
                    "note": snippet.strip()[:240]})
    return agg


def _mentioned_with_exchange_ticker(name: str, texts: list[str]) -> bool:
    """True when the corpus itself shows the entity IMMEDIATELY followed by
    an exchange parenthetical — "Polestar (NASDAQ: PSNY)" — i.e. evidently
    listed even when the symbol sits outside the symbol_profiles universe.
    The parenthetical must directly follow the name (no intervening words),
    so "Loom was acquired by Atlassian (NASDAQ: TEAM)" does NOT mark Loom."""
    pat = re.compile(rf"{re.escape(name)}[^A-Za-z0-9()\n]{{0,3}}"
                     rf"{_EXCHANGE_TICKER_RE.pattern}")
    return any(pat.search(t or "") for t in texts)


def detect_private_companies(corpus: list[dict[str, Any]], *,
                             min_recurrence: int = MIN_RECURRENCE,
                             min_sources: int = MIN_SOURCES,
                             limit: int = MAX_CANDIDATES_PER_RUN,
                             skipped: dict[str, int] | None = None,
                             ) -> list[dict[str, Any]]:
    """Full detection pass: aggregate → gates → symbol-validation exclusion.
    Returns entity dicts (recurrence desc), at most `limit`."""
    def _skip(reason: str, n: int = 1) -> None:
        if skipped is not None:
            skipped[reason] = skipped.get(reason, 0) + n

    ranked = sorted(aggregate_entities(corpus).values(),
                    key=lambda e: (-e["recurrence"], -len(e["sources"]), e["key"]))
    detected: list[dict[str, Any]] = []
    evaluated = 0
    for ent in ranked:
        if len(detected) >= max(1, int(limit)):
            _skip("run_cap", 1)
            continue
        name = ent["name"]
        single = " " not in name
        if ent["recurrence"] < max(1, int(min_recurrence)):
            _skip("low_recurrence")
            continue
        if len(ent["sources"]) < max(1, int(min_sources)):
            _skip("low_cross_source")
            continue
        if single and name.isupper() and len(name) <= 5:
            _skip("acronym_shaped")
            continue
        if single and ent["mid_sentence_count"] == 0:
            # only ever sentence-initial → sentence-case word, not a proper noun
            _skip("sentence_start_only")
            continue
        if evaluated >= _MAX_ENTITY_EVAL:
            _skip("eval_budget_exhausted")
            continue
        evaluated += 1
        if single:
            verdict = _ticker_verdict(name.upper())
            if verdict.get("verdict") == VERDICT_VALID:
                _skip("directly_listed_ticker")
                continue
            if verdict.get("verdict") == VERDICT_NEEDS_VALIDATION:
                _skip("ambiguous_ticker_shape")
                continue
        if _listed_symbols_for_name(name):
            _skip("listed_company_name")
            continue
        if ent["company_cue_count"] == 0:
            # never once mentioned near company-ish language → treat as a
            # common word that slipped the denylist (precision over recall)
            _skip("no_company_context")
            continue
        texts = [str(corpus[i].get("text") or "") for i in ent["row_idxs"]
                 if 0 <= i < len(corpus)]
        if _mentioned_with_exchange_ticker(name, texts):
            _skip("exchange_listed_in_text")
            continue
        ent = dict(ent)
        ent["sources"] = sorted(ent["sources"])[:6]
        ent["cross_source_count"] = len(set(ent["sources"]))
        detected.append(ent)
    return detected


# ── proxy resolution (evidence-only, never invented) ─────────────────────────

def _proxy_patterns(name: str) -> list[tuple[str, str, re.Pattern]]:
    n = re.escape(name)
    co = _CO_CAPTURE
    gap = r"[^.\n]{0,80}?"
    pats = [
        ("acquirer", ACQ_ANNOUNCED, rf"{n}{gap}\bto\s+be\s+acquired\s+by\s+{co}"),
        ("acquirer", ACQ_COMPLETED, rf"{n}{gap}\bacquired\s+by\s+{co}"),
        ("acquirer", ACQ_ANNOUNCED,
         rf"{co}\s+(?:has\s+agreed\s+to|agreed\s+to|plans\s+to|is\s+set\s+to|"
         rf"will|intends\s+to|to)\s+acquire\s+{n}\b"),
        ("acquirer", ACQ_COMPLETED,
         rf"{co}\s+(?:acquired|acquires|has\s+acquired|bought|"
         rf"completed\s+its\s+acquisition\s+of)\s+{n}\b"),
        ("acquirer", ACQ_ANNOUNCED,
         rf"{co}(?:'s|’s)\s+(?:acquisition|takeover|purchase)\s+of\s+{n}\b"),
        ("parent", ACQ_COMPLETED,
         rf"{n}\b,?\s+(?:a|the|its)\s+(?:wholly[\s-]owned\s+)?subsidiary\s+of\s+{co}"),
        ("parent", ACQ_COMPLETED,
         rf"{n}\b,?\s+(?:a|the)\s+(?:unit|division|arm|brand)\s+of\s+{co}"),
        ("parent", ACQ_COMPLETED, rf"{n}{gap}\bowned\s+by\s+{co}"),
        ("parent", ACQ_COMPLETED, rf"{n}{gap}\bparent\s+company,?\s+{co}"),
        ("parent", ACQ_COMPLETED,
         rf"{co},?\s+(?:the\s+)?parent\s+(?:company\s+)?of\s+{n}\b"),
        ("supplier_customer", ACQ_NONE,
         rf"{n}{gap}\b(?:a\s+)?(?:supplier|customer)\s+(?:to|of|for)\s+{co}"),
        ("supplier_customer", ACQ_NONE,
         rf"{co},?\s+a\s+(?:supplier|customer)\s+(?:to|of|for)\s+{n}\b"),
        ("comparable", ACQ_NONE,
         rf"{n}{gap}\b(?:rival|competitor)\s+(?:of\s+|to\s+)?{co}"),
        ("comparable", ACQ_NONE,
         rf"{co},?\s+a\s+(?:rival|competitor)\s+(?:of|to)\s+{n}\b"),
    ]
    return [(rel, status, re.compile(rx)) for rel, status, rx in pats]


_REL_CONFIDENCE_SCALE = {"parent": 1.0, "acquirer": 1.0,
                         "supplier_customer": 0.75, "comparable": 0.7}


def _strip_suffix(name: str) -> str:
    tokens = name.split()
    while len(tokens) > 1 and _tok_key(tokens[-1]) in CORP_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _resolve_company(co_raw: str, snippet: str,
                     private_name: str) -> tuple[str, str, float] | None:
    """Resolve an evidenced public-company string to (display_name, ticker,
    base_confidence). Conservative: unresolvable/ambiguous → None."""
    co = _clean_entity(co_raw) or ""
    if not co or co.lower() == private_name.lower():
        return None

    # 1. exchange parenthetical in the evidence snippet — strongest signal
    m = _EXCHANGE_TICKER_RE.search(snippet)
    if m:
        tick = m.group(1).upper()
        if _ticker_verdict(tick).get("verdict") == VERDICT_VALID:
            return co, tick, 0.8

    # 2. the captured token IS a valid ticker ("acquired by IBM")
    if " " not in co:
        v = _ticker_verdict(co.upper())
        if v.get("verdict") == VERDICT_VALID:
            return str(v.get("company_name") or co), co.upper(), 0.7

    # 3. unique company-name prefix match in symbol_profiles
    for variant in dict.fromkeys([co_raw.strip().strip(_TRIM_CHARS), co,
                                  _strip_suffix(co)]):
        if not variant:
            continue
        syms = _listed_symbols_for_name(variant)
        if len(syms) == 1 and \
                _ticker_verdict(syms[0]).get("verdict") == VERDICT_VALID:
            return co, syms[0], 0.6
    return None


def extract_proxies(name: str, texts: list[str]) -> list[dict[str, Any]]:
    """Scan the entity's OWN corpus texts for ownership/relationship phrases
    and resolve the public side to validated tickers. Returns proxy dicts
    (one per ticker, first/strongest relationship wins); [] when the corpus
    evidences nothing — nothing is ever inferred beyond the text."""
    proxies: dict[str, dict[str, Any]] = {}
    for rel, status, pat in _proxy_patterns(name):
        for text in texts:
            for m in pat.finditer(text or ""):
                snippet = text[max(0, m.start() - 60): m.end() + 100]
                resolved = _resolve_company(m.group(1), snippet, name)
                if not resolved:
                    continue
                co_name, ticker, base = resolved
                if ticker in proxies:
                    continue  # first (strongest-pattern) relationship wins
                confidence = round(base * _REL_CONFIDENCE_SCALE[rel], 2)
                proxy = {"ticker": ticker, "company": co_name,
                         "relationship": rel, "acquisition_status": status,
                         "confidence": confidence,
                         "evidence": snippet.strip()[:240]}
                if rel in ("parent", "acquirer"):
                    pm = _OWN_PCT_RE.search(snippet)
                    if pm:
                        pct = pm.group(1) or pm.group(2)
                        try:
                            proxy["ownership_percent"] = float(pct)
                        except (TypeError, ValueError):
                            pass
                proxies[ticker] = proxy
    return sorted(proxies.values(), key=lambda p: -p["confidence"])


# ── payload building ─────────────────────────────────────────────────────────

def _route_domain(name: str, sample_text: str) -> str:
    """Lane-compatible research_domain pin — ROUTING ONLY, never evidence.
    classify_domain keyword result when it lands in ROUTING_DOMAINS, else
    DEFAULT_ROUTING_DOMAIN."""
    try:
        dom = domains.classify_domain({
            "candidate_type": "TOPIC_CANDIDATE", "label": name,
            "summary": sample_text, "meta": {}, "evidence": []})
        if dom in ROUTING_DOMAINS:
            return dom
    except Exception:
        pass
    return DEFAULT_ROUTING_DOMAIN


def build_private_proxy_json(name: str, proxies: list[dict[str, Any]],
                             evidence_refs: list[dict[str, Any]]) -> dict[str, Any]:
    """The spec Part C meta block. NEVER invents ownership: no proxies →
    nulls + research_only; ownership_percent/materiality stay null/'unknown'
    unless the evidence carried them."""
    ownership = [p for p in proxies
                 if p["relationship"] in ("parent", "acquirer")]
    primary = ownership[0] if ownership else None
    if primary:
        acquisition_status = primary["acquisition_status"]
    elif proxies:
        acquisition_status = ACQ_NONE   # related tickers, no ownership event
    else:
        acquisition_status = ACQ_UNKNOWN
    return {
        "private_company": name,
        "public_parent": primary["company"] if primary else None,
        "public_parent_ticker": primary["ticker"] if primary else None,
        "ownership_relationship": primary["relationship"] if primary else None,
        "ownership_percent_if_known": (primary or {}).get("ownership_percent"),
        "acquisition_status": acquisition_status,
        "materiality_to_parent": "unknown",
        "direct_options_available": False,
        "proxy_underlyings": [{"ticker": p["ticker"],
                               "relationship": p["relationship"],
                               "confidence": p["confidence"]} for p in proxies],
        "options_possible_on": [p["ticker"] for p in proxies],
        "no_direct_trade_reason": NO_DIRECT_OPTIONS_SENTENCE,
        "evidence_refs": evidence_refs[:MAX_EVIDENCE_REFS],
        "recommended_action": "proxy_analysis" if proxies else "research_only",
    }


def build_payload(entity: dict[str, Any], proxies: list[dict[str, Any]],
                  window_days: int = WINDOW_DAYS) -> dict[str, Any]:
    """One inbox.upsert_candidate payload for a detected private company."""
    name = entity["name"]
    refs = list(entity.get("refs") or [])
    for p in proxies:
        if len(refs) >= MAX_EVIDENCE_REFS:
            break
        refs.append({"source_domain": "corpus_evidence", "url": None,
                     "ref": None,
                     "note": f"{p['relationship']} link → {p['ticker']}: "
                             f"{p['evidence']}"[:240]})
    ppj = build_private_proxy_json(name, proxies, refs)
    if proxies:
        proxy_bit = "; ".join(f"{p['ticker']} ({p['relationship']}, "
                              f"conf {p['confidence']})" for p in proxies)
        proxy_txt = f"Evidenced public proxies: {proxy_bit}."
    else:
        proxy_txt = ("No ownership/proxy relationship evidenced in the "
                     "corpus — research only.")
    sample = (refs[0].get("note") if refs else "") or ""
    return dict(
        candidate_type="PRIVATE_COMPANY_PROXY_CANDIDATE",
        label=f"Private-company proxy: {name}",
        summary=(f"{name}: private-company mentions "
                 f"({entity.get('recurrence')} rows, "
                 f"{entity.get('cross_source_count')} sources, {window_days}d). "
                 f"{proxy_txt}")[:300],
        evidence=refs[:MAX_EVIDENCE_REFS],
        seed_symbols=[p["ticker"] for p in proxies],
        meta={
            "producer": PRODUCER,
            "research_domain": _route_domain(name, sample),
            "keywords": ([name] + [p["ticker"] for p in proxies])[:10],
            "entities": [name],
            "private_proxy_json": ppj,
        },
        safe_action_level="OPERATOR_REVIEW_REQUIRED",
        ttl_days=PROXY_TTL_DAYS,
    )


def collect_payloads(*, limit: int = MAX_CANDIDATES_PER_RUN,
                     window_days: int = WINDOW_DAYS,
                     notes: list[str] | None = None,
                     skipped: dict[str, int] | None = None,
                     corpus: list[dict[str, Any]] | None = None,
                     ) -> list[dict[str, Any]]:
    """READ-ONLY end-to-end pass: corpus → detection → proxy resolution →
    payload dicts. Never writes anything (lane runner + dry runs share it)."""
    if corpus is None:
        corpus = collect_corpus(window_days, notes)
    entities = detect_private_companies(
        corpus, min_recurrence=MIN_RECURRENCE, min_sources=MIN_SOURCES,
        limit=limit, skipped=skipped)
    payloads = []
    for ent in entities:
        texts = [str(corpus[i].get("text") or "") for i in ent.get("row_idxs", [])
                 if 0 <= i < len(corpus)]
        payloads.append(build_payload(ent, extract_proxies(ent["name"], texts),
                                      window_days))
    return payloads


# ── run entry point + targeted --company analysis ────────────────────────────

def run_discovery(*, dry_run: bool = False, limit: int | None = None,
                  window_days: int = WINDOW_DAYS) -> dict[str, Any]:
    """Full discovery pass. Live mode writes candidates exclusively through
    inbox.upsert_candidate; dry runs write nothing."""
    notes: list[str] = []
    skipped: dict[str, int] = {}
    corpus = collect_corpus(window_days, notes)
    payloads = collect_payloads(limit=int(limit) if limit else MAX_CANDIDATES_PER_RUN,
                                window_days=window_days, notes=notes,
                                skipped=skipped, corpus=corpus)
    candidates: list[dict[str, Any]] = []
    upserted = 0
    for p in payloads:
        ppj = p["meta"]["private_proxy_json"]
        summary = {"candidate_type": p["candidate_type"], "label": p["label"],
                   "research_domain": p["meta"]["research_domain"],
                   "recommended_action": ppj["recommended_action"],
                   "proxy_underlyings": ppj["proxy_underlyings"],
                   "private_proxy_json": ppj}
        if not dry_run:
            row = inbox.upsert_candidate(actor=ACTOR, **p)
            summary.update({
                "id": row.get("id"), "status": row.get("status"),
                "seen_count": row.get("seen_count"),
                "score": (float(row["discovery_score"])
                          if row.get("discovery_score") is not None else None)})
            upserted += 1
        candidates.append(summary)
    return {
        "mode": "private_proxy",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(dry_run),
        "window_days": int(window_days),
        "thresholds": {"min_recurrence": MIN_RECURRENCE,
                       "min_sources": MIN_SOURCES,
                       "limit": int(limit) if limit else MAX_CANDIDATES_PER_RUN},
        "scanned_rows": len(corpus),
        "detected": len(payloads),
        "upserted": upserted,
        "would_upsert": len(candidates) if dry_run else None,
        "skipped_reasons": skipped,
        "notes": notes,
        "candidates": candidates,
    }


def analyze_company(name: str, *, window_days: int = WINDOW_DAYS,
                    corpus: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Targeted --company analysis of ONE name against the existing corpus.
    ALWAYS report-only (never writes). Honest verdicts:
      no_evidence          name never appears in the corpus → validate-first
      directly_listed      the name itself validates as a listed symbol
      listed_company_name  the name prefix-matches a listed company's profile
      below_thresholds     mentioned, but recurrence/cross-source gates fail
      candidate            passes all gates; payload preview included
    """
    name = (name or "").strip()
    notes: list[str] = []
    if corpus is None:
        corpus = collect_corpus(window_days, notes)

    word = re.compile(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])")
    word_ci = re.compile(word.pattern, re.IGNORECASE)
    rows = [r for r in corpus if word_ci.search(str(r.get("text") or ""))]
    exact_case_rows = [r for r in rows if word.search(str(r.get("text") or ""))]
    sources = sorted({str(r.get("source") or "unknown") for r in rows})

    verdict = _ticker_verdict(name.upper()) if " " not in name else None
    listed = _listed_symbols_for_name(name)

    report: dict[str, Any] = {
        "mode": "private_proxy_company",
        "company": name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": int(window_days),
        "corpus_rows": len(corpus),
        "mentions": len(rows),
        "exact_case_mentions": len(exact_case_rows),
        "cross_source_count": len(sources),
        "sources": sources[:6],
        "ticker_validation": verdict,
        "listed_name_symbols": listed,
        "notes": notes,
        "proxies": [],
        "candidate_payload": None,
        "writes": "none — targeted --company analysis is always report-only",
    }

    if not rows:
        report["status"] = "no_evidence"
        report["message"] = (
            f"No entity evidence for {name!r} in the existing news/research "
            f"corpus ({window_days}d, {len(corpus)} rows). Validate-first: "
            f"confirm the company name and let coverage accumulate before "
            f"proxy research — no candidate can be emitted without evidence.")
        return report
    if verdict and verdict.get("verdict") in (VERDICT_VALID,
                                              VERDICT_NEEDS_VALIDATION):
        report["status"] = "directly_listed"
        report["message"] = (f"{name!r} validates as a listed/ambiguous symbol "
                             f"({verdict.get('verdict')}) — not a private "
                             f"company; use the ticker directly.")
        return report
    if listed:
        report["status"] = "listed_company_name"
        report["message"] = (f"{name!r} matches listed company profile(s) "
                             f"{listed} — not a private company.")
        return report

    texts = [str(r.get("text") or "") for r in rows]
    proxies = extract_proxies(name, texts)
    report["proxies"] = proxies

    entity = {
        "name": name, "key": name.lower(), "recurrence": len(rows),
        "cross_source_count": len(sources), "sources": sources[:6],
        "mid_sentence_count": 0,  # targeted mode: name is operator-supplied
        "refs": [{"source_domain": str(r.get("source") or "unknown"),
                  "url": r.get("url"), "ref": r.get("ref"),
                  "note": str(r.get("text") or "")[:240]}
                 for r in rows[:MAX_EVIDENCE_REFS]],
    }
    payload = build_payload(entity, proxies, window_days)
    report["candidate_payload"] = payload

    gates = {"recurrence_ok": len(rows) >= MIN_RECURRENCE,
             "cross_source_ok": len(sources) >= MIN_SOURCES}
    report["gates"] = gates
    if all(gates.values()):
        report["status"] = "candidate"
        report["message"] = (
            f"{name!r} passes detection gates ({len(rows)} mentions, "
            f"{len(sources)} sources); "
            + (f"{len(proxies)} evidenced public proxies."
               if proxies else "no proxy relationship evidenced in the corpus "
                               "— research_only."))
    else:
        report["status"] = "below_thresholds"
        failed = [k for k, v in gates.items() if not v]
        report["message"] = (
            f"{name!r} is mentioned but fails detection gates ({failed}); "
            f"payload preview shown for review, nothing would be emitted by "
            f"the scheduled lane.")
    return report


# ── worker-pool lane runner (read-only; the pool owns all writes) ────────────

def private_proxy_lane_runner(lane_cfg: dict[str, Any], *,
                              dry_run: bool = False) -> list[dict[str, Any]]:
    """'private_proxy' lane runner — returns payload dicts and NEVER writes
    (worker_pool applies caps, fences, do-no-harm, and the upsert)."""
    try:
        limit = int(lane_cfg.get("max_candidates_per_run") or MAX_CANDIDATES_PER_RUN)
    except (TypeError, ValueError):
        limit = MAX_CANDIDATES_PER_RUN
    return collect_payloads(limit=max(1, limit))


worker_pool.register_lane_runner(LANE_ID, private_proxy_lane_runner, replace=True)
