"""``PositionVerdict@v1`` — the CIO's per-(symbol, account) verdict and its durable history.

Operator's rule (SPEC_ONE_POSITION_VERDICT_20261104 §1b): the CIO is the single decision owner, the verdict is
saved in persistent memory, and "if I have SpaceX in different accounts, each account should be isolated and
counted separately". This module is the only place a verdict is created or read.

It does not decide anything. It stores what ``cio_truth`` decided, with the evidence behind it, so that every
surface can RENDER the same record — Home, Risk, Re-entry, Watch, do-now and Telegram — instead of computing five
different answers, and so that a restart, a release or a new session cannot lose the history.

Totals are deliberately absent: weight of book, concentration and sector exposure are read-time aggregates over
per-account verdicts, never a stored verdict (an ``ALL_ACCOUNTS`` account is refused for that reason).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

SCHEMA = "PositionVerdict@v1"

#: The one producer. A surface that computes its own verdict may not write here — that is the rule, not a default.
CIO_PRODUCER = "cio_truth"

#: Accounts that mean "all of them". A verdict is per account; an aggregate is a read-time computation.
_AGGREGATE_ACCOUNTS = frozenset({"", "*", "all", "ALL", "ALL_ACCOUNTS", "all_accounts", "aggregate", "total"})

REQUIRED_FIELDS = ("symbol", "account", "action", "state", "stage", "confidence", "trigger", "narrative",
                   "as_of", "evidence", "tax_constraint", "alternatives")

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "persistent-state" / "data" / "cio" / "position_verdicts.jsonl"


class NotCIOProducer(RuntimeError):
    """A surface tried to write the verdict. Only ``cio_truth`` may produce one (SPEC §1b rule 1)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(payload: Mapping[str, Any]) -> str:
    material = json.dumps({k: payload.get(k) for k in REQUIRED_FIELDS}, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class VerdictStore:
    """Append-only durable memory for position verdicts, keyed by (symbol, account).

    ``path`` is the durable memory file; the default is the CIO's own memory directory. Every write is one JSON
    object per line and is fsynced, so a crash loses at most the record being written — never the history before it.
    """

    def __init__(self, path: str | Path | None = None, *, producer: str) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.producer = str(producer)

    # ── reads ─────────────────────────────────────────────────────────────────────────────────────────────────
    def _rows(self) -> list[dict[str, Any]]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows

    def history(self, symbol: str, account: str) -> list[dict[str, Any]]:
        """Every verdict for this (symbol, account), oldest first. Another account's record is not here."""
        rows = [r for r in self._rows() if str(r.get("symbol")) == str(symbol)
                and str(r.get("account")) == str(account)]
        return sorted(rows, key=lambda r: (int(r.get("sequence") or 0), str(r.get("known_at") or "")))

    def current(self, symbol: str, account: str) -> Optional[dict[str, Any]]:
        history = self.history(symbol, account)
        return history[-1] if history else None

    # ── the single write path ─────────────────────────────────────────────────────────────────────────────────
    def record(self, payload: Mapping[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
        """Persist one verdict, chained to the previous one for the same (symbol, account)."""
        if self.producer != CIO_PRODUCER:
            raise NotCIOProducer(f"only {CIO_PRODUCER!r} may produce a position verdict; {self.producer!r} may "
                                 "render it, never write it")
        missing = [field for field in REQUIRED_FIELDS if not payload.get(field)]
        if missing:
            raise ValueError(f"a position verdict needs {', '.join(missing)}")
        account = str(payload["account"])
        if account in _AGGREGATE_ACCOUNTS:
            raise ValueError(f"account {account!r} is an aggregate: a verdict is per (symbol, account), and a "
                             "total is computed at read time, never stored")
        symbol = str(payload["symbol"])
        history = self.history(symbol, account)
        previous = history[-1] if history else None
        record: dict[str, Any] = {
            "schema": SCHEMA,
            **{field: payload[field] for field in REQUIRED_FIELDS},
            "symbol": symbol,
            "account": account,
            "sequence": int(previous["sequence"]) + 1 if previous else 1,
            "previous_verdict_id": previous.get("verdict_id") if previous else None,
            "known_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        }
        record["verdict_id"] = f"pv1-{_digest(record)[:24]}"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record


def build_verdict(*, symbol, account, action, state, stage, confidence, trigger, narrative, as_of, evidence,
                  tax_constraint, alternatives) -> dict[str, Any]:
    """Assemble the payload the CIO records. Pure: no IO, so the producer cannot write a verdict it cannot justify.

    The CIO supplies the decision; this only refuses to hand back a payload that is missing what §1b requires —
    evidence, the per-account tax constraint, and the alternatives that were rejected. Every surface still RENDERS
    the record; none of them may call this.
    """
    payload = {
        "symbol": str(symbol), "account": str(account), "action": action, "state": state, "stage": stage,
        "confidence": confidence, "trigger": trigger, "narrative": narrative, "as_of": str(as_of),
        "evidence": list(evidence or []), "tax_constraint": dict(tax_constraint or {}),
        "alternatives": list(alternatives or []),
    }
    missing = [field for field in REQUIRED_FIELDS if not payload.get(field)]
    if missing:
        raise ValueError(f"a position verdict needs {', '.join(missing)}")
    return payload


UNAVAILABLE = "CIO verdict unavailable"


def render_for_surface(store: "VerdictStore", symbol: str, account: str) -> dict[str, Any]:
    """What a surface shows for this (symbol, account): the CIO's record, or the explicit absence of one.

    §1b rule 1: a surface that cannot get the CIO record says so. It never falls back to computing a verdict of
    its own, which is how five surfaces came to disagree about the same position.
    """
    record = store.current(symbol, account)
    if record is not None:
        return {"available": True, "verdict": record}
    return {"available": False, "reason": UNAVAILABLE, "symbol": symbol, "account": account}
