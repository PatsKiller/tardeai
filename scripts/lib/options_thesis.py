"""Options thesis record: the same research bar an equity purchase already clears.

2026-09-26 (operator): options cards showed "no thesis pin" and "Catalyst
missing". The thesis existed -- the symbol thesis store had current pins for the
names on the cards -- but nothing in the options pipeline read it, and the
approval queue refused only on enterprise blocks. An option idea could reach the
operator with no thesis, no research link and no audit trail.

This module builds one record per option idea, keyed by the stable strategy GUID
(``option_strategy_guid``; the date-scoped proposal id changes every day), and
stores every version in an append-only, hash-chained JSONL log. A record that is
missing a required field produces named blocks the approval queue turns into a
refusal.

Advisory only (MBI_BEHAVIOR=0). ``position_sizing_rationale`` is operator-entered
and never computed here; this module sizes, orders and weights nothing.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "OptionsThesisRecord@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
GENESIS = "0" * 64
INCOMPLETE_STATES = frozenset({"RESEARCH_REQUIRED", "INSUFFICIENT_DATA", "STALE"})
BROKEN_STATES = frozenset({"BROKEN", "INVALIDATED", "CONFLICTED"})

# Required before an idea may be queued as approvable. Sizing is operator-entered
# at approval; the CIO approval record is written by resolve_approval.
REQUIRED_FIELDS = (
    "position_guid",
    "strategy_type",
    "investment_thesis",
    "supporting_research",
    "catalysts",
    "risk_factors",
    "entry_criteria",
    "exit_criteria",
    "portfolio_impact",
    "agent_decision_trace",
    "confidence_score",
)
OPERATOR_FIELDS = ("position_sizing_rationale", "cio_approval_record")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_path() -> Path:
    root = Path(os.environ.get("TRADEAI_RUNTIME_ROOT") or Path(__file__).resolve().parents[2])
    return root / "data" / "cio" / "options_theses.jsonl"


def _nonempty(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, (list, tuple, dict, str)):
        return bool(v)
    return True


def build_record(proposal: dict[str, Any], thesis: dict[str, Any]) -> dict[str, Any]:
    """One options thesis record from the proposal and the symbol thesis projection."""
    p = proposal or {}
    t = thesis or {}
    rc = p.get("research_context") or {}
    ent = p.get("enterprise") or {}
    catalyst = p.get("catalyst") or rc.get("catalyst")
    pin = t.get("symbol_thesis_version")
    state = str(t.get("thesis_state") or "INSUFFICIENT_DATA").upper()
    summary = (t.get("thesis_summary") or "").strip()
    risk = [str(x) for x in (t.get("counter_evidence") or []) if x]
    risk += [str(i) for i in (ent.get("issues") or ent.get("warnings") or []) if i]
    if p.get("max_loss") is not None:
        risk.append(f"Max loss per contract ${p.get('max_loss'):,}" if isinstance(p.get("max_loss"), (int, float))
                    else f"Max loss {p.get('max_loss')}")
    exits = [str(x) for x in (t.get("invalidation_conditions") or []) if x]
    if rc.get("invalidated_if"):
        exits.append(str(rc["invalidated_if"]))
    if p.get("expiration"):
        exits.append(f"Expiry {p.get('expiration')}; revisit before assignment or roll.")
    research = {
        "symbol_thesis_pin": pin,
        "research_artifact_id": rc.get("research_artifact_id"),
        "research_as_of": rc.get("research_as_of"),
        "source_lanes": rc.get("source_lanes") or [],
        "evidence_for": t.get("evidence_for") or [],
    }
    has_research = bool(pin) and (bool(research["evidence_for"]) or bool(rc.get("research_artifact_id")) or bool(summary))
    confidence = t.get("thesis_confidence")
    if confidence is None and p.get("edge_score") is not None:
        confidence = round(float(p["edge_score"]) / 100.0, 3)
    record = {
        "schema": SCHEMA,
        "position_guid": p.get("option_strategy_guid"),
        "contract_guid": p.get("contract_guid"),
        "underlying_issuer_guid": (p.get("underlying_identity") or {}).get("issuer_guid") or p.get("issuer_guid"),
        "proposal_id": p.get("id"),
        "symbol": p.get("symbol"),
        "strategy_type": p.get("strategy"),
        "investment_thesis": {
            "symbol_thesis_id": t.get("symbol_thesis_id"),
            "pin": pin,
            "state": state,
            "stance": t.get("thesis_stance"),
            "summary": summary or None,
            "why_option": p.get("why_option") or None,
        } if (pin and summary) else None,
        "supporting_research": research if has_research else None,
        "catalysts": [catalyst] if catalyst else [],
        "risk_factors": risk,
        "entry_criteria": {
            "strike": p.get("strike"), "expiration": p.get("expiration"), "dte": p.get("dte"),
            "premium": p.get("premium"), "breakeven": p.get("breakeven"),
            "underlying_price": p.get("underlying_price"), "data_source": p.get("data_source"),
        } if p.get("strike") is not None and p.get("expiration") else None,
        "exit_criteria": exits if [x for x in exits if not x.startswith("Expiry ")] else [],
        "position_sizing_rationale": None,  # operator-entered only (MBI_BEHAVIOR=0)
        "portfolio_impact": {
            "portfolio_role": t.get("portfolio_role"),
            "account": p.get("account"),
            "max_loss": p.get("max_loss"),
            "capital_required": p.get("capital_required") or p.get("premium_total"),
        },
        "cio_approval_record": None,
        "agent_decision_trace": {
            "engine": "options_engine.generate_proposals",
            "edge_score": p.get("edge_score"),
            "desk_tier": p.get("desk_tier"),
            "quality_gate": p.get("quality_gate") or None,
            "enterprise_blocked": bool(p.get("enterprise_blocked")),
            "generated_at": p.get("generated_at"),
        },
        "confidence_score": confidence,
        "authority": AUTHORITY,
        "financial_action": False,
    }
    record["missing_required"] = [f for f in REQUIRED_FIELDS if not _nonempty(record.get(f))]
    record["pending_operator"] = list(OPERATOR_FIELDS)
    record["thesis_gate_state"] = state
    return record


def thesis_blocks(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Named refusals for the approval queue. Empty list = thesis bar cleared."""
    blocks: list[dict[str, Any]] = []
    state = record.get("thesis_gate_state") or "INSUFFICIENT_DATA"
    try:
        from scripts.lib.thesis_decision_gate import apply_thesis_decision_gate
    except ImportError:
        from lib.thesis_decision_gate import apply_thesis_decision_gate  # type: ignore
    gate = apply_thesis_decision_gate(
        current_action="BUY", governed_verdict=None, thesis_state=state,
        thesis_stance=(record.get("investment_thesis") or {}).get("stance"),
    )
    if gate.get("restricted") or state in INCOMPLETE_STATES | BROKEN_STATES:
        blocks.append({
            "code": "thesis_required",
            "reason": f"symbol thesis {state.lower().replace('_', ' ')}: an option needs the same thesis bar as a stock purchase",
            "gate": gate.get("reason_codes"),
        })
    for field in record.get("missing_required") or []:
        blocks.append({"code": f"thesis_missing_{field}", "reason": f"options thesis record has no {field.replace('_', ' ')}"})
    return blocks


