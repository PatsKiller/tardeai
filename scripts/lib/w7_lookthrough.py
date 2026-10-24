"""Read-only look-through projection, on the CIO's current holdings basis.

No quote/provider calls, writes, inference of company classifications, or fallback
portfolio math. Fund weights are the published cache; classifications are C1 facts
bound to a confirmed security GUID. Unresolved dollars stay visible as gaps.
"""
from __future__ import annotations

from collections import defaultdict
import math
from typing import Any


def number(value: Any) -> float | None:
    try:
        n = float(value) if value is not None and not isinstance(value, bool) else None
        return n if n is not None and math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _fact(row: dict, key: str) -> str | None:
    facts = row.get("company_facts") or (row.get("research") or {}).get("company_facts") or {}
    if not row.get("security_guid") or facts.get("security_guid") != row["security_guid"]:
        return None
    field = facts.get(key) or {}
    # A string without its original evidence is not a classified CIO fact.
    return field.get("value") if isinstance(field, dict) and field.get("source") else None


def project(*, portfolio: dict, holdings: list[dict], companies: list[dict],
            fund_cache: dict, fund_symbols: set[str], proxies: dict[str, str],
            theme_members: dict[str, set[str]], theme_targets: dict,
            snapshot: dict, account: str | None = None) -> dict:
    """Pure projection. ``portfolio`` is W1's resolved total/account model.

    Source contributions retain account, fund/proxy and weight. Cached narrative
    is independently clocked and never used to set exposure or the denominator.
    """
    accounts = portfolio.get("accounts") or []
    if isinstance(accounts, dict):
        accounts = [dict(v, account=k) for k, v in accounts.items() if isinstance(v, dict)]
    selected = next((a for a in accounts if a.get("account") == account), None) if account else portfolio
    total = number((selected or {}).get("total_usd"))
    rows = [h for h in holdings if not account or h.get("account") == account]
    facts = {str(c.get("symbol", "")).upper(): c for c in companies}
    labels = {a.get("account"): a.get("label") for a in accounts}
    amounts: dict[str, float] = defaultdict(float)
    sources: dict[str, list] = defaultdict(list)
    gaps: list[dict] = []
    fund_value = covered_fund = direct_value = 0.0
    missing_funds: list[dict] = []
    for h in rows:
        sym = str(h.get("symbol") or "").upper()
        value = number(h.get("market_value"))
        if h.get("is_cash") or not sym or value is None or value <= 0:
            continue
        acct = h.get("account")
        proxy = proxies.get(sym, sym)
        is_fund = h.get("is_fund") is True or sym in fund_symbols or proxy in fund_cache
        if is_fund:
            fund_value += value
            raw = fund_cache.get(proxy) or {}
            weights = {s: number(w) for s, w in raw.items()} if isinstance(raw, dict) else {}
            valid = bool(weights) and all(w is not None and 0 < w <= 1 for w in weights.values())
            weight_sum = sum(w for w in weights.values() if w is not None)
            if not valid or weight_sum > 1.0001:
                missing_funds.append({"symbol": sym, "account": acct, "value_usd": value,
                                      "reason": "Fund holdings unavailable" if not raw else "Fund weights invalid"})
                continue
            for stock, weight in weights.items():
                amount = value * weight
                amounts[stock] += amount
                sources[stock].append({"symbol": sym, "account": acct, "proxy": proxy if proxy != sym else None,
                                       "account_label": labels.get(acct), "weight": weight, "value_usd": amount, "source": "Published fund holdings"})
            covered_fund += value * weight_sum
            if weight_sum < 0.9999:
                gaps.append({"label": sym + " holdings not published", "value_usd": value * (1 - weight_sum),
                             "account": acct, "reason": "Published top holdings cover part of this fund"})
        else:
            # A holding's explicit equity type or bound C1 record establishes direct stock identity.
            if h.get("asset_type") not in ("equity", "stock", "EQUITY", "STOCK") and sym not in facts:
                gaps.append({"label": sym, "value_usd": value, "account": acct,
                             "reason": "Instrument type unresolved; fund exposure not assumed"})
                continue
            amounts[sym] += value
            direct_value += value
            sources[sym].append({"symbol": sym, "account": acct, "proxy": None, "weight": 1,
                                 "account_label": labels.get(acct), "value_usd": value, "source": "Direct holding"})
    covered = direct_value + covered_fund
    sectors: dict[str, dict] = {}
    industries: dict[tuple[str, str], dict] = {}
    classified = 0.0
    for symbol, value in amounts.items():
        company = facts.get(symbol, {})
        sector = _fact(company, "sector") or "Unclassified"
        industry = _fact(company, "industry") or "Unclassified"
        if industry != "Unclassified":
            classified += value
        sector_row = sectors.setdefault(sector, {"name": sector, "value_usd": 0, "members": []})
        sector_row["value_usd"] += value
        sector_row["members"].append({"symbol": symbol, "value_usd": value, "sources": sources[symbol]})
        industry_row = industries.setdefault((sector, industry), {"sector": sector, "name": industry, "value_usd": 0, "members": []})
        industry_row["value_usd"] += value
        industry_row["members"].append({"symbol": symbol, "value_usd": value})
    pct = lambda value: round(value / total * 100, 2) if total and total > 0 else None
    for row in sectors.values():
        row["portfolio_pct"] = pct(row["value_usd"])
    top = [{"symbol": s, "value_usd": round(v, 2), "portfolio_pct": pct(v), "sources": sources[s]}
           for s, v in sorted(amounts.items(), key=lambda x: (-x[1], x[0]))[:20]]
    themes = []
    theme_gaps = []
    for name, members in theme_members.items():
        value = sum(v for s, v in amounts.items() if s in members)
        themes.append({"name": name, "value_usd": round(value, 2),
                       "looked_through_pct": round(value / covered * 100, 2) if covered else None,
                       "portfolio_pct": pct(value)})
        target = number(theme_targets.get(name))
        if target is not None and total and pct(value) < target:
            theme_gaps.append({"name": name, "current_pct": pct(value), "target_pct": target,
                               "gap_usd": round(max(0, total * target / 100 - value), 2)})
    account_gaps = []
    for a in accounts:
        if account and a.get("account") != account:
            continue
        if str(a.get("state") or a.get("status") or "").upper() in ("STALE", "SERVICE_DOWN", "NO_API_MANUAL", "UNCLASSIFIED"):
            account_gaps.append({"account": a.get("account"), "label": a.get("label"),
                                 "value_usd": number(a.get("last_known_value_usd", a.get("total_usd"))),
                                 "as_of": a.get("as_of"), "reason": a.get("reason") or "Account sync is not current"})
    narrative = {"text": None, "as_of": snapshot.get("grok_generated_at"), "reason": "CIO narrative unavailable"}
    text = snapshot.get("grok_narrative")
    refused = isinstance(text, str) and any(x in text.lower() for x in ("i cannot", "i can't", "unable to", "cannot provide", "can't provide", "as an ai"))
    if snapshot.get("grok_status") == "ok" and text and not refused:
        narrative = {"text": text, "as_of": snapshot.get("grok_generated_at"), "reason": None}
    elif refused:
        narrative["reason"] = "The model declined to provide a narrative"
    if total is None:
        gaps.append({"label": "Portfolio basis", "value_usd": None, "reason": "Canonical portfolio total unavailable"})
    return {"account": account, "as_of": portfolio.get("as_of"), "portfolio_total_usd": total,
            "looked_through_usd": round(covered, 2) if total is not None else None, "portfolio_coverage_pct": pct(covered),
            "fund_value_usd": round(fund_value, 2), "fund_covered_usd": round(covered_fund, 2),
            "fund_coverage_pct": round(covered_fund / fund_value * 100, 2) if fund_value else None,
            "unclassified_industry_usd": round(covered - classified, 2),
            "funds_without_holdings": missing_funds, "account_gaps": account_gaps, "gaps": gaps,
            "sectors": sorted(sectors.values(), key=lambda x: -x["value_usd"]),
            "industries": sorted(industries.values(), key=lambda x: -x["value_usd"]),
            "top_underlying": top, "themes": sorted(themes, key=lambda x: -x["value_usd"]),
            "theme_gaps": theme_gaps, "narrative": narrative}
