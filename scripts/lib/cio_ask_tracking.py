"""Ask the CIO — Phase 10 auto-tracking. READ_ONLY_ADVISORY.

On answer, each entity the question named is tracked through the EXISTING write paths:

1. **My Watchlist** (operator-owned): ``data/portfolios/state/watchlist.json`` — the same file and entry shape that
   ``POST /api/watchlist/write`` (portfolio_server) writes; the thesis is the question. An entry the operator already
   had is never overwritten: the ask is appended to ``ask_threads`` and the operator's thesis stays.
2. **CIO record** (``InstrumentRecordStore``, the one writer of the prospect's record, §26.1): created when absent;
   cognition moves ``next_research_question`` to the question and records the operator turn. Stage, conviction and
   stance stay with the CIO prospect builder — an ask never invents a conviction.
3. **Catalyst watch directive** (``lib.writers.watch_directives_writer.write_watch_directives``, the directive
   table's writer): a ticker directive with the question's keywords for a security, a trend directive keyed on the
   name for a private entity. Operator-created (the operator asked), ``ttl_days`` from config; the writer's
   ``reuse`` rule folds it into an existing directive for the same subject.

Untrack reverses only what the ask added: removes a watchlist entry the ask created (no other tracked thread still
holding it), archives a directive the ask created, and records the change. Nothing is deleted (§0 rule 6).

A private entity never gets a ticker: no watchlist row (the watchlist is symbol-keyed), a trend directive on its name.
No step sizes, orders, stops or weights (MBI_BEHAVIOR=0).
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

from scripts.lib.cio_ask_contract import EntityRef

_STOPWORDS = frozenset(
    "a an and are as at be buy by can could do does for from given has have how i if in into invest is it its me my "
    "of on or over should sell than that the their this to vs was what when where which why will with would you your "
    "about after before now any more less get worth".split()
)


def question_keywords(question: str, entity: EntityRef, *, limit: int = 8) -> list[str]:
    """Keywords for the catalyst watch: the entity's names plus the question's content words."""
    out: list[str] = []
    for w in (entity.symbol, entity.name):
        if w and w not in out:
            out.append(w)
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9&'.-]{2,}", question or ""):
        t = tok.strip(".'").lower()
        if t in _STOPWORDS or t in (x.lower() for x in out):
            continue
        out.append(tok.strip(".'"))
        if len(out) >= limit:
            break
    return out[:limit]


# ── backends (injectable) ──────────────────────────────────────────────────────────────────────────────────────────


class WatchlistFile:
    """The operator watchlist file, exactly as /api/watchlist/write writes it."""

    def __init__(self, path: Optional[Path] = None):
        root = Path(os.environ.get("TRADEAI_ROOT") or Path(__file__).resolve().parents[2])
        self.path = Path(path) if path else root / "data" / "portfolios" / "state" / "watchlist.json"

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except (OSError, json.JSONDecodeError):
            raise RuntimeError(f"watchlist unreadable: {self.path}") from None

    def _save(self, wl: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(wl, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, symbol: str, *, thesis: str, thread_id: str) -> dict[str, Any]:
        wl = self._load()
        sym = symbol.upper()
        cur = wl.get(sym)
        if isinstance(cur, dict):
            threads = list(cur.get("ask_threads") or [])
            if thread_id not in threads:
                threads.append(thread_id)
                cur["ask_threads"] = threads
                wl[sym] = cur
                self._save(wl)
            return {"symbol": sym, "action": "tagged_existing", "created_by_ask": bool(cur.get("added_by_ask"))}
        wl[sym] = {
            "thesis": thesis[:500],
            "target_intent": "ask_the_cio",
            "added": date.today().isoformat(),
            "notes": f"Tracked from Ask the CIO ({thread_id})",
            "watching_since": "",
            "added_by_ask": thread_id,
            "ask_threads": [thread_id],
        }
        self._save(wl)
        return {"symbol": sym, "action": "added", "created_by_ask": True}

    def release(self, symbol: str, *, thread_id: str) -> dict[str, Any]:
        wl = self._load()
        sym = symbol.upper()
        cur = wl.get(sym)
        if not isinstance(cur, dict):
            return {"symbol": sym, "action": "absent"}
        threads = [t for t in (cur.get("ask_threads") or []) if t != thread_id]
        if cur.get("added_by_ask") and not threads:
            wl.pop(sym, None)
            self._save(wl)
            return {"symbol": sym, "action": "removed"}
        cur["ask_threads"] = threads
        wl[sym] = cur
        self._save(wl)
        return {"symbol": sym, "action": "untagged", "kept": "operator entry or another tracked question holds it"}


class CioRecordBackend:
    """The CIO InstrumentRecord: next_research_question + operator turn. Never stage/conviction/size."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path

    def note_question(self, entity: EntityRef, *, question: str, ask_id: str, thread_id: str, channel: str) -> dict:
        from scripts.lib.cio_instrument_record import (  # noqa: PLC0415
            DEFAULT_PATH,
            CognitionNoOp,
            InstrumentRecordStore,
            apply_cognition,
            new_record,
            subject_key,
        )

        root = Path(os.environ.get("TRADEAI_ROOT") or Path(__file__).resolve().parents[2])
        store = InstrumentRecordStore(self.path or (root / DEFAULT_PATH))
        key = subject_key("SECURITY", entity.symbol or entity.name)
        rec = store.load(key)
        created = rec is None
        if created:
            rec = new_record("SECURITY", entity.symbol or entity.name)
            rec["symbols"] = [entity.symbol] if entity.symbol else []
            rec["security_guid"] = entity.security_guid
            rec["issuer_guid"] = entity.issuer_guid
        try:
            rec, changed = apply_cognition(
                rec,
                next_research_question=f"Operator asked: {question[:300]}",
                operator_turn={"ask_id": ask_id, "thread_id": thread_id, "channel": channel, "text": question[:300]},
                artifact_id=ask_id,
            )
        except CognitionNoOp:
            return {"subject_key": key, "action": "unchanged"}
        store.upsert(rec)
        return {"subject_key": key, "action": "created" if created else "updated", "changed": changed}


