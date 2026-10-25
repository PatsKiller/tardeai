"""C1 company-facts quality rules: what counts as a catalyst, and a card's display name.

Pure functions over stored evidence plus one reviewed config
(``config/cio_company_facts_quality.json``). No provider, DB, broker or file write.

A catalyst is a DATED event. Ranking: the next scheduled upcoming event first
(earnings, ex-dividend, FDA/PDUFA, investor day, product launch, deal close, index
change, lockup expiry), then a recent material corporate event (8-K item, results,
guidance change, M&A ...). Price predictions/forecasts, "stocks to buy", listicles/SEO,
plain price moves and insider/holding trades are ``recent_news`` and never the catalyst.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

CONFIG_REL = Path("config/cio_company_facts_quality.json")
REPO = Path(__file__).resolve().parents[2]

UPCOMING = "UPCOMING_EVENT"
MATERIAL = "MATERIAL_EVENT"
NEWS = "NEWS"


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rules(path: Path | str | None = None) -> dict:
    return _load(str(path or REPO / CONFIG_REL))


def _rx(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in patterns]


@lru_cache(maxsize=8)
def _compiled(path: str) -> dict:
    c = _load(path)["catalyst"]
    alias = lambda block: {a.lower(): name for name, al in block.items() for a in al}  # noqa: E731
    return {
        "upcoming": alias(c["upcoming_event_types"]),
        "material": alias(c["material_event_types"]),
        "news": {t.lower() for t in c["news_only_types"]},
        "excluded": {k: _rx(v) for k, v in c["excluded_headline_patterns"].items()},
        "price_move": _rx(c["price_move_patterns"]),
        "material_kw": _rx(c["material_keyword_patterns"]),
        "publishers": {p.casefold() for p in c.get("excluded_publishers") or []},
        "generic": {t.casefold() for t in c.get("generic_name_tokens") or []},
    }


def _c(path=None) -> dict:
    return _compiled(str(path or REPO / CONFIG_REL))


def parse_when(value: Any) -> datetime | None:
    """Aware datetime from an ISO timestamp, or midnight UTC for a plain calendar date."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else None
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        d = date.fromisoformat(text)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc) if d.tzinfo else None


def publisher(fact: dict) -> str | None:
    feed = str(fact.get("feed") or "")
    if feed.startswith("google_news:"):
        return feed.split(":", 1)[1].strip() or None
    head = str(fact.get("headline") or "")
    _, sep, tail = head.rpartition(" - ")
    return tail.strip() if sep and 0 < len(tail.strip()) <= 40 else None


def source_label(fact: dict, path=None) -> str | None:
    """Human source for the card: the publisher, else the configured feed label, else the feed/source id."""
    labels = rules(path)["catalyst"].get("feed_labels") or {}
    feed = str(fact.get("feed") or "")
    if feed.startswith("google_news:"):
        return publisher(fact)
    for key in (feed, str(fact.get("source") or "")):
        if key and key in labels:
            return labels[key]
    return publisher(fact) or (feed or fact.get("source") or None)


def _mentions(headline: str, symbol: str, names: list[str], generic: set[str]) -> bool:
    if re.search(rf"(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9])", headline):
        return True  # ticker is case-sensitive: "Main" is not MAIN
    low = headline.casefold()
    for name in names:
        name = " ".join(str(name or "").split())
        if not name:
            continue
        if name.casefold() in low:
            return True
        first = re.split(r"[\s,]+", name)[0].strip(".").casefold()
        if len(first) >= 3 and first not in generic and re.search(rf"\b{re.escape(first)}", low):
            return True
    return False


def classify(fact: dict, *, symbol: str, names: list[str] | None = None, path=None) -> dict:
    """{class, event_type, reason}: UPCOMING_EVENT / MATERIAL_EVENT qualify as catalysts; NEWS never does."""
    c = _c(path)
    head = " ".join(str(fact.get("headline") or "").split())
    raw_type = str(fact.get("catalyst_type") or "").strip().lower()
    if fact.get("catalyst_class") == UPCOMING or fact.get("event_at"):
        etype = c["upcoming"].get(raw_type) or fact.get("event_type")
        if etype:
            return {"class": UPCOMING, "event_type": etype, "reason": None}
    if not head:
        return {"class": NEWS, "event_type": None, "reason": "no_headline"}
    pub = publisher(fact)
    if pub and pub.casefold() in c["publishers"]:
        return {"class": NEWS, "event_type": None, "reason": "excluded_publisher"}
    for reason, pats in c["excluded"].items():
        if any(p.search(head) for p in pats):
            return {"class": NEWS, "event_type": None, "reason": reason}
    material_kw = any(p.search(head) for p in c["material_kw"])
    if any(p.search(head) for p in c["price_move"]) and not material_kw:
        return {"class": NEWS, "event_type": None, "reason": "price_move"}
    if raw_type in c["news"] or not raw_type:
        return {"class": NEWS, "event_type": None, "reason": f"news_type:{raw_type or 'untyped'}"}
    etype = c["material"].get(raw_type)
    if etype and names and _is_fund(str(names[0]), rules(path)["display_name"]["fund_markers"]):
        # A fund has no 8-K/M&A/results corporate events; its news is commentary. Scheduled events still qualify.
        return {"class": NEWS, "event_type": None, "reason": "fund_commentary"}
    if not etype:
        return {"class": NEWS, "event_type": None, "reason": f"type_not_allowed:{raw_type}"}
    if not _mentions(head, symbol, list(names or []), c["generic"]):
        return {"class": NEWS, "event_type": None, "reason": "headline_does_not_name_subject"}
    return {"class": MATERIAL, "event_type": etype, "reason": None}


