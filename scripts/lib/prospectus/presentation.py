"""How a stored prospectus is PRESENTED — read-time and pure (polish of the approved design prospectus/v001, v001.1).

Operator 2026-10-26: "what are these F with the numbers all over the pages? … internal pointers. Do those really need
to be shown? Is there any way we can polish this any more?"

Nothing here changes what was written, cited or stored. ``present(doc)`` returns a ``presentation`` object that the
API attaches to the detail payload and the HTML / PDF / DOCX renderers read:

* ``footnotes`` — the report's internal fact ids (``F7``) renumbered 1..n in order of first use (verdict line, the
  sections in reading order, then the block texts); each entry keeps its fact id for auditability.
* ``display_name`` — the security's name: the recorded company name, else the name the profile description starts
  with, else the fund universe name, else the symbol (the header never reads "SCHD SCHD").
* ``is_fund`` and ``fund_structure`` — funds get a "Fund structure & holdings" block in place of ownership,
  estimates and the earnings call; fields the house does not hold are named once ("not in our data: …").
* ``coverage`` — only the sources relevant to a security report, grouped used / stale / failed / missing; internal
  plumbing domains (config/prospectus_presentation.json) stay in the JSON and are counted as hidden.

READ_ONLY_ADVISORY: presentation only (MBI_BEHAVIOR=0).
"""
from __future__ import annotations

from datetime import date
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from . import ROOT, SECTION_IDS

SCHEMA = "ProspectusPresentation@v1"
CONFIG_REL = "config/prospectus_presentation.json"

# One bracket group of citation ids: "[F7]", "[F7, F8]", "[^c1]". An id is accepted when it is a known citation /
# fact id or has the internal fact-id shape (F + digits); anything else ("[x]", "[link](url)") stays prose.
GROUP_RE = re.compile(r"\[\^?([A-Za-z][\w.:-]*(?:\s*[,;]\s*\^?[A-Za-z][\w.:-]*)*)\](?!\()")
FACT_ID_RE = re.compile(r"^F\d+$")
UNRELIABLE_RE = re.compile(
    r"(?:statistically\s+)?(?:not reliable|unreliable)(?:\s*\([^)]*\)|:\s*[^;.\n\]\[]+)?", re.IGNORECASE)


