"""Deterministic substantiveness grade for living symbol theses.

READ_ONLY_ADVISORY. No LLM. Same Q1 heuristics as research_quality_sample:
length, ticker mention, symbol-specific fact, non-generic, numeric fidelity,
survive-needles (invalidation / role / why own / catalyst / stop).

PASS (grade A) mints as coverage_state CURRENT.
B and C mint as THIN — they count toward coverage_pct, not substantive_pct.
F (<40 chars) does not mint.

CURRENT is a quality judgment after this module exists. It is not "we have a paragraph."
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ThesisSubstantiveness@v1"

PASS_MIN_CHARS = 400
GRADE_B_MIN_CHARS = 300
FLOOR_CHARS = 40  # today's CURRENT bar; now THIN/C, not CURRENT

SPECIFIC_RE = re.compile(
    r"\b(earnings|guidance|10-[qk]|8-k|s-1|13[df]|dividend|ex-div|buyback|"
    r"fda|pdufa|phase\s*[123]|catalyst|filing|sec\b|aum|nav\b|yield|"
    r"eps\b|revenue|margin|offering|lockup|split)\b",
    re.I,
)
GENERIC_RE = re.compile(
    r"\b(hold\s*/\s*watch|insufficient (fresh )?evidence|do not initiate|"
    r"not a sound candidate|maintain (paper-trading )?watchlist|"
    r"generic sector|wait for (more|clearer)|no new conviction)\b",
    re.I,
)
SURVIVE_NEEDLES = re.compile(
    r"\b(invalidat|what would change|why (own|held|watch)|role\b|"
    r"trim\b|add\b|hold\b|avoid\b|catalyst|stop\b)\b",
    re.I,
)
NUM_RE = re.compile(r"(?<![\w])(?:\$)?\d+\.\d{1,4}(?![\w])")

COVERED_STATES = frozenset({"CURRENT", "THIN", "STALE", "CONFLICTED"})
FRESH_STATES = frozenset({"CURRENT", "THIN"})
SUBSTANTIVE_STATES = frozenset({"CURRENT"})


def join_research_text(
    recommendation: str | None = None,
    dissent: str | None = None,
    evidence: Any = None,
) -> str:
    """Join stored research fields so mint/grade do not throw away paid evidence."""
    parts: list[str] = []
    rec = (recommendation or "").strip()
    if rec:
        parts.append(rec)
    dis = (dissent or "").strip()
    if dis:
        parts.append(dis)
    for item in _evidence_texts(evidence):
        if item and item not in parts:
            parts.append(item)
    return "\n".join(parts).strip()


def _evidence_texts(evidence: Any) -> list[str]:
    if evidence is None or evidence == "":
        return []
    if isinstance(evidence, str):
        s = evidence.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return [s]
        return _evidence_texts(parsed)
    if isinstance(evidence, dict):
        text = evidence.get("text") or evidence.get("body") or evidence.get("summary")
        if text:
            return [str(text).strip()]
        out: list[str] = []
        for v in evidence.values():
            out.extend(_evidence_texts(v))
        return out
    if isinstance(evidence, (list, tuple)):
        out: list[str] = []
        for item in evidence:
            out.extend(_evidence_texts(item))
        return out
    return [str(evidence).strip()] if str(evidence).strip() else []


def numeric_fidelity_fail(text: str, context: str = "") -> bool:
    """True when rec cites a $ / x.xx close-but-not-equal to a context number."""
    rec_nums = set(NUM_RE.findall(text or ""))
    ctx_nums = set(NUM_RE.findall((context or "")[:4000]))
    for rn in rec_nums:
        try:
            rv = float(rn.replace("$", ""))
        except ValueError:
            continue
        for cn in ctx_nums:
            try:
                cv = float(cn.replace("$", ""))
            except ValueError:
                continue
            if cv == 0:
                continue
            ratio = abs(rv - cv) / abs(cv)
            if 0.05 <= ratio <= 0.40 and abs(rv - cv) >= 0.5:
                return True
    return False


def score_text(symbol: str, text: str, context: str = "") -> dict[str, Any]:
    """Q1 row score. thesis_survivable == PASS / grade A (no LLM)."""
    rec = text or ""
    n = len(rec)
    specific = bool(SPECIFIC_RE.search(rec))
    generic = bool(GENERIC_RE.search(rec)) and not specific
    mentions = bool(re.search(rf"\b{re.escape(symbol)}\b", rec, re.I)) if symbol else False
    fidelity_fail = numeric_fidelity_fail(rec, context)
    needles = bool(SURVIVE_NEEDLES.search(rec))
    survive = (
        n >= PASS_MIN_CHARS
        and mentions
        and needles
        and specific
        and not generic
        and not fidelity_fail
    )
    return {
        "symbol": (symbol or "").upper(),
        "n_chars": n,
        "under_300": n < GRADE_B_MIN_CHARS,
        "specific_fact": specific,
        "generic_prose": generic,
        "mentions_symbol": mentions,
        "numeric_fidelity_fail": fidelity_fail,
        "survive_needles": needles,
        "thesis_survivable": survive,
        "preview": rec.replace("\n", " ")[:180],
    }


def grade_text(symbol: str, text: str, context: str = "") -> dict[str, Any]:
    """A/B/C/F + PASS/THIN + coverage_state CURRENT|THIN|RESEARCH_REQUIRED."""
    sc = score_text(symbol, text, context)
    n = int(sc["n_chars"])
    if n < FLOOR_CHARS:
        letter, bucket, state = "F", "SKIP", "RESEARCH_REQUIRED"
    elif (
        n >= PASS_MIN_CHARS
        and sc["mentions_symbol"]
        and sc["specific_fact"]
        and not sc["generic_prose"]
        and not sc["numeric_fidelity_fail"]
        and sc["survive_needles"]
    ):
        letter, bucket, state = "A", "PASS", "CURRENT"
    elif (
        n >= GRADE_B_MIN_CHARS
        and sc["mentions_symbol"]
        and (sc["specific_fact"] or sc["survive_needles"])
        and not sc["generic_prose"]
    ):
        letter, bucket, state = "B", "THIN", "THIN"
    else:
        letter, bucket, state = "C", "THIN", "THIN"
    reasons: list[str] = []
    if n < PASS_MIN_CHARS:
        reasons.append(f"chars={n}<{PASS_MIN_CHARS}")
    if not sc["mentions_symbol"]:
        reasons.append("no_ticker")
    if not sc["specific_fact"]:
        reasons.append("no_specific_fact")
    if sc["generic_prose"]:
        reasons.append("generic_prose")
    if sc["numeric_fidelity_fail"]:
        reasons.append("numeric_fidelity_fail")
    if not sc["survive_needles"]:
        reasons.append("no_survive_needle")
    return {
        **sc,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "grade": letter,
        "bucket": bucket,
        "coverage_state": state,
        "would_mint": state in ("CURRENT", "THIN"),
        "reasons": reasons,
    }


def mint_state_for(grade: dict[str, Any]) -> str:
    """CURRENT | THIN | SKIP."""
    state = str(grade.get("coverage_state") or "")
    if state in ("CURRENT", "THIN"):
        return state
    return "SKIP"


def row_is_covered(row: dict[str, Any]) -> bool:
    st = str(row.get("coverage_state") or row.get("thesis_state") or "")
    if st in COVERED_STATES:
        return True
    summary = (row.get("thesis_summary") or row.get("summary") or "")
    return bool(row.get("has_current_symbol_thesis")) and len(str(summary).strip()) >= FLOOR_CHARS


def row_is_substantive(row: dict[str, Any]) -> bool:
    st = str(row.get("coverage_state") or row.get("thesis_state") or "")
    return st in SUBSTANTIVE_STATES


def coverage_fresh_substantive_pcts(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Three numbers. THIN counts toward coverage and freshness, not substance."""
    rows = list(rows)
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "coverage_n": 0,
            "fresh_n": 0,
            "substantive_n": 0,
            "thin_n": 0,
            "coverage_pct": 0.0,
            "fresh_pct": 0.0,
            "substantive_pct": 0.0,
        }
    coverage_n = sum(1 for r in rows if row_is_covered(r))
    fresh_n = sum(1 for r in rows if r.get("fresh"))
    substantive_n = sum(1 for r in rows if row_is_substantive(r))
    thin_n = sum(1 for r in rows if str(r.get("coverage_state") or r.get("thesis_state") or "") == "THIN")
    return {
        "n": n,
        "coverage_n": coverage_n,
        "fresh_n": fresh_n,
        "substantive_n": substantive_n,
        "thin_n": thin_n,
        "coverage_pct": round(100.0 * coverage_n / n, 2),
        "fresh_pct": round(100.0 * fresh_n / n, 2),
        "substantive_pct": round(100.0 * substantive_n / n, 2),
    }


def pass_fixture(symbol: str) -> str:
    """≥400-char PASS paragraph for tests. Not production copy."""
    s = (symbol or "TICK").upper()
    body = (
        f"{s} is the book's assigned sleeve with a concrete role, not a generic watch. "
        f"Latest packet cites earnings, EPS, and a dividend/NAV yield figure from the filing. "
        f"Hold while the thesis is intact; trim on concentration, add on a documented pullback, "
        f"avoid a new initiation if the catalyst fails. Invalidation: a distribution cut, "
        f"an 8-K that changes the overlay, or guidance that breaks the yield/margin case. "
        f"What would change our mind is a missed catalyst or a stop through the stated level. "
        f"Why own {s}: role is ballast or core, not a trade. SEC filing and ex-div dates "
        f"must stay current. This paragraph exists so tests have a survivable thesis."
    )
    # Guarantee floor without changing the needles/facts above.
    while len(body) < PASS_MIN_CHARS:
        body += f" {s} remains the ticker under review for this living thesis."
    return body
