"""AI claim check (LQ-20261107-154): deterministic checks on an AI-written artifact, plus a closed claim protocol.

Operator mandate 2026-11-07 (DSN-20261107-LLM-AUTOMATION-PROGRAM.md): "the LLM proposes, deterministic code disposes".
This module is the deterministic half of that sentence for every AI-written lane the lead registers in
``config/ai_claim_check_targets.json``:

* **data checks** on the lane's own artifact — a required field that is null, a natural key that repeats, a record
  older than the target's freshness bound, a number outside its declared range, and a declared count that disagrees
  with the list it counts. These are the audit's data checks, run on every record, not on a sample.
* **claim check** — up to three claims are taken from the record's claim field and the model job (injected as a
  callable) is asked to support or refute each one against the STORED source rows. The model's answer is only ever
  recorded when it carries a **verbatim quote** from that source text: a quote that is not a substring of the stored
  rows is itself the finding (``evidence_not_verbatim`` — the model manufactured its own evidence), and a claim the
  model refutes with a verbatim quote is recorded ``HALLUCINATION``. No model, or a malformed answer, is
  ``unverifiable`` — never a pass.

Nothing here writes a store, calls a model or touches a schedule. ``scripts/n8n_ai_claim_check.py`` is the only
caller that writes, and it writes one file (``data/quality/ai_claim_check_verdicts.json``) plus its lane receipt.
MBI_BEHAVIOR = 0: no broker, no order, no send. AUTHORITY: READ_ONLY_ADVISORY over the artifacts it reads.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

SCHEMA = "AiClaimCheckVerdicts@v1"
TARGETS_SCHEMA = "AiClaimCheckTargets@v1"
VERDICTS_FILE = "data/quality/ai_claim_check_verdicts.json"
MAX_CLAIMS = 3
#: The closed vocabulary a model job may answer with. Anything else is a malformed answer, not a verdict.
CLAIM_VERDICTS = ("supported", "refuted")
#: Deterministic finding kinds. A target with any FAILING_FINDINGS entry is FAIL; the rest are informational.
FAILING_FINDINGS = frozenset({"null_field", "duplicate_key", "out_of_range", "count_disagrees", "missing_artifact"})
INFO_FINDINGS = frozenset({"stale"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(value: Any) -> datetime | None:
    """A timezone-aware instant, or None. A naive stamp is assumed UTC (the artifacts carry UTC)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:  # date-only
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _dig(doc: Any, path: str) -> Any:
    """``sources[].title`` / ``a.b`` — the only path grammar a target may use."""
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(part)
    return cur


def _texts(record: Mapping[str, Any], fields: Sequence[str]) -> list[str]:
    """Stored source strings named by ``source_text_fields``: ``a.b``, ``rows[]`` or ``rows[].field``."""
    out: list[str] = []
    for field in fields:
        head, sep, tail = field.partition("[]")
        if sep:
            rows = _dig(record, head) if head else record
            for row in rows if isinstance(rows, list) else []:
                values = ([_dig(row, tail.lstrip("."))] if tail else
                          list(row.values()) if isinstance(row, Mapping) else [])
                out.extend(str(v) for v in values if isinstance(v, str) and v.strip())
            continue
        val = _dig(record, field)
        if isinstance(val, str) and val.strip():
            out.append(val)
        elif isinstance(val, list):
            out.extend(str(v) for v in val if isinstance(v, str) and v.strip())
    return out


