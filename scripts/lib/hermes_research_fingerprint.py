"""Canonical fingerprint for Hermes research request de-duplication.

A fingerprint is an equivalence key for "same research work," not a unique id.

  research_id  = unique instance
  fingerprint  = logical identity of the ask

Two requests are duplicates if they share the same fingerprint.

Included in hash: fp_version, plan_id, situation_type, scope, symbol,
                  thesis_version, normalized questions

Excluded: needed_by, timestamps, priority, research_id, evidence snapshot,
          provenance, output_requirements, constraints
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Iterable, Mapping


FINGERPRINT_VERSION = "fp@v1"  # bump if canonicalization rules change


def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[?.!;,]+$", "", s)  # trailing punctuation
    return s


def _norm_questions(questions: Iterable[Mapping[str, Any] | str]) -> list[str]:
    out: list[str] = []
    for q in questions or []:
        if isinstance(q, str):
            text = q
        else:
            text = str(q.get("text") or q.get("question") or "")
        nt = _norm_text(text)
        if nt:
            out.append(nt)
    # order-invariant: sort + unique
    return sorted(set(out))


def _norm_symbol(subject: Mapping[str, Any] | None, top_symbol: str | None = None) -> str:
    subject = subject or {}
    symbols = subject.get("symbols") or []
    first_sym = symbols[0] if symbols else None
    sym = (
        subject.get("symbol")
        or top_symbol
        or first_sym
        or ""
    )
    return str(sym).strip().upper()


def _norm_scope(subject: Mapping[str, Any] | None, top_symbol: str | None = None) -> str:
    subject = subject or {}
    if subject.get("scope"):
        return str(subject.get("scope")).strip().lower()
    if _norm_symbol(subject, top_symbol):
        return "symbol"
    return "book"


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def canonical_fingerprint_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """
    Fields intentionally EXCLUDED (do not affect fingerprint):
    - needed_by, created_ts, research_id
    - priority (priority bump != new research)
    - context_snapshot numbers (same questions, fresher snapshot = same job)
    - provenance, output_requirements, constraints
    """
    subject = _as_mapping(request.get("subject"))
    # Flatten subject from top-level fields when emitter uses flat request shape
    if not subject:
        subject = {
            "symbol": request.get("symbol"),
            "symbols": request.get("symbols"),
            "scope": request.get("scope"),
            "situation_type": request.get("situation_type"),
        }
    top_symbol = request.get("symbol")
    top_sym_str = top_symbol if isinstance(top_symbol, str) else None
    trigger = _as_mapping(request.get("trigger"))
    situation = str(
        subject.get("situation_type")
        or trigger.get("situation_type")
        or request.get("situation_type")
        or ""
    ).strip().upper()
    return {
        "fp_version": FINGERPRINT_VERSION,
        "plan_id": str(request.get("plan_id") or "").strip(),
        "situation_type": situation,
        "scope": _norm_scope(subject, top_sym_str),
        "symbol": _norm_symbol(subject, top_sym_str),
        "thesis_version": str(request.get("thesis_version") or "").strip().lower(),
        "questions": _norm_questions(request.get("questions") or []),
    }


def compute_fingerprint(request: Mapping[str, Any]) -> str:
    """Return sha256:<hex> fingerprint for a research request mapping."""
    payload = canonical_fingerprint_payload(request)
    if not payload["plan_id"]:
        raise ValueError("plan_id required for research fingerprint")
    if not payload["questions"]:
        raise ValueError("at least one question required for research fingerprint")

    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def compute_fingerprint_from_parts(
    *,
    plan_id: str,
    situation_type: str = "",
    symbol: str = "",
    thesis_version: str = "",
    questions: Iterable[Mapping[str, Any] | str],
    scope: str | None = None,
) -> str:
    """Convenience builder for callers that pass flat plan fields."""
    request: dict[str, Any] = {
        "plan_id": plan_id,
        "situation_type": situation_type,
        "symbol": symbol,
        "thesis_version": thesis_version,
        "questions": list(questions or []),
    }
    if scope is not None:
        request["scope"] = scope
        request["subject"] = {
            "scope": scope,
            "symbol": symbol,
            "situation_type": situation_type,
        }
    return compute_fingerprint(request)