@lru_cache(maxsize=4)
def _config_cached(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def config(root: Path | None = None) -> dict:
    return _config_cached(str((root or ROOT) / CONFIG_REL))


@lru_cache(maxsize=4)
def _fund_names_cached(path: str) -> dict[str, str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = data.get("instruments") if isinstance(data, dict) else data
    out: dict[str, str] = {}
    for r in rows or []:
        if isinstance(r, dict) and r.get("symbol") and r.get("name"):
            out[str(r["symbol"]).upper()] = str(r["name"]).strip()
    return out


def fund_names(root: Path | None = None) -> dict[str, str]:
    rel = config(root).get("fund_names_source") or "config/etf_fund_universe.json"
    return _fund_names_cached(str((root or ROOT) / rel))


# ── prose ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def clean_prose(text: Any) -> str:
    """Render-side cleanup of model prose: dangling empty bullets, doubled spaces, space before punctuation, empty
    brackets left behind. Newlines (paragraphs, lists) are kept."""
    lines = []
    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        if re.match(r"^\s*([-*•]|\d{1,2}[.)])\s*$", raw):
            continue  # an empty bullet is never rendered
        lead = re.match(r"^\s*", raw).group(0)
        body = raw[len(lead):]
        body = re.sub(r"[ \t ]{2,}", " ", body)
        body = re.sub(r"\s+\[\s*\]|\(\s*\)", "", body)
        body = re.sub(r"\s+([,.;:!?])(?=\s|$)", r"\1", body)
        lines.append((lead if re.match(r"^([-*•]|\d{1,2}[.)])\s", body) else "") + body.rstrip())
    out = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def split_ids(group: str) -> list[str]:
    return [i.strip().lstrip("^") for i in re.split(r"[,;]", group) if i.strip()]


def iter_groups(text: str, known: set[str] | None = None) -> Iterable[tuple[re.Match, list[str]]]:
    """Each citation bracket group in ``text`` with its ids (only groups whose every id is a citation)."""
    for m in GROUP_RE.finditer(str(text or "")):
        ids = split_ids(m.group(1))
        if ids and all(FACT_ID_RE.match(i) or (known is not None and i in known) for i in ids):
            yield m, ids


# ── footnotes ──────────────────────────────────────────────────────────────────────────────────────────────────────

def ordered_sections(doc: dict) -> list[dict]:
    """Sections in contract order (unknown ids after), empty bodies dropped, position_and_plan only for holdings."""
    secs = [s for s in doc.get("sections") or [] if isinstance(s, dict) and str(s.get("body_md") or "").strip()]
    if doc.get("scope") == "watch":
        secs = [s for s in secs if s.get("id") != "position_and_plan"]

    def rank(s: dict) -> int:
        return SECTION_IDS.index(s["id"]) if s.get("id") in SECTION_IDS else len(SECTION_IDS)

    return [s for _, s in sorted(enumerate(secs), key=lambda p: (rank(p[1]), p[0]))]


def _walk_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


#: Blocks that render before the narrative sections (the page puts "My history" right after the verdict tiles).
LEADING_BLOCKS = ("my_history",)


def citation_texts(doc: dict) -> list[str]:
    """Texts in reading order: verdict line, the leading blocks, the sections, then every other block string."""
    blocks = doc.get("blocks") if isinstance(doc.get("blocks"), dict) else {}
    lead = [t for k in LEADING_BLOCKS for t in _walk_strings(blocks.get(k))]
    rest = [t for k, v in blocks.items() if k not in LEADING_BLOCKS for t in _walk_strings(v)]
    return [str(doc.get("verdict_line") or "")] + lead + [str(s.get("body_md") or "") for s in ordered_sections(doc)] + rest


def _known(doc: dict) -> dict[str, dict]:
    known: dict[str, dict] = {}
    for f in doc.get("facts") or []:
        if isinstance(f, dict) and f.get("id"):
            known[str(f["id"])] = f
    for s in doc.get("sections") or []:
        for c in (s or {}).get("citations") or []:
            if isinstance(c, dict) and c.get("id"):
                known[str(c["id"])] = {**known.get(str(c["id"]), {}), **{k: v for k, v in c.items() if v not in (None, "")}}
    return known


def _value_text(f: dict) -> str:
    if "value" in f and f["value"] is not None:
        v = f["value"]
        s = f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)
        return s + (f" {f['unit']}" if f.get("unit") and f["unit"] not in ("%",) else ("%" if f.get("unit") == "%" else ""))
    t = str(f.get("text") or "").strip()
    return t if len(t) <= 140 else t[:137].rstrip() + "…"


def footnotes(doc: dict) -> list[dict]:
    """[{n, id, label, source, as_of, url, value}] — 1..n in order of first use."""
    known = _known(doc)
    order: list[str] = []
    seen: set[str] = set()
    for text in citation_texts(doc):
        for _, ids in iter_groups(text, set(known)):
            for i in ids:
                if i not in seen:
                    seen.add(i)
                    order.append(i)
    out = []
    for n, fid in enumerate(order, start=1):
        f = known.get(fid) or {}
        out.append({"n": n, "id": fid, "label": str(f.get("label") or "Source not recorded"),
                    "source": str(f.get("source") or ""), "as_of": f.get("as_of"), "url": f.get("url"),
                    "value": _value_text(f) if f else ""})
    return out


def numbers(notes: list[dict]) -> dict[str, int]:
    return {e["id"]: e["n"] for e in notes}


def section_notes(doc: dict, notes: list[dict]) -> dict[str, list[int]]:
    """Per section id: the footnote numbers it uses, ascending."""
    num = numbers(notes)
    out: dict[str, list[int]] = {}
    for s in ordered_sections(doc):
        ns = sorted({num[i] for _, ids in iter_groups(s.get("body_md") or "", set(num)) for i in ids if i in num})
        out[str(s.get("id"))] = ns
    return out


def strip_citations(text: Any) -> str:
    """Plain text with every citation group removed (for places that cannot show a superscript)."""
    s = GROUP_RE.sub(lambda m: "" if all(FACT_ID_RE.match(i) for i in split_ids(m.group(1))) else m.group(0), str(text or ""))
    return clean_prose(s)


# ── name ───────────────────────────────────────────────────────────────────────────────────────────────────────────

_NAME_END = re.compile(r"\s(?:provides|is|are|was|operates|engages|designs|develops|offers|manufactures|focuses|through|"
                       r"together|invests|seeks|tracks|aims|holds|owns)\b|,|\(", re.IGNORECASE)
_NAME_LOWER_OK = {"of", "and", "&", "the", "de", "for", "in", "on", "plc", "inc", "inc.", "co", "co.", "ltd", "ltd."}
_NAME_BAD_FIRST = {"the", "this", "that", "it", "a", "an", "our", "its", "to", "in", "for", "under", "as", "with",
                   "we", "founded", "based", "headquartered", "since", "through"}


def name_from_description(desc: Any) -> str | None:
    """The proper name a profile description starts with ("Broadcom Inc. designs …" → "Broadcom Inc"), or None."""
    s = str(desc or "").strip()
    if not s:
        return None
    m = _NAME_END.search(s)
    head = (s[: m.start()] if m else "").strip().rstrip(".").strip()
    words = head.split()
    if not words or len(words) > 8 or words[0].lower() in _NAME_BAD_FIRST:
        return None
    if not all(w[:1].isupper() or w[:1].isdigit() or w.lower() in _NAME_LOWER_OK for w in words):
        return None
    return head


def display_name(doc: dict, root: Path | None = None) -> str:
    """Recorded name → profile-description name → fund universe name → symbol."""
    sym = str(doc.get("symbol") or "").upper()
    name = str(doc.get("name") or "").strip()
    if name and name.upper() != sym:
        return name
    for f in doc.get("facts") or []:
        if isinstance(f, dict) and re.match(r"^(Business description|Company description)", str(f.get("label") or ""), re.I):
            got = name_from_description(f.get("text") or f.get("value"))
            if got and got.upper() != sym:
                return got
    return fund_names(root).get(sym) or sym


def index_name(symbol: str, name: Any, root: Path | None = None) -> str:
    """The list row's name: the recorded name, else the fund universe name, else the symbol."""
    sym = str(symbol or "").upper()
    n = str(name or "").strip()
    if n and n.upper() != sym:
        return n
    return fund_names(root).get(sym) or sym


# ── funds ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def is_fund(doc: dict) -> bool:
    b = doc.get("blocks") or {}
    fp = b.get("fund_profile")
    if isinstance(fp, dict) and fp and not fp.get("not_applicable"):
        return True
    return bool(b.get("fund_lookthrough"))


def _f(v: Any) -> float | None:
    try:
        return None if v is None or v == "" or isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return None


def _pct(v: float | None, digits: int = 2, signed: bool = False) -> str:
    return "" if v is None else f"{v:+.{digits}f}%" if signed else f"{v:.{digits}f}%"


def _usd(v: float | None, digits: int = 2) -> str:
    if v is None:
        return ""
    if abs(v) >= 1e9:
        return f"${v / 1e9:,.1f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:,.1f}M"
    return f"${v:,.{digits}f}"


def _day(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def distribution_growth_3y(history: list[dict]) -> float | None:
    """Trailing-12-month distributions now vs three years earlier, % change; None unless both windows are covered."""
    rows = sorted(((d, _f(h.get("amount"))) for h in history or [] if isinstance(h, dict)
                   for d in [_day(h.get("ex_date"))] if d is not None and _f(h.get("amount")) is not None))
    if len(rows) < 2:
        return None
    last = rows[-1][0]
    then = date(last.year - 3, last.month, min(last.day, 28))
    if rows[0][0] > date(then.year - 1, then.month, then.day):
        return None  # history does not reach back a full trailing year before the 3-year mark
    now_sum = sum(a for d, a in rows if (last - d).days < 365)
    then_sum = sum(a for d, a in rows if 0 <= (then - d).days < 365)
    if not then_sum:
        return None
    return (now_sum / then_sum - 1.0) * 100.0


def _holdings(fp: dict, lt: dict) -> list[dict]:
    rows = []
    for h in (lt.get("top_holdings") or fp.get("top_holdings") or []):
        if not isinstance(h, dict):
            continue
        w = _f(next((h.get(k) for k in ("pct", "weight_pct", "weight") if h.get(k) is not None), None))
        sym = str(h.get("ticker") or h.get("symbol") or "").upper() or None
        name = str(h.get("name") or sym or "").strip()
        if name:
            rows.append({"symbol": sym, "name": name, "weight_pct": w})
    rows.sort(key=lambda r: -(r["weight_pct"] or 0))
    return rows[:10]


def _weights(d: Any) -> list[dict]:
    if isinstance(d, dict):
        items = [(k, _f(v)) for k, v in d.items()]
    elif isinstance(d, list):
        items = [(str(r.get("name") or r.get("sector") or r.get("country") or ""), _f(r.get("pct") or r.get("weight_pct")))
                 for r in d if isinstance(r, dict)]
    else:
        items = []
    return [{"name": k, "weight_pct": v} for k, v in sorted(items, key=lambda kv: -(kv[1] or 0)) if k and v is not None]


def fund_structure(doc: dict) -> dict | None:
    """The "Fund structure & holdings" block for funds (None for stocks). Every row reads an existing block field;
    a field the house does not hold is named once in ``missing`` (rendered "not in our data: …")."""
    if not is_fund(doc):
        return None
    b = doc.get("blocks") or {}
    fp = b.get("fund_profile") if isinstance(b.get("fund_profile"), dict) else {}
    lt = b.get("fund_lookthrough") if isinstance(b.get("fund_lookthrough"), dict) else {}
    cites = fp.get("facts") if isinstance(fp.get("facts"), dict) else {}
    rows: list[dict] = []
    missing: list[str] = []

    def add(group: str, label: str, value: str, *fields: str) -> None:
        if value:
            rows.append({"group": group, "label": label, "value": value,
                         "cites": [cites[f] for f in fields if cites.get(f)]})
        else:
            missing.append(label)

    first = lambda *ks: next((fp.get(k) for k in ks if fp.get(k) not in (None, "")), None)  # noqa: E731
    # Identity
    add("identity", "Index tracked", str(first("index_tracked", "index", "benchmark_index") or ""))
    add("identity", "Issuer", str(first("issuer", "fund_family", "sponsor") or ""))
    add("identity", "Inception", str(first("inception_date", "inception") or "")[:10])
    add("identity", "Expense ratio", _pct(_f(fp.get("expense_ratio_pct"))), "expense_ratio_pct")
    add("identity", "Assets under management", _usd(_f(first("aum_usd", "total_assets_usd"))), "aum_usd")
    if fp.get("category"):
        peers = ", ".join(str(p) for p in fp.get("peers") or [])
        add("identity", "Category · peers", f"{fp['category']}" + (f" · {peers}" if peers else ""), "category")
    # Holdings
    top = _holdings(fp, lt)
    count = _f(first("holdings_count", "num_holdings")) or _f(lt.get("holdings_count"))
    add("holdings", "Number of holdings", f"{int(count):,}" if count else "", "holdings_count")
    weights = [h["weight_pct"] for h in top if h["weight_pct"] is not None]
    if top:
        conc = sum(weights) if weights else None
        add("holdings", f"Top {len(top)} concentration", _pct(conc, 1) if conc is not None else "")
    else:
        missing.append("Top 10 holdings")
    sectors = _weights(lt.get("sector_weights") or fp.get("sector_weights"))
    countries = _weights(lt.get("country_weights") or fp.get("country_weights"))
    if sectors:
        add("holdings", "Largest sector", f"{sectors[0]['name']} {_pct(sectors[0]['weight_pct'], 1)}")
    else:
        missing.append("Sector weights")
    if not countries:
        missing.append("Country weights")
    # Distribution
    yld, ttm = _f(fp.get("dividend_yield_pct")), _f(fp.get("ttm_distribution"))
    add("distribution", "Distribution yield · TTM",
        " · ".join(x for x in (_pct(yld), (f"{_usd(ttm, 3)}/share" if ttm is not None else "")) if x),
        "dividend_yield_pct", "ttm_distribution")
    last = _f(fp.get("last_distribution"))
    add("distribution", "Last distribution · cadence",
        " · ".join(x for x in ((f"{_usd(last, 3)} on {fp.get('last_distribution_date')}" if last is not None and fp.get("last_distribution_date")
                                else _usd(last, 3)), str(fp.get("distribution_cadence") or "")) if x),
        "last_distribution")
    g3 = _f(fp.get("distribution_growth_3y_pct"))
    if g3 is None:
        g3 = distribution_growth_3y(fp.get("dividend_history") or [])
    add("distribution", "Distribution growth · 3 years", _pct(g3, 1, signed=True))
    # Liquidity
    adv = _f(first("avg_daily_volume", "avg_volume_3m", "avg_volume"))
    add("liquidity", "Average daily volume", f"{adv:,.0f} shares" if adv is not None else "")
    add("liquidity", "Bid-ask spread", _pct(_f(first("bid_ask_spread_pct", "spread_pct")), 3))
    add("liquidity", "Premium / discount to NAV", _pct(_f(first("premium_discount_pct", "nav_premium_pct")), 2, signed=True))
    # Tracking (1Y): the fund vs its index (when recorded) and vs its category peers (house closes)
    rel = (b.get("relative_performance") or {}).get("returns") or []
    by = {str(r.get("name")): _f(r.get("1Y")) for r in rel if isinstance(r, dict)}
    mine = by.get(str(doc.get("symbol") or "").upper())
    idx_ret = _f(first("index_return_1y_pct"))
    if mine is not None and idx_ret is not None:
        add("tracking", "1Y vs its index", f"{mine - idx_ret:+.2f} pts (fund {_pct(mine, 1)}, index {_pct(idx_ret, 1)})")
    else:
        missing.append("Index tracking gap")
    peer_rets = [(p, by[p]) for p in (str(x).upper() for x in fp.get("peers") or []) if by.get(p) is not None]
    if mine is not None and peer_rets:
        vals = sorted(v for _, v in peer_rets)
        mid = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2
        add("tracking", "1Y vs category peers",
            f"{mine - mid:+.1f} pts vs peer median ({', '.join(f'{p} {_pct(v, 1)}' for p, v in peer_rets)})")
    else:
        missing.append("Peer return gap")
    # Overlap with the operator's book (look-through) — rendered when a source supplies it
    ov = fp.get("book_overlap") if isinstance(fp.get("book_overlap"), dict) else (
        lt.get("book_overlap") if isinstance(lt.get("book_overlap"), dict) else None)
    overlap = None
    if ov and _f(ov.get("pct")) is not None:
        direct = [str(x) for x in ov.get("direct") or []]
        via = [str(x) for x in ov.get("via_funds") or []]
        overlap = {"pct": _f(ov.get("pct")), "direct": direct, "via_funds": via, "basis": ov.get("basis")}
        add("overlap", "Overlap with your book", f"{_pct(overlap['pct'], 1)} of the top holdings you already own"
            + (f" — directly: {', '.join(direct)}" if direct else "") + (f"; via your funds: {', '.join(via)}" if via else ""))
    else:
        missing.append("Overlap with your book")
    return {"rows": rows, "top_holdings": top, "sectors": sectors[:10], "countries": countries[:10],
            "missing": missing, "as_of": lt.get("as_of") or fp.get("as_of")}


#: Blocks that do not apply to a fund (hidden, never "not available"): replaced by fund_structure.
FUND_HIDDEN_BLOCKS = ("estimates", "ownership_flows", "earnings_call", "fund_profile", "fund_lookthrough")


# ── coverage ───────────────────────────────────────────────────────────────────────────────────────────────────────

COVERAGE_GROUPS = (("used", "Used"), ("stale", "Stale"), ("failed", "Failed"), ("missing", "Missing"))


def coverage_label(domain: str, given: Any = None, root: Path | None = None) -> str:
    if given:
        return str(given)
    lab = (config(root).get("coverage_labels") or {}).get(domain)
    return lab or re.sub(r"[_-]+", " ", str(domain or "")).strip().capitalize()


def coverage(doc: dict, root: Path | None = None) -> dict:
    cfg = config(root)
    hide_domains = set(cfg.get("hidden_coverage_domains") or [])
    hide_status = set(cfg.get("hidden_coverage_statuses") or ["not_applicable"])
    groups: dict[str, list[dict]] = {g: [] for g, _ in COVERAGE_GROUPS}
    hidden = 0
    for d in (doc.get("source_coverage") or {}).get("domains") or []:
        if not isinstance(d, dict):
            continue
        st = str(d.get("status") or "").lower()
        if d.get("domain") in hide_domains or st in hide_status:
            hidden += 1
            continue
        g = st if st in ("used", "stale", "failed") else "missing"
        groups[g].append({"domain": d.get("domain"), "label": coverage_label(str(d.get("domain")), d.get("label"), root),
                          "status": st, "as_of": d.get("as_of"), "reason": d.get("reason")})
    return {"groups": groups, "counts": {g: len(v) for g, v in groups.items()}, "hidden": hidden,
            "key_gaps": list((doc.get("source_coverage") or {}).get("key_gaps") or [])}


# ── the whole presentation ─────────────────────────────────────────────────────────────────────────────────────────

def present(doc: dict, root: Path | None = None) -> dict:
    """The presentation object for one stored prospectus (never raises on a malformed document)."""
    try:
        notes = footnotes(doc)
        return {"schema": SCHEMA, "display_name": display_name(doc, root), "is_fund": is_fund(doc),
                "footnotes": notes, "section_footnotes": section_notes(doc, notes),
                "fund_structure": fund_structure(doc), "coverage": coverage(doc, root)}
    except Exception as exc:  # noqa: BLE001 - presentation never breaks reading the report
        return {"schema": SCHEMA, "error": type(exc).__name__, "display_name": str(doc.get("symbol") or ""),
                "is_fund": False, "footnotes": [], "section_footnotes": {}, "fund_structure": None, "coverage": None}
