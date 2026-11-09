"""cio_brief_consistency.py — the CIO overnight brief must say only what its own rows say (LQ-20261107-1318).

The operator's complaint (2026-11-08, 20:22 ET): "why did we get two different results? why wasn't it uniform?"
The 18:00 preview was hand-composed prose; the live brief was a document. They disagreed. Two rules make that
recurrence visible instead of invisible:

* :func:`check_brief` — CLAIMS. Every synopsis line must carry ``source_ids``; every source id must resolve to a
  row or a named feed the brief itself carries; every sentence of an LLM-written summary must name either a symbol
  the brief holds a row for or a parenthetical source tag (a deterministic summary is projected from the same
  document's rows and its context lines name the regime and the calendar, so it is not gated for mapping); and a
  summary that says "no cause" about a name whose research row names one is a contradiction, not a summary —
  that check runs on both kinds of summary.
* :func:`run_check` — ONE RUN. The Home card embeds a copy of the brief, so a card assembled from two builds (a
  fresh ``stop_advice`` beside an older ``synopsis``) can disagree with itself. Every piece that carries a
  ``run_id`` is compared to the document's; a piece that carries only a clock is compared to that clock with a
  tolerance, because a run's own steps finish minutes apart.

Pure: a document in, findings out. No database, no network, no LLM, no writes. Advisory only — this module never
decides a verdict, it only refuses to let a claim stand without the row that supports it.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

SCHEMA = "CIOOvernightBrief@v1"

#: A run's own steps (positions -> synopsis -> research) finish minutes apart; anything older than this is another
#: build. The brief lane runs several times a day, so a previous run is always hours away.
PIECE_CLOCK_TOLERANCE = timedelta(minutes=60)

#: Source-id families the brief may cite. `<prefix>:<rest>`; a bare id from this set is also accepted.
_KNOWN_BARE = {
    "market_risk", "macro_calendar", "earnings_dates", "market_regime_snapshots", "risk_regime",
    "positions_current", "reentry_decision_desk", "stop_last_known", "news", "research", "filings",
    "calendar", "quotes",
}

#: Parenthetical tags a summary sentence may carry instead of naming a symbol: "(research)", "(week_ahead)".
_TAG = re.compile(r"\(([^)]{2,80})\)")
_TAG_OK = re.compile(r"^[a-z0-9_ ,/&+-]+$")

_NO_CAUSE = (
    "does not support a specific", "no specific cause", "no cause", "nothing explains",
    "could not be explained", "unexplained", "no actor or mechanism is evidenced", "without a cause",
)
_EVIDENCE_NONE = (
    "does not support", "no direct cause", "no evidence", "not supported", "no mechanism", "cannot be tied",
)
_SEGMENT = re.compile(r"\b(WHO/WHAT|WHY|IMPACT)\s*:", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

#: Upper-case tokens that are not symbols. Kept small and explicit: a gate that cries wolf gets suppressed, and a
#: suppressed gate is worse than no gate.
_NOT_SYMBOLS = {
    "CPI", "PPI", "FOMC", "FED", "ETF", "ETFS", "ATR", "GTC", "ET", "UTC", "CIO", "CEO", "CFO", "SEC", "FDA",
    "IPO", "AI", "US", "USA", "NYSE", "NASDAQ", "SIP", "AM", "PM", "WHO", "WHAT", "WHY", "IMPACT", "QTY", "HOLD",
    "RAISE", "ADD", "STOP", "RED", "ORANGE", "GREEN", "YELLOW", "OK", "NO", "AND", "OR", "THE", "FOR", "NOT",
    "NEW", "ONE", "TWO", "ALL", "IV", "HV", "RSI", "MACD", "SMA", "EMA", "VIX", "SPX", "NDX", "DJI", "WARN",
    "STRESS", "SECTOR", "TECHNICAL", "NEAR", "ENTRY", "OVERSOLD", "REVIEW", "WAIT", "READY", "BREADTH",
}


def _str(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _dt(v: Any) -> datetime | None:
    """Any timestamp the brief writes, as an aware UTC datetime; None when it cannot be read."""
    if isinstance(v, datetime):
        d = v
    else:
        s = _str(v)
        if not s:
            return None
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def _add(out: list[dict[str, str]], code: str, where: str, detail: str) -> None:
    out.append({"code": code, "where": where, "detail": detail})


# ── the rows a claim may point at ────────────────────────────────────────────────────────────────────────────


def _rows(doc: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = [r for r in (doc.get("holdings") or []) if isinstance(r, Mapping)]
    rows += [r for r in (doc.get("stop_advice") or []) if isinstance(r, Mapping)]
    rows += [r for r in (doc.get("watchlist") or []) if isinstance(r, Mapping)]
    return rows


def row_symbols(doc: Mapping[str, Any]) -> set[str]:
    """Every symbol the document carries a row for; a claim naming a name must have one."""
    out: set[str] = set()
    for r in _rows(doc):
        sym = _str(r.get("symbol")).upper()
        if sym:
            out.add(sym)
    wa = doc.get("week_ahead")
    for ev in (wa.get("earnings") or []) if isinstance(wa, Mapping) else []:
        if isinstance(ev, Mapping):
            sym = _str(ev.get("symbol")).upper()
            if sym:
                out.add(sym)
    return out


def _news_ids(doc: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for r in _rows(doc):
        for n in r.get("news") or []:
            if isinstance(n, Mapping) and n.get("id") is not None:
                out.add(str(n["id"]))
    return out


def _research_lanes(doc: Mapping[str, Any]) -> set[str]:
    lanes: set[str] = set()
    for r in _rows(doc):
        res = r.get("research")
        if isinstance(res, Mapping):
            lane = _str(res.get("lane")).lower()
            if lane:
                lanes.add(lane)
    return lanes


def resolves(source_id: str, doc: Mapping[str, Any]) -> bool:
    """Is this source id backed by the document? ``news:<id>`` must be a news row, ``research:<lane>`` a lane that
    answered, ``stop_last_known:<SYM>[:account]`` a name with a row; the rest are named feeds the brief reads."""
    sid = _str(source_id)
    if not sid:
        return False
    head, _, rest = sid.partition(":")
    if not rest:
        return head in _KNOWN_BARE
    if head not in _KNOWN_BARE:
        return False
    if head == "news":
        return rest.split(":")[0] in _news_ids(doc)
    if head == "research":
        lanes = _research_lanes(doc)
        return not lanes or rest.lower() in lanes  # a brief that answered nothing still owns the citation form
    if head == "stop_last_known":
        return rest.split(":")[0].upper() in row_symbols(doc)
    return True


# ── claims ──────────────────────────────────────────────────────────────────────────────────────────────────


def _synopsis_blocks(doc: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    syn = doc.get("synopsis")
    if not isinstance(syn, Mapping):
        return []
    return [(k, v) for k, v in syn.items() if isinstance(v, Mapping)]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text or "") if s.strip()]


def _sentence_symbols(sentence: str, symbols: set[str]) -> list[str]:
    toks = set(re.findall(r"\b[A-Z][A-Z0-9]{1,5}\b", sentence))
    return sorted(t for t in toks if t in symbols and t not in _NOT_SYMBOLS)


def _has_source_tag(sentence: str) -> bool:
    return any(_TAG_OK.match(tag.strip()) and len(tag.split()) <= 4 for tag in _TAG.findall(sentence))


def _names_cause(research_text: str) -> bool | None:
    """True when the research's WHY segment names something, False when it says the evidence does not, None with
    no WHY segment at all (the research was not written to that shape, so there is nothing to contradict)."""
    text = _str(research_text)
    if not text:
        return None
    marks = list(_SEGMENT.finditer(text))
    parts: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        parts[m.group(1).upper()] = text[m.end():end].strip()
    why = parts.get("WHY")
    if why is None:
        return None
    low = why.lower()
    return not any(p in low for p in _EVIDENCE_NONE)


def _says_no_cause(text: str) -> bool:
    low = _str(text).lower()
    return any(p in low for p in _NO_CAUSE)


def _research_by_symbol(doc: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for r in _rows(doc):
        sym = _str(r.get("symbol")).upper()
        res = r.get("research")
        if sym and isinstance(res, Mapping):
            out.setdefault(sym, res)
    return out


def check_brief(doc: Mapping[str, Any] | None) -> dict[str, Any]:
    """``{"state": "PASS"|"FAIL", "schema", "run_id", "findings": [...], "checked": {...}}``.

    FAIL means the brief is not fit to publish: a claim with no row behind it is exactly the disagreement the
    operator was shown. Every finding names its place, so a writer (or a reviewer) can fix it without reading prose.
    """
    if not isinstance(doc, Mapping):
        return {"state": "FAIL", "schema": None, "run_id": None, "checked": {},
                "findings": [{"code": "not_a_document", "where": "-", "detail": "not a JSON object"}]}

    findings: list[dict[str, str]] = []
    symbols = row_symbols(doc)
    blocks = _synopsis_blocks(doc)

    # 0. a gate that passes whatever it is handed passes nothing
    if _str(doc.get("schema")) != SCHEMA:
        _add(findings, "not_a_document", "schema",
             f"schema is {_str(doc.get('schema')) or '(missing)'!r}, not {SCHEMA}")

    # 1. every synopsis line carries the ids of the rows it summarizes
    for key, block in blocks:
        line = _str(block.get("line"))
        if line and not (block.get("source_ids") or []):
            _add(findings, "synopsis_line_without_sources", f"synopsis.{key}", line[:120])

    # 2. every id resolves to a row or a named feed
    for key, block in blocks:
        for sid in block.get("source_ids") or []:
            if not resolves(str(sid), doc):
                _add(findings, "unknown_source_id", f"synopsis.{key}", str(sid))
    syn = doc.get("synopsis")
    if isinstance(syn, Mapping):
        for sid in syn.get("source_ids") or []:
            if not resolves(str(sid), doc):
                _add(findings, "unknown_source_id", "synopsis", str(sid))
    for row in doc.get("stop_advice") or []:
        if isinstance(row, Mapping):
            for sid in row.get("source_ids") or []:
                if not resolves(str(sid), doc):
                    _add(findings, "unknown_source_id", f"stop_advice.{row.get('symbol')}", str(sid))

    # 3. every summary sentence maps to a symbol row or a source tag. Only prose is gated: a deterministic
    #    summary is projected from this document's own rows by the same run (its context lines name the regime,
    #    the macro calendar and the advisory footer, not a holding), while an LLM summary is the text that can
    #    drift from the rows — and is what the operator was shown disagreeing with Home.
    summary = doc.get("summary")
    summary_text = _str(summary.get("text")) if isinstance(summary, Mapping) else ""
    sentences = _sentences(summary_text)
    summary_claims = _str(summary.get("source")).lower() == "llm" if isinstance(summary, Mapping) else False
    if summary_claims:
        for sentence in sentences:
            if not _sentence_symbols(sentence, symbols) and not _has_source_tag(sentence):
                _add(findings, "unmapped_summary_sentence", "summary.text", sentence[:160])

    # 4. a summary (or synopsis) line may not say "no cause" about a name whose research names one
    research = _research_by_symbol(doc)
    for sentence in sentences:
        if not _says_no_cause(sentence):
            continue
        for sym in _sentence_symbols(sentence, symbols):
            if _names_cause(_str((research.get(sym) or {}).get("text"))) is True:
                _add(findings, "summary_says_no_cause_research_names_one", f"summary.text {sym}",
                     f"{sym}: the summary says there is no cause; its research row names one")
    for key, block in blocks:
        line = _str(block.get("line"))
        if not line or not _says_no_cause(line):
            continue
        for sym in _sentence_symbols(line, symbols):
            if _names_cause(_str((research.get(sym) or {}).get("text"))) is True:
                _add(findings, "synopsis_says_no_cause_research_names_one", f"synopsis.{key} {sym}",
                     f"{sym}: the synopsis says there is no cause; its research row names one")

    checked = {
        "rows": len(_rows(doc)),
        "synopsis_blocks": len(blocks),
        "summary_sentences": len(sentences),
        "summary_claims": summary_claims,
    }
    return {
        "state": "FAIL" if findings else "PASS",
        "schema": _str(doc.get("schema")) or None,
        "run_id": _str(doc.get("run_id")) or None,
        "findings": findings,
        "checked": checked,
    }


# ── one run ─────────────────────────────────────────────────────────────────────────────────────────────────


def _pieces(doc: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    out: list[tuple[str, Mapping[str, Any]]] = []
    syn = doc.get("synopsis")
    if isinstance(syn, Mapping):
        out.append(("synopsis", syn))
    for i, row in enumerate(doc.get("stop_advice") or []):
        if isinstance(row, Mapping):
            out.append((f"stop_advice[{row.get('symbol') or i}]", row))
    return out


def run_check(doc: Mapping[str, Any] | None) -> dict[str, Any]:
    """Is every run-scoped piece of this brief from the document's own run?

    ``same_run`` is False only on a contradiction: a piece that names a different ``run_id``, or a piece whose own
    clock is older than :data:`PIECE_CLOCK_TOLERANCE` before the document's ``generated_at``. A piece carrying
    neither id nor clock is not a contradiction, only unverifiable; it is listed under ``unverifiable`` so the
    writer hook (cc-deepseek-3) can close the gap by stamping ``run_id`` on each piece.
    """
    if not isinstance(doc, Mapping):
        return {"run_id": None, "generated_at": None, "same_run": False,
                "differing": [], "unverifiable": [], "text": "no brief to read"}
    rid = _str(doc.get("run_id")) or None
    gen = _dt(doc.get("generated_at"))
    differing: list[dict[str, str]] = []
    unverifiable: list[str] = []
    for name, piece in _pieces(doc):
        pid = _str(piece.get("run_id")) or None
        clock = _dt(piece.get("as_of")) or _dt(piece.get("generated_at"))
        if rid and pid:
            if pid != rid:
                differing.append({"piece": name, "run_id": pid, "detail": f"{name} is from run {pid}, not {rid}"})
            continue
        if clock and gen:
            delta = gen - clock
            if delta > PIECE_CLOCK_TOLERANCE:
                mins = int(delta.total_seconds() // 60)
                differing.append({"piece": name, "run_id": None,
                                  "detail": f"{name} was built {mins} min before this run ({clock.isoformat()})"})
            continue
        if not clock and not pid:
            unverifiable.append(name)
    text = None
    if rid is None:
        text = "the brief carries no run_id, so its pieces cannot be tied to one build"
    elif differing:
        text = "; ".join(d["detail"] for d in differing[:3])
        if len(differing) > 3:
            text += f"; and {len(differing) - 3} more"
    return {
        "run_id": rid,
        "generated_at": _str(doc.get("generated_at")) or None,
        "same_run": rid is not None and not differing,
        "differing": differing,
        "unverifiable": unverifiable,
        "text": text,
    }


def iter_findings(doc: Mapping[str, Any] | None) -> Iterable[dict[str, str]]:
    """Convenience for a writer hook: the findings alone."""
    return check_brief(doc)["findings"]
