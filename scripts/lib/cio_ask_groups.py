"""Ask the CIO — "My questions" grouping (Screen 5 of the approved TradeInView/My-questions SPEC). READ_ONLY_ADVISORY.

    GET  /api/v2/cio/asks?group_by=security|sector|theme|date|none&q=&channel=cc|telegram
    POST /api/v2/cio/asks/<thread_id>/regroup   {ask_id, group_by, group_key | null}

Every grouped value is read, never guessed:

* security — the registry ``security_guid`` the ask resolved to (``ask.entity_resolved``); the label is the ticker the
  resolution carried, the sub-line the GUID-bound CIO company facts (C1: company / sector / industry). A private
  entity groups by its ``entity_guid``; a question with no resolved entity is "No security resolved".
* sector — C1 ``company_facts.sector.value`` for that GUID; absent → "Unclassified" (never inferred from a name).
* theme — the thesis catalog ``config/thesis.json`` (each thesis' ``tickers``); a name in none → "No theme". When the
  catalog has no thesis the Theme grouping is reported unavailable with its reason (the UI then omits the button).
* date — the ET calendar day the question was asked (``asked_at``).
* none — one group, newest first.

A question can sit in several groups (it names two securities). A manual regroup is an ``ask.group_override`` event
appended to the ask ledger — history is never edited; the newest override per (ask_id, group_by) wins, and
``group_key: null`` means "ungrouped" for that grouping.

CIO memory per group: the newest answer time on the ledger for that group's questions (the ``ask_the_cio`` memory of
record) plus, for a security group, the CIO prospect record's stance and conviction when that store is live (an
explicit gap otherwise). Pure functions; the API layer injects the readers.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo

GROUP_BYS = ("security", "sector", "theme", "date", "none")
CHANNELS = ("cc", "telegram", "whatsapp", "event")
ET = ZoneInfo("America/New_York")
THESIS_CATALOG = Path(__file__).resolve().parents[2] / "config" / "thesis.json"
NO_SECURITY = "No security resolved"
UNCLASSIFIED = "Unclassified"
NO_THEME = "No theme"


def load_themes(path: Optional[Path] = None) -> dict[str, Any]:
    """{available, reason, source, by_symbol: {SYM: [{key, label}]}} from the thesis catalog. Never invents a theme."""
    p = Path(path) if path else THESIS_CATALOG
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"available": False, "reason": f"thesis catalog unreadable ({type(exc).__name__})", "source": str(p),
                "by_symbol": {}}
    by_symbol: dict[str, list[dict[str, str]]] = {}
    for key, row in (doc.items() if isinstance(doc, dict) else []):
        if not isinstance(row, dict) or not isinstance(row.get("tickers"), list):
            continue
        label = str(row.get("description") or key)
        for sym in row["tickers"]:
            if isinstance(sym, str) and sym.strip():
                by_symbol.setdefault(sym.strip().upper(), []).append({"key": key, "label": label})
    if not by_symbol:
        return {"available": False, "reason": "thesis catalog holds no thesis with tickers", "source": str(p),
                "by_symbol": {}}
    return {"available": True, "reason": None, "source": "config/thesis.json", "by_symbol": by_symbol}


def _et_day(at: Any) -> Optional[str]:
    try:
        dt = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return None  # a naive time is not a time; never assume a zone
    return dt.astimezone(ET).date().isoformat()


def _fact(facts: dict[str, Any], name: str) -> Optional[str]:
    v = ((facts or {}).get(name) or {}).get("value")
    return v.strip() if isinstance(v, str) and v.strip() else None


def overrides_from(events: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Newest ``ask.group_override`` per (ask_id, group_by). Ledger order is append order."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for e in events:
        if e.get("kind") != "ask.group_override":
            continue
        k = (str(e.get("ask_id") or ""), str(e.get("group_by") or ""))
        prev = out.get(k)
        if prev is None or str(e.get("at") or "") >= str(prev.get("at") or ""):
            out[k] = e
    return out


def _question_rows(threads: dict[str, dict[str, Any]], *, q: str, channel: Optional[str]) -> list[dict[str, Any]]:
    needle = (q or "").strip().lower()
    rows = []
    for t in threads.values():
        ents = [e for e in (t.get("entities") or []) if isinstance(e, dict)]
        for turn in t.get("turns") or []:
            if turn.get("turn_kind") == "reanswer":
                continue  # a re-answer is the CIO's turn, not a question the operator asked
            if channel and turn.get("channel") != channel:
                continue
            answers = turn.get("answers") or []
            last = answers[-1] if answers else {}
            row = {"ask_id": turn.get("ask_id"), "thread_id": t.get("thread_id"), "question": turn.get("question"),
                   "channel": turn.get("channel"), "asked_at": turn.get("asked_at"), "turn_kind": turn.get("turn_kind"),
                   "depth": last.get("depth"), "status": last.get("status"), "answered_at": last.get("produced_at"),
                   "entities": ents}
            if needle:
                hay = " ".join([str(row["question"] or "")] + [
                    " ".join(str(e.get(k) or "") for k in ("symbol", "name")) for e in ents]).lower()
                if needle not in hay:
                    continue
            rows.append(row)
    rows.sort(key=lambda r: str(r.get("asked_at") or ""), reverse=True)
    return rows


def _keys_for(row: dict[str, Any], group_by: str, *, facts_for: Callable[[dict], dict], themes: dict[str, Any]):
    """[(key, label, sub, symbol|None, guid|None)] for one question under one grouping."""
    ents = row["entities"]
    if group_by == "none":
        return [("all", "All questions", None, None, None)]
    if group_by == "date":
        day = _et_day(row.get("asked_at"))
        return [(day or "undated", day or "Date not recorded", "ET day asked", None, None)]
    resolved = [e for e in ents if e.get("security_guid") or e.get("entity_guid")]
    if not resolved:
        return [("unresolved", NO_SECURITY, "the question named no resolved security", None, None)]
    out = []
    for e in resolved:
        guid = e.get("security_guid")
        sym = (e.get("symbol") or "").upper() or None
        if group_by == "security":
            if not guid:
                out.append((f"entity:{e['entity_guid']}", e.get("name") or "Private entity", "private entity · no listed security",
                            None, None))
                continue
            f = facts_for(e) or {}
            sub = " · ".join(x for x in (_fact(f, "company"), _fact(f, "sector"), _fact(f, "industry")) if x) or None
            out.append((f"security:{guid}", sym or e.get("name") or guid, sub, sym, guid))
        elif group_by == "sector":
            sector = _fact(facts_for(e) or {}, "sector") if guid else None
            out.append((f"sector:{sector}" if sector else "sector:unclassified", sector or UNCLASSIFIED,
                        None if sector else "no sector on the CIO record (C1)", sym, guid))
        elif group_by == "theme":
            tagged = (themes.get("by_symbol") or {}).get(sym or "", []) if guid else []
            if not tagged:
                out.append(("theme:none", NO_THEME, "not in any thesis in config/thesis.json", sym, guid))
            for th in tagged:
                out.append((f"theme:{th['key']}", th["label"], "thesis catalog", sym, guid))
    # one question once per group even when two entities land in the same group
    seen, uniq = set(), []
    for k in out:
        if k[0] not in seen:
            seen.add(k[0]); uniq.append(k)
    return uniq


def group_questions(threads: dict[str, dict[str, Any]], *, group_by: str = "security", q: str = "",
                    channel: Optional[str] = None, events: Iterable[dict[str, Any]] = (),
                    facts_for: Callable[[dict], dict] = lambda e: {},
                    stance_for: Callable[[list[str]], dict[str, dict[str, Any]]] = lambda syms: {},
                    themes: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """The grouped "My questions" projection. Raises ValueError on an unknown group_by/channel."""
    if group_by not in GROUP_BYS:
        raise ValueError(f"group_by must be one of {GROUP_BYS}")
    if channel is not None and channel not in CHANNELS:
        raise ValueError(f"channel must be one of {CHANNELS}")
    themes = themes if themes is not None else load_themes()
    rows = _question_rows(threads, q=q, channel=channel)
    overrides = overrides_from(events)
    groups: dict[str, dict[str, Any]] = {}
    labels: dict[str, tuple] = {}
    for row in rows:
        keys = _keys_for(row, group_by, facts_for=facts_for, themes=themes)
        ov = overrides.get((str(row["ask_id"]), group_by))
        if ov is not None:
            target = ov.get("group_key")
            if target is None:
                keys = [("ungrouped", "Ungrouped", "you removed these from their group", None, None)]
            else:
                known = labels.get(target) or next((k for k in keys if k[0] == target), None)
                keys = [known or (target, ov.get("group_label") or target, "moved here by you", None, None)]
            row = {**row, "override": {"group_key": target, "at": ov.get("at")}}
        for key, label, sub, sym, guid in keys:
            labels.setdefault(key, (key, label, sub, sym, guid))
            g = groups.setdefault(key, {"key": key, "label": label, "sub": sub, "symbol": sym, "security_guid": guid,
                                        "questions": [], "thread_ids": [], "symbols": []})
            g["questions"].append({k: row[k] for k in ("ask_id", "thread_id", "question", "channel", "asked_at",
                                                       "turn_kind", "depth", "status", "answered_at")}
                                  | ({"override": row["override"]} if "override" in row else {}))
            if row["thread_id"] not in g["thread_ids"]:
                g["thread_ids"].append(row["thread_id"])
            for e in row["entities"]:
                s = (e.get("symbol") or "").upper()
                if s and s not in g["symbols"] and (group_by != "security" or e.get("security_guid") == guid):
                    g["symbols"].append(s)
    security_syms = sorted({g["symbol"] for g in groups.values() if g.get("symbol") and group_by == "security"})
    stances = stance_for(security_syms) if security_syms else {}
    out = []
    for g in groups.values():
        answered = [x["answered_at"] for x in g["questions"] if x.get("answered_at")]
        st = stances.get(g["symbol"] or "") if g.get("symbol") else None
        g["counts"] = {"questions": len(g["questions"]), "threads": len(g["thread_ids"]), "names": len(g["symbols"])}
        g["memory"] = {
            "last_answer_at": max(answered) if answered else None,
            "last_answer_source": "cio_ask_events answer_version" if answered else None,
            "last_answer_missing_reason": None if answered else "no answer recorded yet",
            "stance": (st or {}).get("stance"), "conviction": (st or {}).get("conviction"),
            "stance_as_of": (st or {}).get("as_of"), "stance_source": (st or {}).get("source"),
            "stance_missing_reason": None if st and st.get("stance") else
            ((st or {}).get("missing_reason") or ("CIO stance applies to a security group only"
                                                  if group_by != "security" or not g.get("symbol")
                                                  else "no CIO prospect record for this security")),
        }
        lifecycles = [(threads.get(tid) or {}).get("lifecycle") for tid in g["thread_ids"]]
        lifecycles = [x for x in lifecycles if isinstance(x, dict)]
        # Both security groups of one question reuse its canonical lifecycle; grouping never starts work.
        if lifecycles:
            rank = {"failed": 8, "blocked": 7, "overdue": 6, "partial": 5, "checking": 4, "deferred": 3, "not_checked": 2, "current": 1}
            g["lifecycle"] = max(lifecycles, key=lambda x: rank.get(x.get("state"), 9))
        g["newest_at"] = max((str(x.get("asked_at") or "") for x in g["questions"]), default="")
        out.append(g)
    if group_by == "date":
        out.sort(key=lambda g: g["key"], reverse=True)
    else:
        # most recently asked first; the catch-all groups (unresolved / unclassified / no theme / ungrouped) last
        out.sort(key=lambda g: g["newest_at"], reverse=True)
        out.sort(key=lambda g: g["key"] in ("unresolved", "sector:unclassified", "theme:none", "ungrouped"))
    group_bys = [{"id": gb, "available": gb != "theme" or bool(themes.get("available")),
                  "reason": themes.get("reason") if gb == "theme" and not themes.get("available") else None}
                 for gb in GROUP_BYS]
    return {"group_by": group_by, "q": q or "", "channel": channel, "groups": out,
            "counts": {"groups": len(out), "questions": len(rows),
                       "threads": len({r["thread_id"] for r in rows})},
            "group_bys": group_bys, "theme_source": themes.get("source")}


def related_from_memory(thread: dict[str, Any], threads: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Per ask_id of ``thread``: the earlier asks its newest answer actually recalled (answer ``recall`` refs).

    Never a fresh similarity search: only refs persisted on the answer version are resolved, to the ask they name
    (``ask_x`` or ``ask_x:vN``). A ref that resolves to nothing on the ledger is returned with ``missing_reason``."""
    by_ask: dict[str, tuple[dict, dict]] = {}
    for t in threads.values():
        for turn in t.get("turns") or []:
            if turn.get("ask_id"):
                by_ask[str(turn["ask_id"])] = (t, turn)
    out: dict[str, list[dict[str, Any]]] = {}
    for turn in thread.get("turns") or []:
        answers = turn.get("answers") or []
        if not answers:
            continue
        rows, seen = [], set()
        for block in answers[-1].get("recall") or []:
            for item in (block or {}).get("items") or []:
                ref = str(item.get("ref") or "")
                ask_id = ref.split(":", 1)[0]
                if not ask_id.startswith("ask_") or ask_id in seen or ask_id == turn.get("ask_id"):
                    continue
                seen.add(ask_id)
                hit = by_ask.get(ask_id)
                if hit is None:
                    rows.append({"ask_id": ask_id, "ref": ref, "memory_key": block.get("key"), "thread_id": None,
                                 "question": None, "asked_at": item.get("at"), "source": item.get("source"),
                                 "missing_reason": "recalled ask is not on the ask ledger"})
                    continue
                t, other = hit
                rows.append({"ask_id": ask_id, "ref": ref, "memory_key": block.get("key"), "thread_id": t.get("thread_id"),
                             "question": other.get("question"), "asked_at": other.get("asked_at"),
                             "channel": other.get("channel"), "source": item.get("source"), "missing_reason": None})
        out[str(turn.get("ask_id"))] = rows
    return out


__all__ = ["GROUP_BYS", "CHANNELS", "group_questions", "related_from_memory", "overrides_from", "load_themes"]
