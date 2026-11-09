"""The CIO's reasoning pass: a complete, sourced packet in; a validated plan out (LQ-20261107-1320).

Why this module exists. The overnight brief's ``llm_narrative`` sent ``json.dumps(packet)[:12000]``
— the model saw a packet cut mid-way (news titles only, research text truncated) while
``latest.json`` was ~75k characters. That is why a summary could say ANET "names no cause" when
the research answer named a sale: the answer was not in the model's input at all. Here a packet is
built **per held name, structured and complete**, and nothing is ever cut from a held name: if the
packet must shrink, optional sections (long price history, extra news rows) go first and the drop
is recorded in the packet and the receipt.

Two operator rails decide the shape (2026-11-08, verbatim relayed by claude-lead):

* "We don't want no false positives. So anything we want is accurate actionable validated data."
  Every value the model may use is a **fact**: ``{"value", "unit", "source_id", "as_of"}``. The
  model's answer is then validated against the packet — a number that is not a fact, a citation
  that is not a source_id, or a fact past its freshness limit is a rejection, and the caller falls
  back to the deterministic line. Nothing is shown "with a caveat"; it is dropped.
* "the data should be consistent … it should come across to any medium." The packet carries the
  market-read **record id** and the CIO verdict's record id, and surfaces a disagreement between
  them instead of silently preferring one.

Tier A (held names, Home, stop advice) is ``claude-opus-5-5`` at medium effort through the
governed Anthropic transport; the process id is ``cio_held_thinking``. This module builds the
request and the validator; the caller owns the transport. ``--dry-run`` prints the exact request
that WOULD be sent — packet size, token estimate, body digest — and never calls a model.

AUTHORITY: READ_ONLY_ADVISORY. No quantity, order, stop instruction or broker call is produced;
"protect" and "re-enter" are advisory conditions the CIO may act on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

SCHEMA = "CIOThinkingPacket@v1"
THINKING_SCHEMA = "CIOThinking@v1"
PROCESS_ID = "cio_held_thinking"
MODEL = "claude-opus-5-5"          # Tier A (config/anthropic_credit_policy.json models.high)
EFFORT = "medium"                  # operator 2026-11-08: "Opus 5.5 Medium for the front page"
TIER = "high"
MAX_TOKENS = 4096
MAX_PACKET_CHARS = 120_000         # a ceiling, not a truncation point: sections drop first
MAX_NEWS_PER_NAME = 6
MAX_FILINGS_PER_NAME = 6
MAX_BARS_PER_NAME = 5
MAX_MEMORY_PER_NAME = 6

#: A source older than its limit is not a reading; the validator rejects it (operator rule 1).
FRESHNESS_HOURS = {
    "quote": 36.0,
    "bars": 96.0,
    "stops": 96.0,
    "news": 72.0,
    "sec": 240.0,
    "research": 24.0,
    "risk_tier": 24.0,
    "regime": 12.0,
    "outlook": 24.0,
    "cio_verdict": 24.0,
    "memory": 24.0 * 30,
    "calendar": 24.0 * 10,
    "macro": 24.0,
}

#: A printed number, including the magnitude shorthand a source uses ("$44.4M", "260k",
#: "44.4 million").
_NUMBER_RE = re.compile(
    r"-?\$?\d[\d,]*(?:\.\d+)?"
    r"(?:\s*(?:million|billion|thousand|mn|bn|[MBKmbk])(?![a-z]))?"
    r"\s*%?"
)
#: Names, not measurements: a form, regulation or quarter label is a word. Masked before a number
#: is extracted, so "Form 144" and "10b5-1" are never mistaken for an invented quantity.
_LABEL_RE = re.compile(
    r"\b10b5-?1\b|\b10b-?5\b|\b1[03]\s?[DG]\b|\b(?:8|10)-K(?:/A)?\b|\b10-Q\b|\bS-\d+\b|\bQ[1-4]\b"
    r"|@v\d+\b",
    re.I,
)
#: A form number is masked only when the packet itself carries that form; "Form 999" does not.
_FORM_RE = re.compile(r"\b(?:Form|form)\s+(\d+[A-Za-z/\-]*)")
_MAGNITUDE = {"m": 1e6, "million": 1e6, "mn": 1e6, "b": 1e9, "billion": 1e9, "bn": 1e9,
              "k": 1e3, "thousand": 1e3}
_UNIT_GUESS = (
    (re.compile(r"^\$"), "usd"),
    (re.compile(r"%$"), "pct"),
)


# ── facts ────────────────────────────────────────────────────────────────────────────────────


def _iso(value: Any) -> Optional[str]:
    """An ISO-8601 instant, or None. A date alone is read at 00:00 UTC."""
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def fact(value: Any, *, unit: str, source_id: str, as_of: Any) -> Optional[dict[str, Any]]:
    """One citable value. ``None`` when the value or its source stamp is unknown — an unstated
    number is omitted, never defaulted to zero."""
    if value is None or value == "":
        return None
    try:
        num: Any = float(value) if not isinstance(value, bool) else None
    except (TypeError, ValueError):
        num = None
    if num is None:
        return None
    stamp = _iso(as_of)
    if not stamp:
        return None
    return {"value": num, "unit": unit, "source_id": str(source_id), "as_of": stamp}


def fact_text(value: Any, *, source_id: str, as_of: Any) -> Optional[dict[str, Any]]:
    """A citable non-numeric statement (a headline, a research sentence)."""
    text = str(value or "").strip()
    stamp = _iso(as_of)
    if not text or not stamp:
        return None
    return {"text": text, "source_id": str(source_id), "as_of": stamp}


def _unit_of_token(token: str) -> str:
    for rx, unit in _UNIT_GUESS:
        if rx.search(token):
            return unit
    return "number"


def number_key(value: Any) -> Optional[str]:
    """The comparison form of a printed number: no currency sign, no commas, no percent sign,
    no magnitude word, trailing zeros trimmed. ``$44.4M``, ``44.4 million`` and ``44400000`` are
    one key; ``164.27`` is 164.27."""
    text = str(value or "").strip().lower()
    if not text:
        return None
    mult = 1.0
    m = re.search(r"(million|billion|thousand|mn|bn|[mbk])\s*%?\s*$", text)
    if m:
        mult = _MAGNITUDE[m.group(1)]
        text = text[: m.start()]
    cleaned = re.sub(r"[^\d.]", "", text)
    if not cleaned or cleaned.count(".") > 1:
        return None
    try:
        num = float(cleaned) * mult
    except ValueError:
        return None
    if num == 0:
        return "0"
    return f"{num:.10f}".rstrip("0").rstrip(".")


def _mask_labels(text: str, allowed_forms: Optional[Iterable[str]] = None) -> str:
    text = _LABEL_RE.sub(" ", str(text or ""))

    def repl(m: "re.Match[str]") -> str:
        num = re.match(r"\d+", m.group(1))
        return " " if num and num.group(0) in allowed_forms else m.group(0)

    if allowed_forms is not None:
        text = _FORM_RE.sub(repl, text)
    return text


def numbers_in(text: Any, *, allowed_forms: Optional[Iterable[str]] = None) -> list[str]:
    """Every printed number in a sentence, in comparison form."""
    out = []
    for m in _NUMBER_RE.finditer(_mask_labels(text, allowed_forms)):
        key = number_key(m.group(0))
        if key:
            out.append(key)
    return out


# ── the packet ──────────────────────────────────────────────────────────────────────────────


def _news_rows(news: Sequence[Mapping[str, Any]], symbol: str, *, dropped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows, total = [], len(news)
    for n in news[:MAX_NEWS_PER_NAME]:
        sid = f"news:{n.get('id')}" if n.get("id") is not None else f"news:{symbol}:{n.get('published_at')}"
        rows.append({
            "title": str(n.get("title") or "")[:400],
            "summary": str(n.get("summary") or "")[:800] or None,
            "source": n.get("source"),
            "source_id": sid,
            "as_of": _iso(n.get("published_at")),
            "url": n.get("url") or n.get("source_url"),
        })
    if total > len(rows):
        dropped.append({"symbol": symbol, "section": "news", "count": total - len(rows),
                        "reason": f"beyond the newest {MAX_NEWS_PER_NAME}"})
    return rows


def _filing_rows(filings: Sequence[Mapping[str, Any]], symbol: str) -> list[dict[str, Any]]:
    rows = []
    for f in filings[:MAX_FILINGS_PER_NAME]:
        sid = f.get("id")
        rows.append({
            "form": f.get("form"),
            "code": f.get("code"),
            "filer": f.get("filer"),
            "relation": f.get("relation"),
            "intent": f.get("intent"),
            "shares": fact(f.get("shares"), unit="shares",
                           source_id=f"sec:{sid}", as_of=f.get("filed")),
            "value": fact(f.get("value"), unit="usd",
                          source_id=f"sec:{sid}", as_of=f.get("filed")),
            "filed": _iso(f.get("filed")),
            "source_id": f"sec:{sid}",
            "url": f.get("url"),
        })
    return rows


def _stop_facts(stops: Mapping[str, Any], symbol: str) -> list[dict[str, Any]]:
    out = []
    for s in (stops or {}).get("working") or []:
        out.append({
            "account": s.get("account"),
            "price": fact(s.get("stop_price"), unit="price",
                          source_id=f"stop_last_known:{symbol}:{s.get('account')}",
                          as_of=s.get("captured_at")),
            "qty": fact(s.get("qty"), unit="shares",
                        source_id=f"stop_last_known:{symbol}:{s.get('account')}",
                        as_of=s.get("captured_at")),
            "status": s.get("status"),
        })
    return [s for s in out if s.get("price") or s.get("qty")]


def holding_block(item: Mapping[str, Any], *, dropped: list[dict[str, Any]],
                  packet_as_of: Any = None) -> dict[str, Any]:
    """One held name, complete: price, position, stops, news, filings, events, research, memory."""
    symbol = str(item.get("symbol") or "").upper()
    quote_source = f"quote:{symbol}:{item.get('quote_source') or 'unknown'}"
    as_of = item.get("quote_time") or item.get("as_of")
    block: dict[str, Any] = {
        "symbol": symbol,
        "held": True,
        "price": fact(item.get("price"), unit="price", source_id=quote_source, as_of=as_of),
        "move_pct": fact(item.get("move_pct"), unit="pct", source_id=quote_source, as_of=as_of),
        "market_value": fact(item.get("market_value"), unit="usd",
                             source_id=f"holdings:{symbol}", as_of=item.get("holdings_as_of") or as_of),
        "shares": fact(item.get("shares"), unit="shares",
                       source_id=f"holdings:{symbol}", as_of=item.get("holdings_as_of") or as_of),
        "stops": _stop_facts(item.get("stops") or {}, symbol),
        "stop_coverage": (item.get("stops") or {}).get("coverage"),
        "stop_cushion": fact((item.get("stops") or {}).get("cushion"), unit="pct",
                             source_id=f"stops:{symbol}",
                             as_of=(item.get("stops") or {}).get("captured_at")),
        "bar_closes": [
            {"date": b.get("date") or b.get("session_date"),
             "close": fact(b.get("close"), unit="price", source_id=f"bars:{symbol}",
                           as_of=b.get("date") or b.get("session_date"))}
            for b in (item.get("bars") or [])[-MAX_BARS_PER_NAME:]
        ],
        "news": _news_rows(item.get("news") or [], symbol, dropped=dropped),
        "filings": _filing_rows(item.get("filings") or [], symbol),
        "events": [e for e in (item.get("events") or []) if isinstance(e, Mapping)],
        "research": {
            "status": (item.get("research") or {}).get("status"),
            "lane": (item.get("research") or {}).get("lane"),
            "text": (item.get("research") or {}).get("text"),
            "sources": (item.get("research") or {}).get("sources"),
        },
        "memory_events": [m for m in ((item.get("memory") or {}).get("events") or []) if m][:MAX_MEMORY_PER_NAME],
        "cio_decision": item.get("cio_decision"),
        "action_advisory": item.get("action_advisory"),
        "reasons": item.get("reasons"),
    }
    block["facts"] = facts_of(block)
    annotate_staleness(block["facts"], as_of=packet_as_of)
    block["numbers"] = sorted({k for f in block["facts"]
                               if f.get("value") is not None and not f.get("stale")
                               for k in [number_key(f.get("value"))] if k})
    block["materiality"] = _materiality(block)
    # A stale price or stop is not a reading. The name is carried with one line instead of a
    # number the CIO must not act on, and any model answer for it is rejected.
    blocking = [f for f in block["facts"]
                if f.get("stale") and _source_class(str(f.get("source_id"))) in {"quote", "stops"}]
    block["measurable"] = not blocking
    block["not_measured"] = (None if not blocking
                             else f"not measured: {blocking[0]['stale_detail']}")
    return block


def annotate_staleness(facts: Iterable[Mapping[str, Any]], *, as_of: Any) -> None:
    for f in facts:
        detail = freshness_problem(f, as_of=as_of)
        if detail:
            # facts_of returns copies of the packet's own dicts, so these keys annotate the copy
            # the caller is about to store; the declared Mapping type is what mypy sees.
            f["stale"] = True  # type: ignore[index] -- see above
            f["stale_detail"] = detail  # type: ignore[index] -- see above


def _materiality(block: Mapping[str, Any]) -> float:
    """How much this name deserves the model's attention: dollars at risk × the move.

    A ranking weight only — it never reaches the operator and never stands in for a value. A name
    with neither dollars nor a move ranks by whether it has an event; 0 here is "nothing to weigh",
    not "the position is worth nothing".
    """
    mv_fact = block.get("market_value") or {}
    move_fact = block.get("move_pct") or {}
    mv = float(mv_fact["value"]) if mv_fact.get("value") is not None else None
    move = abs(float(move_fact["value"])) if move_fact.get("value") is not None else None
    has_event = 1.0 if block.get("events") else 0.0
    if mv is None and move is None:
        return has_event
    dollars = 0.0 if mv is None else mv / 1000.0
    momentum = 0.0 if move is None else move / 10.0
    return round(dollars * (1.0 + momentum) + has_event, 3)


#: Derived keys. Walking them again would duplicate every fact and rewrite its path.
_DERIVED = {"facts", "numbers", "stats", "materiality"}


def facts_of(node: Any, *, _path: str = "") -> list[dict[str, Any]]:
    """Every fact in a packet node, with the path it sits at."""
    out: list[dict[str, Any]] = []
    if isinstance(node, Mapping):
        if "source_id" in node and "as_of" in node and ("value" in node or "text" in node):
            out.append({**node, "path": _path or "fact"})
            return out
        for key, value in node.items():
            if key in _DERIVED:
                continue
            out.extend(facts_of(value, _path=f"{_path}.{key}" if _path else str(key)))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            out.extend(facts_of(value, _path=f"{_path}[{i}]"))
    return out


def build_packet(
    items: Sequence[Mapping[str, Any]],
    *,
    as_of: Any,
    run_id: Optional[str] = None,
    regime: Optional[Mapping[str, Any]] = None,
    outlook: Optional[Mapping[str, Any]] = None,
    cio_verdict: Optional[Mapping[str, Any]] = None,
    macro_gate: Optional[Mapping[str, Any]] = None,
    reentry: Optional[Mapping[str, Any]] = None,
    calendar: Optional[Mapping[str, Any]] = None,
    risk_tier: Optional[Mapping[str, Any]] = None,
    report: Optional[Mapping[str, Any]] = None,
    prior_packet: Optional[Mapping[str, Any]] = None,
    prior_thinking: Optional[Mapping[str, Any]] = None,
    optional_items: Optional[Sequence[Mapping[str, Any]]] = None,
    max_chars: int = MAX_PACKET_CHARS,
) -> dict[str, Any]:
    """The complete, sourced packet for the reasoning pass.

    Held names are never dropped and never cut: if the serialized packet exceeds ``max_chars``,
    optional sections shrink in this order — price history, then news depth, then filing depth —
    and every drop is listed in ``dropped``. A section that would still not fit is a hard refusal
    (``packet_over_budget``), because silently sending a partial held name is the defect this
    module replaces.
    """
    dropped: list[dict[str, Any]] = []
    stamp = _iso(as_of)
    if not stamp:
        raise ValueError("as_of_required")
    blocks = [holding_block(it, dropped=dropped, packet_as_of=stamp) for it in items]
    blocks.sort(key=lambda b: b["materiality"], reverse=True)
    # Non-held names (watched, not owned) are included as context and are the first thing to go:
    # a held name's block is never dropped to make room.
    for it in optional_items or []:
        block = holding_block(it, dropped=dropped, packet_as_of=stamp)
        block["held"] = False
        blocks.append(block)

    record: dict[str, Any] = {
        "regime": _record_block(regime, kind="regime", source_prefix="regime"),
        "outlook": _record_block(outlook, kind="outlook", source_prefix="outlook"),
        "cio_verdict": _record_block(cio_verdict, kind="cio_verdict", source_prefix="cio_verdict"),
    }
    record["disagreement"] = disagreement(record.get("regime"), record.get("outlook"), record.get("cio_verdict"))

    packet: dict[str, Any] = {
        "schema": SCHEMA,
        "as_of": stamp,
        "run_id": run_id,
        "advisory_only": True,
        "verdict_owner": "CIO",
        "process_id": PROCESS_ID,
        "model": {"id": MODEL, "effort": EFFORT, "tier": TIER},
        "record": record,
        "macro_gate": dict(macro_gate or {}) or None,
        "reentry": dict(reentry or {}) or None,
        "risk_tier": dict(risk_tier or {}) or None,
        "week_ahead": dict(calendar or {}) or None,
        "report": dict(report or {}) or None,
        "delta": (delta_block(prior_packet, {"as_of": stamp, "names": blocks}, prior_thinking)
                  if prior_packet else None),
        "names": blocks,
        "dropped": dropped,
    }
    _recount(packet)
    if packet["stats"]["chars"] > max_chars:
        packet = _shrink(packet, max_chars)
    return packet


def _record_block(doc: Optional[Mapping[str, Any]], *, kind: str, source_prefix: str) -> Optional[dict[str, Any]]:
    """A market-read record reduced to the fields a medium may print, with its own record id."""
    if not doc:
        return None
    rid = doc.get("record_id") or doc.get("id")
    as_of = doc.get("as_of") or doc.get("generated_at") or doc.get("observed_at")
    out: dict[str, Any] = {"record_id": rid, "as_of": _iso(as_of)}
    for key in ("regime", "posture", "score", "confidence", "odds", "verdict", "caveat"):
        if key in doc and not isinstance(doc[key], (dict, list)):
            out[key] = doc[key]
    out["values"] = [f for f in facts_of({k: v for k, v in doc.items() if k not in {"values"}})
                     if str(f.get("source_id") or "").startswith(source_prefix)]
    if not out["values"]:
        # A record without per-field stamps still carries one stamp for the whole record.
        for key in ("score", "confidence", "odds"):
            if isinstance(doc.get(key), (int, float)):
                out.setdefault("values", []).append(
                    {"value": float(doc[key]), "unit": key, "source_id": f"{source_prefix}:{rid}",
                     "as_of": out["as_of"], "path": key}
                )
    return out


def disagreement(*blocks: Optional[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Where two market-read records say different things. Shown, never silently resolved."""
    out = []
    named = [(b.get("record_id"), b) for b in blocks if b]
    for i in range(len(named)):
        for j in range(i + 1, len(named)):
            (rid_a, a), (rid_b, b) = named[i], named[j]
            for key in ("regime", "posture", "verdict"):
                va, vb = a.get(key), b.get(key)
                if va and vb and str(va).lower() != str(vb).lower():
                    out.append({"field": key, "left": {"record_id": rid_a, "value": va},
                                "right": {"record_id": rid_b, "value": vb}})
    return out