def load_targets(path: Path | str) -> list[dict[str, Any]]:
    """The registered targets, validated enough to fail loudly on a typo rather than silently check nothing."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, Mapping) or doc.get("schema") != TARGETS_SCHEMA:
        raise ValueError(f"targets file is not {TARGETS_SCHEMA}")
    targets = doc.get("targets")
    if not isinstance(targets, list):
        raise ValueError("targets must be a list")
    seen: set[str] = set()
    for t in targets:
        if not isinstance(t, Mapping):
            raise ValueError("every target must be an object")
        tid = t.get("id")
        if not isinstance(tid, str) or not tid or tid in seen:
            raise ValueError(f"target id {tid!r} missing or repeated")
        seen.add(tid)
        if t.get("kind") not in ("json", "jsonl_dir"):
            raise ValueError(f"{tid}: kind must be json or jsonl_dir")
        if not isinstance(t.get("path"), str) or not t["path"] or Path(t["path"]).is_absolute():
            raise ValueError(f"{tid}: path must be a relative state-root path")
        if not (isinstance(t.get("natural_key"), list) and t["natural_key"]):
            raise ValueError(f"{tid}: natural_key must be a non-empty list")
        if not isinstance(t.get("claim_field"), str) and t.get("claim_field") is not None:
            raise ValueError(f"{tid}: claim_field must be a string or null")
    return [dict(t) for t in targets]


def _records(target: Mapping[str, Any], root: Path) -> tuple[list[dict[str, Any]], str | None]:
    """The target's records, newest file last for a jsonl_dir. Returns (records, error)."""
    base = root / str(target["path"])
    try:
        if target["kind"] == "json":
            doc = json.loads(base.read_text(encoding="utf-8"))
            rows = _dig(doc, str(target.get("records_path") or "")) if target.get("records_path") else doc
            if not isinstance(rows, list):
                return [], "records_not_a_list"
            return [r for r in rows if isinstance(r, Mapping)], None
        if not base.is_dir():
            return [], "artifact_missing"
        files = sorted(base.glob(str(target.get("file_glob") or "*.jsonl")))
        if not files:
            return [], "artifact_missing"
        rows: list[dict[str, Any]] = []
        for line in files[-1].read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                except ValueError:
                    return [], "unparseable_line"
                if isinstance(row, Mapping):
                    rows.append(row)
        return rows, None
    except OSError as exc:
        return [], f"unreadable:{type(exc).__name__}"


def data_checks(target: Mapping[str, Any], records: Sequence[Mapping[str, Any]], *, now: datetime) -> list[dict]:
    """Null / duplicate / stale / range / count checks over every record. One finding per defect."""
    tid, findings = str(target.get("id")), []
    required = [str(f) for f in (target.get("required") or [])]
    key_fields = [str(f) for f in target.get("natural_key") or []]
    ts_field = target.get("timestamp_field")
    max_age_h = target.get("max_age_h")
    ranges = target.get("ranges") or {}
    counts = target.get("count_matches") or {}
    seen: collections.Counter = collections.Counter()
    for index, rec in enumerate(records):
        key = "|".join(str(_dig(rec, f)) for f in key_fields)
        for field in required:
            if _dig(rec, field) in (None, "", [], {}):
                findings.append({"kind": "null_field", "target": tid, "record": index, "key": key, "field": field})
        seen[key] += 1
        for field, (lo, hi) in ranges.items():
            val = _dig(rec, field)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and not (lo <= val <= hi):
                findings.append({"kind": "out_of_range", "target": tid, "record": index, "key": key,
                                 "field": field, "value": val, "range": [lo, hi]})
        for left, right in counts.items():
            lval, rval = _dig(rec, left), _dig(rec, right)
            if isinstance(lval, int) and isinstance(rval, list) and lval != len(rval):
                findings.append({"kind": "count_disagrees", "target": tid, "record": index, "key": key,
                                 "field": left, "declared": lval, "actual": len(rval)})
        if ts_field and isinstance(max_age_h, (int, float)):
            stamp = _ts(_dig(rec, ts_field))
            if stamp is None:
                findings.append({"kind": "null_field", "target": tid, "record": index, "key": key, "field": ts_field})
            elif (now - stamp).total_seconds() > float(max_age_h) * 3600:
                findings.append({"kind": "stale", "target": tid, "record": index, "key": key,
                                 "field": ts_field, "at": stamp.isoformat(),
                                 "age_h": round((now - stamp).total_seconds() / 3600, 1)})
    for key, n in seen.items():
        if n > 1:
            findings.append({"kind": "duplicate_key", "target": tid, "key": key, "records": n,
                             "natural_key": key_fields})
    return findings


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def first_claims(claim_text: Any, *, limit: int = MAX_CLAIMS) -> list[str]:
    """Up to ``limit`` claims: the sentences of the claim field, in order, never invented or truncated mid-sentence."""
    if not isinstance(claim_text, str):
        return []
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", claim_text) if p.strip()]
    return parts[:limit]


