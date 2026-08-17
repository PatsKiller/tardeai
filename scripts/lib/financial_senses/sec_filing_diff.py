"""sec_filing_diff — deterministic like-for-like comparison of SEC XBRL facts.

Two facts are comparable only when their reporting *context* is equivalent.
For duration facts (revenue, net income, operating cash flow, capex, ...) this
means the same duration kind (annual vs quarterly vs YTD) and, where present,
the same fiscal period (fp) and frame type. Instantaneous facts (cash, debt,
shares) use point-in-time semantics keyed by end date.

When equivalence cannot be established the result is COMPARISON_UNAVAILABLE,
never a silently mismatched delta.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Any

COMPARISON_OK = "OK"
COMPARISON_UNAVAILABLE = "COMPARISON_UNAVAILABLE"
COMPARISON_NOT_APPLICABLE = "NOT_APPLICABLE"

# Canonical financial-advisory keys -> US-GAAP tags.
FACT_TAGS = {
    "revenue": "Revenues",
    "operating_income": "OperatingIncomeLoss",
    "net_income": "NetIncomeLoss",
    "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
    "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
    "cash": "CashAndCashEquivalentsAtCarryingValue",
    "debt": "LongTermDebtNoncurrent",
    "shares": "EntityCommonStockSharesOutstanding",
    "segment_metrics": "SegmentReportingInformation",
}

# Nature of each canonical fact: duration (flow) or instantaneous (stock).
FACT_KINDS = {
    "revenue": "DURATION",
    "operating_income": "DURATION",
    "net_income": "DURATION",
    "operating_cash_flow": "DURATION",
    "capex": "DURATION",
    "segment_metrics": "DURATION",
    "cash": "INSTANT",
    "debt": "INSTANT",
    "shares": "INSTANT",
}

# Sign conventions so a delta is meaningful even when one period is negative.
SIGN_FLIP_KEYS = {"net_income", "operating_income", "operating_cash_flow"}

MATERIALITY_THRESHOLDS = {
    "revenue": 5.0,
    "operating_income": 10.0,
    "net_income": 10.0,
    "operating_cash_flow": 10.0,
    "capex": 15.0,
    "cash": 10.0,
    "debt": 10.0,
    "shares": 5.0,
    "segment_metrics": 10.0,
}

_QTRS = ("Q1", "Q2", "Q3", "Q4")

# Tolerance (days) for treating two YTD spans as the same cumulative horizon when
# no fiscal-period label is present (e.g. ~181d vs ~182d). Larger divergence
# (e.g. ~181d vs ~273d) is a different cumulative horizon and is NOT comparable.
YTD_SPAN_TOLERANCE_DAYS = 5


def _span_days(fact: Any) -> int | None:
    """Return the start→end span in days, or None if it cannot be established."""
    if not isinstance(fact, dict):
        return None
    start = fact.get("start")
    end = fact.get("end")
    if not start or not end:
        return None
    try:
        return (_date.fromisoformat(str(end)) - _date.fromisoformat(str(start))).days
    except ValueError:
        return None


def _frame_type(frame: Any) -> str | None:
    """Classify an SEC `frame` string using official conventions.

    Duration frames: CY#### (annual), CY####Q# (quarter). Instantaneous frames:
    CY####Q#I. A YTD period has no distinct standard SEC frame — it is
    established from start/end duration — so no synthetic "YTD####" frame is
    treated as authoritative.
    """
    if not frame:
        return None
    f = str(frame).upper()
    if f.endswith("I"):
        if f[:-1].startswith("CY"):
            return "INSTANT"
    if f.startswith("CY") and len(f) == 6 and f[2:].isdigit():
        return "ANNUAL"
    if f.startswith("CY") and "Q" in f:
        return "QUARTERLY"
    return None


def duration_kind(fact: Any) -> str | None:
    """Return the duration kind of a fact, or None if it cannot be established.

    Returns ANNUAL / QUARTERLY / YTD / INSTANT / None (unknown).

    The actual start→end duration is the PRIMARY signal. A fiscal-period label
    fp=Q2/Q3 does NOT by itself prove a three-month duration: the SEC
    companyfacts shape can carry fp=Q2/Q3 on a six- or nine-month YTD fact.
    frame/form/fy corroborate only when dates are unusable or ambiguous, and
    they never override a clear multi-quarter duration into QUARTERLY.
    """
    if not isinstance(fact, dict):
        return None
    start = fact.get("start")
    end = fact.get("end")
    if not start:
        # No start date means an instantaneous (point-in-time) fact.
        return "INSTANT"
    if not end:
        return None

    days = None
    try:
        days = (_date.fromisoformat(str(end)) - _date.fromisoformat(str(start))).days
    except ValueError:
        days = None

    if days is not None:
        if days >= 300:
            return "ANNUAL"
        if days >= 120:
            return "YTD"
        if days >= 60:
            return "QUARTERLY"

    # Dates unusable or span too short to classify: corroborate with frame/fp.
    ft = _frame_type(fact.get("frame"))
    if ft:
        return ft
    fp = str(fact.get("fp") or "").upper()
    if fp == "FY":
        return "ANNUAL"
    if fp in _QTRS:
        return "QUARTERLY"
    return None


def _fp(fact: Any) -> str | None:
    if not isinstance(fact, dict):
        return None
    fp = str(fact.get("fp") or "").strip().upper()
    return fp or None


def _ytd_horizon(fact: Any):
    """Return the cumulative-horizon discriminator for a YTD duration fact.

    YTD facts span multiple quarters (six-, nine-month cumulative), so two YTD
    facts are NOT like-for-like merely because both classify as YTD. The horizon
    is the fiscal period (Q2 vs Q3) when present; otherwise it is the span
    bucketed with tolerance so ~181d and ~182d compare but ~181d and ~273d do
    not. Returns None when neither can be established.
    """
    if not isinstance(fact, dict):
        return None
    fp = _fp(fact)
    if fp:
        return ("fp", fp)
    span = _span_days(fact)
    if span is not None:
        return ("span", round(span / YTD_SPAN_TOLERANCE_DAYS))
    return None


def _numeric(fact: Any):
    if not isinstance(fact, dict):
        return None
    try:
        return float(fact.get("value"))
    except (TypeError, ValueError):
        return None


def _select_by_key(facts: dict, key: str):
    """Look up a fact by canonical key then by tag."""
    if not isinstance(facts, dict):
        return None
    if key in facts:
        return facts[key]
    tag = FACT_TAGS.get(key)
    if tag and tag in facts:
        return facts[tag]
    return None


def _to_list(fact: Any) -> list:
    """Normalize a fact slot (single dict, list of dicts, or None) to a list."""
    if fact is None:
        return []
    if isinstance(fact, list):
        return [f for f in fact if isinstance(f, dict)]
    if isinstance(fact, dict):
        return [fact]
    return []


def _context_key(key: str, fact: dict) -> tuple:
    """Compute the like-for-like pairing key for a fact."""
    unit = fact.get("units")
    if FACT_KINDS.get(key) == "INSTANT":
        return ("INSTANT", unit)
    dk = duration_kind(fact)
    if dk == "QUARTERLY":
        fp = _fp(fact)
    elif dk == "YTD":
        fp = _ytd_horizon(fact)
    else:
        fp = None
    return ("DURATION", unit, dk, fp)


def _single_pair_reason(key: str, fact_a: dict, fact_b: dict) -> str | None:
    """Return a reason two single facts cannot be compared, else None."""
    unit_a = fact_a.get("units")
    unit_b = fact_b.get("units")
    if unit_a and unit_b and unit_a != unit_b:
        return f"unit_mismatch {unit_a} vs {unit_b}"
    if FACT_KINDS.get(key) == "DURATION":
        ka = duration_kind(fact_a)
        kb = duration_kind(fact_b)
        if ka is None or kb is None or ka == "INSTANT" or kb == "INSTANT":
            return f"duration_context_unavailable ({ka} vs {kb})"
        if ka != kb:
            return f"duration_context_mismatch {ka} vs {kb}"
        if ka == "QUARTERLY":
            fpa = _fp(fact_a)
            fpb = _fp(fact_b)
            if fpa and fpb and fpa != fpb:
                return f"fiscal_period_mismatch {fpa} vs {fpb}"
        if ka == "YTD":
            # YTD facts accumulate over different horizons (Q2 vs Q3, 6M vs 9M).
            # Same fiscal period or a within-tolerance span is comparable; a
            # differing horizon is NOT and must fail closed.
            ha = _ytd_horizon(fact_a)
            hb = _ytd_horizon(fact_b)
            if ha is not None and hb is not None and ha != hb:
                return f"ytd_horizon_mismatch {ha} vs {hb}"
    return None


def _pair_by_context(key: str, list_a: list, list_b: list):
    """Pair facts by equivalent context; return (pairs, ambiguous, unmatched).

    Rows sharing the same context (e.g. 10-K vs 10-K/A amendments) are collapsed
    to the latest-filed row on each side before pairing. Distinct contexts that
    both appear on both sides (e.g. a QTD and a YTD row) produce more than one
    equally valid pairing and are reported as ambiguous.
    """
    a_map: dict = {}
    b_map: dict = {}
    for f in list_a:
        a_map.setdefault(_context_key(key, f), []).append(f)
    for f in list_b:
        b_map.setdefault(_context_key(key, f), []).append(f)

    pairs = []
    ambiguous = []
    unmatched = []
    for ck in sorted(set(a_map) | set(b_map), key=str):
        fa = a_map.get(ck, [])
        fb = b_map.get(ck, [])
        if not fa or not fb:
            unmatched.append(ck)
            continue
        # Collapse same-context amendments to the latest-filed row.
        fa_one = max(fa, key=lambda f: str(f.get("filed") or ""))
        fb_one = max(fb, key=lambda f: str(f.get("filed") or ""))
        pairs.append((fa_one, fb_one))

    if len(pairs) > 1:
        # More than one equally valid context pairing remains.
        ambiguous = sorted(set(a_map) & set(b_map), key=str)
        pairs = []
    return pairs, ambiguous, unmatched


def compare_filing_facts(facts_a: dict, facts_b: dict) -> dict:
    """Compare two filing fact sets with like-for-like context enforcement.

    Each tag may carry a single fact dict or a list of candidate context dicts
    (e.g. a QTD and a YTD row sharing the same end date). Candidate contexts are
    preserved and paired by equivalent context; when no unique like-for-like
    pair can be established the result is COMPARISON_UNAVAILABLE.
    """
    out: dict = {
        "comparisons": {},
        "comparison_status": COMPARISON_OK,
        "unavailable_keys": [],
        "notes": [],
    }

    for key in FACT_TAGS:
        list_a = _to_list(_select_by_key(facts_a, key))
        list_b = _to_list(_select_by_key(facts_b, key))
        entry: dict[str, Any] = {
            "key": key,
            "tag": FACT_TAGS[key],
            "a": None,
            "b": None,
            "comparison_status": COMPARISON_OK,
            "reason": None,
            "delta": None,
            "delta_pct": None,
            "material": None,
        }

        if not list_a and not list_b:
            # Absent from both periods: not a comparison failure.
            entry["comparison_status"] = COMPARISON_NOT_APPLICABLE
            entry["reason"] = "not_present_either_period"
            out["comparisons"][key] = entry
            continue

        if not list_a or not list_b:
            entry["comparison_status"] = COMPARISON_UNAVAILABLE
            entry["reason"] = "missing_fact"
            out["unavailable_keys"].append(key)
            out["comparisons"][key] = entry
            continue

        # Resolve exactly one like-for-like pair.
        fact_a: dict | None = None
        fact_b: dict | None = None
        reason: str | None = None
        if len(list_a) == 1 and len(list_b) == 1:
            reason = _single_pair_reason(key, list_a[0], list_b[0])
            if reason is None:
                fact_a, fact_b = list_a[0], list_b[0]
        else:
            pairs, ambiguous, unmatched = _pair_by_context(key, list_a, list_b)
            if ambiguous:
                reason = "ambiguous_context"
            elif unmatched:
                reason = "no_like_for_like_pair"
            elif len(pairs) == 1:
                fact_a, fact_b = pairs[0]
            elif len(pairs) > 1:
                # Multiple equivalent-context rows (e.g. refiled/amended rows):
                # select the latest filed on each side deterministically.
                fact_a = max((p[0] for p in pairs), key=lambda f: str(f.get("filed") or ""))
                fact_b = max((p[1] for p in pairs), key=lambda f: str(f.get("filed") or ""))
            else:
                reason = "no_like_for_like_pair"

        if reason is not None:
            entry["comparison_status"] = COMPARISON_UNAVAILABLE
            entry["reason"] = reason
            out["unavailable_keys"].append(key)
            out["comparisons"][key] = entry
            continue

        entry["a"] = _numeric(fact_a)
        entry["b"] = _numeric(fact_b)
        a = entry["a"]
        b = entry["b"]
        if a is None or b is None:
            entry["comparison_status"] = COMPARISON_UNAVAILABLE
            entry["reason"] = "non_numeric_value"
            out["unavailable_keys"].append(key)
            out["comparisons"][key] = entry
            continue

        delta = round(b - a, 6)
        entry["delta"] = delta
        if a != 0:
            entry["delta_pct"] = round((delta / abs(a)) * 100.0, 4)
        else:
            entry["delta_pct"] = None
        threshold = MATERIALITY_THRESHOLDS.get(key)
        if threshold is not None and entry["delta_pct"] is not None:
            entry["material"] = abs(entry["delta_pct"]) >= threshold
        out["comparisons"][key] = entry

    if out["unavailable_keys"]:
        out["comparison_status"] = COMPARISON_UNAVAILABLE
        out["notes"].append(
            f"{len(out['unavailable_keys'])} keys unavailable for like-for-like comparison"
        )
    return out
