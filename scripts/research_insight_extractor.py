#!/usr/bin/env python3
"""research_insight_extractor.py — Extract structured insights from research sources.

Converts free-text research (news articles, transcripts, notes) into structured
decision-ready data with strategy_type, thesis, time_horizon, confidence.

Usage:
    python3 scripts/research_insight_extractor.py --from-news [--json]
    python3 scripts/research_insight_extractor.py --from-text "DGRO is a great dividend growth ETF for long-term income" --symbol DGRO [--json]
    python3 scripts/research_insight_extractor.py --from-catalysts [--json]
"""
import json, os, re, sys, hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

# Thesis detection keywords
_BULLISH = {"buy", "add", "accumulate", "upgrade", "outperform", "bullish", "upside",
            "growth", "opportunity", "breakout", "undervalued", "strong", "dividend raise",
            "dividend increase", "beat expectations", "guidance raise", "contract win"}
_BEARISH = {"sell", "trim", "avoid", "downgrade", "underperform", "bearish", "downside",
            "risk", "overvalued", "breakdown", "dividend cut", "miss", "guidance lower",
            "debt concern", "default risk", "recession"}
_INCOME = {"dividend", "yield", "income", "distribution", "payout", "coupon", "DRIP",
           "ex-div", "covered call", "premium", "monthly income"}
_HORIZON_SHORT = {"this week", "short-term", "swing", "day trade", "near-term", "immediate"}
_HORIZON_LONG = {"long-term", "retirement", "compound", "decade", "5-year", "10-year", "lifetime"}

# A ticker is 1-5 capitals. Every one of the 5,197 bad ``symbol`` values measured on 2026-11-07 is a topic code
# (``d194_closed_end_funds_...``, ``k_medicaid_...``) carried in the source row's own ``symbol`` column.
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def symbol_universe(cur) -> set[str]:
    """Every symbol the desks know as an instrument: the strategy classification table + the watchlist master.

    This is the validation set for a *source-provided* symbol. It is deliberately wider than the set the free-text
    scan uses (active strategy rows only): a bare uppercase word in prose is a ticker only if a desk tracks it,
    whereas a source's own symbol field is a deliberate assertion that only needs to name a real instrument.
    """
    cur.execute("""SELECT upper(symbol) AS s FROM ticker_strategy_classifications WHERE symbol IS NOT NULL
                   UNION
                   SELECT upper(symbol) AS s FROM watchlist_symbol_master WHERE symbol IS NOT NULL""")
    return {r["s"] for r in cur.fetchall() if r.get("s")}


def validate_symbol(candidate, universe) -> str | None:
    """A candidate is a symbol only when it is ticker-shaped AND a known instrument; otherwise it is a topic tag."""
    s = str(candidate or "").strip().upper()
    if not s or not _TICKER_RE.fullmatch(s):
        return None
    return s if s in universe else None


def is_topic_slug(symbol) -> bool:
    """A source ``symbol`` that is a topic code (``d194_closed_end_funds``, ``k_medicaid_...``), not a ticker.

    Ticker shape is the same ``^[A-Z]{1,5}$`` rule as :func:`validate_symbol`. A class share such as ``BRK.B``
    is not a slug: it has no underscore, no digit and is not longer than five characters, so the row is still
    examined. An empty source symbol is not a slug.
    """
    raw = str(symbol or "").strip()
    if not raw:
        return False
    upper = raw.upper()
    if _TICKER_RE.fullmatch(upper):
        return False
    return "_" in raw or any(ch.isdigit() for ch in raw) or len(upper) > 5


def _scripts_on_path() -> None:
    root = str(PROJECT_ROOT / "scripts")
    if root not in sys.path:
        sys.path.insert(0, root)


def _names_for(session: dict, symbol: str) -> list[str]:
    """Issuer descriptions already on the instrument record. A test injects ``names_by_symbol``; CI does not
    open the instrument file. No name means no company-name match, which is the closed answer."""
    table = session.get("names_by_symbol")
    if isinstance(table, dict):
        return [str(n) for n in (table.get(symbol) or []) if n]
    if os.environ.get("TRADE_AI_CI") == "1":
        return []
    cache = session.get("instrument_names")
    if cache is None:
        try:
            _scripts_on_path()
            from lib.company_name_index import _instruments
            cache = _instruments() or {}
        except Exception:
            cache = {}
        session["instrument_names"] = cache
    entry = cache.get(symbol) if isinstance(cache, dict) else None
    desc = entry.get("description") if isinstance(entry, dict) else None
    return [str(desc)] if desc else []


