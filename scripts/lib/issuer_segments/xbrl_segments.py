"""Pure parser: segment-axis revenue facts from one filing's XBRL instance (+ its label linkbase).

No network, no store, no model. Input is bytes; output is a plain dict. DSN-20261101 §2.1–§2.4:

* the period is the filing's own (``dei:DocumentPeriodEndDate``); among durations ending there that carry segment
  facts the shortest wins (the quarter in a 10-Q, the year in a 10-K — ``period_basis: latest_quarter``);
* the revenue concept is the first of ``revenue_concepts`` that appears WITH the segment axis in that period;
* a segment's figure is the context whose only dimension is the segment axis, else the one that adds only
  ``ConsolidationItemsAxis = OperatingSegmentsMember`` (IBM and HON tag it that way);
* children are the contexts that add exactly one drill-down axis (ProductOrService / Subsegments); they are returned
  for the mapping step to use only when an issuer-scoped rule asks for a drill-down;
* reconciling members (corporate, eliminations) are kept apart; the gap between the consolidated total and the
  operating segments is reported, never hidden.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

# Elements are matched by local name in any namespace ("{*}"): the parser needs no namespace URI and contacts no host.
XLINK = "{http://www.w3.org/1999/xlink}"
STD_LABEL_ROLE_SUFFIX = "/2003/role/label"  # the XBRL standard label role (".../2003/role/label")


class ParseError(ValueError):
    pass


def _qname_from_tag(tag: str, nsmap: dict[str, str]) -> str:
    if tag.startswith("{"):
        uri, local = tag[1:].split("}", 1)
        return f"{nsmap.get(uri, uri)}:{local}"
    return tag


def _ns_prefixes(xml_bytes: bytes) -> dict[str, str]:
    """namespace URI -> prefix, as declared in the document (first declaration wins)."""
    out: dict[str, str] = {}
    for prefix, uri in re.findall(rb'xmlns:([A-Za-z0-9_.-]+)="([^"]+)"', xml_bytes[:200_000]):
        out.setdefault(uri.decode(), prefix.decode())
    return out


def _d(s: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat((s or "").strip()[:10])
    except ValueError:
        return None


def parse_labels(lab_bytes: Optional[bytes]) -> dict[str, str]:
    """Element id (``spcx_SIMember``) -> standard label, with a trailing ``[Member]`` removed."""
    if not lab_bytes:
        return {}
    root = ET.fromstring(lab_bytes)
    out: dict[str, str] = {}
    for link in root.iterfind(".//{*}labelLink"):
        loc_to_el: dict[str, str] = {}
        for loc in link.iterfind(".//{*}loc"):
            href = loc.get(f"{XLINK}href") or ""
            loc_to_el[loc.get(f"{XLINK}label") or ""] = href.split("#", 1)[-1]
        lab_text: dict[str, str] = {}
        for lab in link.iterfind(".//{*}label"):
            if (lab.get(f"{XLINK}role") or STD_LABEL_ROLE_SUFFIX).endswith(STD_LABEL_ROLE_SUFFIX):
                lab_text[lab.get(f"{XLINK}label") or ""] = (lab.text or "").strip()
        for arc in link.iterfind(".//{*}labelArc"):
            el = loc_to_el.get(arc.get(f"{XLINK}from") or "")
            txt = lab_text.get(arc.get(f"{XLINK}to") or "")
            if el and txt and el not in out:
                out[el] = re.sub(r"\s*\[Member\]\s*$", "", txt)
    return out


def _label_for(member: str, labels: dict[str, str]) -> str:
    key = member.replace(":", "_", 1)
    if key in labels:
        return labels[key]
    local = member.split(":", 1)[-1]
    local = re.sub(r"(Segment)?Member$", "", local)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", local)


def parse_instance(xml_bytes: bytes, *, revenue_concepts: list[str], segment_axis: str,
                   drilldown_axes: list[str], consolidation_axis: str, operating_segments_member: str,
                   reconciling_members: list[str], labels: Optional[dict[str, str]] = None,
                   sum_tolerance: float = 0.01) -> dict[str, Any]:
    labels = labels or {}
    nsmap = _ns_prefixes(xml_bytes)
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ParseError(f"instance is not XML: {exc}") from None

    contexts: dict[str, dict[str, Any]] = {}
    for c in root.iterfind(".//{*}context"):
        per = c.find("{*}period")
        if per is None:
            continue
        start, end = per.find("{*}startDate"), per.find("{*}endDate")
        if start is None or end is None:
            continue  # instant contexts carry no revenue
        typed = any(True for _ in c.iterfind(".//{*}typedMember"))
        dims = {m.get("dimension"): (m.text or "").strip() for m in c.iterfind(".//{*}explicitMember")}
        contexts[c.get("id") or ""] = {"start": _d(start.text), "end": _d(end.text), "dims": dims, "typed": typed}

    period_end = None
    for el in root:
        if _qname_from_tag(el.tag, nsmap).endswith(":DocumentPeriodEndDate"):
            period_end = _d(el.text)
            break

    usd_units = {u.get("id") for u in root.iterfind(".//{*}unit")
                 if any((m.text or "").strip().lower().endswith(":usd") or (m.text or "").strip().upper() == "USD"
                        for m in u.iterfind(".//{*}measure"))}

    # concept -> list of (context, value)
    facts: dict[str, list[tuple[dict[str, Any], Decimal]]] = {c: [] for c in revenue_concepts}
    for el in root:
        q = _qname_from_tag(el.tag, nsmap)
        local = q.split(":", 1)[-1]
        if local not in facts or not q.startswith("us-gaap:"):
            continue
        if el.get("unitRef") not in usd_units:
            continue
        ctx = contexts.get(el.get("contextRef") or "")
        if not ctx or ctx["typed"] or el.text is None:
            continue
        try:
            facts[local].append((ctx, Decimal(el.text.strip())))
        except InvalidOperation:
            continue

    def _seg_facts(concept: str) -> list[tuple[dict[str, Any], Decimal]]:
        return [(c, v) for c, v in facts[concept] if segment_axis in c["dims"]]

    chosen = next((c for c in revenue_concepts if _seg_facts(c)), None)
    if chosen is None:
        return {"status": "no_segment_facts", "period_end": period_end.isoformat() if period_end else None}

    seg = _seg_facts(chosen)
    ends = sorted({c["end"] for c, _ in seg if c["end"]}, reverse=True)
    end = period_end if period_end in ends else (ends[0] if ends else None)
    durations = sorted({(c["end"] - c["start"]).days for c, _ in seg if c["end"] == end and c["start"]})
    if end is None or not durations:
        return {"status": "no_segment_facts", "period_end": period_end.isoformat() if period_end else None}
    dur = durations[0]

    def _in_period(c: dict[str, Any]) -> bool:
        return c["end"] == end and c["start"] is not None and (c["end"] - c["start"]).days == dur

    opseg = {consolidation_axis: operating_segments_member}

    def _value(dims_wanted: dict[str, str]) -> Optional[Decimal]:
        """Value for an exact dimension set, else that set + ConsolidationItems=OperatingSegments."""
        for want in (dims_wanted, {**dims_wanted, **opseg}):
            vals = {v for c, v in facts[chosen] if _in_period(c) and c["dims"] == want}
            if vals:
                if len(vals) > 1:
                    raise ParseError(f"conflicting values for {want}: {sorted(vals)}")
                return vals.pop()
        return None

    consolidated = _value({})
    members = sorted({c["dims"][segment_axis] for c, _ in seg if _in_period(c)})
    segments, reconciling = [], []
    for m in members:
        val = _value({segment_axis: m})
        if val is None:
            continue
        children = []
        for ax in drilldown_axes:
            kids = sorted({c["dims"][ax] for c, _ in facts[chosen]
                           if _in_period(c) and c["dims"].get(segment_axis) == m and ax in c["dims"]})
            for k in kids:
                kv = _value({segment_axis: m, ax: k})
                if kv is not None:
                    children.append({"member": k, "label": _label_for(k, labels), "axis": ax, "revenue_usd": int(kv)})
        row = {"member": m, "label": _label_for(m, labels), "revenue_usd": int(val), "children": children}
        (reconciling if m in reconciling_members else segments).append(row)

    seg_sum = sum(r["revenue_usd"] for r in segments)
    rec_sum = sum(r["revenue_usd"] for r in reconciling)
    total = int(consolidated) if consolidated is not None else None
    gap = (total - seg_sum - rec_sum) if total is not None else None
    reconciles = bool(total) and abs(total - seg_sum - rec_sum) <= sum_tolerance * total
    return {
        "status": "ok" if segments else "no_segment_facts",
        "concept": f"us-gaap:{chosen}",
        "period": {"start": (end.fromordinal(end.toordinal() - dur)).isoformat(), "end": end.isoformat(),
                   "days": dur, "kind": "Q" if dur < 200 else "FY"},
        "consolidated_usd": total,
        "segments": segments,
        "reconciling": reconciling,
        "unallocated_usd": gap,
        "reconciles": reconciles,
    }