def _shrink(packet: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """Drop optional names and depth, lowest-materiality first, and record it. A held name's
    events, research, stops and news headline are never touched."""
    for block in sorted([b for b in packet["names"] if not b.get("held")], key=lambda b: b["materiality"]):
        packet["names"].remove(block)
        packet["dropped"].append({"symbol": block.get("symbol"), "section": "name", "count": 1,
                                  "reason": "packet over budget; not held"})
        if _recount(packet)["stats"]["chars"] <= max_chars:
            return packet
    for depth in ("bars", "news", "filings"):
        keep = {"bars": 2, "news": 3, "filings": 2}[depth]
        for block in sorted(packet["names"], key=lambda b: b["materiality"]):
            field = "bar_closes" if depth == "bars" else depth
            rows = block.get(field) or []
            if len(rows) > keep:
                block[field] = rows[:keep]
                packet["dropped"].append({"symbol": block["symbol"], "section": depth,
                                          "count": len(rows) - keep, "reason": "packet over budget"})
                packet["stats"]["chars"] = len(json.dumps(packet, default=str))
                if packet["stats"]["chars"] <= max_chars:
                    return _recount(packet)
    _recount(packet)
    if packet["stats"]["chars"] > max_chars:
        raise ValueError("packet_over_budget")
    return packet


def _recount(packet: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in packet.items() if k not in {"facts", "numbers", "stats"}}
    facts: list[dict[str, Any]] = []
    for key, value in body.items():
        facts.extend(facts_of(value, _path=key))
    annotate_staleness(facts, as_of=packet.get("as_of"))
    packet["facts"] = facts
    # A stale value is not citable: a number the model prints that only a stale fact supports is
    # an invented number to this validator, which is the operator's "dropped, never shown".
    packet["numbers"] = sorted({k for f in facts
                                if f.get("value") is not None and not f.get("stale")
                                for k in [number_key(f.get("value"))] if k})
    text = json.dumps(packet, default=str)
    packet.setdefault("stats", {})["names"] = len(packet.get("names") or [])
    packet["stats"].update({"chars": len(text), "est_tokens": estimate_tokens(text),
                            "facts": len(facts)})
    return packet


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


# ── freshness ───────────────────────────────────────────────────────────────────────────────


def _source_class(source_id: str) -> str:
    return str(source_id or "").split(":", 1)[0]


def freshness_problem(f: Mapping[str, Any], *, as_of: Any) -> Optional[str]:
    """``stale:<class>`` when a fact's stamp is older than its class allows (or in the future)."""
    cls = _source_class(str(f.get("source_id") or ""))
    limit = FRESHNESS_HOURS.get(cls)
    stamp = _iso(f.get("as_of"))
    now = _iso(as_of)
    if limit is None or stamp is None or now is None:
        return None
    age = (datetime.fromisoformat(now) - datetime.fromisoformat(stamp)).total_seconds() / 3600.0
    if age > limit:
        return f"stale:{cls}:{age:.1f}h>{limit:g}h"
    return None


# ── the validator ───────────────────────────────────────────────────────────────────────────


def _numbers_in_thinking(
    node: Any, *, allowed_forms: Optional[Iterable[str]] = None, _path: str = ""
) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key in {"source_id", "record_id", "schema", "model", "symbol"}:
                continue
            out.extend(_numbers_in_thinking(value, allowed_forms=allowed_forms,
                                            _path=f"{_path}.{key}" if _path else str(key)))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            out.extend(_numbers_in_thinking(value, allowed_forms=allowed_forms, _path=f"{_path}[{i}]"))
    elif isinstance(node, str):
        for key in numbers_in(node, allowed_forms=allowed_forms):
            out.append((key, _path or "text"))
    return out


def _form_vocabulary(packet: Mapping[str, Any]) -> set[str]:
    """The form numbers the packet actually carries ("144", "4")."""
    out: set[str] = set()
    for block in packet.get("names") or []:
        for row in block.get("filings") or []:
            for m in re.finditer(r"\d+", str(row.get("form") or "")):
                out.add(m.group(0))
    return out


def _date_numbers(packet: Mapping[str, Any]) -> set[str]:
    """The numbers a date in the packet is built from, so a printed date must be a packet date."""
    out: set[str] = set()
    rx = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")
    for f in packet.get("facts") or []:
        for m in rx.finditer(str(f.get("as_of") or "")):
            out.update(k for k in numbers_in(m.group(0)) if k)
    return out


def _source_ids_in(node: Any) -> set[str]:
    if isinstance(node, Mapping):
        out = {str(node["source_id"])} if "source_id" in node else set()
        for value in node.values():
            out |= _source_ids_in(value)
        return out
    if isinstance(node, list):
        out: set[str] = set()
        for value in node:
            out |= _source_ids_in(value)
        return out
    return set()


def validate(thinking: Mapping[str, Any], packet: Mapping[str, Any]) -> dict[str, Any]:
    """The no-false-positives gate. Returns ``{"ok", "problems", "checked_numbers", "sources"}``.

    Rejections, in the operator's words:
    * a number that is not a fact in the packet ("invented_number");
    * a number whose fact is past its freshness limit ("stale_input");
    * a ``source_id`` that names nothing in the packet ("unknown_source");
    * a value cited to a fact with a different value ("mismatched_value").

    ``thinking`` is the structured answer: ``{"names": {SYM: {"what_happened", "why_it_matters",
    "both_ways", "protect": {...}, "reentry": {...}, "watch": [...]}}}``. Prose is allowed only
    inside those fields; every number in every field must be a packet fact.
    """
    problems: list[dict[str, Any]] = []
    if not isinstance(thinking, Mapping):
        return {"ok": False, "problems": [{"code": "not_a_mapping"}], "checked_numbers": 0, "sources": 0}
    allowed_forms = _form_vocabulary(packet)
    known = set(packet.get("numbers") or []) | _date_numbers(packet)
    facts_by_source: dict[str, list[dict[str, Any]]] = {}
    for f in packet.get("facts") or []:
        facts_by_source.setdefault(str(f.get("source_id") or ""), []).append(f)

    for key, path in _numbers_in_thinking(thinking, allowed_forms=allowed_forms):
        if key not in known:
            problems.append({"code": "invented_number", "number": key, "path": path})
    for sid in sorted(_source_ids_in(thinking)):
        if sid not in facts_by_source and not any(sid_from_packet.startswith(sid) for sid_from_packet in facts_by_source):
            problems.append({"code": "unknown_source", "source_id": sid})
        elif facts_by_source.get(sid) and all(f.get("stale") for f in facts_by_source[sid]):
            problems.append({"code": "stale_input", "source_id": sid,
                             "detail": facts_by_source[sid][0].get("stale_detail")})
    seen = 0
    for sym, body in (thinking.get("names") or {}).items():
        block = next((b for b in packet.get("names") or [] if b.get("symbol") == sym), None)
        if block is None:
            problems.append({"code": "unknown_name", "symbol": sym})
            continue
        if block.get("measurable") is False:
            problems.append({"code": "stale_input", "symbol": sym,
                             "detail": block.get("not_measured")})
            continue
        for field in ("protect", "reentry"):
            plan = body.get(field) if isinstance(body, Mapping) else None
            if not isinstance(plan, Mapping):
                continue
            level = plan.get("level")
            sid = plan.get("source_id")
            if level is None:
                continue
            seen += 1
            key = number_key(level)
            if not key:
                problems.append({"code": "invalid_level", "symbol": sym, "field": field, "level": str(level)[:40]})
                continue
            if sid:
                # A cited level must be a fact of the packet, and the value must match it.
                if str(sid) not in facts_by_source:
                    problems.append({"code": "unknown_source", "symbol": sym, "source_id": sid})
                elif not any(number_key(f.get("value")) == key for f in facts_by_source[str(sid)]):
                    problems.append({"code": "mismatched_value", "symbol": sym, "field": field,
                                     "number": key, "source_id": sid})
            elif key not in (block.get("numbers") or []):
                problems.append({"code": "level_not_in_packet", "symbol": sym, "field": field, "number": key})
    return {
        "ok": not problems,
        "problems": problems,
        "checked_numbers": sum(len(numbers_in(str(v), allowed_forms=allowed_forms))
                               for v in _string_values(thinking)),
        "sources": len(facts_by_source),
        "levels_checked": seen,
    }


def _string_values(node: Any) -> Iterable[str]:
    if isinstance(node, Mapping):
        for value in node.values():
            yield from _string_values(value)
    elif isinstance(node, list):
        for value in node:
            yield from _string_values(value)
    elif isinstance(node, str):
        yield node


# ── the deterministic fallback ──────────────────────────────────────────────────────────────


def deterministic_thinking(block: Mapping[str, Any], *, model_label: str = "fallback") -> dict[str, Any]:
    """The line the card shows when the model is unavailable or its answer is rejected.

    Every number is taken from the block's own facts, so the fallback passes the same validator.
    """
    sym = block.get("symbol")
    ev = (block.get("events") or [{}])[0]
    size = (ev.get("size") or {})
    stops = [s for s in (block.get("stops") or []) if s.get("price")]
    stop = stops[0]["price"]["value"] if stops else None
    what = ev.get("what") or f"a {block.get('move_pct', {}).get('value')}% move"
    if ev.get("who") and size.get("shares") is not None:
        what = f"{ev['who']} {ev.get('kind')}: {size['shares']:,.0f} shares"
        if size.get("value_usd") is not None:
            what += f" (~${size['value_usd']:,.0f})"
    parts = [f"{sym}: {what}."]
    if ev.get("premise_correction"):
        parts.append(f"Read it as {ev['premise_correction']}.")
    if stop is not None:
        parts.append(f"Working stop ${stop:,.2f} on the record.")
    parts.append("Model reasoning unavailable; this is the deterministic line.")
    return {
        "schema": THINKING_SCHEMA,
        "symbol": sym,
        "model": model_label,
        "text": " ".join(parts),
        "protect": ({"level": stop, "source_id": stops[0]["price"]["source_id"],
                     "condition": "keep the working stop"} if stop is not None else None),
        "reentry": None,
    }


# ── delta replay: T0's plan against T1's packet ────────────────────────────────────────────


def _valued_facts(block: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(f.get("path")): f for f in block.get("facts") or [] if f.get("value") is not None}


def diff_packets(prev: Mapping[str, Any], cur: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every fact that appeared or changed between two packets, carrying its current source.

    Only values that are facts in the new packet appear here, so whatever the model repeats from
    this block still traces to a source id.
    """
    out: list[dict[str, Any]] = []
    prev_names = {b.get("symbol"): b for b in prev.get("names") or []}
    for block in cur.get("names") or []:
        sym = block.get("symbol")
        before = prev_names.get(sym)
        if before is None:
            out.append({"symbol": sym, "change": "new_name", "field": "name",
                        "value": (block.get("price") or {}).get("value"), "unit": "price",
                        "source_id": f"holdings:{sym}", "as_of": cur.get("as_of")})
            continue
        old = _valued_facts(before)
        for path, f in _valued_facts(block).items():
            prior = old.get(path)
            if prior is None or number_key(prior.get("value")) != number_key(f.get("value")):
                out.append({"symbol": sym, "change": "changed", "field": path,
                            "from": prior.get("value") if prior else None,
                            "value": f.get("value"), "unit": f.get("unit"),
                            "source_id": f.get("source_id"), "as_of": f.get("as_of")})
    return out


def _plan_fact(plan: Any, *, as_of: Any) -> Optional[dict[str, Any]]:
    """A prior plan's level as a citable fact, so T1 may quote it without inventing it."""
    if not isinstance(plan, Mapping) or plan.get("level") is None:
        return None
    return {
        "value": plan.get("level"), "unit": "price",
        "source_id": str(plan.get("source_id") or "plan:prior"), "as_of": _iso(as_of),
        "condition": plan.get("condition"), "origin": "prior_plan",
    }


def delta_block(
    prev: Mapping[str, Any],
    cur: Mapping[str, Any],
    prior_thinking: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """T0's plan replayed against T1: what moved, and whether T0's protect/re-entry fired.

    The prior plan is read from CIO memory (``prior_thinking``), not rebuilt, so the model sees
    what it actually said last time and must say plainly if it changed its mind. A plan level
    counts as reached only by comparing it with a current price fact.
    """
    changes = diff_packets(prev, cur)
    prior_names = (prior_thinking or {}).get("names") or {}
    plans: dict[str, Any] = {}
    for block in cur.get("names") or []:
        sym = block.get("symbol")
        body = prior_names.get(sym)
        if not isinstance(body, Mapping):
            continue
        price = (block.get("price") or {}).get("value")
        protect = _plan_fact(body.get("protect"), as_of=prev.get("as_of"))
        reentry = _plan_fact(body.get("reentry"), as_of=prev.get("as_of"))
        state, evidence = "open", None
        if protect and price is not None and float(price) <= float(protect["value"]):
            state = "protect_reached"
            evidence = {"price": (block.get("price") or {}), "level": protect}
        elif reentry and price is not None and float(price) >= float(reentry["value"]):
            state = "reentry_reached"
            evidence = {"price": (block.get("price") or {}), "level": reentry}
        plans[sym] = {"prior_protect": protect, "prior_reentry": reentry,
                      "state": state, "evidence": evidence,
                      "say": {
                          "open": "T0's plan still stands; restate it only if the reason changed.",
                          "protect_reached": "The price reached T0's protect level: say what happened and what is next.",
                          "reentry_reached": "The price reached T0's re-entry level: say whether the condition is met.",
                      }[state]}
    return {"from": prev.get("as_of"), "to": cur.get("as_of"),
            "changes": changes, "plans": plans}


# ── CIO memory ─────────────────────────────────────────────────────────────────────────────


def _record_id(record: Mapping[str, Any]) -> str:
    body = json.dumps({k: v for k, v in record.items() if k not in {"record_id"}}, sort_keys=True, default=str)
    return "think:" + hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]


def remember(symbol: str, record: Mapping[str, Any], *, root: Optional[Path] = None,
             path: Optional[Path] = None, subject_guid: Optional[str] = None) -> dict[str, Any]:
    """Persist one dated thinking record to the CIO memory spine. Never raises."""
    sym = str(symbol or "").upper().strip()
    if not sym or not record:
        return {"stored": False, "reason": "symbol_or_record_required"}
    rid = str(record.get("record_id") or _record_id(record))
    body = dict(record, record_id=rid, schema=THINKING_SCHEMA, symbol=sym)
    summary = "CIOThinking@v1 " + json.dumps(body, sort_keys=True, default=str)[:700]
    try:
        from scripts.lib.cross_asset.security_research_spine import upsert_research_memory
    except Exception:  # noqa: BLE001 -- the spine imports under two roots; a missing memory is
        # reported as a reason, never raised into the brief
        try:
            from lib.cross_asset.security_research_spine import (  # type: ignore -- fallback root
                upsert_research_memory,
            )
        except Exception:  # noqa: BLE001 -- both roots missing: report, do not raise
            return {"stored": False, "reason": "spine_module_unavailable"}
    try:
        res = upsert_research_memory(
            sym, silo="cio", kind="cio_thinking", summary=summary, artifact_id=rid,
            refs=list(record.get("source_ids") or [])[:20],
            tags=["cio_thinking", "holdings", "lifecycle"], thesis_patch=None,
            subject_guid=subject_guid, path=path, root=root,
        )
    except Exception as exc:  # noqa: BLE001 -- memory is an addition, never a gate
        return {"stored": False, "reason": f"{type(exc).__name__}:{exc}"[:160]}
    ok = bool(res.get("ok"))
    out = {"stored": ok, "record_id": rid}
    if not ok:
        out["reason"] = str(res.get("error") or "not_stored")[:160]
    return out


def recall(symbol: str, *, root: Optional[Path] = None, path: Optional[Path] = None,
           limit: int = 5) -> dict[str, Any]:
    """The thinking records already filed for the symbol, newest first. Never raises.

    Returns ``{"records", "ok", "error"}``. An unreadable memory is ``ok: False``, not an empty
    list: "the CIO has no prior plan" and "the CIO's memory could not be read" are different
    claims, and only the first may present itself as memory.
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return {"records": [], "ok": False, "error": "symbol_required"}
    try:
        from scripts.lib.cross_asset.security_research_spine import load_latest
    except Exception:  # noqa: BLE001 -- the spine imports under two roots; report the absence
        try:
            from lib.cross_asset.security_research_spine import (  # type: ignore -- fallback root
                load_latest,
            )
        except Exception:  # noqa: BLE001 -- both roots missing: an unknown, not an empty memory
            return {"records": [], "ok": False, "error": "spine_module_unavailable"}
    try:
        spine = load_latest(sym, path=path, root=root)
    except Exception as exc:  # noqa: BLE001 -- a read failure is reported, never shown as "no plan"
        return {"records": [], "ok": False, "error": type(exc).__name__}
    if not spine:
        return {"records": [], "ok": True, "error": None}
    out = []
    for c in spine.get("contributions") or []:
        if str(c.get("kind") or "") != "cio_thinking":
            continue
        text = str(c.get("summary") or "")
        if not text.startswith("CIOThinking@v1 "):
            continue
        try:
            out.append(json.loads(text[len("CIOThinking@v1 "):]))
        except ValueError:
            continue
    return {"records": out[:limit], "ok": True, "error": None}


# ── request and dry run ────────────────────────────────────────────────────────────────────


def system_prompt() -> str:
    return (
        "You are the CIO's reasoning pass. You receive a complete deterministic packet: market "
        "read record ids, holdings with stops, normalized events (WHO/WHAT/size/10b5-1/stake %), "
        "research answers, filings and CIO memory. Reason like an analyst about each material "
        "held name: what happened, why it matters, what could happen both ways, and an IF/THEN "
        "plan — protect (an existing or raised stop that locks gain) and re-entry if stopped out "
        "(a level and a condition, e.g. after the sale window or after CPI). Every number you "
        "write must be copied from the packet and cited by its source_id; never compute, round "
        "or invent one. Advisory only: no order, no size, no stop instruction. Return JSON only, "
        "schema CIOThinking@v1: {\"names\": {SYMBOL: {\"what_happened\", \"why_it_matters\", "
        "\"both_ways\", \"protect\": {\"level\", \"source_id\", \"condition\"}, "
        "\"reentry\": {\"level\", \"source_id\", \"condition\"}, \"watch\": [...]}}}."
    )


def build_request(packet: Mapping[str, Any], *, model: str = MODEL, effort: str = EFFORT,
                  max_tokens: int = MAX_TOKENS) -> dict[str, Any]:
    """The exact Messages request that would be sent. No truncation: the packet is the body."""
    body = json.dumps(packet, default=str, sort_keys=False)
    return {
        "model": model,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
        "system": [{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": body}]}],
    }


def request_digest(request: Mapping[str, Any]) -> dict[str, Any]:
    body = json.dumps(request, sort_keys=True, default=str)
    return {
        "chars": len(body),
        "est_tokens": estimate_tokens(body),
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "model": request.get("model"),
        "effort": (request.get("output_config") or {}).get("effort"),
        "max_tokens": request.get("max_tokens"),
    }


def _load_items_from_doc(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    stamps = doc.get("source_timestamps") or {}
    items = []
    for h in doc.get("holdings") or []:
        items.append(dict(h, quote_time=stamps.get("quotes"),
                          holdings_as_of=stamps.get("positions") or doc.get("as_of")))
    return items


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CIO reasoning packet + validator (dry run only)")
    ap.add_argument("--doc", default=None,
                    help="a brief latest.json to build the packet from (default: the state root's brief)")
    ap.add_argument("--state-root", default=None)
    ap.add_argument("--dry-run", action="store_true", help="print the packet stats and the exact request; no call")
    ap.add_argument("--show-body", action="store_true", help="also print the exact request body")
    ap.add_argument("--max-chars", type=int, default=MAX_PACKET_CHARS)
    args = ap.parse_args(argv)

    # The state root is the brief's own convention: an explicit argument, then the environment,
    # then the persistent-state the operator runs from (never a path written into this file).
    state_root = Path(args.state_root or os.environ.get("TRADEAI_STATE_ROOT")
                      or (Path.home() / "trade-ai-releases" / "persistent-state"))
    path = Path(args.doc) if args.doc else state_root / "data" / "runtime" / "cio_overnight_brief" / "latest.json"
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    items = _load_items_from_doc(doc)
    # The regime/outlook/verdict records are read from their own latest files when present; the
    # packet keeps their record ids so every medium prints the same record.
    root = Path(args.state_root) if args.state_root else (Path(path).parents[3] if args.doc else state_root)
    packet = build_packet(
        items,
        as_of=doc.get("as_of"),
        run_id=doc.get("run_id"),
        regime=_read_record(root, "cio_regime"),
        outlook=_read_record(root, "market_outlook"),
        cio_verdict=_read_record(root, "cio_verdict"),
        calendar=doc.get("week_ahead"),
        risk_tier=doc.get("risk_tier"),
        report={"synopsis": doc.get("synopsis"), "gaps": doc.get("gaps")},
        max_chars=args.max_chars,
    )
    request = build_request(packet)
    out = {
        "dry_run": True,
        "doc": str(path),
        "packet": packet["stats"],
        "names": [{"symbol": b["symbol"], "facts": len(b["facts"]), "events": len(b["events"]),
                   "materiality": b["materiality"]} for b in packet["names"]],
        "dropped": packet["dropped"],
        "stale_inputs": [{"source_id": f.get("source_id"), "detail": f.get("stale_detail")}
                         for f in packet["facts"] if f.get("stale")],
        "not_measured": [{"symbol": b["symbol"], "line": b["not_measured"]}
                         for b in packet["names"] if not b.get("measurable", True)],
        "request": request_digest(request),
        "would_send": False,
    }
    print(json.dumps(out, indent=1, default=str))
    if args.show_body:
        print(json.dumps(request, indent=1, default=str))
    return 0


def _read_record(root: Path, name: str) -> Optional[dict[str, Any]]:
    for rel in (f"data/runtime/{name}/latest.json", f"data/runtime/{name}_latest.json"):
        p = root / rel
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- an unreadable record is absent, not a crash
            continue
    return None


if __name__ == "__main__":
    raise SystemExit(main())
