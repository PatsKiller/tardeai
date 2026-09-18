"""agent_number_grounding.py — did the agent's numbers come from what it was given?

WHY
---
Agent jobs (Maria, Steph, risk, tax, full chain) build their facts from the
Command Center first: position, prices, RSI/ATR/moving averages, strategy card,
stop, news, fundamentals, Hermes research. Then ONE model call writes the
analysis. Until 2026-09-13 nothing told the model to use only those facts, and
nothing checked the numbers in its answer against them. A price, target or
percentage the model remembered or invented was stored beside real ones, with
the same confidence.

WHAT
----
Two halves, both deterministic:

* the prompt rule (`cio_agent_contract.GROUNDING_RULE`, rule G0): state only
  numbers that appear in the supplied context, or simple arithmetic on them;
* this module: after the answer is parsed, every non-trivial number in the
  summary, narrative, evidence and next action is looked up in the text the
  model was actually sent. A number is SUPPORTED when it matches a supplied
  number within rounding (the precision the agent wrote) or 0.5 %, or as a
  percent or fraction of one. A percent change or difference also counts when
  it is between a supplied PRICE (a dollar figure on a line about price, close,
  last or current) and another supplied dollar figure, and only within the
  precision written: pairwise changes across every figure are so dense that an
  invented 27.3 % matched one by chance. Not checked: small bare integers (0-31: counts, days,
  list numbers), years, account names such as 401k, and the agent's own stated
  confidence.

VERDICT
-------
    no_numbers   nothing to check
    grounded     unsupported numbers below the thresholds (listed anyway)
    ungrounded   at least MIN_UNSUPPORTED numbers (default 3) AND at least
                 MAX_SHARE (default 0.5) of the checked numbers are unsupported.
                 Chosen from a dry run over 300 stored results: 2 / 0.25 flagged
                 119, 3 / 0.34 flagged 46, 3 / 0.5 flagged 10 (upper bounds).

MODES (env AGENT_NUMBER_GROUNDING_MODE)
---------------------------------------
    enforce (default)  an ungrounded answer is demoted: recommendation becomes
                       RESEARCH_MORE, confidence is capped below the 40 % gate
                       (rule G4), reason code UNGROUNDED_NUMBERS is added, the
                       summary names the unverified numbers, and the original
                       recommendation and confidence are kept in the report
    record             the report is stored with the result; nothing is changed
    off                no check

Pure: no I/O, no model call. Nothing here sizes, orders, stops or touches a
broker (MBI_BEHAVIOR = 0).
"""
from __future__ import annotations

import bisect
import os
import re
from typing import Any, Iterable, Optional

SCHEMA = "AgentNumberGrounding@v1"
MODE_ENV = "AGENT_NUMBER_GROUNDING_MODE"
MIN_UNSUPPORTED_ENV = "AGENT_NUMBER_GROUNDING_MIN_UNSUPPORTED"
MAX_SHARE_ENV = "AGENT_NUMBER_GROUNDING_MAX_SHARE"
UNGROUNDED_CODE = "UNGROUNDED_NUMBERS"
DEMOTED_RECOMMENDATION = "RESEARCH_MORE"
#: Below rule G4's 40 % confidence gate, so every reader treats it as a skip.
DEMOTED_CONFIDENCE_CAP = 0.39
REL_TOLERANCE = 0.005
#: Supplied dollar figures used to derive percent changes and differences.
_DERIVE_LIMIT = 40
#: Price anchors: the first two dollar figures on price/close lines (the latest prices).
#: Agents measure changes from the current price; more anchors let invented
#: percentages match a pair by chance (27.3% matched $35.40 vs a $27.80 low).
_ANCHOR_LIMIT = 2
_PRICE_LINE_RE = re.compile(r"\b(price|prices|close|closed|closing|last|current)\b", re.I)
#: Why enforce is the default: a dry run 2026-09-13 over 300 stored results, with
#: each answer checked against its stored input snapshot plus the static prompt
#: rules, flagged 3 at the default thresholds. The live prompt carries everything
#: in that snapshot and more (news, RAG, Hermes, peer notes), so 3/300 is an upper
#: bound on demotions. scripts/report_agent_number_grounding.py shows the live
#: rate; AGENT_NUMBER_GROUNDING_MODE=record flags without changing anything.
DEFAULT_MODE = "enforce"
#: Tokens that look like numbers with a k/b suffix but name account types.
_ACCOUNT_TOKENS = frozenset({"401k", "403b", "457b", "401K", "403B", "457B"})
_CONFIDENCE_WORDS = ("confidence", "conf ", "conf:", "conf=")

_SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9}
#: A minus sign counts as part of a code only when glued to a word or digit
#: ("gpt-5.4", "2026-09-13"). After a space or colon it is a sign: "SMA20: -26.84%"
#: must yield 26.84, or an agent correctly quoting it is flagged (dry run 2026-09-13).
_NUM_RE = re.compile(
    r"(?<![A-Za-z0-9_/.])(?<![A-Za-z0-9]-)"
    r"(?:(?P<dollar>\$)\s?)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<suffix>[kKmMbB](?![A-Za-z]))?"
    r"(?P<pct>\s?%)?"
    r"(?![A-Za-z0-9_/]|\.\d|-[A-Za-z])"
)


def extract_numbers(text: str) -> list[dict[str, Any]]:
    """Every number in ``text`` with its value, precision and unit markers."""
    out: list[dict[str, Any]] = []
    for m in _NUM_RE.finditer(str(text or "")):
        raw_num = m.group("num").replace(",", "")
        try:
            base = float(raw_num)
        except ValueError:
            continue
        suffix = (m.group("suffix") or "").lower()
        decimals = len(raw_num.split(".", 1)[1]) if "." in raw_num else 0
        mult = _SUFFIX.get(suffix, 1.0)
        if m.group(0).strip() in _ACCOUNT_TOKENS:
            continue
        out.append({
            "start": m.start(),
            "end": m.end(),
            "raw": m.group(0).strip(),
            "value": abs(base * mult),
            "decimals": decimals,
            "multiplier": mult,
            "is_dollar": bool(m.group("dollar")),
            "is_pct": bool(m.group("pct")),
            "has_suffix": bool(suffix),
        })
    return out


def _is_trivial(n: dict[str, Any]) -> bool:
    if n["is_dollar"] or n["is_pct"] or n["decimals"] or n["has_suffix"]:
        return False
    v = n["value"]
    return v <= 31 or 1900 <= v <= 2100


def supplied_values(text: str) -> tuple[list[float], list[float]]:
    """(direct, derived), each sorted.

    direct:  supplied numbers and their percent/fraction forms
    derived: percent changes and differences between supplied dollar figures
    """
    direct: set[float] = set()
    dollars: list[float] = []
    anchors: list[float] = []
    for line in str(text or "").splitlines():
        price_line = bool(_PRICE_LINE_RE.search(line))
        for n in extract_numbers(line):
            v = n["value"]
            direct.update((v, v * 100.0, v / 100.0))
            if not n["is_dollar"] or v <= 0:
                continue
            if v not in dollars and len(dollars) < _DERIVE_LIMIT:
                dollars.append(v)
            if price_line and v not in anchors and len(anchors) < _ANCHOR_LIMIT:
                anchors.append(v)
    derived: set[float] = set()
    for a in anchors:
        for b in dollars:
            if a != b:
                derived.update((abs(a - b), abs(a - b) / b * 100.0, abs(a - b) / a * 100.0))
    return sorted(direct), sorted(derived)


def _within(values: list[float], v: float, tol: float) -> bool:
    i = bisect.bisect_left(values, v - tol)
    return i < len(values) and values[i] <= v + tol


def _supported(n: dict[str, Any], supplied: tuple[list[float], list[float]]) -> bool:
    direct, derived = supplied
    v = n["value"]
    rounding = 0.5 * (10 ** -n["decimals"]) * n["multiplier"]
    if _within(direct, v, max(rounding, REL_TOLERANCE * v, 1e-9)):
        return True
    return _within(derived, v, max(rounding, 1e-9))


def _is_stated_confidence(text: str, n: dict[str, Any]) -> bool:
    before = str(text)[max(0, n["start"] - 24):n["start"]].lower()
    after = str(text)[n["end"]:n["end"] + 14].lower()
    return any(w in before for w in _CONFIDENCE_WORDS) or "confiden" in after


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def mode() -> str:
    m = str(os.environ.get(MODE_ENV, DEFAULT_MODE)).strip().lower()
    return m if m in ("enforce", "record", "off") else DEFAULT_MODE