def validate_claims(answer: Any, source_texts: Sequence[str], claims: Sequence[str]) -> list[dict]:
    """Dispose of the model's answer. Deterministic: a quote must be a verbatim substring of the stored text."""
    norm_sources = [_normalise(t) for t in source_texts]
    out: list[dict] = []
    rows = answer.get("claims") if isinstance(answer, Mapping) else None
    rows = rows if isinstance(rows, list) else []
    for index, claim in enumerate(claims):
        row = rows[index] if index < len(rows) and isinstance(rows[index], Mapping) else None
        if row is None:
            out.append({"claim": claim, "verdict": "unverifiable", "why": "model_did_not_answer"})
            continue
        verdict = row.get("verdict")
        quote = row.get("evidence_quote")
        if verdict not in CLAIM_VERDICTS:
            out.append({"claim": claim, "verdict": "unverifiable", "why": "verdict_not_in_vocabulary",
                        "model_verdict": verdict if isinstance(verdict, str) else None})
            continue
        if not isinstance(quote, str) or not _normalise(quote):
            out.append({"claim": claim, "verdict": "unverifiable", "why": "no_evidence_quote"})
            continue
        quote_n = _normalise(quote)
        if not any(quote_n in src for src in norm_sources):
            # The model's own evidence is not in the stored rows: that is a HALLUCINATION, whatever it claimed.
            out.append({"claim": claim, "verdict": "HALLUCINATION", "why": "evidence_not_verbatim",
                        "model_verdict": verdict, "quote": quote})
            continue
        out.append({"claim": claim, "verdict": verdict, "quote": quote})
    return out


