"""Beliefs from settled outcomes onto the InstrumentRecord (tranche 1, Slice 2).

The one writer of ``InstrumentRecord.beliefs``. It reads ONLY settled rows:

* ``data/runtime/advisory_outcomes.jsonl`` — the advisory desk's 30/60/90d
  deterministic scorer (``correct`` per verdict). Population ``advisory_verdict``.
* ``data/cio/outcome_observations.jsonl`` — resolved checkpoints whose
  ``realized_state`` carries a price change; scored with
  ``outcome_to_lesson._direction`` (HOLD/WAIT are never scored). Population
  ``checkpoint``.
* ``<wake_root>/commitment_outcomes.jsonl`` — CONFIRMED / REFUTED governed
  commitment outcomes from the sweep. Population ``governed_commitment``.

and attaches ratified lessons (``advisory_kb_lessons.jsonl`` status ratified;
CIO ``lesson_candidates.jsonl`` promotion_stage OPERATOR_APPROVED / PROMOTED)
as ``lesson_ids``. Nothing PROVISIONAL, PROPOSED or REVIEW_READY reaches a belief.

The math is ``settle_agent_commitments.SettlementLedger.calibration`` (the
Lane-D shadow contract, MIN_SAMPLES=5) and the id is
``campaign_interfaces.mint_belief_proposal_id``; this module is that contract's
first production consumer. Persistence goes through
``cio_instrument_record.apply_belief`` — the rail refuses any behaviour key
inside the block and any ``live_mutation``.

Never invents an outcome: a row with no direction, no settled state or no
record to join is counted and skipped. MBI_BEHAVIOR = 0 throughout.

SCHEDULED_ENTRYPOINT: see scripts/write_instrument_beliefs.py (lane
``instrument-belief-writer``, proposed cron 50 18 * * *; install is §17).

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.campaign_interfaces import mint_belief_proposal_id  # noqa: E402
from scripts.lib.cio_instrument_record import (  # noqa: E402
    AUTHORITY,
    BELIEF_MIN_SAMPLES,
    DEFAULT_PATH,
    MBI_BEHAVIOR,
    CognitionNoOp,
    InstrumentRecordStore,
    apply_belief,
    subject_key_for_symbol,
)

SCHEMA = "InstrumentBeliefWriter@v1"
ADVISORY_OUTCOMES_REL = "data/runtime/advisory_outcomes.jsonl"
OBSERVATIONS_REL = "data/cio/outcome_observations.jsonl"
KB_LESSONS_REL = "data/runtime/advisory_kb_lessons.jsonl"
CIO_LESSONS_REL = "data/cio/lesson_candidates.jsonl"
COMMITMENT_OUTCOMES_NAME = "commitment_outcomes.jsonl"
LATEST_REL = "data/cio/instrument_belief_latest.json"

POP_ADVISORY = "advisory_verdict"
POP_CHECKPOINT = "checkpoint"
POP_COMMITMENT = "governed_commitment"
RATIFIED_CIO_STAGES = frozenset({"OPERATOR_APPROVED", "PROMOTED"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


def _sym(v: Any) -> str:
    return str(v or "").strip().upper()


# ── settled rows → SettlementLedger outcome shape ─────────────────────────

def _settled(outcome_id: str, ok: bool, *, population: str, horizon: str,
             subject_key: str, recommendation: str, produced_at: str,
             source_id: str) -> dict[str, Any]:
    return {
        "outcome_id": str(outcome_id),
        "lifecycle_state": "SUCCESSFUL" if ok else "UNSUCCESSFUL",
        "population": population,
        "horizon": str(horizon),
        "subject_key": subject_key,
        "recommendation": _sym(recommendation),
        "produced_at": str(produced_at or ""),
        "commitment_id": str(source_id),
        "wake_id": "",
    }


def rows_from_advisory_outcomes(rows: Iterable[dict[str, Any]], *,
                                subject_key_for: Callable[[str], Optional[str]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    out: list[dict[str, Any]] = []
    skipped = defaultdict(int)
    for r in rows:
        if not isinstance(r.get("correct"), bool):
            skipped["advisory_no_settled_bit"] += 1
            continue
        sym = _sym(r.get("symbol"))
        skey = subject_key_for(sym) if sym else None
        if not skey:
            skipped["advisory_no_record"] += 1
            continue
        verdict = _sym(r.get("verdict"))
        if not verdict:
            skipped["advisory_no_verdict"] += 1
            continue
        horizon = f"{int(r.get('horizon_d') or 0)}d"
        sid = str(r.get("source_row_id") or "")
        out.append(_settled(f"adv:{sid}:{horizon}", bool(r["correct"]), population=POP_ADVISORY,
                            horizon=horizon, subject_key=skey, recommendation=verdict,
                            produced_at=str(r.get("scored_at") or r.get("ts") or ""), source_id=sid))
    return out, dict(skipped)


def rows_from_observations(rows: Iterable[dict[str, Any]], *,
                           subject_key_for: Callable[[str], Optional[str]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    from scripts.lib.outcome_to_lesson import _direction

    out: list[dict[str, Any]] = []
    skipped = defaultdict(int)
    for r in rows:
        realized = r.get("realized_state") or {}
        change = None
        for key in ("change_pct", "return_pct", "pct_change"):
            if isinstance(realized, dict) and realized.get(key) is not None:
                try:
                    change = float(realized.get(key))
                except (TypeError, ValueError):
                    change = None
                break
        orig = r.get("original_decision_state") or {}
        rec = _sym(orig.get("recommendation"))
        direction = _direction(change, rec)
        if direction is None:
            skipped["checkpoint_no_direction"] += 1
            continue
        skey = r.get("subject_key") or subject_key_for(_sym(orig.get("symbol")))
        if not skey:
            skipped["checkpoint_no_record"] += 1
            continue
        oid = str(r.get("outcome_id") or "")
        if not oid:
            skipped["checkpoint_no_outcome_id"] += 1
            continue
        out.append(_settled(oid, direction == "CONFIRMED", population=POP_CHECKPOINT,
                            horizon=str(r.get("horizon") or ""), subject_key=skey, recommendation=rec,
                            produced_at=str(r.get("observed_at") or ""), source_id=str(r.get("decision_id") or "")))
    return out, dict(skipped)


def rows_from_commitment_outcomes(rows: Iterable[dict[str, Any]], *,
                                  subject_key_for_guid: Callable[[str], Optional[str]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    out: list[dict[str, Any]] = []
    skipped = defaultdict(int)
    for r in rows:
        state = _sym(r.get("outcome"))
        if state not in ("CONFIRMED", "REFUTED"):
            skipped["commitment_not_settled"] += 1
            continue
        guid = str(r.get("subject_guid") or "")
        skey = subject_key_for_guid(guid) if guid else None
        if not skey:
            skipped["commitment_no_record"] += 1
            continue
        rec = _sym(r.get("stance") or r.get("recommendation") or "COMMITMENT")
        out.append(_settled(str(r.get("outcome_id") or r.get("idempotency_key") or r.get("commitment_id") or ""), state == "CONFIRMED",
                            population=POP_COMMITMENT, horizon=str(r.get("horizon") or ""),
                            subject_key=skey, recommendation=rec,
                            produced_at=str(r.get("evaluated_at") or r.get("produced_at") or ""),
                            source_id=str(r.get("commitment_id") or "")))
    return out, dict(skipped)


# ── ratified lessons ───────────────────────────────────────────────────────

def ratified_lesson_ids(kb_rows: Iterable[dict[str, Any]], cio_rows: Iterable[dict[str, Any]],
                        *, symbols: Iterable[str]) -> list[str]:
    want = {_sym(s) for s in symbols if s}
    ids: list[str] = []
    for l in kb_rows:
        if str(l.get("status") or "") != "ratified":
            continue
        syms = {_sym(s) for s in (l.get("symbols") or [])}
        if syms & want and l.get("id"):
            ids.append(str(l["id"]))
    for l in cio_rows:
        if str(l.get("promotion_stage") or "").upper() not in RATIFIED_CIO_STAGES:
            continue
        scope = l.get("scope") or {}
        syms = set()
        if isinstance(scope, dict):
            syms = {_sym(s) for s in (scope.get("symbols") or [scope.get("symbol")]) if s}
        elif isinstance(scope, str):
            syms = {_sym(scope)}
        if syms & want and l.get("lesson_id"):
            ids.append(str(l["lesson_id"]))
    return sorted(set(ids))


# ── beliefs ────────────────────────────────────────────────────────────────

def beliefs_from_settled(settled: list[dict[str, Any]], *, records: dict[str, dict[str, Any]],
                         lesson_ids_for: Callable[[dict[str, Any]], list[str]],
                         now: Optional[str] = None,
                         min_samples: int = BELIEF_MIN_SAMPLES) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    """Group settled rows by (subject_key, recommendation, horizon, population) → belief blocks."""
    from scripts.settle_agent_commitments import SettlementLedger

    now = now or _now_iso()
    ledger = SettlementLedger()
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in settled:
        groups[(row["subject_key"], row["recommendation"], row["horizon"], row["population"])].append(row)
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    stats = defaultdict(int)
    for (skey, rec, horizon, pop), rows in sorted(groups.items()):
        record = records.get(skey)
        if record is None:
            stats["group_no_record"] += 1
            continue
        cal = ledger.calibration(rows, population=pop, horizon=horizon)
        if cal["sample_size"] < min_samples or not cal["qualified"]:
            stats["group_unqualified"] += 1
            continue
        belief_key = f"{skey}|{rec}|{horizon}|{pop}" if pop != POP_ADVISORY else f"{skey}|{rec}|{horizon}"
        prior = next((b for b in (record.get("beliefs") or []) if isinstance(b, dict)
                      and b.get("belief_key") == belief_key), None)
        revision = int((prior or {}).get("revision") or 0)
        ids = cal["outcome_ids"]
        if prior is None or sorted(prior.get("outcome_ids") or []) != ids:
            revision += 1
        pid = mint_belief_proposal_id(ids[-1], belief_key, revision)
        out[skey].append({
            "belief_key": belief_key,
            "population": pop,
            "horizon": horizon,
            "recommendation": rec,
            "sample_size": cal["sample_size"],
            "successful": cal["successful"],
            "success_rate": cal["success_rate"],
            "outcome_ids": ids,
            "lesson_ids": lesson_ids_for(record),
            "belief_proposal_id": pid,
            "revision": revision,
            "as_of": now,
            "written_by": "cio_belief_writer",
            "calibration_schema": cal.get("schema_version"),
            "live_mutation": False,
        })
        stats["beliefs_computed"] += 1
    return dict(out), dict(stats)


def update_beliefs_from_settled(root: Path | str, *, wake_root: Path | str | None = None,
                                apply: bool = True, now: Optional[str] = None,
                                store: InstrumentRecordStore | None = None,
                                subject_key_for_guid: Callable[[str], Optional[str]] | None = None,
                                write_latest: bool = True) -> dict[str, Any]:
    """Read settled rows under ``root``, write beliefs to the record store."""
    root_p = Path(root)
    now = now or _now_iso()
    st = store or InstrumentRecordStore(root_p / DEFAULT_PATH)
    records = {r.get("subject_key"): r for r in st.all() if isinstance(r, dict) and r.get("subject_key")}

    def _skey(sym: str) -> Optional[str]:
        return subject_key_for_symbol(sym, store=st) if sym else None

    def _skey_guid(guid: str) -> Optional[str]:
        if subject_key_for_guid is not None:
            return subject_key_for_guid(guid)
        try:
            from scripts.lib import identity_registry as reg

            ent = (reg.load_cached().get("entities") or {}).get(guid) or {}
            sym = _sym(ent.get("ticker_alias"))
            return _skey(sym) if sym else None
        except Exception:  # noqa: BLE001
            return None

    adv, sk1 = rows_from_advisory_outcomes(_jsonl(root_p / ADVISORY_OUTCOMES_REL), subject_key_for=_skey)
    obs, sk2 = rows_from_observations(_jsonl(root_p / OBSERVATIONS_REL), subject_key_for=_skey)
    com_rows = _jsonl(Path(wake_root) / COMMITMENT_OUTCOMES_NAME) if wake_root else []
    com, sk3 = rows_from_commitment_outcomes(com_rows, subject_key_for_guid=_skey_guid)
    settled = adv + obs + com

    kb = _jsonl(root_p / KB_LESSONS_REL)
    cio = _jsonl(root_p / CIO_LESSONS_REL)

    def _lessons(record: dict[str, Any]) -> list[str]:
        return ratified_lesson_ids(kb, cio, symbols=record.get("symbols") or [])

    computed, stats = beliefs_from_settled(settled, records=records, lesson_ids_for=_lessons, now=now)

    written: list[dict[str, Any]] = []
    noop = 0
    refused = 0
    for skey, blocks in sorted(computed.items()):
        rec = records[skey]
        changed_any = False
        for blk in blocks:
            try:
                rec, changed = apply_belief(rec, belief=blk, strict=True)
                changed_any = changed_any or bool(changed)
            except CognitionNoOp:
                noop += 1
            except Exception:  # noqa: BLE001 — a refused block is counted, never written
                refused += 1
        if changed_any and apply:
            st.upsert(rec)
            written.append({"subject_key": skey, "belief_keys": [b["belief_key"] for b in blocks]})
        elif changed_any:
            written.append({"subject_key": skey, "belief_keys": [b["belief_key"] for b in blocks], "dry_run": True})

    summary = {
        "schema": SCHEMA,
        "as_of": now,
        "applied": bool(apply),
        "settled_rows": {"advisory": len(adv), "checkpoint": len(obs), "governed_commitment": len(com)},
        "skipped": {**sk1, **sk2, **sk3},
        "groups": stats,
        "subjects_with_records": len(records),
        "written_beliefs": sum(len(w["belief_keys"]) for w in written if not w.get("dry_run")),
        "would_write_beliefs": sum(len(w["belief_keys"]) for w in written),
        "subjects_written": [w["subject_key"] for w in written],
        "noop": noop,
        "refused": refused,
        "store": str(st.path),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI_BEHAVIOR,
        "financial_action": False,
    }
    if write_latest and apply:
        latest = root_p / LATEST_REL
        try:
            latest.parent.mkdir(parents=True, exist_ok=True)
            latest.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
        except OSError:
            pass
    return summary


__all__ = [
    "SCHEMA",
    "rows_from_advisory_outcomes",
    "rows_from_observations",
    "rows_from_commitment_outcomes",
    "ratified_lesson_ids",
    "beliefs_from_settled",
    "update_beliefs_from_settled",
]
