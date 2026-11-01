"""R15 decision anchor: a recorded resolution holds until a side changes ACTION or conviction moves +/-5.

EXCEPTIONS_MATRIX.md R15 (binding): "a resolution holds until a side changes ACTION or conviction moves +/-5; a new
flag needs 2 consecutive runs". The two-run rule lives in the security profile and the runner's observations.
This module owns the decision anchor:

  record_anchor(record, decision)   at decision time (ledger.transition): every side's ACTION as a position-aware
                                    ordinal, the chosen side, holding state and the subject's conviction
  anchor_holds(anchor, sides, held) at evaluation time: no anchored side changed its action and no side that
                                    disagrees with the decision is new

The conviction comparison stays in the engine (profiles/security.py compares ctx["conviction"] with the anchor's
conviction against RULEBOOK hysteresis.conviction_delta). Pure; no I/O.
"""
from __future__ import annotations

from .profiles.vocabulary import ordinal

SCHEMA = "ConflictDecisionAnchor@v1"
DECISION_SOURCES = frozenset({"CIO decision", "operator decision"})


def decision_source(actor_kind: str) -> str:
    return "operator decision" if actor_kind == "operator" else "CIO decision"


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def record_anchor(record: dict, decision: dict, *, conviction=None) -> dict:
    """The anchor stored on ConflictDecision@v1 (decision["anchor"]); actions as ordinals, never free text."""
    context = (record.get("subject") or {}).get("context") or {}
    held = context.get("held")
    sides = {}
    for item in record.get("sides") or []:
        source = item.get("source")
        if source and source not in DECISION_SOURCES:
            sides[source] = ordinal(item.get("value"), held)
    recorded = _number(conviction) if conviction is not None else _number(context.get("conviction"))
    return {"schema": SCHEMA, "held": held if isinstance(held, bool) else None, "sides": sides,
            "chosen": [decision_source(decision.get("actor_kind")), ordinal(decision.get("chosen_side"), held)],
            "conviction": recorded,
            "conviction_source": "decision caller" if conviction is not None else "ledger subject context"}


def anchor_holds(anchor: dict, sides: list[dict], held) -> bool:
    """True when every current side keeps its anchored action and no disagreeing side is new.

    ``sides`` are the engine's finding sides (source + described value) for the current run.
    """
    if not isinstance(anchor, dict) or anchor.get("schema") != SCHEMA:
        return False
    if isinstance(anchor.get("held"), bool) and anchor["held"] != held:
        return False                       # the position changed: every ordinal changes meaning
    chosen = (anchor.get("chosen") or [None, None])[1]
    anchored = anchor.get("sides") or {}
    for item in sides:
        source = item.get("source")
        if source in DECISION_SOURCES:
            continue
        current = ordinal(item.get("value"), held)
        if current is None:
            return False
        if source in anchored:
            if anchored[source] != current:
                return False               # a side changed ACTION
        elif not _compatible(current, chosen, held):
            return False                   # a new side disagrees with the decision
    return True


def _compatible(a, b, held) -> bool:
    """Same rule as SecurityStanceProfile.compare on ordinals (R6: adjacent held step = agreement)."""
    if a is None or b is None:
        return False
    return a == b or bool(held) and abs(a - b) == 1 and {a, b} != {0, 2}
