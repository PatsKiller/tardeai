"""Deterministic segment -> group mapping (DSN-20261101 §3.1, §3.4). Pure: config dict + parsed filing in, split out.

Rule order (first match wins): issuer-scoped rule (by CIK) -> standard us-gaap/srt member rule -> label keyword
pattern. A label that matches patterns of two different groups is ambiguous and never auto-mapped. Unmatched and
ambiguous lines are queued for the model-classified path (P3, a stub today) and their share falls back to the
issuer's profile sector with flag ``segment_unmapped_fallback``. Reconciling items (corporate, eliminations) and any
unallocated gap form the residual, which also goes to the profile sector (``residual: true``).

Output keys are ``share``/``revenue_usd``, never ``weight`` (a market-risk BEHAVIOR_FIELDS key).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAP_PATH = PROJECT_ROOT / "config" / "issuer_segment_map.json"
UNKNOWN_GROUP = "unknown"


def load_map(path: Optional[Path] = None) -> dict[str, Any]:
    return json.loads(Path(path or MAP_PATH).read_text(encoding="utf-8"))


def _cik10(cik: Any) -> str:
    return "".join(ch for ch in str(cik or "") if ch.isdigit()).zfill(10)


def _issuer_rule(cfg: dict[str, Any], cik: str, member: str) -> Optional[dict[str, Any]]:
    for r in cfg.get("issuer_rules") or []:
        if _cik10(r.get("cik")) == cik and r.get("member") == member:
            return r
    return None


def classify_line(cfg: dict[str, Any], cik: str, member: str, label: str) -> dict[str, Any]:
    """{status: mapped|ambiguous|unmapped, group, themes, rule_id, candidates}. Never guesses."""
    sectors = set(cfg.get("sector_keys") or [])
    themes_ok = set(cfg.get("theme_keys") or [])
    r = _issuer_rule(cfg, cik, member)
    if r and r.get("group"):
        if r["group"] not in sectors:
            raise ValueError(f"issuer rule {r.get('id')}: group {r['group']!r} is not a sector key")
        bad = [t for t in r.get("themes") or [] if t not in themes_ok]
        if bad:
            raise ValueError(f"issuer rule {r.get('id')}: unknown theme(s) {bad}")
        return {"status": "mapped", "group": r["group"], "themes": list(r.get("themes") or []),
                "rule_id": r["id"], "rule_kind": "issuer"}
    for s in cfg.get("standard_member_rules") or []:
        if s.get("member") == member:
            return {"status": "mapped", "group": s["group"], "themes": [], "rule_id": s["id"], "rule_kind": "standard"}
    hits = []
    for p in cfg.get("label_patterns") or []:
        if re.search(p["pattern"], label or "", flags=re.IGNORECASE):
            hits.append(p)
    groups = sorted({h["group"] for h in hits})
    if len(groups) == 1:
        return {"status": "mapped", "group": groups[0], "themes": [], "rule_id": hits[0]["id"], "rule_kind": "label"}
    if len(groups) > 1:
        return {"status": "ambiguous", "group": None, "themes": [], "rule_id": None, "candidates": groups}
    return {"status": "unmapped", "group": None, "themes": [], "rule_id": None}


def map_issuer(parsed: dict[str, Any], *, cik: Any, symbol: str, profile_group: Optional[str],
               cfg: dict[str, Any]) -> dict[str, Any]:
    """Per-issuer split: lines, residual, queue, sector ``groups`` and theme overlays, as shares of revenue."""
    ext = cfg.get("extraction") or {}
    tol = float(ext.get("sum_tolerance", 0.01))
    nd = int(ext.get("share_decimals", 4))
    cik = _cik10(cik)
    flags: list[str] = []
    if parsed.get("status") != "ok":
        return {"symbol": symbol, "cik": cik, "status": parsed.get("status") or "no_segment_facts",
                "flags": ["no_filing_split"], "groups": {}, "themes": {}, "lines": [], "queue": [], "residual": None}
    fallback = profile_group or UNKNOWN_GROUP
    if not profile_group:
        flags.append("no_profile_sector")

    # 1. lines (segments, or a segment's drill-down children when an issuer rule asks for it)
    lines: list[dict[str, Any]] = []
    for seg in parsed["segments"]:
        rule = _issuer_rule(cfg, cik, seg["member"])
        ax = (rule or {}).get("drilldown_axis")
        if ax:
            kids = [c for c in seg.get("children") or [] if c["axis"] == ax and c["revenue_usd"] != 0]
            ksum = sum(c["revenue_usd"] for c in kids)
            if kids and seg["revenue_usd"] and abs(ksum - seg["revenue_usd"]) <= tol * abs(seg["revenue_usd"]):
                for c in kids:
                    lines.append({"member": c["member"], "label": c["label"], "parent": seg["member"],
                                  "revenue_usd": c["revenue_usd"], "drilldown_rule": rule["id"]})
                continue
            flags.append(f"drilldown_not_reconciled:{seg['member']}")
        lines.append({"member": seg["member"], "label": seg["label"], "parent": None, "revenue_usd": seg["revenue_usd"]})

    # 2. denominator (§3.4): consolidated revenue, or the positive reportable segments when eliminations are negative
    pos = sum(r["revenue_usd"] for r in parsed["segments"] if r["revenue_usd"] > 0)
    total = parsed.get("consolidated_usd")
    if not total or total < pos:
        denom = pos
        flags.append("denominator_positive_segments")
    else:
        denom = total
    if not denom:
        return {"symbol": symbol, "cik": cik, "status": "refused", "flags": flags + ["zero_revenue"],
                "groups": {}, "themes": {}, "lines": [], "queue": [], "residual": None}
    if not parsed.get("reconciles"):
        flags.append("did_not_reconcile")

    groups: dict[str, float] = {}
    themes: dict[str, float] = {}
    out_lines, queue = [], []
    lines_usd = 0
    for ln in lines:
        c = classify_line(cfg, cik, ln["member"], ln["label"])
        share = ln["revenue_usd"] / denom
        row = {**ln, "share": round(share, nd), "status": c["status"], "group": c["group"],
               "themes": c["themes"], "rule_id": c["rule_id"], "basis": "deterministic" if c["status"] == "mapped" else None}
        if c["status"] == "mapped":
            groups[c["group"]] = groups.get(c["group"], 0.0) + share
            for t in c["themes"]:
                themes[t] = themes.get(t, 0.0) + share
            lines_usd += ln["revenue_usd"]
        else:
            row.update({"group": fallback, "basis": "profile_fallback", "flag": "segment_unmapped_fallback",
                        "candidates": c.get("candidates")})
            groups[fallback] = groups.get(fallback, 0.0) + share
            queue.append({"member": ln["member"], "label": ln["label"], "reason": c["status"],
                          "revenue_usd": ln["revenue_usd"], "candidates": c.get("candidates")})
            lines_usd += ln["revenue_usd"]
        out_lines.append(row)
    if queue:
        flags.append("segment_unmapped_fallback")

    residual_usd = denom - lines_usd
    residual = {"revenue_usd": residual_usd, "share": round(residual_usd / denom, nd), "group": fallback,
                "residual": True, "members": [r["member"] for r in parsed.get("reconciling") or []],
                "unallocated_usd": parsed.get("unallocated_usd")}
    if residual_usd:
        groups[fallback] = groups.get(fallback, 0.0) + residual_usd / denom

    sector_sum = sum(groups.values())
    if abs(sector_sum - 1.0) > tol:
        flags.append("sector_sum_out_of_tolerance")
    return {
        "symbol": symbol, "cik": cik, "status": "ok", "flags": flags,
        "concept": parsed.get("concept"), "period": parsed.get("period"), "consolidated_usd": total,
        "denominator_usd": denom,
        "groups": {g: round(v, nd) for g, v in sorted(groups.items(), key=lambda kv: -kv[1])},
        "themes": {t: round(v, nd) for t, v in sorted(themes.items())},
        "lines": out_lines, "queue": queue, "residual": residual,
    }