def scheduled_events(symbol: str, profile: dict | None, *, now: datetime, path=None) -> list[dict]:
    """Upcoming dated events already stored on the symbol profile (no provider call)."""
    cfg = rules(path)["catalyst"]
    p = profile or {}
    out = []
    when = parse_when(p.get("next_earnings_date"))
    observed = parse_when(p.get("updated_at"))
    if when is None:
        return out
    # A scheduled date read from a long-unrefreshed profile is not a current schedule.
    if observed is None or (now - observed).days > int(cfg["scheduled_source_max_age_days"]):
        return out
    if not (now.date() <= when.date() and (when - now).days <= int(cfg["upcoming_horizon_days"])):
        return out
    out.append({"source": "symbol_profiles", "feed": "symbol_profiles", "catalyst_type": "earnings",
                "catalyst_class": UPCOMING, "event_type": "earnings",
                "headline": f"{symbol} earnings report scheduled", "event_at": when.date().isoformat(),
                "observed_at": observed.isoformat(), "clock_kind": "scheduled_event_date",
                "producer_source": p.get("source"), "verification_basis": "STORED_PROFILE_SCHEDULE",
                "source_ref": "symbol_profiles.next_earnings_date"})
    return out


def fact_date(fact: dict) -> tuple[str | None, str]:
    """(YYYY-MM-DD, kind) from the source event: scheduled event date, else publication, else observation."""
    for key, kind in (("event_at", "event_date"), ("published_at", "published"), ("observed_at", "observed")):
        d = parse_when(fact.get(key))
        if d:
            return d.date().isoformat(), kind
    return None, "date_unknown"


# ---------------------------------------------------------------- display names

_ACRONYM = re.compile(r"^[A-Z0-9&.\-]+$")


def _strip_suffixes(name: str, suffixes: set[str]) -> str:
    text = " ".join(name.replace(",", " ").split())
    if text.casefold().startswith("the "):
        text = text[4:]
    tokens = text.split(" ")
    while len(tokens) > 1 and tokens[-1].casefold() in suffixes:
        tokens.pop()
    return " ".join(tokens).strip(" .,")


def _is_fund(name: str, markers: list[str]) -> bool:
    low = name.casefold()
    return any(re.search(rf"\b{re.escape(m)}\b", low) for m in markers)


def _title(name: str, keep_upper: set[str]) -> str:
    out = []
    for tok in name.split(" "):
        if tok.upper() in keep_upper or (len(tok) <= 3 and _ACRONYM.match(tok) and not re.search(r"[AEIOU]", tok)):
            out.append(tok.upper())
        else:
            out.append("-".join(part[:1].upper() + part[1:].lower() for part in tok.split("-")))
    return " ".join(out)


def _mostly_upper(name: str) -> bool:
    letters = [ch for ch in name if ch.isalpha()]
    return bool(letters) and sum(ch.isupper() for ch in letters) / len(letters) > 0.8 and len(letters) > 4


def _from_description(desc: str | None) -> str | None:
    """The registered name that opens a stored profile description ("Arista Networks, Inc. engages ...")."""
    m = re.match(r"^\s*((?:The )?[A-Z0-9][\w&.'\-]*(?:\s+[A-Z0-9&(][\w&.'\-()]*){0,6}?)"
                 r",?\s+(?:Inc\.|Inc\b|Incorporated|Corporation|Corp\.|Company|Ltd\.|Limited|plc|N\.V\.|PBC|Co\b|Holdings)",
                 str(desc or ""))
    return m.group(1).strip() if m else None


def display_name(symbol: str, legal_name: str | None, *, finviz_name: str | None = None,
                 description: str | None = None, path=None) -> dict:
    """{display_name, legal_name, display_name_source}. Never returns an ALL-CAPS registry string."""
    cfg = rules(path)["display_name"]
    suffixes = {s.casefold() for s in cfg["legal_suffixes"]}
    keep = {k.upper() for k in cfg["keep_upper_tokens"]}
    sym = str(symbol or "").upper()
    override = (cfg.get("overrides") or {}).get(sym)
    legal = " ".join(str(legal_name or "").split()) or None
    if override:
        return {"display_name": override, "legal_name": legal, "display_name_source": "config_override"}
    for raw, src in ((finviz_name, "finviz_enrichment.company"), (_from_description(description), "profile_description_name"),
                     (legal, "registered_name_normalized")):
        raw = " ".join(str(raw or "").split())
        if not raw:
            continue
        fund = _is_fund(raw, cfg["fund_markers"])
        name = raw if fund else _strip_suffixes(raw, suffixes)
        if not name:
            continue
        if _mostly_upper(name):
            if src != "registered_name_normalized":
                continue  # a mixed-case source is preferred; fall through to the next one
            name = _title(name, keep)
        return {"display_name": name, "legal_name": legal, "display_name_source": src}
    return {"display_name": None, "legal_name": legal, "display_name_source": None}
