"""S0 operator loop — mint, attach, rehydrate, and remember the turn.

`S0_OPERATOR_CONVERSE` existed, but free-text questions minted a plan with
**empty `symbols`**. The live book shows it: the S0 for "alex what can i
reenter n…" carries `symbols: []`. With no symbol, nothing loads
`registry[symbol]`, no thesis or prior artifact is rehydrated, and the desk
looks like it only knows SCHD — the one name that happens to carry an operator
defer already.

`extract_symbols` was already written, in `cio_telegram_converse`. It was never
wired into `cio_converse_core.process_operator_message`, the channel-agnostic
path that mints. This module closes that gap and adds the three things a turn
needs to be worth anything: a stable id, an attach rule, and a rehydrated
bundle handed to the gate.

Builds no chat transport. Reads the converse payloads already in the store.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

S0_SCHEMA = "S0OperatorTurn@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

SITUATION_TYPE = "S0_OPERATOR_CONVERSE"
TURNS_REL = "data/cio/cio_operator_turns.jsonl"

QUESTION, ACK, DEFER, REJECT = "question", "ack", "defer", "reject"
INTENTS = (QUESTION, ACK, DEFER, REJECT)

# Refuse-to-mint classes. A TEST ticker or a cash row is not an entity the desk
# can hold a thesis about, and a dust residual is a rounding artefact — minting
# an S0 for any of them creates a subject that can never be answered.
REFUSE_TEST = "test_symbol"
REFUSE_CASH = "cash_or_non_entity"
REFUSE_DUST = "dust_residual"
REFUSE_NONE = "no_symbol_extracted"

_TEST_PREFIXES = ("TEST", "ZZZ", "DUMMY", "SOAK")
_CASH = {"CASH", "USD", "SPAXX", "MMF"}

_ACK_RE = re.compile(r"\b(ack|acknowledge[d]?|agreed|approved|ok(ay)?)\b", re.I)
_DEFER_RE = re.compile(r"\b(defer|wait|hold off|later|not yet|park)\b", re.I)
_REJECT_RE = re.compile(r"\b(reject|no thanks|decline|drop it|cancel)\b", re.I)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_hash(text: Any) -> str:
    return hashlib.sha256(str(text or "").strip().lower().encode()).hexdigest()[:16]


def turn_id_for(symbol: Any, text: Any, created_at: str) -> str:
    raw = f"{str(symbol or '-').upper()}|{text_hash(text)}|{created_at[:19]}"
    return "turn_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def classify_intent(text: str) -> str:
    """Coarse intent. Order matters: reject beats defer beats ack."""
    t = str(text or "")
    if _REJECT_RE.search(t):
        return REJECT
    if _DEFER_RE.search(t):
        return DEFER
    if _ACK_RE.search(t):
        return ACK
    return QUESTION


def extract_operator_symbols(text: str) -> list[str]:
    """Reuse the existing extractor rather than writing a second one."""
    try:
        from scripts.lib.cio_telegram_converse import extract_symbols

        return [str(s).upper() for s in (extract_symbols(text) or [])]
    except Exception:
        return []


def mint_eligibility(symbol: Any, *, dust: Optional[set[str]] = None
                     ) -> Optional[str]:
    """None means eligible; otherwise the refusal reason."""
    s = str(symbol or "").strip().upper()
    if not s:
        return REFUSE_NONE
    if any(s.startswith(p) for p in _TEST_PREFIXES):
        return REFUSE_TEST
    if s in _CASH:
        return REFUSE_CASH
    if dust and s in {str(d).upper() for d in dust}:
        return REFUSE_DUST
    try:
        from scripts.lib.holdings_universe import classify_instrument_id

        if str(classify_instrument_id(s) or "").upper() in {"CUSIP", "ISIN", "SEDOL"}:
            return REFUSE_TEST
    except Exception:
        pass
    return None


def _open(plan: dict[str, Any]) -> bool:
    return str(plan.get("status") or "") in {"draft", "proposed"}


def newest_open_plan_for(symbol: Any, plans: list[dict[str, Any]], *,
                         situation_type: Optional[str] = None
                         ) -> Optional[dict[str, Any]]:
    """Newest open plan mentioning `symbol`, optionally of one kind."""
    s = str(symbol or "").upper()
    hits = []
    for p in plans or []:
        if not isinstance(p, dict) or not _open(p):
            continue
        if situation_type and str(p.get("situation_type")) != situation_type:
            continue
        syms = {str(x).upper() for x in (p.get("symbols") or [])}
        if s and s in syms:
            hits.append(p)
    if not hits:
        return None
    hits.sort(key=lambda p: str(p.get("updated_ts") or p.get("created_ts") or ""),
              reverse=True)
    return hits[0]


def route_turn(text: str, *, plans: Optional[list[dict[str, Any]]] = None,
               plan_id: Optional[str] = None,
               dust: Optional[set[str]] = None,
               desk_pin: Optional[str] = None,
               now: Optional[datetime] = None) -> dict[str, Any]:
    """Decide what one operator turn does. Mints nothing itself.

    attach   an open plan for that symbol already exists — the turn joins it.
             This is what stops a second SCHD S6 every time the operator says
             "defer".
    mint     no open plan for a mintable symbol -> ONE S0 draft.
    refuse   TEST / CASH / dust / no symbol -> recorded, never minted.
    """
    ts = (now or datetime.now(timezone.utc)).isoformat()
    intent = classify_intent(text)
    symbols = extract_operator_symbols(text)
    plans = list(plans or [])

    # An explicit plan_id wins: the operator replied in a thread.
    if plan_id:
        sym = None
        for p in plans:
            if str(p.get("plan_id")) == str(plan_id):
                syms = p.get("symbols") or []
                sym = str(syms[0]).upper() if syms else None
                break
        return _turn("attach", plan_id=plan_id, symbol=sym, text=text,
                     intent=intent, ts=ts, reason="explicit_plan_id")

    if not symbols:
        return _turn("refuse", plan_id=None, symbol=None, text=text,
                     intent=intent, ts=ts, reason=REFUSE_NONE)

    symbol = symbols[0]
    why = mint_eligibility(symbol, dust=dust)
    existing = newest_open_plan_for(symbol, plans)

    # Attach beats refuse: an ack/defer on an existing plan is meaningful even
    # for a symbol we would not mint a fresh S0 for.
    if existing is not None:
        return _turn("attach", plan_id=existing.get("plan_id"), symbol=symbol,
                     text=text, intent=intent, ts=ts,
                     reason="existing_open_plan",
                     attached_situation_type=existing.get("situation_type"))
    if why:
        return _turn("refuse", plan_id=None, symbol=symbol, text=text,
                     intent=intent, ts=ts, reason=why)
    return _turn("mint", plan_id=None, symbol=symbol, text=text, intent=intent,
                 ts=ts, reason="no_open_plan_for_symbol",
                 mint_situation_type=SITUATION_TYPE,
                 thesis_version=desk_pin)


def _turn(action: str, *, plan_id: Any, symbol: Any, text: Any, intent: str,
          ts: str, reason: str, **extra: Any) -> dict[str, Any]:
    row = {
        "schema": S0_SCHEMA,
        "action": action,
        "turn_id": turn_id_for(symbol, text, ts),
        "plan_id": plan_id,
        "symbol": symbol,
        "text_hash": text_hash(text),
        "intent": intent,
        "reason": reason,
        "created_at": ts,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
    row.update(extra)
    return row


# ------------------------------------------------------------------ storage

def turns_path(root: Path | str) -> Path:
    return Path(root) / TURNS_REL


def persist_turn(root: Path | str, turn: dict[str, Any]) -> dict[str, Any]:
    p = turns_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(turn, ensure_ascii=False) + "\n")
    return {"wrote": True, "turn_id": turn.get("turn_id"), "path": str(p)}


def load_turns(root: Path | str) -> list[dict[str, Any]]:
    p = turns_path(root)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def last_turn_for(symbol: Any, root: Path | str) -> Optional[dict[str, Any]]:
    """The most recent turn for a symbol — what the next wake must see."""
    s = str(symbol or "").upper()
    hits = [t for t in load_turns(root)
            if str(t.get("symbol") or "").upper() == s]
    if not hits:
        return None
    hits.sort(key=lambda t: str(t.get("created_at") or ""))
    return hits[-1]


def operator_last_line(symbol: Any, root: Path | str) -> Optional[str]:
    """"operator last: defer" — the SCHD pattern, generalised.

    Text itself is not replayed; only the intent and when. The turn store keeps
    a hash, not the words, so a product surface cannot leak an operator message
    it was never asked to display.
    """
    t = last_turn_for(symbol, root)
    if not t:
        return None
    return f"operator last: {t.get('intent')} ({str(t.get('created_at'))[:10]})"


# ---------------------------------------------------------------- rehydrate

def rehydrate(symbol: Any, *, root: Path | str,
              plan_id: Optional[str] = None,
              plans: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Everything the gate needs about one subject, in one read.

    The point is what it prevents. Without this the gate is handed a bare
    symbol, decides `flash`, and pays to re-learn what the desk already knows —
    the prior artifact, the operator's last defer, the lesson bound to the last
    checkpoint. Every field degrades to None independently, so a missing store
    narrows the bundle instead of emptying it.
    """
    s = str(symbol or "").upper()
    root = Path(root)
    bundle: dict[str, Any] = {
        "schema": "S0RehydrateBundle@v1",
        "symbol": s or None,
        "plan_id": plan_id,
        "as_of": _utc(),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }

    open_plans = [p for p in (plans or []) if isinstance(p, dict) and _open(p)
                  and s in {str(x).upper() for x in (p.get("symbols") or [])}]
    bundle["open_plans"] = [p.get("plan_id") for p in open_plans]
    bundle["open_plan_kinds"] = sorted({str(p.get("situation_type"))
                                        for p in open_plans})

    try:
        from scripts.lib.cio_research_history import (
            gate_inputs_for, history_by_plan,
        )

        hist = history_by_plan(root)
        pid = plan_id or (open_plans[0].get("plan_id") if open_plans else None)
        bundle["research"] = gate_inputs_for(pid, hist) if pid else {
            "prior_outcome": None, "prior_artifact_ids": [], "research_id": None}
    except Exception:
        bundle["research"] = {"prior_outcome": None, "prior_artifact_ids": [],
                              "research_id": None}

    try:
        bundle["operator_last"] = operator_last_line(s, root)
        lt = last_turn_for(s, root)
        bundle["last_turn_id"] = (lt or {}).get("turn_id")
        bundle["last_turn_intent"] = (lt or {}).get("intent")
    except Exception:
        bundle["operator_last"] = None

    try:
        from scripts.lib.cio_specialist_artifact import load as load_artifacts

        arts = [a for a in load_artifacts(root)
                if str(a.get("plan_id") or "") in set(bundle["open_plans"])]
        arts.sort(key=lambda a: str(a.get("created_at") or ""))
        latest = arts[-1] if arts else None
        bundle["latest_artifact"] = (
            {"artifact_id": latest.get("artifact_id"),
             "provider": latest.get("provider"),
             "outcome": latest.get("outcome")} if latest else None)
    except Exception:
        bundle["latest_artifact"] = None

    try:
        from scripts.lib.cio_lesson_bind import store_path as lesson_path

        lp = lesson_path(root)
        lessons = []
        if lp.is_file():
            for line in lp.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("plan_id") in set(bundle["open_plans"]):
                    lessons.append(row.get("lesson_id"))
        bundle["lesson_ids"] = [x for x in lessons if x]
    except Exception:
        bundle["lesson_ids"] = []

    bundle["desk_pin_only"] = not bool(bundle.get("latest_artifact"))
    return bundle


