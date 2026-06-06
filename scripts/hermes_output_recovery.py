#!/usr/bin/env python3
"""hermes_output_recovery.py — BOUNDED lenient summary recovery for Hermes trade-reflection output.

Used ONLY when strict validation fails for MISSING summary. Recovers a usable summary from alternate
model-output shapes (different keys, or a coherent first paragraph) WITHOUT fabricating content or
lowering the quality bar: recovered summaries must be specific (mention the symbol/context), substantive
(>= min_chars), and non-evasive. Generic / "I cannot" / too-short → stay rejected.
"""
import json
import re

ALT_KEYS = ["summary", "trade_summary", "reflection_summary", "analysis_summary",
            "executive_summary", "rationale", "analysis"]
EVASIVE = ("i cannot", "i can't", "not enough information", "insufficient information",
           "unable to analyze", "unable to analyse", "no data", "cannot provide", "as an ai")
VALIDATOR_VERSION = "summary_recovery_v1"


def _is_specific(text, symbol):
    t = (text or "").strip()
    if len(t) < 80:
        return False, "too_short"
    low = t.lower()
    if any(e in low for e in EVASIVE):
        return False, "evasive_or_insufficient"
    # Must be trade-SPECIFIC, not boilerplate: require the symbol OR an outcome figure OR >=2 distinct
    # trade-context terms. A single bare word like "trade" is not enough (rejects generic filler).
    ctx = ("entry", "entered", "exit", "exited", "stop", "target", "pnl", "p&l", "r-multiple",
           "r multiple", "setup", "catalyst", "breakout", "pullback", "win", "loss", "gain",
           "profit", "return", "drawdown", "thesis", "resistance", "support")
    has_sym = bool(symbol) and re.search(r"\b" + re.escape(symbol) + r"\b", t, re.I)
    has_outcome = bool(re.search(r"[-+]?\d+(\.\d+)?\s*(%|r\b)|\b(gain|loss|profit|win|loser|winner)\b", low))
    ctx_count = sum(1 for c in ctx if c in low)
    if not (has_sym or has_outcome or ctx_count >= 2):
        return False, "generic_insufficient_trade_specificity"
    # not just bullets without substance
    stripped = re.sub(r"[\s\-\*•\d\.\)]", "", t)
    if len(stripped) < 50:
        return False, "bullets_no_substance"
    return True, None


def recover_summary_from_output(raw_output, *, symbol=None, min_chars=80):
    out = {"recovered": False, "summary": None, "source_key": None, "recovery_method": None,
           "confidence": "none", "rejection_reason": None, "validator_version": VALIDATOR_VERSION}

    obj = raw_output
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except Exception:
            obj = {"__rawtext__": raw_output}

    # 1. alternate keys in a JSON object
    if isinstance(obj, dict):
        for k in ALT_KEYS:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                ok, why = _is_specific(v, symbol)
                if ok:
                    out.update({"recovered": True, "summary": v.strip(), "source_key": k,
                                "recovery_method": "alt_key",
                                "confidence": "high" if k in ("summary", "trade_summary", "reflection_summary") else "medium"})
                    return out
                out["rejection_reason"] = f"{k}:{why}"
        # 2. first sufficiently-specific textual block among string values
        for k, v in obj.items():
            if k in ALT_KEYS or k == "__rawtext__":
                continue
            if isinstance(v, str) and len(v.strip()) >= min_chars:
                ok, why = _is_specific(v, symbol)
                if ok:
                    out.update({"recovered": True, "summary": v.strip(), "source_key": k,
                                "recovery_method": "first_text_block", "confidence": "low"})
                    return out
        rawtext = obj.get("__rawtext__")
    else:
        rawtext = raw_output if isinstance(raw_output, str) else None

    # 3. first coherent paragraph from raw text (only when JSON parse failed)
    if rawtext:
        para = next((p.strip() for p in re.split(r"\n\s*\n", rawtext) if len(p.strip()) >= min_chars), None)
        if para:
            ok, why = _is_specific(para, symbol)
            if ok:
                out.update({"recovered": True, "summary": para, "source_key": "__rawtext__",
                            "recovery_method": "raw_paragraph", "confidence": "low"})
                return out
            out["rejection_reason"] = out["rejection_reason"] or f"rawtext:{why}"

    out["rejection_reason"] = out["rejection_reason"] or "no_recoverable_summary"
    return out


if __name__ == "__main__":
    import sys
    print(json.dumps(recover_summary_from_output(json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}, symbol=sys.argv[2] if len(sys.argv) > 2 else None), indent=2))