def _content_hash(record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k not in ("recorded_at", "version", "pin", "timestamp_history")}
    body["agent_decision_trace"] = {k: v for k, v in (body.get("agent_decision_trace") or {}).items()
                                    if k != "generated_at"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class OptionsThesisStore:
    """Append-only, hash-chained JSONL; a new version only when content changes."""

    def __init__(self, path: Optional[Path | str] = None):
        self.path = Path(path) if path else _default_path()

    def _events(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def history(self, position_guid: str) -> list[dict[str, Any]]:
        return [e for e in self._events() if e.get("position_guid") == position_guid]

    def current(self, position_guid: str) -> Optional[dict[str, Any]]:
        versions = [e for e in self.history(position_guid) if e.get("event_type") == "OPTIONS_THESIS_VERSION"]
        return versions[-1] if versions else None

    def _append(self, event: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        with open(lock, "a+", encoding="utf-8") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            events = self._events()
            prev = events[-1].get("event_hash") if events else GENESIS
            event = dict(event, prev_event_hash=prev, recorded_at=event.get("recorded_at") or _now())
            event["event_hash"] = hashlib.sha256(
                (prev + json.dumps(event, sort_keys=True, default=str)).encode()).hexdigest()
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, default=str) + "\n")
        return event

    def publish(self, record: dict[str, Any]) -> dict[str, Any]:
        """Store a version if the content changed; return the current version either way."""
        guid = record.get("position_guid")
        if not guid:
            return dict(record, version=None, pin=None, stored=False)
        chash = _content_hash(record)
        cur = self.current(guid)
        if cur and cur.get("content_hash") == chash:
            return dict(cur, stored=False)
        version = int((cur or {}).get("version") or 0) + 1
        event = dict(record, event_type="OPTIONS_THESIS_VERSION", version=version,
                     pin=f"opt_{guid}@v{version}", content_hash=chash,
                     supersedes=(cur or {}).get("pin"))
        return dict(self._append(event), stored=True)

    def record_approval(self, position_guid: str, *, proposal_id: str, action: str,
                        reviewer: str, note: str = "") -> Optional[dict[str, Any]]:
        if not position_guid:
            return None
        return self._append({
            "event_type": "OPTIONS_THESIS_CIO_APPROVAL",
            "position_guid": position_guid,
            "proposal_id": proposal_id,
            "action": action,
            "reviewer": reviewer,
            "note": note,
            "authority": AUTHORITY,
        })

    def verify_chain(self) -> bool:
        prev = GENESIS
        for e in self._events():
            body = {k: v for k, v in e.items() if k != "event_hash"}
            if e.get("prev_event_hash") != prev:
                return False
            if hashlib.sha256((prev + json.dumps(body, sort_keys=True, default=str)).encode()).hexdigest() != e.get("event_hash"):
                return False
            prev = e["event_hash"]
        return True
