"""Mandatory cross-checks for the site audit (SPEC_SITE_AUDIT_AUTOREMEDIATE_LOOP_20261104 piece 5).

Four checks that the crawl cannot make on its own, because each needs two facts compared rather than one screen read:

  now_price            the "now" a page shows against the quote the server says it has (the 2026-11-04 Risk case: a card
                       said CONFIRMED with "now —" while the server held 132.99 @14:00:04Z)
  verdict_vs_price     a verdict against the price it is a verdict about (CONFIRMED while the price is below the
                       invalidation level is a contradiction, not a stale display)
  same_figure_everywhere  one figure rendered on two surfaces must agree (day P&L in the header and on the account row)
  card_completeness    §6 of the spec: a card in a TOP list missing a technical, or without a CIO thesis carrying an
                       as_of, is **P1** — the same defect class as FQ-114 from the operator's screen. Everywhere else a
                       missing field is P2 *only if the card gives a reason for it*; an unexplained gap is the defect.

The point of this module is that the deep crawl and these checks agree on what "complete" means: `REQUIRED_TECHNICAL`
and `top_list()` are the single definition both use. Pure: dicts in, findings out; no I/O, no clock read unless passed.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

SCHEMA = "SiteAuditCrossChecks@v1"
#: Dark-contract declaration: a library with no production importer yet — the site-audit capture (piece 4) is the
#: intended caller. Until it lands, the module is exercised by its own CI gate, not by a scheduled entrypoint.
SCHEDULED_ENTRYPOINT = (
    "NONE — library, unscheduled by design; its caller is the site-audit capture lane (spec piece 4). "
    "Scheduling is operator-only (AGENTS.md §17)."
)

#: The technical fields a symbol card must show. Kept here, not in the crawler, so both agree.
REQUIRED_TECHNICAL = (
    "price", "rsi", "macd", "sma20", "sma50", "sma200",
    "support1", "support2", "resistance1", "resistance2", "trend",
)

#: Lists whose cards are TOP lists: their gaps are P1 per §6.
TOP_LISTS = frozenset({
    "best_opportunities", "home_top5", "watch_top_ideas", "reentry_candidates", "cio_top_opportunities",
})

_PM_TOLERANCE_PCT = 0.05   # two surfaces may differ by a rounding cent, not by a figure


def _finding(check: str, symbol: Optional[str], severity: str, what: str, why: str, evidence: dict) -> dict:
    if severity not in ("P1", "P2", "P3"):
        raise ValueError(f"severity must be P1/P2/P3, got {severity!r}")
    return {"check": check, "symbol": symbol, "severity": severity, "what": what, "why": why, "evidence": evidence}


def top_list(list_kind: Optional[str]) -> bool:
    """Labels and ids both count: "Best Opportunities" and "best_opportunities" are the same list."""
    slug = str(list_kind or "").strip().lower().replace(" ", "_").replace("-", "_")
    return slug in TOP_LISTS


def card_completeness(card: dict[str, Any], *, list_kind: Optional[str] = None) -> list[dict]:
    """§6: technicals, and a CIO thesis or stance carrying an as_of.

    A TOP-list card is P1 for either gap. Elsewhere the gap is P2 *when the card explains it* and P3 when it does not —
    an unexplained hole is worse than a stated one, because the operator cannot tell it from a bug.
    """
    sym = str(card.get("symbol") or "")
    top = top_list(list_kind)
    out: list[dict] = []
    missing = [f for f in REQUIRED_TECHNICAL if card.get(f) in (None, "", [])]
    if missing:
        sev = "P1" if top else ("P2" if card.get("missing_reason") else "P3")
        out.append(_finding(
            "card_completeness", sym, sev,
            f"{sym or 'card'} is missing {len(missing)} technical field(s): {', '.join(missing)}",
            "A top-list card is P1 without its technicals (§6)." if top else
            ("The card states why the field is missing." if card.get("missing_reason") else
             "The card does not say why the field is missing."),
            {"missing": missing, "list_kind": list_kind, "reason": card.get("missing_reason")}))
    thesis = card.get("cio_thesis") if isinstance(card.get("cio_thesis"), dict) else {}
    stance = str(card.get("cio_stance") or thesis.get("stance") or "").strip()
    as_of = str(card.get("cio_thesis_as_of") or thesis.get("as_of") or "").strip()
    if not stance:
        out.append(_finding("card_completeness", sym, "P1" if top else "P2",
                            f"{sym or 'card'} shows no CIO thesis or stance",
                            "Every symbol card must carry the CIO's view (§6).",
                            {"list_kind": list_kind}))
    elif not as_of:
        out.append(_finding("card_completeness", sym, "P1" if top else "P2",
                            f"{sym or 'card'} shows a CIO stance with no as_of",
                            "A stance with no as_of cannot be told from an old one — it is P1 in a top list (§6).",
                            {"stance": stance, "list_kind": list_kind}))
    return out


def now_price(card: dict[str, Any], quote: Optional[dict[str, Any]], *, now: str | None = None) -> list[dict]:
    """The card's "now" against the quote the server holds. A stored prior close is never a "now"."""
    sym = str(card.get("symbol") or "")
    shown = card.get("now")
    if not isinstance(quote, dict):
        return [] if shown in (None, "", "—", "unavailable") else [
            _finding("now_price", sym, "P2", f"{sym} shows a now price with no quote to support it",
                     "A price that cannot be traced to the server's quote is unverifiable.",
                     {"shown": shown})]
    price = quote.get("price")
    if shown in (None, "", "—", "unavailable", "stale"):
        if isinstance(price, (int, float)):
            return [_finding("now_price", sym, "P1",
                             f"{sym} shows no now price while the server holds {price}",
                             "The 2026-11-04 case: the card said 'now —' beside a live quote. A withheld price is a defect.",
                             {"server_price": price, "server_as_of": quote.get("as_of"), "shown": shown})]
        return []
    try:
        shown_num = float(str(shown).replace("$", "").replace(",", ""))
    except ValueError:
        return [_finding("now_price", sym, "P2", f"{sym} now price is not a number: {shown!r}",
                         "A non-numeric price cannot be compared with anything.", {"shown": shown})]
    if isinstance(price, (int, float)) and price > 0:
        drift = abs(shown_num - float(price)) / float(price) * 100
        if drift > _PM_TOLERANCE_PCT:
            return [_finding("now_price", sym, "P1",
                             f"{sym} shows {shown_num:.2f} while the server holds {float(price):.2f}",
                             "Two different prices for one symbol on one screen.",
                             {"shown": shown_num, "server": float(price), "drift_pct": round(drift, 3),
                              "server_as_of": quote.get("as_of"), "session": quote.get("session")})]
    return []


