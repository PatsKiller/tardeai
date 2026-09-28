"""intelligence_client — the one door to platform memory (Wave 1, tranche 1: READS + receipts).

Package: docs/architecture/cognitive_transformation_20260927/ (01 §2–§4, 03 §2–§4).
Approval: pkg-20260927-cogx-w1-d9e1 items 5 and 8 (operator 2026-09-27).

What this module IS (tranche 1)
- ``open_context``: read memory BEFORE acting — facts (durable agent memory), the living symbol
  thesis, calibrated beliefs on the instrument record, open contradiction candidates — for a set of
  subjects, resolved to registry GUIDs. Returns a ``MemoryContext@v1`` dict and appends a context row
  (read receipt) to an append-only JSONL.
- ``retrieve_or_generate``: run the seven-step retrieval ladder (03 §3) BEFORE any generation and write
  a ``RetrievalReceipt@v1``. In SHADOW mode (the default, and the only mode Wave 1 ships) generation
  proceeds regardless and the receipt records what WOULD have been reused. ENFORCED mode is coded
  behind the policy switch for Wave 2 and is exercised only by tests.
- ``commit``: record the outcome on the context row (write-after-act receipt). Deltas are recorded on
  the row, NOT written to any canonical store — the write path is Wave 2 (01 §3.2).

What this module is NOT
- Not a store. Every loader wraps an existing reader; nothing here owns data.
- Not an authority. MBI_BEHAVIOR = 0: a delta naming any BEHAVIOR_FIELDS key is refused
  (``BehaviorWriteRefused``), the same rail as cio_instrument_record.
- Not a merger of silos (AGENTS.md §0 rule 5). It gives nine silos one door; the Ring 1 linter
  (scripts/check_memory_chokepoint.py) ratchets direct imports down over time.

Reads that write (declared, so nobody is surprised): the durable memory provider's ``search`` logs
each retrieval to ``aif_memory_retrievals.jsonl`` (its own accounting — the same thing every existing
reader does); ``record_consumption`` appends a MemoryConsumptionReceipt. Both are receipts, not state.

Every loader is injectable (``Loaders``) so tests are hermetic; every default loader fails SOFT into
``degraded_reasons`` — except that DECIDE/ADVISE in ENFORCED mode fail CLOSED (``MemoryUnavailable``).

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA_CONTEXT = "MemoryContext@v1"
SCHEMA_RETRIEVAL = "RetrievalReceipt@v1"
SCHEMA_COMMIT = "MemoryCommit@v1"

PURPOSES = ("RESEARCH", "DECIDE", "ADVISE", "MONITOR", "CURATE", "ANSWER_OPERATOR")
FAIL_CLOSED_PURPOSES = ("DECIDE", "ADVISE")
MODES = ("SHADOW", "ENFORCED")
DECISIONS = ("HIT_FRESH", "HIT_STALE", "HIT_PARTIAL", "MISS")
REQUIRED_CLASSES_FOR_DECISION = ("facts", "beliefs", "contradictions")
# A context carries at most this many contradiction rows; the count is always exact. V alone had 7,676
# open candidates on 2026-09-27 (live proof) — embedding them made one context row 1.8 MB.
CONTRADICTIONS_IN_CONTEXT = 25

NAMESPACES = ("SEC", "ISS", "OPT", "THESIS", "EVID", "Q", "DEC", "WAKE", "COMMIT", "OUT", "AGENT",
              "BELIEF", "CKPT", "LANE", "RUN", "BREACH", "LESSON", "PROC", "RISK", "CONTRA", "EVENT",
              "MACRO", "REGIME")

# Freshness SLAs per class (02 §4): thesis 30 d, evidence 72 h.
THESIS_SLA_HOURS = 30 * 24
EVIDENCE_SLA_HOURS = 72
DEFAULT_ANSWER_SLA_HOURS = {"thesis": THESIS_SLA_HOURS, "bull": THESIS_SLA_HOURS, "bear": THESIS_SLA_HOURS,
                            "risk": THESIS_SLA_HOURS, "catalyst": EVIDENCE_SLA_HOURS, "stance": THESIS_SLA_HOURS}
QUESTION_CLASS_TO_THESIS_FIELD = {
    "thesis": "summary", "stance": "stance", "bull": "evidence_for", "bear": "counter_evidence",
    "risk": "invalidation_conditions", "catalyst": "catalysts", "what_changes": "what_changes_my_mind",
}

# The behaviour rail — same names as cio_instrument_record.BEHAVIOR_FIELDS; imported lazily so this
# module has no hard dependency, but the tuple is asserted equal in tests.
_BEHAVIOR_FIELDS_FALLBACK = ("recommended_delta_usd", "size_usd", "shares", "qty", "order",
                             "stop", "limit", "target_weight_pct", "trade", "execution")


class MemoryUnavailable(RuntimeError):
    """A DECIDE/ADVISE context could not be opened in ENFORCED mode. The caller must HOLD."""


class BehaviorWriteRefused(ValueError):
    """A commit named a behaviour field. There is no variable to raise; this is the rail."""


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(ts: _dt.datetime | None) -> str | None:
    return ts.isoformat() if ts else None


def _parse_ts(value: Any) -> _dt.datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return _dt.datetime.fromtimestamp(float(value), tz=_dt.timezone.utc)
    s = str(value).strip().replace("Z", "+00:00")
    try:
        ts = _dt.datetime.fromisoformat(s)
    except ValueError:
        try:
            ts = _dt.datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=_dt.timezone.utc)
        except ValueError:
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return ts


def _age_hours(value: Any, now: _dt.datetime) -> float | None:
    ts = _parse_ts(value)
    if ts is None:
        return None
    return max(0.0, (now - ts).total_seconds() / 3600.0)


def _freshness(age_hours: float | None, sla_hours: float) -> str:
    if age_hours is None:
        return "UNKNOWN"
    return "CURRENT" if age_hours <= sla_hours else "STALE"


def behavior_fields() -> tuple[str, ...]:
    try:
        from cio_instrument_record import BEHAVIOR_FIELDS  # type: ignore
        return tuple(BEHAVIOR_FIELDS)
    except Exception:  # noqa: BLE001 — the rail must exist even when the module is absent
        return _BEHAVIOR_FIELDS_FALLBACK


def resolve_mode(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    mode = str(env.get("TRADEAI_INTELLIGENCE_MODE", "SHADOW")).upper()
    return mode if mode in MODES else "SHADOW"


# ─────────────────────────────────────────────────────────────────────────────
# Paths (append-only receipts). Env first, then root/data/cio, then cwd/data/cio.
# ─────────────────────────────────────────────────────────────────────────────

def _cio_dir(root: Path | None, env: dict) -> Path:
    if env.get("TRADEAI_CIO_DIR"):
        return Path(env["TRADEAI_CIO_DIR"])
    base = root or Path(env.get("TRADEAI_ROOT") or env.get("MATURITY_CONTROL_ROOT") or Path.cwd())
    return Path(base) / "data" / "cio"


def contexts_path(root: Path | None = None, env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("TRADEAI_MEMORY_CONTEXTS_PATH") or (_cio_dir(root, env) / "memory_contexts.jsonl"))


def retrieval_receipts_path(root: Path | None = None, env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("TRADEAI_RETRIEVAL_RECEIPTS_PATH") or (_cio_dir(root, env) / "retrieval_receipts.jsonl"))


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Loaders — every read the façade performs, injectable.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Loaders:
    """Each callable reads one existing store. Any of them may raise; open_context degrades."""
    resolve_subject: Callable[[str], dict | None] | None = None      # symbol -> registry entity
    facts: Callable[[list[str], list[str]], dict] | None = None      # (symbols, guids) -> provider search result
    instrument: Callable[[str], dict | None] | None = None           # symbol -> InstrumentRecord (with beliefs[])
    thesis: Callable[[str], dict | None] | None = None               # symbol -> current symbol thesis record
    contradictions: Callable[[str], list[dict]] | None = None        # symbol -> candidate rows
    research_objects: Callable[[str], list[dict]] | None = None      # symbol -> ResearchObject rows (window)
    hermes_completed: Callable[[str], dict | None] | None = None     # fingerprint -> completed request/result
    hermes_results: Callable[[str], list[dict]] | None = None        # symbol -> completed result rows (window)
    now: Callable[[], _dt.datetime] = field(default=_now)
    release_sha: str | None = None


def default_loaders(root: Path | None = None, env: dict | None = None) -> Loaders:
    """Wrap the existing readers. Imports are lazy so a missing module degrades one class, not all."""
    env = os.environ if env is None else env
    root = Path(root) if root else None

    def resolve_subject(symbol: str) -> dict | None:
        import identity_registry  # type: ignore
        reg = identity_registry.load_cached() if root is None else identity_registry.load_cached(root=root)
        return identity_registry.lookup_symbol(reg, symbol.upper())

    def facts(symbols: list[str], guids: list[str]) -> dict:
        from agent_durable_memory import get_durable_provider  # type: ignore
        from agent_memory_governance import retrieve_for_context  # type: ignore
        provider = get_durable_provider(root) if root is not None else get_durable_provider()
        query = f"{' '.join(symbols)} investment thesis research context".strip()
        return retrieve_for_context(provider, query=query, symbols=symbols, top_k=8, budget_tokens=1500)

    def instrument(symbol: str) -> dict | None:
        from cio_instrument_record import load_instrument_record_for_wake  # type: ignore
        out = load_instrument_record_for_wake(symbol=symbol, root=root)
        return out.get("record") if out and out.get("ok") else None

    def thesis(symbol: str) -> dict | None:
        from cio_theses import CIOThesisStore  # type: ignore
        from symbol_thesis_coverage import symbol_thesis_id  # type: ignore
        cio = _cio_dir(root, env)
        store = CIOThesisStore(event_path=cio / "cio_theses.jsonl", projection_path=cio / "cio_theses_projection.json")
        return store.get_current(symbol_thesis_id(symbol))

    def contradictions(symbol: str) -> list[dict]:
        # Streams the candidates file; does not load 128k rows into memory (consumer.load_candidates does).
        path = _cio_dir(root, env) / "research_contradiction_candidates.jsonl"
        sym = symbol.upper()
        out: list[dict] = []
        if not path.exists():
            return out
        max_lines = int(env.get("TRADEAI_CONTRADICTION_SCAN_MAX_LINES", "400000"))
        with path.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines:
                    break
                if sym not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("schema") != "ResearchContradictionCandidate@v1":
                    continue
                if str(row.get("left_symbol", "")).upper() == sym or str(row.get("right_symbol", "")).upper() == sym:
                    if row.get("status", "CANDIDATE") == "CANDIDATE":
                        out.append(row)
        return out

    def research_objects(symbol: str) -> list[dict]:
        import hermes_web_research  # type: ignore
        s = hermes_web_research.settings()
        return hermes_web_research.reused_objects(symbol.upper(), s, dict(env))

    def hermes_completed(fingerprint: str) -> dict | None:
        import cio_hermes_research  # type: ignore
        return cio_hermes_research.find_latest_completed_by_fingerprint(fingerprint)

    def hermes_results(symbol: str) -> list[dict]:
        path = _cio_dir(root, env) / "hermes_research_results.jsonl"
        sym = symbol.upper()
        out: list[dict] = []
        if not path.exists():
            return out
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if sym not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(row.get("symbol", "")).upper() == sym and row.get("status") in (None, "completed", "COMPLETED", "ok"):
                    out.append(row)
        return out

    return Loaders(resolve_subject=resolve_subject, facts=facts, instrument=instrument, thesis=thesis,
                   contradictions=contradictions, research_objects=research_objects,
                   hermes_completed=hermes_completed, hermes_results=hermes_results,
                   release_sha=env.get("TRADEAI_RELEASE_SHA"))


# ─────────────────────────────────────────────────────────────────────────────
# Subjects
# ─────────────────────────────────────────────────────────────────────────────

def is_namespaced(key: str) -> bool:
    ns, _, rest = str(key).partition(":")
    return bool(rest) and ns in NAMESPACES


def _resolve_subjects(subjects: Iterable[str], loaders: Loaders, degraded: list[str]) -> list[dict]:
    out: list[dict] = []
    for raw in subjects:
        raw = str(raw).strip()
        if not raw:
            continue
        if is_namespaced(raw):
            out.append({"input": raw, "guid": raw, "symbol": None, "identity_status": "NAMESPACED"})
            continue
        sym = raw.upper()
        entity = None
        try:
            entity = loaders.resolve_subject(sym) if loaders.resolve_subject else None
        except Exception as exc:  # noqa: BLE001
            degraded.append(f"IDENTITY_LOADER_FAILED:{sym}:{type(exc).__name__}")
        if entity and (entity.get("security_guid") or entity.get("subject_guid")):
            guid = entity.get("security_guid") or entity.get("subject_guid")
            out.append({"input": raw, "guid": f"SEC:{guid}", "security_guid": guid,
                        "issuer_guid": entity.get("issuer_guid"), "symbol": sym,
                        "identity_status": entity.get("identity_status", "CONFIRMED")})
        else:
            degraded.append(f"IDENTITY_UNRESOLVED:{sym}")
            out.append({"input": raw, "guid": None, "symbol": sym, "identity_status": "UNRESOLVED"})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# open_context
# ─────────────────────────────────────────────────────────────────────────────

def open_context(actor: dict, purpose: str, subjects: Iterable[str], *, as_of: str | None = None,
                 classes: Iterable[str] | None = None, mode: str | None = None,
                 loaders: Loaders | None = None, root: Path | None = None, env: dict | None = None,
                 write_receipt: bool = True) -> dict:
    """Read memory before acting. Returns a MemoryContext@v1 dict.

    ``actor``: {lane_id, agent_id?, release_sha?, boot_id?}. ``purpose``: one of PURPOSES.
    ``subjects``: symbols or namespaced keys. ``classes``: subset of
    {facts, thesis, beliefs, contradictions} to load (default all).
    SHADOW (default): every failure degrades. ENFORCED: DECIDE/ADVISE with a failed required class
    raises MemoryUnavailable — the caller holds; it never falls back to a raw store.
    """
    env = os.environ if env is None else env
    purpose = str(purpose).upper()
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}, got {purpose!r}")
    mode = (mode or resolve_mode(env)).upper()
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if not isinstance(actor, dict) or not actor.get("lane_id"):
        raise ValueError("actor.lane_id is required")
    loaders = loaders or default_loaders(root, env)
    wanted = set(classes) if classes else {"facts", "thesis", "beliefs", "contradictions"}
    now = loaders.now()
    degraded: list[str] = []
    subs = _resolve_subjects(subjects, loaders, degraded)
    symbols = [s["symbol"] for s in subs if s.get("symbol")]
    guids = [s["guid"] for s in subs if s.get("guid")]
    failed_classes: list[str] = []

    ctx: dict[str, Any] = {
        "schema": SCHEMA_CONTEXT,
        "context_id": "ctx_" + uuid.uuid4().hex[:16],
        "actor": {"lane_id": actor.get("lane_id"), "agent_id": actor.get("agent_id"),
                  "release_sha": actor.get("release_sha") or loaders.release_sha, "boot_id": actor.get("boot_id")},
        "purpose": purpose,
        "mode": mode,
        "subjects": subs,
        "opened_at": _iso(now),
        "as_of": as_of or _iso(now),
        "facts": [],
        "thesis": {},
        "beliefs": [],
        "open_contradictions": [],
        "open_contradictions_count": 0,
        "prior_decisions": {"state": "UNMEASURED", "note": "DECISION class joins the record in Wave 2 (02 §2)"},
        "lessons": [],
        "lessons_state": "NONE_PROMOTED",
        "operator_turns": {"state": "UNMEASURED"},
        "retrieval_receipt": None,
        "degraded": False,
        "degraded_reasons": degraded,
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
    }

    # facts
    if "facts" in wanted:
        try:
            if loaders.facts is None:
                raise RuntimeError("no facts loader")
            res = loaders.facts(symbols, guids) or {}
            rows = list(res.get("supporting") or res.get("records") or []) + list(res.get("counter_memory") or res.get("counter") or [])
            conflicts = {c.get("memory_id") for c in (res.get("conflicts") or []) if isinstance(c, dict)}
            for r in rows:
                if not isinstance(r, dict):
                    continue
                age = _age_hours(r.get("as_of") or r.get("created_at"), now)
                exp = _parse_ts(r.get("expires_at"))
                fresh = "STALE" if (exp and exp < now) else _freshness(age, THESIS_SLA_HOURS)
                ctx["facts"].append({
                    "fact_id": r.get("memory_id"), "class": "RESEARCH" if str(r.get("memory_type", "")).upper().startswith("RESEARCH") else "COMPANY",
                    "memory_type": r.get("memory_type"), "subject_guid": r.get("subject_guid"),
                    "symbols": r.get("symbols"), "confidence": r.get("confidence"),
                    "freshness_state": fresh, "age_hours": age,
                    "contradiction_state": "OPEN" if (r.get("contradicts") or r.get("memory_id") in conflicts) else "NONE",
                    "status": r.get("status"), "lineage_ref": (r.get("source_refs") or r.get("source_event_ids") or [None])[0],
                    "retrieval_status": res.get("retrieval_status"),
                })
            ctx["fact_ids"] = [f["fact_id"] for f in ctx["facts"] if f.get("fact_id")]
        except Exception as exc:  # noqa: BLE001
            failed_classes.append("facts"); degraded.append(f"FACTS_UNAVAILABLE:{type(exc).__name__}")

    # thesis (first symbol subject; multi-subject contexts carry the first thesis and list the rest)
    if "thesis" in wanted and symbols:
        try:
            if loaders.thesis is None:
                raise RuntimeError("no thesis loader")
            th = loaders.thesis(symbols[0])
            if th:
                age = _age_hours(th.get("updated_ts") or th.get("published_ts") or th.get("created_ts"), now)
                ctx["thesis"] = {
                    "thesis_id": th.get("thesis_id"), "version": th.get("version"), "pin": th.get("thesis_version"),
                    "stance": th.get("stance"), "summary": th.get("summary"),
                    "evidence_for": th.get("evidence_for"), "counter_evidence": th.get("counter_evidence"),
                    "invalidation_conditions": th.get("invalidation_conditions"), "catalysts": th.get("catalysts"),
                    "what_changes_my_mind": th.get("what_changes_my_mind"), "research_gaps": th.get("research_gaps"),
                    "status": th.get("status"), "age_hours": age, "freshness_state": _freshness(age, THESIS_SLA_HOURS),
                    "parent_version": th.get("parent_version"),
                }
            else:
                ctx["thesis"] = {"state": "NONE"}
        except Exception as exc:  # noqa: BLE001
            failed_classes.append("thesis"); degraded.append(f"THESIS_UNAVAILABLE:{type(exc).__name__}")

    # beliefs
    if "beliefs" in wanted and symbols:
        try:
            if loaders.instrument is None:
                raise RuntimeError("no instrument loader")
            rec = loaders.instrument(symbols[0]) or {}
            for b in rec.get("beliefs") or []:
                if isinstance(b, dict):
                    ctx["beliefs"].append({k: b.get(k) for k in ("belief_key", "population", "horizon", "recommendation",
                                                                  "sample_size", "successful", "success_rate", "revision", "as_of")})
            ctx["instrument_subject_key"] = rec.get("subject_key")
            ctx["next_research_question"] = rec.get("next_research_question")
            ctx["last_outcome"] = rec.get("last_outcome")
        except Exception as exc:  # noqa: BLE001
            failed_classes.append("beliefs"); degraded.append(f"BELIEFS_UNAVAILABLE:{type(exc).__name__}")

    # contradictions
    if "contradictions" in wanted and symbols:
        try:
            if loaders.contradictions is None:
                raise RuntimeError("no contradictions loader")
            total = 0
            for sym in symbols:
                for c in loaders.contradictions(sym) or []:
                    total += 1
                    if len(ctx["open_contradictions"]) < CONTRADICTIONS_IN_CONTEXT:
                        ctx["open_contradictions"].append({"contradiction_id": c.get("candidate_id"), "symbol": sym,
                                                           "left": c.get("left_artifact_id"), "right": c.get("right_artifact_id"),
                                                           "opposition": c.get("opposition"), "state": "OPEN"})
            ctx["open_contradictions_count"] = total
            if total > CONTRADICTIONS_IN_CONTEXT:
                ctx["open_contradictions_truncated"] = True
        except Exception as exc:  # noqa: BLE001
            failed_classes.append("contradictions"); degraded.append(f"CONTRADICTIONS_UNAVAILABLE:{type(exc).__name__}")

    ctx["failed_classes"] = failed_classes
    ctx["degraded"] = bool(degraded)
    ctx["contradiction_state"] = "OPEN" if ctx["open_contradictions"] else ("UNKNOWN" if "contradictions" in failed_classes else "NONE")

    if mode == "ENFORCED" and purpose in FAIL_CLOSED_PURPOSES:
        blocking = [c for c in failed_classes if c in REQUIRED_CLASSES_FOR_DECISION]
        unresolved = [s for s in subs if s.get("identity_status") == "UNRESOLVED"]
        if blocking or unresolved:
            if write_receipt:
                _append(contexts_path(root, env), {**ctx, "event": "REFUSED", "disposition": "HOLD_MEMORY_UNAVAILABLE"})
            raise MemoryUnavailable(f"{purpose} refused: failed={blocking} unresolved={[s['input'] for s in unresolved]}")

    if write_receipt:
        _append(contexts_path(root, env), {**ctx, "event": "OPENED"})
        _consumption_receipt(ctx, root, env)
    return ctx


def _consumption_receipt(ctx: dict, root: Path | None, env: dict) -> None:
    """MemoryConsumptionReceipt@v1 through the existing chokepoint; fail-soft; only when facts were read."""
    ids = ctx.get("fact_ids") or []
    if not ids:
        return
    try:
        from memory_consumption_receipt import record_consumption  # type: ignore
        record_consumption(consumer="intelligence_client", purpose=ctx["purpose"].lower(),
                           symbols=[s.get("symbol") for s in ctx["subjects"] if s.get("symbol")],
                           result={"memory_ids": ids, "supporting": [{"memory_id": i} for i in ids],
                                   "retrieval_status": "OK"},
                           correlation_id=ctx["context_id"], root=root)
    except Exception as exc:  # noqa: BLE001
        ctx["degraded_reasons"].append(f"CONSUMPTION_RECEIPT_FAILED:{type(exc).__name__}")


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval ladder (03 §3) — shadow in Wave 1
# ─────────────────────────────────────────────────────────────────────────────

def _step(n: int, key: str, store: str, hit: bool, refs: list, t0: float, note: str | None = None) -> dict:
    row = {"step": n, "key": key, "store": store, "hit": bool(hit), "refs": refs[:20],
           "ms": round((time.perf_counter() - t0) * 1000, 2)}
    if note:
        row["note"] = note
    return row


def run_ladder(ctx: dict, question: dict, loaders: Loaders, *, now: _dt.datetime | None = None) -> tuple[list[dict], str, list]:
    """Return (ladder rows, decision, reused_refs). Pure given the loaders."""
    now = now or loaders.now()
    qclass = str(question.get("question_class") or "thesis").lower()
    horizon = str(question.get("horizon") or "default")
    sym = next((s["symbol"] for s in ctx.get("subjects", []) if s.get("symbol")), None)
    guid = next((s["guid"] for s in ctx.get("subjects", []) if s.get("guid")), None)
    sla_h = float(question.get("sla_hours") or DEFAULT_ANSWER_SLA_HOURS.get(qclass, EVIDENCE_SLA_HOURS))
    ladder: list[dict] = []
    reused: list = []
    hit1 = hit1_fresh = hit2 = hit2_fresh = hit3 = hit5 = False

    # 1 deterministic — Hermes fingerprint (the only deterministic key that exists today)
    t0 = time.perf_counter()
    fp = question.get("fingerprint")
    refs: list = []
    note = None
    if fp and loaders.hermes_completed:
        try:
            done = loaders.hermes_completed(fp)
            if done:
                age = _age_hours(done.get("completed_ts") or done.get("as_of") or done.get("updated_ts"), now)
                hit1 = True
                hit1_fresh = age is not None and age <= sla_h
                refs = [done.get("research_id") or done.get("result_id")]
        except Exception as exc:  # noqa: BLE001
            note = f"loader_failed:{type(exc).__name__}"
    else:
        note = "no_fingerprint" if not fp else "no_loader"
    ladder.append(_step(1, f"{guid or sym}×{qclass}×{horizon}", "hermes_research_projection", hit1, refs, t0, note))
    if hit1:
        reused += refs

    # 2 thesis field
    t0 = time.perf_counter()
    th = ctx.get("thesis") or {}
    fld = QUESTION_CLASS_TO_THESIS_FIELD.get(qclass, "summary")
    val = th.get(fld)
    hit2 = bool(val) and th.get("status") in (None, "active")
    hit2_fresh = hit2 and th.get("freshness_state") == "CURRENT"
    refs = [f"{th.get('thesis_id')}@v{th.get('version')}"] if hit2 else []
    ladder.append(_step(2, f"THESIS:{th.get('thesis_id')}.{fld}", "cio_theses", hit2, refs, t0,
                        None if th else "no_thesis"))
    if hit2:
        reused += refs

    # 3 evidence — research objects (72 h) + completed Hermes results for the symbol
    t0 = time.perf_counter()
    refs = []
    note = None
    if sym:
        try:
            for ro in (loaders.research_objects(sym) if loaders.research_objects else []) or []:
                refs.append(ro.get("research_object_id") or ro.get("id") or ro.get("url"))
        except Exception as exc:  # noqa: BLE001
            note = f"research_objects_failed:{type(exc).__name__}"
        try:
            for r in (loaders.hermes_results(sym) if loaders.hermes_results else []) or []:
                age = _age_hours(r.get("completed_ts") or r.get("as_of"), now)
                if age is not None and age <= sla_h:
                    refs.append(r.get("result_id") or r.get("research_id"))
        except Exception as exc:  # noqa: BLE001
            note = (note + ";" if note else "") + f"hermes_results_failed:{type(exc).__name__}"
    refs = [r for r in refs if r]
    hit3 = bool(refs)
    ladder.append(_step(3, f"EVID:{sym}", "research_objects+hermes_results", hit3, refs, t0, note))
    if hit3:
        reused += refs

    # 4 contradiction — from the context
    t0 = time.perf_counter()
    contras = [c.get("contradiction_id") for c in ctx.get("open_contradictions") or []]
    ladder.append(_step(4, f"CONTRA:{sym}", "research_contradiction_candidates", bool(contras), contras, t0))

    # 5 citation — URLs already captured for the subject (per URL per day)
    t0 = time.perf_counter()
    urls: list = []
    if sym and loaders.research_objects:
        try:
            for ro in loaders.research_objects(sym) or []:
                u = ro.get("source_url_canonical") or ro.get("url") or ro.get("source_url")
                if u:
                    urls.append(u)
        except Exception:  # noqa: BLE001
            pass
    hit5 = bool(urls)
    ladder.append(_step(5, f"URL/day:{sym}", "research_objects", hit5, sorted(set(urls)), t0))

    # 6 version — the thesis pin / supersedes chain
    t0 = time.perf_counter()
    ver_refs = [th.get("pin") or f"{th.get('thesis_id')}@v{th.get('version')}"] if th.get("thesis_id") else []
    ladder.append(_step(6, f"VERSION:{th.get('thesis_id')}", "cio_theses.supersedes", bool(ver_refs), ver_refs, t0))

    # 7 semantic — not installed until the embedding table + local model (12 SW-1)
    t0 = time.perf_counter()
    ladder.append(_step(7, f"EMB:{qclass}", "intelligence.embedding", False, [], t0, "not_installed"))

    if hit1_fresh or hit2_fresh:
        decision = "HIT_FRESH"
    elif hit1 or hit2:
        decision = "HIT_STALE"
    elif hit3 or hit5:
        decision = "HIT_PARTIAL"
    else:
        decision = "MISS"
    return ladder, decision, [r for r in reused if r]


def retrieve_or_generate(ctx: dict, question: dict, generator: Callable[[dict, dict, dict], Any] | None = None, *,
                         loaders: Loaders | None = None, root: Path | None = None, env: dict | None = None,
                         write_receipt: bool = True) -> dict:
    """Run the ladder, write a RetrievalReceipt@v1, then generate (SHADOW always; ENFORCED only on non-HIT_FRESH).

    ``question``: {text, question_class, horizon?, fingerprint?, sla_hours?}.
    ``generator(ctx, question, receipt)`` is the caller's existing generation; it is never called with
    behaviour authority. Returns {decision, receipt, answer, generated}.
    """
    env = os.environ if env is None else env
    loaders = loaders or default_loaders(root, env)
    now = loaders.now()
    ladder, decision, reused = run_ladder(ctx, question, loaders, now=now)
    mode = ctx.get("mode") or resolve_mode(env)
    generated = False
    reason = None
    answer = None
    if generator is not None:
        if mode == "ENFORCED" and decision == "HIT_FRESH":
            answer = {"from_record": True, "refs": reused}
        else:
            reason = "SHADOW" if mode == "SHADOW" else decision
            if question.get("operator_forced"):
                reason = "OPERATOR_FORCED"
    receipt = {
        "schema": SCHEMA_RETRIEVAL,
        "receipt_id": "rr_" + uuid.uuid4().hex[:16],
        "context_id": ctx.get("context_id"),
        "lane_id": (ctx.get("actor") or {}).get("lane_id"),
        "subject_guid": next((s.get("guid") for s in ctx.get("subjects", []) if s.get("guid")), None),
        "symbol": next((s.get("symbol") for s in ctx.get("subjects", []) if s.get("symbol")), None),
        "question": {"text": question.get("text"), "question_class": question.get("question_class"),
                     "horizon": question.get("horizon") or "default"},
        "ladder": ladder,
        "decision": decision,
        "reused_refs": reused,
        "generated": generator is not None and answer is None,
        "generation_reason": reason,
        "mode": mode,
        "release_sha": (ctx.get("actor") or {}).get("release_sha"),
        "created_at": _iso(now),
        "authority": "READ_ONLY_ADVISORY",
    }
    if write_receipt:
        _append(retrieval_receipts_path(root, env), receipt)
    ctx["retrieval_receipt"] = receipt["receipt_id"]
    if generator is not None and answer is None:
        answer = generator(ctx, question, receipt)
        generated = True
    return {"decision": decision, "receipt": receipt, "answer": answer, "generated": generated}


# ─────────────────────────────────────────────────────────────────────────────
# commit — write-after-act receipt (deltas recorded, not applied, in Wave 1)
# ─────────────────────────────────────────────────────────────────────────────

def _scan_behavior(obj: Any, path: str = "") -> list[str]:
    hits: list[str] = []
    fields = set(behavior_fields())
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) in fields:
                hits.append(f"{path}.{k}" if path else str(k))
            hits += _scan_behavior(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            hits += _scan_behavior(v, f"{path}[{i}]")
    return hits


def commit(ctx: dict, outcome: dict, *, deltas: Iterable[dict] = (), confidence_updates: Iterable[dict] = (),
           freshness_updates: Iterable[dict] = (), contradiction_updates: Iterable[dict] = (),
           influence: dict | None = None, root: Path | None = None, env: dict | None = None,
           write_receipt: bool = True) -> dict:
    """Record what the actor learned. Refuses any behaviour field anywhere in the payload."""
    env = os.environ if env is None else env
    deltas = list(deltas)
    payload = {"outcome": outcome, "deltas": deltas, "confidence_updates": list(confidence_updates),
               "freshness_updates": list(freshness_updates), "contradiction_updates": list(contradiction_updates)}
    hits = _scan_behavior(payload)
    if hits:
        raise BehaviorWriteRefused(f"commit named behaviour fields {hits}; MBI_BEHAVIOR = 0")
    infl = {"consulted": bool(ctx.get("facts") or ctx.get("beliefs") or ctx.get("thesis")),
            "changed_decision": False, "mode": ctx.get("mode", "SHADOW")}
    if influence:
        infl.update({k: influence[k] for k in ("consulted", "changed_decision", "mode") if k in influence})
    row = {
        "schema": SCHEMA_COMMIT, "event": "COMMITTED", "context_id": ctx.get("context_id"),
        "lane_id": (ctx.get("actor") or {}).get("lane_id"), "purpose": ctx.get("purpose"),
        "committed_at": _iso(_now()), "influence": infl, "delta_count": len(deltas),
        "deltas_applied": False, "deltas_note": "recorded on the receipt only; the write path is Wave 2",
        "payload_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest(),
        **payload,
        "authority": "READ_ONLY_ADVISORY", "memory_behavior_influence": 0,
    }
    if write_receipt:
        _append(contexts_path(root, env), row)
    ctx["committed_at"] = row["committed_at"]
    ctx["influence"] = infl
    return row



# ─────────────────────────────────────────────────────────────────────────────
# Shadow helpers for the producer hooks (Wave 1 tranche 2). Fail-soft by construction: a hook
# must never change a producer's output or raise into it. They return None on any failure.
# ─────────────────────────────────────────────────────────────────────────────

def shadow_open(lane_id: str, subjects: Iterable[str], purpose: str = "RESEARCH", *, agent_id: str | None = None,
                question: dict | None = None, root: Path | None = None, env: dict | None = None) -> dict | None:
    """open_context in SHADOW and, when a question is given, observe the ladder as the caller's own
    generation (receipt generated=True, reason SHADOW_CALLER). Returns the context or None."""
    try:
        subs = [s for s in (subjects or []) if s]
        if not subs:
            return None
        ctx = open_context({"lane_id": lane_id, "agent_id": agent_id}, purpose, subs, mode="SHADOW", root=root, env=env)
        if question:
            observe_generation(ctx, question, root=root, env=env)
        # Every hooked producer beats (06 §3): file fallback only, never Postgres from here, never raises.
        try:
            from supervisor_heartbeat import beat  # type: ignore
            beat(lane_id, work_claimed=1, memory_context_ok=not ctx.get("degraded"),
                 degraded_reasons=list(ctx.get("degraded_reasons") or [])[:5], root=root, env=env)
        except Exception:  # noqa: BLE001
            pass
        return ctx
    except Exception:  # noqa: BLE001 — shadow never raises into a producer
        return None


def observe_generation(ctx: dict, question: dict, *, root: Path | None = None, env: dict | None = None,
                       loaders: Loaders | None = None) -> dict | None:
    """The caller is about to generate anyway: run the ladder and write a receipt that says so."""
    try:
        env = os.environ if env is None else env
        loaders = loaders or default_loaders(root, env)
        ladder, decision, reused = run_ladder(ctx, question, loaders, now=loaders.now())
        receipt = {
            "schema": SCHEMA_RETRIEVAL, "receipt_id": "rr_" + uuid.uuid4().hex[:16], "context_id": ctx.get("context_id"),
            "lane_id": (ctx.get("actor") or {}).get("lane_id"),
            "subject_guid": next((s.get("guid") for s in ctx.get("subjects", []) if s.get("guid")), None),
            "symbol": next((s.get("symbol") for s in ctx.get("subjects", []) if s.get("symbol")), None),
            "question": {"text": (question.get("text") or "")[:500], "question_class": question.get("question_class"), "horizon": question.get("horizon") or "default"},
            "ladder": ladder, "decision": decision, "reused_refs": reused, "generated": True, "generation_reason": "SHADOW_CALLER",
            "mode": "SHADOW", "release_sha": (ctx.get("actor") or {}).get("release_sha"), "created_at": _iso(loaders.now()), "authority": "READ_ONLY_ADVISORY",
        }
        _append(retrieval_receipts_path(root, env), receipt)
        ctx["retrieval_receipt"] = receipt["receipt_id"]
        return receipt
    except Exception:  # noqa: BLE001
        return None


def shadow_commit(ctx: dict | None, outcome: dict, *, root: Path | None = None, env: dict | None = None) -> dict | None:
    """commit that never raises. Outcomes are refs and kinds only; a behaviour field is still refused
    (and the refusal is itself recorded as a REFUSED row) — that rail is not softened."""
    if not ctx:
        return None
    try:
        return commit(ctx, outcome, root=root, env=env)
    except BehaviorWriteRefused as exc:
        try:
            _append(contexts_path(root, env), {"schema": SCHEMA_COMMIT, "event": "REFUSED", "context_id": ctx.get("context_id"),
                                               "reason": str(exc)[:200], "committed_at": _iso(_now())})
        except Exception:  # noqa: BLE001
            pass
        return None
    except Exception:  # noqa: BLE001
        return None

__all__ = ["open_context", "retrieve_or_generate", "run_ladder", "commit", "Loaders", "default_loaders",
           "MemoryUnavailable", "BehaviorWriteRefused", "contexts_path", "retrieval_receipts_path",
           "resolve_mode", "is_namespaced", "behavior_fields", "SCHEMA_CONTEXT", "SCHEMA_RETRIEVAL",
           "SCHEMA_COMMIT", "PURPOSES", "MODES", "DECISIONS", "shadow_open", "observe_generation", "shadow_commit"]