def check_grounding(
    texts: Iterable[str],
    supplied_text: str,
    *,
    min_unsupported: Optional[int] = None,
    max_share: Optional[float] = None,
) -> dict[str, Any]:
    """Compare the numbers in ``texts`` with the numbers in ``supplied_text``."""
    # Maturity 2026-09-18: prior defaults (3 / 0.5) left 0/942 "ungrounded"
    # while many rows still listed unsupported tokens at ~14% share. Tighten so
    # real invented figures demote; soft_unsupported is still reported when
    # below the demotion bar.
    min_u = int(min_unsupported if min_unsupported is not None else _env_float(MIN_UNSUPPORTED_ENV, 2))
    share_cap = float(max_share if max_share is not None else _env_float(MAX_SHARE_ENV, 0.20))
    supplied = supplied_values(supplied_text)
    checked: list[str] = []
    unsupported: list[str] = []
    seen: set[str] = set()
    for t in texts:
        for n in extract_numbers(t):
            if _is_trivial(n) or n["raw"] in seen or _is_stated_confidence(t, n):
                continue
            seen.add(n["raw"])
            checked.append(n["raw"])
            if not _supported(n, supplied):
                unsupported.append(n["raw"])
    share = (len(unsupported) / len(checked)) if checked else 0.0
    if not checked:
        verdict = "no_numbers"
    elif len(unsupported) >= max(1, min_u) and share >= share_cap:
        verdict = "ungrounded"
    elif unsupported:
        verdict = "soft_unsupported"  # present but below demotion bar — report honesty
    else:
        verdict = "grounded"
    return {
        "schema": SCHEMA,
        "verdict": verdict,
        "checked": len(checked),
        "supported": len(checked) - len(unsupported),
        "unsupported": unsupported[:20],
        "unsupported_share": round(share, 3),
        "thresholds": {"min_unsupported": min_u, "max_share": share_cap},
        "supplied_chars": len(supplied_text or ""),
    }


def _answer_texts(parsed: dict[str, Any]) -> list[str]:
    narrative = "\n".join(
        line for line in str(parsed.get("full_narrative") or "").splitlines()
        if not line.strip().startswith(("Model:", "## "))
    )
    texts = [str(parsed.get("summary") or ""), narrative, str(parsed.get("next_action") or "")]
    for ev in parsed.get("evidence") or []:
        texts.append(str(ev.get("text") if isinstance(ev, dict) else ev))
    return texts


def apply_number_grounding(
    parsed: dict[str, Any],
    supplied_text: str,
    *,
    mode_override: Optional[str] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(result, report). In enforce mode an ungrounded result comes back demoted."""
    m = (mode_override or mode()).lower()
    if m == "off":
        return parsed, {"schema": SCHEMA, "mode": "off", "verdict": "not_checked"}
    if not str(supplied_text or "").strip():
        return parsed, {"schema": SCHEMA, "mode": m, "verdict": "not_checked",
                        "reason": "the prompt text was not available to check against"}
    report = check_grounding(_answer_texts(parsed), supplied_text)
    report["mode"] = m
    report["demoted"] = False
    # soft_unsupported is honesty-only (no demotion); ungrounded demotes in enforce.
    if report["verdict"] != "ungrounded" or m != "enforce":
        return parsed, report
    out = dict(parsed)
    report["original_recommendation"] = parsed.get("recommendation")
    report["original_confidence"] = parsed.get("confidence")
    listed = ", ".join(report["unsupported"][:5])
    out["recommendation"] = DEMOTED_RECOMMENDATION
    try:
        out["confidence"] = min(float(parsed.get("confidence") or 0.0), DEMOTED_CONFIDENCE_CAP)
    except (TypeError, ValueError):
        out["confidence"] = DEMOTED_CONFIDENCE_CAP
    codes = [c for c in (parsed.get("reason_codes") or []) if c != UNGROUNDED_CODE]
    out["reason_codes"] = codes + [UNGROUNDED_CODE]
    out["summary"] = (f"Unverified numbers, not in the supplied data: {listed}. "
                      + str(parsed.get("summary") or ""))[:500]
    doubt = str(parsed.get("data_i_doubt") or "").strip()
    note = f"numbers not found in the supplied context: {listed}"
    out["data_i_doubt"] = note if doubt in ("", "none") else f"{doubt}; {note}"
    report["demoted"] = True
    return out, report