def _tracked(session: dict, candidates: list[str]) -> set[str]:
    """Held symbols plus which of ``candidates`` are on the watchlist.

    A test injects ``held_watch``. CI does not read holdings. Production uses the existing held reader
    (holdings file, symbols only) and ``membership_watchlist`` for the candidates. A failed read is an empty
    set: a bare ticker is then refused, which does not create a false symbol.
    """
    if "held_watch" in session:
        return {str(s).strip().upper() for s in session["held_watch"] if str(s).strip()}
    if os.environ.get("TRADE_AI_CI") == "1":
        return set()
    held = session.get("_held_symbols")
    if held is None:
        held = set()
        try:
            _scripts_on_path()
            from lib.data_broker.watch_domains import membership_held
            symbols, _label = membership_held()
            held = {str(s).strip().upper() for s in symbols if str(s).strip()}
        except Exception:
            held = set()
        session["_held_symbols"] = held
    watch: set[str] = set()
    try:
        _scripts_on_path()
        from lib.data_broker.watch_domains import membership_watchlist
        watch = {str(s).strip().upper() for s in membership_watchlist(candidates) if str(s).strip()}
    except Exception:
        watch = set()
    return set(held) | watch


def _company_hit_symbols(session: dict, text: str, known: set, universe: set) -> list[str]:
    """Symbols whose issuer name occurs in ``text``, even when the ticker word does not.

    The candidate list is otherwise the uppercase tokens, so "Coca-Cola Consolidated reported" would
    never be offered to the matcher. An injected ``names_by_symbol`` is the whole pool (tests). In
    production the pool is the active strategy symbols, and a 5-letter hint word must occur before the
    phrase matcher runs.
    """
    table = session.get("names_by_symbol")
    if isinstance(table, dict):
        pool = [str(s).strip().upper() for s in table if str(s).strip()]
    elif os.environ.get("TRADE_AI_CI") == "1":
        return []
    else:
        pool = list(known)
    if not pool or not text:
        return []
    _scripts_on_path()
    from lib.symbol_match import evidence

    allowed = set(known) | set(universe)
    body = text.lower()
    found: list[str] = []
    for sym in pool:
        if allowed and sym not in allowed:
            continue
        names = _names_for(session, sym)
        if not names:
            continue
        if not any(len(word) >= 5 and word in body for name in names for word in re.split(r"[^A-Za-z]+", name.lower())):
            continue
        if evidence(text, sym, company_names=names).get("how") == "company" and sym not in found:
            found.append(sym)
    return found


def _topic_skip(source_type: str, source_reference: str | None) -> dict:
    return {
        "symbol": None,
        "strategy_type": None,
        "source_type": source_type,
        "source_reference": source_reference,
        "supporting_entities": [],
        "skipped": "topic_slug",
        "source_symbol_not_ticker": True,
        "active": False,
        "id": None,
        "bare_tickers_refused": [],
    }


def _url_host(url) -> str | None:
    try:
        host = (urlparse(str(url or "")).hostname or "").lower().strip(".")
    except (ValueError, AttributeError):
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def source_id_for_url(cur, url, cache: dict | None = None) -> int | None:
    """The registered ``research_sources`` row for the article's own host, or None when the host is not registered.

    Attribution is only ever an exact host match. ``news_articles.source`` values like ``google_news:Yahoo
    Finance`` are feeds, not publishers, so nothing is inferred from them; an unregistered publisher stays NULL.
    """
    host = _url_host(url)
    if not host:
        return None
    if cache is not None and host in cache:
        return cache[host]
    cur.execute("""SELECT id FROM research_sources
                    WHERE source_type='web' AND lower(regexp_replace(source_name, '^www\\.', '')) = %s
                    ORDER BY active DESC, id ASC LIMIT 1""", (host,))
    r = cur.fetchone()
    sid = int(r["id"]) if r and r.get("id") is not None else None
    if cache is not None:
        cache[host] = sid
    return sid


def has_signal(insight: dict) -> bool:
    """False for the neutral default the keyword extractor emits when it finds nothing.

    Measured 2026-11-07: 47,388 of 52,520 rows (90%) were ``neutral`` at confidence 0.5 — the default, not an
    observation. Such a row is still written (it is how the batch selector knows the source was examined, since it
    de-duplicates on ``source_reference``) but with ``active=false``, so no consumer reads it as research.
    """
    return (insight.get("thesis_type") != "neutral"
            or insight.get("price_target") is not None
            or insight.get("yield_thesis") is not None)