def gate_input_from(bundle: dict[str, Any], *, kind: str = "held_core_thesis",
                    material: bool = True) -> dict[str, Any]:
    """Shape the bundle for ResearchNeedDecision@v2.

    Carries `prior_outcome` through, so a subject with a tainted or already-VALID
    artifact is routed by the ladder instead of paying for a fresh first pass.
    """
    research = bundle.get("research") or {}
    return {
        "plan_id": bundle.get("plan_id") or (bundle.get("open_plans") or [None])[0],
        "symbol": bundle.get("symbol"),
        "kind": kind,
        "material": material,
        "prior_outcome": research.get("prior_outcome"),
        "prior_artifact_ids": research.get("prior_artifact_ids") or [],
        "research_id": research.get("research_id"),
    }


# ------------------------------------------------- symbol thesis honesty

RESEARCH_REQUIRED = "RESEARCH_REQUIRED"
DESK_PIN_ONLY = "DESK_PIN_ONLY"
HAS_THESIS = "HAS_SYMBOL_THESIS"


def thesis_coverage(*, held_non_dust: list[str],
                    thesis_symbols: Optional[set[str]] = None,
                    root: Path | str | None = None) -> dict[str, Any]:
    """Held non-dust names with and without a symbol thesis.

    Deliberately does NOT auto-mint. Stamping `desk@v5` on twenty names the desk
    has never reasoned about would make the coverage number look complete while
    making it mean nothing — the gap is the finding.
    """
    have = {str(s).upper() for s in (thesis_symbols or set())}
    rows = []
    for sym in sorted({str(s).upper() for s in (held_non_dust or [])}):
        if sym in have:
            state = HAS_THESIS
        else:
            state = RESEARCH_REQUIRED
        rows.append({"symbol": sym, "state": state})
    missing = [r["symbol"] for r in rows if r["state"] != HAS_THESIS]
    return {
        "schema": "CIOSymbolThesisCoverage@v1",
        "authority": AUTHORITY,
        "held_non_dust_n": len(rows),
        "with_thesis_n": sum(1 for r in rows if r["state"] == HAS_THESIS),
        "missing_n": len(missing),
        "missing": missing,
        "rows": rows,
        "auto_minted": False,
        "note": ("Missing reads RESEARCH_REQUIRED / DESK_PIN_ONLY. Nothing is "
                 "auto-minted: a desk stamp on every name would make coverage "
                 "look complete and mean nothing."),
    }