def _claim_candidates(target: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> list[tuple]:
    """(index, record, claims) for each record whose claim field holds a checkable claim.

    A record the target declares claim-free (``claim_skip_when``) is not a candidate: momentum's
    ``no_clear_catalyst`` rows say "No clear catalyst found", which is an honest absence, not a claim.
    """
    claim_field = str(target.get("claim_field") or "")
    skip_when = target.get("claim_skip_when") or {}
    out: list[tuple] = []
    for index, rec in enumerate(records):
        if any(_dig(rec, str(field)) in values for field, values in skip_when.items()):
            continue
        wanted = first_claims(_dig(rec, claim_field))
        if wanted:
            out.append((index, rec, wanted))
    return out


def _evenly(candidates: Sequence[tuple], cap: int) -> list[tuple]:
    """At most ``cap`` candidates, spread across the whole artifact rather than the first ``cap`` rows."""
    if cap <= 0 or len(candidates) <= cap:
        return list(candidates)
    step = len(candidates) / float(cap)
    return [candidates[int(i * step)] for i in range(cap)]


def check_target(target: Mapping[str, Any], root: Path, *, now: datetime,
                 model: Callable[[dict[str, Any]], Any] | None = None) -> dict[str, Any]:
    """One target's verdicts: data findings, up to three claim verdicts, and the target's grade."""
    tid = str(target.get("id"))
    records, error = _records(target, root)
    if error:
        return {"id": tid, "verdict": "FAIL", "checked": 0, "findings": [
            {"kind": "missing_artifact", "target": tid, "why": error, "path": str(target.get("path"))}],
            "claims": [],
            # an artifact that could not be read holds no claims: zero here is a true count, not an unknown
            "claim_verdicts": {"supported": 0, "refuted": 0, "HALLUCINATION": 0, "unverifiable": 0, "disputed": 0},
            "claim_records": 0, "claim_records_skipped": 0, "missing_artifacts": 1}
    findings = data_checks(target, records, now=now)
    claims: list[dict] = []
    claim_field = target.get("claim_field")
    candidates = _claim_candidates(target, records) if claim_field else []
    cap = target.get("max_claim_records")
    picked = _evenly(candidates, int(cap)) if isinstance(cap, int) else list(candidates)
    if claim_field:
        source_fields = [str(f) for f in (target.get("source_text_fields") or [])]
        for index, rec, wanted in picked:
            key = "|".join(str(_dig(rec, f)) for f in (target.get("natural_key") or []))
            texts = _texts(rec, source_fields)
            if model is None:
                claims.extend({"record": index, "key": key, "claim": c, "verdict": "unverifiable",
                               "why": "model_unavailable"} for c in wanted)
                continue
            try:  # ONE call per record: the model judges this record's claims against its stored rows
                answer = model({"lane": tid, "record_key": key, "claims": wanted, "sources": texts})
            except Exception as exc:  # noqa: BLE001 -- a model failure is evidence, never the run's death
                message = str(exc)
                why = message[:80] if message.startswith("model_unavailable") else f"model_error:{type(exc).__name__}"
                claims.extend({"record": index, "key": key, "claim": c, "verdict": "unverifiable",
                               "why": why} for c in wanted)
                continue
            for verdict in validate_claims(answer, texts, wanted):
                claims.append({"record": index, "key": key, **verdict})
    hallucinated = sum(1 for c in claims if c["verdict"] == "HALLUCINATION")
    unverifiable = sum(1 for c in claims if c["verdict"] == "unverifiable")
    # a claim the model REFUTES with a verbatim source quote is an unsupported AI claim: it fails the target just
    # like a manufactured quote does, or the lane would grade a record whose prose the sources contradict as green
    disputed = sum(1 for c in claims if c["verdict"] in ("refuted", "HALLUCINATION"))
    failed = any(f["kind"] in FAILING_FINDINGS for f in findings)
    verdict = "FAIL" if (failed or disputed) else ("UNVERIFIABLE" if unverifiable else "PASS")
    return {"id": tid, "verdict": verdict, "checked": len(records), "findings": findings, "claims": claims,
            # the cap is reported, never silent: how many claim-bearing records were graded and how many were not
            "claim_records": len(picked), "claim_records_skipped": len(candidates) - len(picked),
            "missing_artifacts": 0,
            "claim_verdicts": {"supported": sum(1 for c in claims if c["verdict"] == "supported"),
                               "refuted": sum(1 for c in claims if c["verdict"] == "refuted"),
                               "HALLUCINATION": hallucinated, "unverifiable": unverifiable,
                               "disputed": disputed}}


def build_verdicts(targets: Iterable[Mapping[str, Any]], root: Path, *, now: datetime | None = None,
                   model: Callable[[dict[str, Any]], Any] | None = None, run_id: str | None = None) -> dict:
    """The verdicts document ``scripts/n8n_ai_claim_check.py`` writes. Pure: no I/O besides reading the targets."""
    now = now or _now()
    results = [check_target(t, root, now=now, model=model) for t in targets]
    counts = {
        "targets": len(results),
        "failing_targets": sum(1 for r in results if r["verdict"] == "FAIL"),
        "unverifiable_targets": sum(1 for r in results if r["verdict"] == "UNVERIFIABLE"),
        "records": sum(r["checked"] for r in results),
        "findings": sum(len(r["findings"]) for r in results),
        "claims": sum(len(r["claims"]) for r in results),
        "hallucinations": sum(r["claim_verdicts"]["HALLUCINATION"] for r in results),
        "unverifiable_claims": sum(r["claim_verdicts"]["unverifiable"] for r in results),
        # direct indexing on purpose: every check_target row carries these counters, and a result that lost one is a
        # bug that must raise here rather than be summed as a confident zero (the producer flattens failure trap)
        "claim_records": sum(r["claim_records"] for r in results),
        "claim_records_skipped": sum(r["claim_records_skipped"] for r in results),
        "missing_artifacts": sum(r["missing_artifacts"] for r in results),
    }
    return {"schema": SCHEMA, "generated_at": now.isoformat(), "run_id": run_id,
            "verdict": ("FAIL" if counts["failing_targets"] else
                        ("UNVERIFIABLE" if counts["unverifiable_targets"] else "PASS")),
            "counts": counts, "targets": results}


def verdicts_path(root: Path | str) -> Path:
    return Path(root) / VERDICTS_FILE


def write_verdicts(root: Path | str, doc: Mapping[str, Any]) -> Path:
    """Atomic replace; no deletes, no other store touched."""
    try:
        from scripts.lib.data_broker.atomic_json import atomic_write_json
    except ImportError:  # scripts/ on sys.path, repo root not
        # the same module under its top-level name when only scripts/ is importable -- the fallback is deliberate
        from lib.data_broker.atomic_json import atomic_write_json  # type: ignore[no-redef] -- fallback import path

    target = verdicts_path(root)
    atomic_write_json(target, dict(doc), indent=1)
    return target


def now_iso() -> str:
    return _now().isoformat()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