def _get_conn(dry_run: bool = False):
    import psycopg2
    # Env first (the executor passes the allowlisted DB_PASSWORD), then the checkout .env line (cron sources none).
    # No env and no .env (a fresh worktree) -> no password argument: libpq's own lookup (~/.pgpass) decides.
    pw = os.environ.get("DB_PASSWORD", "")
    env_file = PROJECT_ROOT / ".env"
    if not pw and env_file.is_file():
        for line in env_file.read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", **({"password": pw} if pw else {}))
    if dry_run:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from lib.lane_last_receipt import enforce_readonly
        enforce_readonly(conn)  # dry run: the server refuses any write (AGENTS.md §6)
    return conn


def extract_insight(text: str, symbol: str = None, source_type: str = "manual",
                    source_reference: str = None, dry_run: bool = False,
                    source_url: str = None, session: dict | None = None) -> dict:
    """Extract structured insight from free text. Classification-first.

    dry_run: classify only -- returns before the INSERT (AGENTS.md §6), READ ONLY session.

    session: an optional batch context (``{"conn", "cur", "known", "universe", "source_ids"}``). The cron path used
    to open a database connection per article and re-read the symbol tables every time; a batch now shares one
    connection and one symbol universe. When no session is given this function opens and closes its own.

    2026-11-07 (LQ-20261107-124): three data defects, each fixed where it was produced —
    (1) a source's ``symbol`` value is validated against the instrument universe instead of being uppercased
        straight into the row (34% of the last run's rows carried a topic code as a symbol);
    (2) ``source_id`` is resolved from the article's own URL host against ``research_sources`` (was NULL on all
        52,520 rows);
    (3) the neutral/0.5 default is written ``active=false``, so a row that says nothing is not read as research.
    """
    import psycopg2.extras
    # A topic-slug source row is not an insight. Checked before any connection so the batch cannot write one.
    if is_topic_slug(symbol):
        return _topic_skip(source_type, source_reference)
    own = session is None
    if own:
        conn = _get_conn(dry_run)
        session = {"conn": conn, "cur": conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)}
    cur = session["cur"]

    if "known" not in session:
        cur.execute("SELECT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
        session["known"] = {r["symbol"] for r in cur.fetchall()}
    if "universe" not in session:
        session["universe"] = symbol_universe(cur)
    known, universe = session["known"], session["universe"]

    text_lower = text.lower()
    words = set(text_lower.split())

    # A symbol needs a cashtag, the company's name, or a source symbol that is held or on the watchlist.
    # A bare uppercase word that happens to be a listed ticker (COLA, RMD) is refused. lib.symbol_match.evidence
    # is that check; how=ticker is not acceptance, and the LQ-1061 subject filter is a different question.
    _scripts_on_path()
    from lib.symbol_match import evidence

    given = validate_symbol(symbol, universe)
    candidates: list[str] = []
    if given:
        candidates.append(given)
    for raw in re.findall(r"\$([A-Za-z]{1,5})\b", text or ""):
        sym = raw.upper()
        if sym in universe and sym not in candidates:
            candidates.append(sym)
    for w in re.findall(r"\b[A-Z]{2,5}\b", text or ""):
        if (w in known or w in universe) and w not in candidates:
            candidates.append(w)
    for sym in _company_hit_symbols(session, text, known, universe):
        if sym not in candidates:
            candidates.append(sym)
    tracked = _tracked(session, candidates)
    symbols_found: list[str] = []
    refused: list[str] = []
    if given and given in tracked:
        symbols_found.append(given)
    for sym in candidates:
        if sym in symbols_found:
            continue
        how = evidence(text, sym, company_names=_names_for(session, sym)).get("how")
        if how in {"cashtag", "company"}:
            symbols_found.append(sym)
        else:
            refused.append(sym)

    # Get strategy_type from classification
    strategy_type = None
    if symbols_found:
        cur.execute("SELECT strategy_type FROM ticker_strategy_classifications WHERE symbol=%s AND active=TRUE",
                    (symbols_found[0],))
        r = cur.fetchone()
        if r:
            strategy_type = r["strategy_type"]

    # Detect thesis type
    bull_score = sum(1 for kw in _BULLISH if kw in text_lower)
    bear_score = sum(1 for kw in _BEARISH if kw in text_lower)
    thesis_type = "neutral"
    if bull_score > bear_score + 1:
        thesis_type = "bullish"
    elif bear_score > bull_score + 1:
        thesis_type = "bearish"
    elif bull_score > 0 and bear_score > 0:
        thesis_type = "mixed"

    # Detect time horizon
    time_horizon = "medium"
    if any(kw in text_lower for kw in _HORIZON_SHORT):
        time_horizon = "short"
    elif any(kw in text_lower for kw in _HORIZON_LONG):
        time_horizon = "long"

    # Confidence from text signals
    confidence = 0.5
    if bull_score + bear_score >= 4:
        confidence = 0.7
    if bull_score + bear_score >= 6:
        confidence = 0.8

    # Income relevance
    income_words = sum(1 for kw in _INCOME if kw in text_lower)
    yield_thesis = None
    if income_words >= 2:
        yield_thesis = f"{income_words} income-related signals detected"

    # Key arguments extraction (simple: first 3 sentences)
    sentences = [s.strip() for s in re.split(r'[.!?]', text) if len(s.strip()) > 20]
    key_args = [{"text": s[:200]} for s in sentences[:3]]

    # Contradiction flags
    contradictions = []
    if bull_score > 0 and bear_score > 0:
        contradictions.append({"type": "mixed_signals", "detail": f"bullish:{bull_score} bearish:{bear_score}"})

    # Structured thesis
    structured = f"{thesis_type.upper()} ({time_horizon}-term)"
    if symbols_found:
        structured = f"{symbols_found[0]}: {structured}"
    if yield_thesis:
        structured += " — income-relevant"

    # Price target extraction
    price_target = None
    pt_match = re.search(r'(?:target|price target|PT)[:\s]*\$?(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if pt_match:
        price_target = float(pt_match.group(1))

    insight = {
        "symbol": symbols_found[0] if symbols_found else None,
        "strategy_type": strategy_type,
        "source_type": source_type,
        "source_reference": source_reference,
        "thesis_type": thesis_type,
        "time_horizon": time_horizon,
        "confidence": confidence,
        "headline": text[:100],
        "structured_thesis": structured,
        "supporting_entities": symbols_found,
        "key_arguments": key_args,
        "contradiction_flags": contradictions,
        "price_target": price_target,
        "yield_thesis": yield_thesis,
        "risk_factors": [],
        "raw_text": text[:2000],
        "extraction_model": "keyword_v1",
        "extraction_confidence": confidence,
    }

    insight["source_id"] = (source_id_for_url(cur, source_url, session.setdefault("source_ids", {}))
                            if source_url else None)
    insight["active"] = has_signal(insight)
    # The source's own value, kept for the run's accounting (a topic code is reported, never written as a symbol).
    insight["source_symbol_not_ticker"] = bool(symbol) and given is None
    insight["bare_tickers_refused"] = refused
    insight["skipped"] = None

    if dry_run:
        insight["id"] = None
        if own:
            conn.close()
        return insight

    # Store in DB
    cur.execute("""
        INSERT INTO research_insights
            (symbol, strategy_type, source_id, source_type, source_reference, thesis_type, time_horizon,
             confidence, headline, structured_thesis, supporting_entities, key_arguments,
             contradiction_flags, price_target, yield_thesis, risk_factors, raw_text,
             extraction_model, extraction_confidence, active)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (insight["symbol"], insight["strategy_type"], insight["source_id"], source_type, source_reference,
          thesis_type, time_horizon, confidence, insight["headline"][:200],
          structured, symbols_found, json.dumps(key_args, default=str),
          json.dumps(contradictions, default=str), price_target, yield_thesis,
          json.dumps([], default=str), text[:2000], "keyword_v1", confidence, insight["active"]))
    row = cur.fetchone()
    insight["id"] = row["id"] if row else None

    if own:
        conn.commit()
        conn.close()
    return insight


def _open_session(dry_run: bool) -> dict:
    """One connection for a whole batch (the cron path used to open one per article)."""
    import psycopg2.extras
    conn = _get_conn(dry_run)
    return {"conn": conn, "cur": conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)}


def _count(skips: dict | None, key: str) -> None:
    if skips is not None:
        skips[key] = skips.get(key, 0) + 1  # nosemgrep: tq-py-missing-as-zero -- a skip counter starts at zero because nothing has been skipped yet; it counts rows this run examined and set aside, never a measurement of the source


def _note(row: dict, skips: dict | None) -> None:
    """Account for a row that was examined but carries no usable symbol / no signal (never silently dropped)."""
    if row.get("skipped") == "topic_slug":
        _count(skips, "topic_slug")
        return
    if row.get("source_symbol_not_ticker"):
        _count(skips, "source_symbol_not_ticker")
    if row.get("bare_tickers_refused"):
        _count(skips, "bare_ticker_no_evidence")
    if not row.get("active", True):
        _count(skips, "no_signal")


def extract_from_news(limit: int = 100, dry_run: bool = False, errors: list = None, skips: dict = None) -> list:
    """Extract insights from recent news articles that don't have linked insights yet.

    errors: when given, collects one string per failed extraction (was silently dropped).
    skips: when given, counts candidates skipped before extraction (``text_too_short``), a source ``symbol`` that
    was a topic code (``source_symbol_not_ticker``), and rows with no signal (``no_signal``)."""
    session = _open_session(dry_run)
    cur, conn = session["cur"], session["conn"]

    cur.execute("""
        SELECT na.id, na.symbol, na.title, na.summary, na.source, na.strategy_type, na.source_url
        FROM news_articles na
        WHERE na.relevance_score >= 0.4
        AND NOT EXISTS (SELECT 1 FROM research_insights ri WHERE ri.source_reference = 'news:' || na.id::text)
        ORDER BY na.created_at DESC LIMIT %s
    """, (limit,))
    articles = cur.fetchall()

    results = []
    try:
        for a in articles:
            text = f"{a.get('title', '')}. {a.get('summary', '')}"
            if len(text.strip()) < 20:
                _count(skips, "text_too_short")
                continue
            if is_topic_slug(a.get("symbol")):
                _count(skips, "topic_slug")
                continue
            try:
                r = extract_insight(text, symbol=a.get("symbol"), source_type="news",
                                    source_reference=f"news:{a['id']}", dry_run=dry_run,
                                    source_url=a.get("source_url"), session=session)
                conn.commit()  # LQ-20261107-198: the batch path shares one connection; commit each row or close() discards it
                results.append(r)
                _note(r, skips)
            except Exception as e:
                conn.rollback()  # a failed row must not poison the shared transaction (earlier rows are already committed)
                if errors is not None:
                    errors.append(f"news:{a['id']}: {type(e).__name__}: {str(e)[:120]}")
    finally:
        conn.close()
    return results


def extract_from_catalysts(limit: int = 100, dry_run: bool = False, errors: list = None, skips: dict = None) -> list:
    """Extract insights from catalyst events (``errors`` / ``skips`` as in extract_from_news)."""
    session = _open_session(dry_run)
    cur, conn = session["cur"], session["conn"]

    cur.execute("""
        SELECT ce.id, ce.symbol, ce.headline, ce.description, ce.catalyst_type, ce.strategy_type, ce.source_url
        FROM catalyst_events ce
        WHERE ce.confidence >= 0.3
        AND NOT EXISTS (SELECT 1 FROM research_insights ri WHERE ri.source_reference = 'catalyst:' || ce.id::text)
        ORDER BY ce.created_at DESC LIMIT %s
    """, (limit,))
    catalysts = cur.fetchall()

    results = []
    try:
        for c in catalysts:
            text = f"{c.get('headline', '')}. {c.get('description', '')}"
            if len(text.strip()) < 20:
                _count(skips, "text_too_short")
                continue
            if is_topic_slug(c.get("symbol")):
                _count(skips, "topic_slug")
                continue
            try:
                r = extract_insight(text, symbol=c.get("symbol"), source_type="catalyst",
                                    source_reference=f"catalyst:{c['id']}", dry_run=dry_run,
                                    source_url=c.get("source_url"), session=session)
                conn.commit()  # LQ-20261107-198: see extract_from_news
                results.append(r)
                _note(r, skips)
            except Exception as e:
                conn.rollback()
                if errors is not None:
                    errors.append(f"catalyst:{c['id']}: {type(e).__name__}: {str(e)[:120]}")
    finally:
        conn.close()
    return results


def run_default(dry_run: bool = False, as_json: bool = False) -> int:
    """Default/cron path: news + catalysts. Exit 1 only when extractions were attempted and EVERY one
    failed (a run that wrote nothing it could have); per-item failures are counted, not hidden."""
    started_at = datetime.now(timezone.utc).isoformat()
    errors: list = []
    skips: dict = {}
    try:
        n = extract_from_news(dry_run=dry_run, errors=errors, skips=skips)
        c = extract_from_catalysts(dry_run=dry_run, errors=errors, skips=skips)
    except Exception as exc:
        if not dry_run:
            _receipt(ok=False, started_at=started_at, error=f"{type(exc).__name__}: {exc}",
                     output={"produced_count": 0, "attempted_count": 0,
                             "skipped_reasons": {"dependency_unavailable": 1}})
        raise
    verb = "Would extract" if dry_run else "Extracted"
    print(f"[research] {verb} {len(n)} from news, {len(c)} from catalysts ({len(n)+len(c)} total)"
          + (f", {len(errors)} failed" if errors else ""))
    for e in errors[:5]:
        print(f"  failed: {e}")
    if skips:
        print("  skipped: " + ", ".join(f"{k}={v}" for k, v in sorted(skips.items())))
    if as_json:
        print(json.dumps({"news": len(n), "catalysts": len(c), "failed": len(errors),
                          "dry_run": dry_run}, indent=2))
    ok = not (errors and not (n or c))
    output = lane_output(n + c, failed=len(errors), skips=skips, dry_run=dry_run)
    if not dry_run:
        _receipt(ok=ok, started_at=started_at,
                 error=None if ok else f"all {len(errors)} extractions failed: {errors[0]}",
                 summary={"news": len(n), "catalysts": len(c), "failed": len(errors)}, output=output)
    else:  # dry run: no receipt (AGENTS.md §6); the fields a real run would record, on stderr
        print("LANE_OUTPUT " + json.dumps(output, sort_keys=True), file=sys.stderr)
    return 0 if ok else 1


def lane_output(results: list, *, failed: int, skips: dict, dry_run: bool) -> dict:
    """LaneRunReceipt@v2 output fields (n8n expected_output, unit: signal rows inserted into research_insights).

    produced = rows with a RETURNING id that carry a signal (``active``; a dry run inserts nothing: 0, the
    would-insert count is ``dry_run``). A row examined and found signal-less is counted under
    ``skipped_reasons.no_signal``, and one whose source ``symbol`` was a topic code under
    ``source_symbol_not_ticker``. attempted = candidates (news + catalysts with no linked insight yet) extracted or
    failed. Every candidate already has a row (NOT EXISTS on source_reference) = ``no_new_input``."""
    produced = [r for r in results if r.get("id") is not None and r.get("active", True)]
    inserted = len(produced)
    skipped = {k: int(v) for k, v in skips.items() if v}
    if failed:
        skipped["extract_failed"] = int(failed)
    if dry_run and results:
        skipped["dry_run"] = len(results)
    attempted = len(results) + int(failed)
    if inserted:
        empty_reason = None
    elif not attempted:
        empty_reason = "no_new_input"
    elif dry_run:
        empty_reason = None
    else:
        # examined and found nothing: the store gained a row, but not an insight
        empty_reason = "no_signal" if results else None
    return {"produced_count": inserted, "attempted_count": max(attempted, inserted), "skipped_reasons": skipped,
            "empty_reason": empty_reason}


def _receipt(**kw):
    """Real-run receipt (data/runtime/research-insight-extractor_last.json, ok_at on success only)."""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from lib.lane_last_receipt import write_lane_receipt

    kw.setdefault("exit_code", 0 if kw.get("ok") else 1)
    write_lane_receipt("research-insight-extractor", script="research_insight_extractor.py", **kw)


if __name__ == "__main__":
    if "--from-text" in sys.argv:
        idx = sys.argv.index("--from-text")
        text = sys.argv[idx + 1]
        sym = sys.argv[sys.argv.index("--symbol") + 1].upper() if "--symbol" in sys.argv else None
        r = extract_insight(text, symbol=sym)
        print(f"  {r['symbol'] or '?':>6} {r['thesis_type']:>8} {r['time_horizon']:>6} conf={r['confidence']:.1f} — {r['structured_thesis']}")
    elif "--from-news" in sys.argv:
        results = extract_from_news()
        print(f"[research] Extracted {len(results)} insights from news")
        if "--json" in sys.argv:
            print(json.dumps(results[:5], indent=2, default=str))
    elif "--from-catalysts" in sys.argv:
        results = extract_from_catalysts()
        print(f"[research] Extracted {len(results)} insights from catalysts")
    else:
        # Default (the cron form): extract from both
        sys.exit(run_default(dry_run="--dry-run" in sys.argv, as_json="--json" in sys.argv))