def _default_db_target() -> Callable[..., Any]:
    """The same DB callable api_v2 uses for directive writes (db_adapter._execute)."""

    def _q(sql, params=None, fetch="all"):
        import sys  # noqa: PLC0415

        root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(root / "scripts"))
        from db_adapter import USE_DB, _execute  # noqa: PLC0415

        if not USE_DB:
            raise RuntimeError("database disabled (USE_DB false)")
        return _execute(sql, params, fetch=fetch)

    return _q


class DirectiveBackend:
    def __init__(self, target: Optional[Callable[..., Any]] = None, *, ttl_days: int = 90):
        self.target = target
        self.ttl_days = ttl_days

    def create(self, entity: EntityRef, *, keywords: list[str], question: str, thread_id: str) -> dict:
        from scripts.lib.writers.watch_directives_writer import write_watch_directives  # noqa: PLC0415

        tgt = self.target or _default_db_target()
        if entity.kind == "security" and entity.symbol:
            row = {
                "kind": "ticker",
                "label": f"Ask the CIO: {entity.symbol}",
                "spec": {"symbol": entity.symbol, "keywords": keywords, "ask_thread_id": thread_id},
            }
        else:
            row = {
                "kind": "trend",
                "label": f"Ask the CIO: {entity.name}",
                "spec": {
                    "keywords": keywords,
                    "seed_symbols": [],
                    "ask_thread_id": thread_id,
                    "entity_guid": entity.entity_guid,
                },
            }
        row.update(
            {
                "rationale": f"Operator question ({thread_id}): {question[:240]}",
                "created_by": "operator",
                "ttl_days": self.ttl_days,
                "priority": "normal",
                "trade_ai_enabled": entity.kind == "security",
                "hermes_enabled": False,
            }
        )
        rc = write_watch_directives(tgt, [row], source="ask_the_cio", on_duplicate="reuse")
        if rc.rows_rejected:
            return {"action": "rejected", "reason": "; ".join(str(r.get("reason")) for r in rc.rows_rejected)}
        return {
            "action": "created" if rc.ids else "reused",
            "directive_id": rc.directive_id,
            "created_by_ask": bool(rc.ids),
        }

    def archive(self, directive_id: Any) -> dict:
        from scripts.lib.writers.watch_directives_writer import set_watch_directive_status  # noqa: PLC0415

        rc = set_watch_directive_status(
            self.target or _default_db_target(), directive_id, "archived", source="ask_the_cio"
        )
        return {"action": "archived" if not rc.rows_rejected else "rejected", "directive_id": directive_id}


class Tracker:
    """Runs the three tracking steps; each step degrades on its own and says so in the receipt."""

    def __init__(self, *, watchlist=None, record=None, directives=None, enabled_steps: Optional[dict] = None):
        self.watchlist = watchlist or WatchlistFile()
        self.record = record or CioRecordBackend()
        self.directives = directives or DirectiveBackend()
        self.steps = {"watchlist": True, "cio_record": True, "directive": True, **(enabled_steps or {})}

    def track(self, entity: EntityRef, *, question: str, ask_id: str, thread_id: str, channel: str) -> dict:
        actions: dict[str, Any] = {}
        if self.steps["watchlist"]:
            if entity.kind == "security" and entity.symbol:
                actions["watchlist"] = _safe(
                    lambda: self.watchlist.add(entity.symbol, thesis=question, thread_id=thread_id)
                )
            else:
                actions["watchlist"] = {"action": "skipped", "reason": "no listed security (never invent a ticker)"}
        if self.steps["cio_record"]:
            if entity.kind == "security" and entity.security_guid:
                actions["cio_record"] = _safe(
                    lambda: self.record.note_question(
                        entity, question=question, ask_id=ask_id, thread_id=thread_id, channel=channel
                    )
                )
            else:
                actions["cio_record"] = {"action": "skipped", "reason": "no CONFIRMED security_guid (§26.1)"}
        if self.steps["directive"]:
            kw = question_keywords(question, entity)
            actions["directive"] = _safe(
                lambda: self.directives.create(entity, keywords=kw, question=question, thread_id=thread_id)
            )
        return actions

    def untrack(self, entity: dict, *, thread_id: str, prior_actions: dict) -> dict:
        actions: dict[str, Any] = {}
        sym = entity.get("symbol")
        if sym and entity.get("kind") == "security":
            actions["watchlist"] = _safe(lambda: self.watchlist.release(sym, thread_id=thread_id))
        d = (prior_actions or {}).get("directive") or {}
        if d.get("created_by_ask") and d.get("directive_id") is not None:
            actions["directive"] = _safe(lambda: self.directives.archive(d["directive_id"]))
        else:
            actions["directive"] = {"action": "kept", "reason": "directive existed before the ask (reused)"}
        actions["cio_record"] = {"action": "kept", "reason": "the record is history; untrack never rewrites it"}
        return actions


def _safe(fn: Callable[[], dict]) -> dict:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — one failed step never costs the operator the answer
        return {"action": "failed", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


__all__ = ["Tracker", "WatchlistFile", "CioRecordBackend", "DirectiveBackend", "question_keywords"]