def verdict_vs_price(card: dict[str, Any]) -> list[dict]:
    """A verdict that contradicts the price it is about. CONFIRMED below the invalidation level is the SPCX case."""
    sym = str(card.get("symbol") or "")
    verdict = str(card.get("verdict") or "").strip().upper()
    invalidation = card.get("invalidation_level")
    price = card.get("now_price")
    if price is None and isinstance(card.get("now"), (int, float)):
        price = card.get("now")
    if not verdict or invalidation is None or price is None:
        return []
    try:
        price_f, inval_f = float(price), float(invalidation)
    except (TypeError, ValueError):
        return []
    if verdict in ("CONFIRMED", "BASING", "EARLY SETUP") and price_f < inval_f:
        return [_finding("verdict_vs_price", sym, "P1",
                         f"{sym} is {verdict.title()} while its price {price_f:.2f} is below the invalidation {inval_f:.2f}",
                         "The verdict and the price disagree; the operator is being told to act on a dead setup.",
                         {"verdict": verdict, "price": price_f, "invalidation": inval_f,
                          "now_as_of": card.get("now_as_of")})]
    return []


def same_figure_everywhere(figure: str, surfaces: Iterable[dict[str, Any]], *, unit: str = "usd") -> list[dict]:
    """One figure, several places. Each surface: {name, value}. Any pair beyond a cent/rounding step is a P1."""
    values = [(str(s.get("name") or "?"), s.get("value")) for s in surfaces]
    numeric = [(n, float(v)) for n, v in values if isinstance(v, (int, float))]
    if len(numeric) < 2:
        return []
    lo = min(v for _, v in numeric)
    hi = max(v for _, v in numeric)
    if unit == "pct" and hi - lo <= 0.01:
        return []
    if unit == "usd" and (hi - lo) <= 0.01:
        return []
    spread = hi - lo
    return [_finding("same_figure_everywhere", None, "P1",
                     f"{figure} differs across the page: {', '.join(f'{n} {v:,.2f}' for n, v in numeric)}",
                     "One figure, one value — two surfaces showing different numbers is how a wrong number becomes trusted.",
                     {"figure": figure, "unit": unit, "values": [{"surface": n, "value": v} for n, v in numeric],
                      "spread": round(spread, 2)})]


def run(cards: Iterable[dict[str, Any]], *, quotes: Optional[dict[str, dict]] = None,
        figures: Optional[dict[str, Iterable[dict]]] = None, now: str | None = None) -> dict[str, Any]:
    """Every check over a captured page. Cards carry `symbol`, `list_kind`, a quote or its absence, and the verdict."""
    quotes = quotes or {}
    out: list[dict] = []
    seen = 0
    for card in cards:
        if not isinstance(card, dict):
            continue
        seen += 1
        out += card_completeness(card, list_kind=card.get("list_kind"))
        out += now_price(card, quotes.get(str(card.get("symbol") or "").upper()), now=now)
        out += verdict_vs_price(card)
    for figure, surfaces in (figures or {}).items():
        out += same_figure_everywhere(figure, surfaces)
    out.sort(key=lambda f: ({"P1": 0, "P2": 1, "P3": 2}[f["severity"]], f["check"], str(f["symbol"])))
    return {"schema": SCHEMA, "cards": seen, "findings": out,
            "counts": {s: sum(1 for f in out if f["severity"] == s) for s in ("P1", "P2", "P3")},
            "authority": "READ_ONLY_ADVISORY"}
