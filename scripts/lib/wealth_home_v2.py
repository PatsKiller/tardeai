"""Stored Home v2 presentation contract. Financial aggregation runs ONLY in dp-live.

GET reads one already-published Home slice; only calendar and source ages move at serve time.
No providers, broker subsystem, advice generation, scheduler, or durable write is reachable here.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
import json
import math
from urllib.parse import urlencode, urlsplit

from scripts.lib.market_risk import sessions

UTC = timezone.utc
COLORS = {"known": "green", "partial": "amber", "stale": "amber", "unknown": "grey"}
TODAY = {"stance":"Daily decision", "tiles":"Portfolio snapshot", "movers":"Top movers", "stops":"Protection review", "week":"This week", "news":"What to read first", "accounts":"Accounts", "setups":"Latest finished setups", "watch":"Watch movers and re-entry", "brief":"Historical CIO brief", "pulse":"System pulse"}
OUTLOOK = {"temperature":"Market temperature", "regime":"Market regime", "disagreements":"Engine disagreements", "sectors":"Sector states", "hedge":"Hedge and rotation", "week":"Week ahead", "futures":"Futures and overseas", "headlines":"Market headlines", "marketMovers":"Scanner movers"}
NEEDS = {"summary":"Review queue", "protect":"Protect", "decide":"Decide", "reentry":"Stopped-out tracker", "fix":"Fix", "incidents":"Incident history"}


def number(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (ValueError, TypeError):
        return None
    return n if math.isfinite(n) else None


def gap_reason(value):
    return value.get("reason") if isinstance(value,dict) else str(value) if value else None


def count(value):
    n=number(value)
    return int(n) if n is not None and n >= 0 and n.is_integer() else None


def timestamp(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def iso(value):
    at = timestamp(value)
    return at.isoformat().replace("+00:00", "Z") if at else None


def money(value, signed=False):
    n = number(value)
    if n is None:
        return None
    return ("+" if signed and n > 0 else "-" if n < 0 else "") + f"${abs(n):,.2f}"


def pct(value, signed=False):
    n = number(value)
    return None if n is None else f"{n:+.2f}%" if signed and n != 0 else f"{n:.2f}%"


def tone(value):
    n = number(value)
    return "grey" if n is None or n == 0 else "green" if n > 0 else "red"


def source_meta(source, clock=None, stale_after_s=None, *, now=None, reason=None, stale=False):
    now = now or datetime.now(UTC)
    at = timestamp(clock)
    age = (now - at).total_seconds() if at else None
    valid = age is not None and age >= -5
    old = stale or (valid and stale_after_s is not None and age > stale_after_s)
    verdict = "unknown" if not valid else "stale" if old else "known"
    return {"source":source, "clock":iso(clock), "as_of":iso(clock), "age_s":max(0, int(age)) if valid else None,
            "stale_after_s":stale_after_s, "verdict":verdict, "state":COLORS[verdict],
            "reason":reason or ("Source clock missing or timezone unqualified" if not valid else "Stored observation is stale" if old else None)}


def session_clock(now):
    local = now.astimezone(sessions.ET)
    key = sessions.session_label(now)
    key = {"premarket":"pre_market", "afterhours":"after_hours", "overnight":"closed"}.get(key,key)
    day = local.date()
    candidate = datetime.combine(day,time(9,30),sessions.ET)
    while not sessions.is_trading_day(day) or candidate <= local:
        day += timedelta(days=1)
        candidate = datetime.combine(day,time(9,30),sessions.ET)
    last = sessions.last_closed_session(now)
    return {"key":key, "label":{"pre_market":"Pre-market", "regular":"Regular session", "after_hours":"After-hours", "closed":"Closed"}[key],
            "last_session_date":last.isoformat(), "next_open":iso(candidate), "regular_close":iso(datetime.combine(local.date(),sessions.close_time(local.date()),sessions.ET)) if sessions.is_trading_day(local.date()) else None,
            "timezone":"America/New_York"}


def cell(label, display=None, *, value=None, secondary=None, meta=None, state=None, tooltip=None):
    meta = meta or source_meta("not served")
    verdict = meta["verdict"] if display is not None else "unknown"
    return {**meta, "label":label, "verdict":verdict, "state":state or COLORS[verdict], "value":value,
            "display":display, "secondary":secondary or [], "tooltip":tooltip or meta.get("reason") or meta["source"]}


def section(title, *, meta=None, metrics=None, rows=None, notes=None, links=None, reason=None):
    meta = meta or source_meta("not served")
    available = bool(metrics or rows)
    return {**meta, "title":title, "available":available, "metrics":metrics or [], "rows":rows or [],
            "notes":notes or [], "links":links or [], "reason":reason or meta.get("reason") or (None if available else "Stored producer coverage is not available for this panel")}


def fact(label, value, *, state="grey", **extra):
    return {"label":label, "value":value, "state":state, **extra}


def holding_href(symbol, account=None):
    query = {"hv_query":symbol}
    if account:
        query["hv_account"] = account
    return "/wealth/portfolio/holdings?" + urlencode(query)


def unique_positions(rows):
    """Canonical account+instrument identity once; conflicting duplicates are excluded, never divided.

    Same-source duplicates and parent/child joins cannot amplify a position. Rows missing account identity
    never collapse under symbol alone: they are rejected and named in coverage instead.
    """
    grouped, rejected = {}, []
    for row in rows if isinstance(rows,list) else []:
        if not isinstance(row,dict):
            rejected.append("malformed position")
            continue
        account = str(row.get("account_id") or "").strip()
        instrument = str(row.get("instrument_id") or row.get("instrument_guid") or row.get("symbol") or "").strip().upper()
        if not account or not instrument:
            rejected.append("position identity missing")
            continue
        key = (account,instrument)
        if key not in grouped:
            grouped[key] = row
        elif grouped[key] is not None and any(grouped[key].get(k) != row.get(k) for k in ("market_value","shares","quantity")):
            grouped[key] = None
    for key, value in grouped.items():
        if value is None:
            rejected.append("conflicting position identity")
    return [v for v in grouped.values() if v is not None], rejected


def exposure_by_symbol(rows):
    unique, rejected = unique_positions(rows)
    out = {}
    for row in unique:
        sym = str(row.get("symbol") or "").upper()
        rec = out.setdefault(sym,{"value":0.0,"known":0,"total":0})
        rec["total"] += 1
        value = number(row.get("market_value"))
        if value is not None:
            rec["known"] += 1
            rec["value"] += value
    for rec in out.values():
        rec["coverage"] = f"{rec['known']}/{rec['total']} account positions with value"
        rec["complete"] = rec["known"] == rec["total"]
        if rec["known"] == 0:
            rec["value"] = None
    return out, rejected


def safe_url(value):
    try:
        parsed = urlsplit(str(value or ""))
        return str(value) if parsed.scheme in ("https","http") and parsed.netloc and not parsed.username and not parsed.password else None
    except ValueError:
        return None


def build(*, cio=None, market=None, overview=None, scanner=None, slices=None, health=None, now=None, stop_stale_after_s=None):
    """Pure producer-side composer over stored read models; arguments are synthetic-testable."""
    now = now or datetime.now(UTC)
    cio, market, overview, scanner, slices = (v if isinstance(v,dict) else {} for v in (cio,market,overview,scanner,slices))
    portfolio = cio.get("portfolio") or {}
    positions = cio.get("positions") or {}
    stop_contract = cio.get("stops") or {}
    if stop_stale_after_s is None and number(stop_contract.get("stale_after_hours")) is not None:
        stop_stale_after_s = number(stop_contract["stale_after_hours"]) * 3600
    rows, rejected = unique_positions(positions.get("rows") or [])
    exposure, _ = exposure_by_symbol(rows)
    pm = source_meta("cio.pages.portfolio",portfolio.get("quote_as_of") or portfolio.get("positions_as_of"), now=now, stale=bool(portfolio.get("stale")),reason=gap_reason(portfolio.get("gap")))
    rm = source_meta("market_risk.latest.projection",market.get("as_of"),3600,now=now,stale=bool(market.get("stale")))
    sm = source_meta("cio.pages.positions",positions.get("as_of"),now=now,stale=bool(positions.get("stale")),reason=gap_reason(positions.get("gap")))
    regime = cio.get("regime") or {}
    regime_row = regime.get("regime") or regime.get("data") or regime
    if regime.get("label") and not regime_row.get("regime_label"):
        regime_row = {**regime_row,"regime_label":regime["label"]}
    scanner = {**{k:v for k,v in (("vix",regime.get("vix")),("vix_source",regime.get("vix_source")),("vix_observation_time",regime.get("vix_as_of")),("vix_stale_after_hours",regime.get("vix_stale_after_hours"))) if v is not None},**scanner}
    gm = source_meta("cio.pages.regime",regime.get("as_of") or regime_row.get("generated_at"),number(regime.get("stale_after_hours"))*3600 if number(regime.get("stale_after_hours")) is not None else None,now=now,stale=bool(regime.get("stale")),reason=gap_reason(regime.get("gap")))
    vm = source_meta(scanner.get("vix_source") or "trade_ai_cache.vix",scanner.get("vix_observation_time"),number(scanner.get("vix_stale_after_hours"))*3600 if number(scanner.get("vix_stale_after_hours")) is not None else None,now=now)
    value,cash = number(portfolio.get("total_usd")),number(portfolio.get("cash_usd"))
    cash_pct = cash/value*100 if cash is not None and value is not None and value>0 else None
    covariance = portfolio.get("day_pl_coverage") or {}
    day = number(portfolio.get("day_pl_usd"))
    day_clock=(portfolio.get("clock_provenance") or {}).get("day_pnl") or {}
    day_meta = source_meta("cio.pages.portfolio.stored_day_change",day_clock.get("as_of"),now=now,reason=gap_reason(day_clock.get("gap")) or "Stored row day-change observation clock is not supplied")
    if day is not None:
        day_meta.update(verdict="partial",state="amber",reason="Current-holdings estimate; source interval is unproven")
    if not portfolio.get("day_pl_complete") and day is not None:
        day_meta.update(verdict="partial",state="amber",reason=portfolio.get("day_pl_gap") or "Current-holdings price movement has incomplete coverage")
    tier = str(market.get("tier") or "UNKNOWN")
    tier_state = {"BLUE":"grey","GREEN":"green","YELLOW":"amber","ORANGE":"amber","RED":"red"}.get(tier,"grey")
    temp_display = f"{tier} · {market['score']}" if number(market.get("score")) is not None else None
    session = session_clock(now)
    cells = {
        "session":cell("Session",session["label"],value=session,meta=source_meta("NYSE exchange calendar",now,now=now),state="grey",secondary=["Last session "+session["last_session_date"],"Next open "+timestamp(session["next_open"]).astimezone(sessions.ET).strftime("%a %b %d %H:%M ET")]),
        "session_pl":cell("Session P/L estimate",money(day,True),value={"amount":day,"usd":day,"pct":number(portfolio.get("day_pl_pct")),"coverage":covariance,"method":"Stored current-holdings price movement; not verified account return","interval":{"source":"cio.pages.portfolio","from":None,"to":portfolio.get("quote_as_of"),"session_date":None},"verified":False},meta=day_meta,secondary=[pct(portfolio.get("day_pl_pct"),True) or "Percentage unknown","Current-holdings estimate · interval not served"],tooltip="Stored current-holdings estimate; account performance may use another method/interval. Extended-only coverage is not served and is never inferred."),
        "account_value":cell("Household value",money(value),value={"usd":value,"cash_usd":cash,"cash_pct":cash_pct,"approx_ytd":None,"batch_built_at":iso(portfolio.get("valuation_as_of")),"quote_as_of":iso(portfolio.get("quote_as_of")),"positions_as_of":iso(portfolio.get("positions_as_of"))},meta=pm,secondary=["Cash "+(money(cash) or "Unknown")+" · "+(pct(cash_pct) or "Unknown")+" derived","Approximate YTD not served"]),
        "temperature":cell("Temperature",temp_display,value={"tier":tier,"score":market.get("score"),"stance":market.get("reason")},meta=rm,state=tier_state if rm["verdict"]=="known" else "grey",secondary=[str(market.get("reason") or "Stance not served")]),
        "regime":cell("Regime",regime_row.get("regime_label") or regime.get("label"),value={"label":regime_row.get("regime_label"),"score":regime_row.get("regime_score"),"confidence":regime_row.get("confidence")},meta=gm),
        "vix":cell("VIX",str(scanner["vix"]) if number(scanner.get("vix")) is not None else None,value={"index":number(scanner.get("vix")),"source":scanner.get("vix_source")},meta=vm,state="grey"),
        "operating_mode":cell("Operating mode",None,meta=source_meta("Typed operating-mode flags not in stored Home product",now=now),tooltip="Buy-risk stance, kill and live-submit flags require a reviewed stored read model; no flag is inferred or changed."),
        "health":cell("Health",None,meta=source_meta("Health findings not in stored Home product",now=now),tooltip="Incident history and component checks are different populations from current critical/total health findings.")}
    today = {k:section(v) for k,v in TODAY.items()}
    outlook = {k:section(v) for k,v in OUTLOOK.items()}
    needs = {k:section(v) for k,v in NEEDS.items()}
    temp_metrics = [fact("Tier",tier,state=tier_state),fact("Score",str(market["score"]) if number(market.get("score")) is not None else None),fact("Evaluation",rm["clock"]),fact("Episode",str((market.get("episode") or {}).get("id")) if (market.get("episode") or {}).get("id") else None)]
    today["stance"] = section(TODAY["stance"],meta=rm,metrics=temp_metrics+[fact("Buys",None,qualifier="Stored buy-risk stance not served"),fact("Stops to decide",None,qualifier="Typed decision subset not served"),fact("Unprotected",None,qualifier="Applicable current protection population not supplied"),fact("Re-entry",None,qualifier="Ready/near/total stage contract not served")],notes=[str(market.get("reason") or "No stored dated stance"),"Saved engine evidence, not a new synthesized recommendation"],links=[{"label":"Needs your review","href":"/wealth/home/needs"}])
    today["tiles"] = section(TODAY["tiles"],meta=pm,metrics=[fact("Portfolio",money(value)),fact("Session estimate",money(day,True),state=tone(day),signed=True),fact("Approximate YTD",None,qualifier="Compatible stored flow-adjusted period not served"),fact("Realized P/L",None,qualifier="Partial basis/ledger coverage not served"),fact("Trading record",None,qualifier="Comparable finished-trade population not served")],notes=["Session estimate: current holdings, not verified return; raw NAV growth is not investment profit."])
    account_rows = [{"id":str(a.get("account_id") or i),"label":a.get("account_label") or "Account label unavailable","facts":[fact("Value",money(a.get("total_usd"))),fact("Cash",money(a.get("cash_usd"))),fact("Session estimate",money(a.get("day_pl_usd"),True),state=tone(a.get("day_pl_usd")),signed=True)],"clock":iso(a.get("as_of") or pm["clock"]),"source":pm["source"],"href":"/wealth/portfolio/holdings?"+urlencode({"hv_account":a.get("account_id") or ""})} for i,a in enumerate(portfolio.get("accounts") or []) if isinstance(a,dict)]
    today["accounts"] = section(TODAY["accounts"],meta=pm,rows=account_rows,notes=["Household and account results retain their own eligible population; missing account results remain unknown."])
    protect=[]
    for i,row in enumerate(rows):
        # Use the retained canonical verdict only. stop_state alone cannot establish applicability.
        proof = row.get("protection") if isinstance(row.get("protection"),dict) else {}
        canonical = str(row.get("protection_state") or proof.get("state") or "UNKNOWN").upper()
        pending = row.get("stop_state") == "pending_activation"
        stop_meta = source_meta(row.get("stop_source") or "cio.pages.positions.stop evidence",row.get("stop_captured_at"),stop_stale_after_s,now=now,stale=sm["verdict"]!="known")
        proven = (canonical == "PROTECTED" and row.get("broker_protected") is True
                  and number(row.get("stop_price")) is not None and number(row.get("stop_price")) > 0
                  and bool(row.get("stop_source")) and stop_stale_after_s is not None and stop_meta["verdict"] == "known")
        shortfall = number(row.get("resting_coverage_shortfall_qty"))
        partial = proven and shortfall is not None and shortfall > 0
        status = "Partial resting coverage" if partial else "Recorded active" if proven else "Pending activation" if pending else "Not applicable" if canonical == "EXEMPT" else "Gap" if canonical == "GAP" and stop_meta["verdict"] == "known" else "Current protection proof unavailable"
        state = "amber" if partial else "green" if proven else "amber" if pending else "red" if status == "Gap" else "grey"
        if stop_meta["verdict"] == "stale": state = "amber"
        detail = f"{row.get('account_label') or 'Account unavailable'} · {status} · canonical applicability {'served' if canonical != 'UNKNOWN' else 'not retained in stored projection'}"
        protect.append({**stop_meta,"id":str(i),"symbol":row.get("symbol"),"label":str(row.get("symbol") or "Unknown instrument"),"detail":detail,"state":state,"href":holding_href(str(row.get("symbol") or ""),row.get("account_id")),"facts":[fact("Protection",status,state=state,current_status=True),fact("Stored level",money(row.get("stop_price"))),fact("Distance",pct(row.get("resting_stop_distance_pct"))),fact("Covered shares",str(row["resting_loss_qty"]) if number(row.get("resting_loss_qty")) is not None else None),fact("Uncovered shares",str(shortfall) if shortfall is not None else None),fact("Shares",str(row["shares"]) if number(row.get("shares")) is not None else None)],"evidence":row.get("stop_evidence") or {}})
    today["stops"] = section(TODAY["stops"],meta=sm,rows=protect,notes=["Pending activation is not active protection. Observation age and account scope remain explicit. Historical incidents are separate."]+([f"Rejected {len(rejected)} ambiguous position identity rows"] if rejected else []))
    needs["protect"] = deepcopy(today["stops"]); needs["protect"]["title"] = NEEDS["protect"]
    queue = cio.get("do_now") or {}
    qrows=[]
    queue_items = [it for it in (queue.get("all_items") or queue.get("items") or []) if isinstance(it,dict)]
    for i,item in enumerate(queue_items):
        if not isinstance(item,dict): continue
        qrows.append({"id":str(item.get("id") or i),"label":str(item.get("title") or item.get("label") or "Review item"),"detail":str(item.get("reason") or item.get("why") or "Stored queue evidence"),"source":item.get("source") or "cio.pages.do_now","clock":iso(queue.get("as_of")),"state":"amber","category":item.get("category"),"facts":[fact("Category",item.get("category"))]})
    qm = source_meta("cio.pages.do_now",queue.get("as_of"),now=now,stale=bool(queue.get("stale")))
    category_counts = {c:sum(1 for it in (queue.get("all_items") or queue.get("items") or []) if isinstance(it,dict) and it.get("category")==c) for c in ("protect","decide","fix")} if "all_items" in queue else {}
    counts = queue.get("counts") if isinstance(queue.get("counts"),dict) else category_counts
    counts = {k:count(v) for k,v in counts.items()} if qm["verdict"]=="known" and queue.get("state")!="UNKNOWN" else {}
    needs["summary"] = section(NEEDS["summary"],meta=qm,metrics=[fact("Money decisions today",None,qualifier="Typed money-decision population not served"),fact("Protect money",str(counts["protect"]) if counts.get("protect") is not None else None),fact("Decide",str(counts["decide"]) if counts.get("decide") is not None else None),fact("Fix system",str(counts["fix"]) if counts.get("fix") is not None else None),fact("Queue freshness",qm["verdict"],state=qm["state"],clock=qm["clock"])],rows=qrows,notes=["Counts describe this stored queue only. Protection evidence and incident history have distinct populations."])
    needs["decide"] = section(NEEDS["decide"],meta=qm,rows=[r for r in qrows if r.get("category")=="decide"])
    inc = slices.get("incidents") or {}
    im = source_meta("home.incidents",(inc.get("snapshot") or {}).get("computed_at"),180,now=now)
    incidents=[{"id":str(it.get("incident_id") or i),"label":str(it.get("category") or it.get("alert_type") or "Unclassified"),"detail":str(it.get("cause") or it.get("reason") or "Recorded incident"),"clock":iso(it.get("last_seen_at")),"source":str(it.get("alert_type") or "home.incidents"),"state":"grey","facts":[fact("First seen",iso(it.get("first_seen_at"))),fact("Last seen",iso(it.get("last_seen_at")))]} for i,it in enumerate(inc.get("items") or []) if isinstance(it,dict)]
    needs["incidents"] = section(NEEDS["incidents"],meta=im,rows=incidents,notes=["Recorded incident history, not a current protection verdict. Category is retained from the registered incident type; message fallback is not classification evidence."]); needs["incidents"]["collapsed"]=True
    outlook["temperature"] = section(OUTLOOK["temperature"],meta=rm,metrics=temp_metrics,rows=[{"id":str(i),"label":str(c.get("label") or c.get("category") or c.get("name") or i),"detail":str(c.get("reason") or ""),"facts":[fact("Score",str(c["score"]) if number(c.get("score")) is not None else None)]} for i,c in enumerate(market.get("categories") or []) if isinstance(c,dict)],notes=["Engine cutoffs are not supplied in this stored contract; no invented gauge boundaries."])
    outlook["regime"] = section(OUTLOOK["regime"],meta=gm,metrics=[fact("Regime",regime_row.get("regime_label") or regime.get("label")),fact("Confidence",str(regime_row["confidence"]) if number(regime_row.get("confidence")) is not None else None),fact("Score",str(regime_row["regime_score"]) if number(regime_row.get("regime_score")) is not None else None)],rows=[{"id":k,"label":k.replace("_state"," ").replace("_"," "),"detail":str(regime_row[k])} for k in ("volatility_state","trend_state","breadth_state","liquidity_state","leadership_state","risk_appetite_state","macro_state","data_freshness_state") if regime_row.get(k) is not None])
    news=[]
    for i,item in enumerate((market.get("material_news") or {}).get("items") or []):
        if not isinstance(item,dict): continue
        sym=str(item.get("symbol") or "").upper()
        headlines=item.get("headlines") or [item]
        for j,headline in enumerate(headlines if isinstance(headlines,list) else []):
            if not isinstance(headline,dict): continue
            title=headline.get("title") or headline.get("headline")
            if not title: continue
            link=safe_url(headline.get("source_url") or headline.get("url"))
            news.append({"id":f"{i}:{j}","label":str(title),"symbol":sym,"candidate":True,"issuerVerified":False,"source":headline.get("source") or "market_risk.material_news","clock":iso(headline.get("published_at")),"state":"grey","href":holding_href(sym) if sym in exposure else "/v3/watch/intelligence/"+sym,"facts":[fact("Entity match","Unverified source-tagged candidate"),fact("Publisher",headline.get("source")),fact("Publication",iso(headline.get("published_at")))],"links":[{"label":"Original source","href":link}] if link else []})
    today["news"] = section(TODAY["news"],meta=rm,rows=news,notes=["Ticker tags and headline substrings do not prove issuer relevance. Candidates do not carry personalized exposure claims or ranked advice."])
    outlook["headlines"] = deepcopy(today["news"]); outlook["headlines"]["title"]=OUTLOOK["headlines"]
    context = market.get("home_v007") or {}
    symbol_context = context.get("symbols") if isinstance(context.get("symbols"),dict) else {}
    reentry = market.get("reentry_watch") if isinstance(market.get("reentry_watch"),dict) else {}
    def measured(raw):
        return raw if isinstance(raw,dict) and raw.get("state")=="measured" else {}
    def meta_for(raw, fallback):
        return source_meta(raw.get("source") or fallback,raw.get("as_of"),now=now,stale=raw.get("state")!="measured",reason=raw.get("reason"))
    mover_rows=[]; event_rows=[]; context_news=[]
    for sym, data in sorted(symbol_context.items()):
        if not isinstance(data,dict): continue
        scope="held" if sym in exposure else "watch" if sym in reentry else "unknown"
        href=holding_href(sym) if scope=="held" else "/v3/watch/intelligence/"+sym
        quote, change = measured(data.get("quote")), measured(data.get("day_change"))
        change_value = change.get("value") if isinstance(change.get("value"),dict) else {}
        if scope != "unknown" and (quote or change):
            delta=number(change_value.get("pct"))
            mover_rows.append({**meta_for(quote or change,"market_risk.home_v007"),"id":sym,"symbol":sym,"label":sym,"scope":scope,"href":href,"_rank":delta,"facts":[fact("Price",money(quote.get("value"))),fact("Change",pct(delta,True),state=tone(delta),signed=True),fact("Reference session",change.get("reference_session_date"))],"detail":"Stored guarded quote; change versus previous completed NYSE session close"})
        event = data.get("next_event") or {}
        ev = event.get("value") if isinstance(event.get("value"),dict) else {}
        if scope != "unknown" and ev:
            event_rows.append({**meta_for(event,"canonical_symbol_calendar"),"id":sym,"symbol":sym,"label":sym+" · "+str(ev.get("kind") or "Recorded event"),"href":href,"scope":scope,"facts":[fact("Recorded date",ev.get("date")),fact("Timing","Unconfirmed date-only event")],"detail":"Stored calendar date; exchange time and confirmed/estimated status are not supplied"})
        headlines = data.get("headlines") or {}
        for j,h in enumerate(headlines.get("value") if isinstance(headlines.get("value"),list) else []):
            if not isinstance(h,dict) or not isinstance(h.get("title"),str): continue
            url=safe_url(h.get("source_url") or h.get("url"))
            context_news.append({**meta_for(headlines,"guarded_symbol_headlines"),"id":sym+":"+str(j),"symbol":sym,"label":h["title"],"scope":scope,"candidate":True,"issuerVerified":False,"href":href,"facts":[fact("Entity match","Unverified source-tagged candidate"),fact("Publisher",h.get("source")),fact("Publication",iso(h.get("published_at"))),fact("Ingest/read clock",iso(headlines.get("as_of")))],"links":[{"label":"Original source","href":url}] if url else []})
    mover_rows.sort(key=lambda r:(r.get("_rank") is None,-abs(r.get("_rank") or 0),r["symbol"]))
    for row in mover_rows: row.pop("_rank",None)
    today["movers"]=section(TODAY["movers"],meta=rm,rows=mover_rows,notes=["Ranked by absolute served day-change percentage, not dollar contribution. Bounded stored Home context coverage; Held/Watch identifies the retained source population. No dollar contribution is inferred from incomplete position/quote joins."])
    today["week"]=section(TODAY["week"],meta=rm,rows=event_rows,notes=["Recorded held/watched dates from the bounded stored Home context. Date-only events are not confirmed event times; full-universe coverage is not claimed."])
    outlook["week"]=deepcopy(today["week"]);outlook["week"]["title"]=OUTLOOK["week"]
    if context_news:
        today["news"]=section(TODAY["news"],meta=rm,rows=context_news,notes=["Source-tagged candidates; issuer/entity match remains unverified. No personalized financial consequence is asserted."])
        outlook["headlines"]=deepcopy(today["news"]);outlook["headlines"]["title"]=OUTLOOK["headlines"]
    watch_rows=[]
    for sym,card in sorted(reentry.items()):
        if sym.startswith("_") or not isinstance(card,dict): continue
        conditions=card.get("conditions") or []
        progress=[c["met"] for c in conditions if isinstance(c,dict) and isinstance(c.get("met"),bool)]
        facts=[fact("Stage",card.get("status")),fact("Exit date",card.get("exit_date")),fact("Source session date",card.get("as_of")),fact("Conditions",str(card.get("met"))+" / "+str(card.get("of")) if count(card.get("met")) is not None and count(card.get("of")) is not None else None)]
        watch_rows.append({"id":sym,"label":sym,"symbol":sym,"scope":"held" if sym in exposure else "watch","href":holding_href(sym) if sym in exposure else "/v3/watch/intelligence/"+sym,"source":"market_risk.reentry_watch","clock":None,"state":"grey","detail":str(card.get("headline") or card.get("error") or "Stored re-entry evidence"),"facts":facts,**({"progress":progress} if len(progress)==5 else {})})
    today["watch"]=section(TODAY["watch"],meta=rm,rows=watch_rows,notes=["Retained re-entry conditions, not a new recommendation. Source session dates are not fabricated UTC observation clocks."])
    needs["reentry"]=deepcopy(today["watch"]);needs["reentry"]["title"]=NEEDS["reentry"]
    groups=(market.get("sectors") or {}).get("groups") or []
    from scripts.lib.market_risk.risk_budget import PROFILE_SECTOR_LABELS, GROUP_TO_SECTOR
    by_sector={GROUP_TO_SECTOR.get(g.get("key"),g.get("label")):g for g in groups if isinstance(g,dict) and g.get("kind","sector")=="sector"}
    sector_rows=[]
    for label in PROFILE_SECTOR_LABELS:
        g=by_sector.get(label)
        if g is None:
            sector_rows.append({"id":label,"label":label,"source":"market_risk canonical sector universe","clock":None,"state":"grey","detail":"Not measured in the stored sector projection","facts":[fact("State",None,qualifier="Stored sector evidence not served")]})
        else:
            sector_rows.append({"id":str(g.get("key") or label),"label":label,"source":"market_risk.sectors","clock":iso(g.get("as_of")),"state":{"STRESS":"red","WEAK":"amber","RESILIENT":"green"}.get(g.get("state"),"grey"),"facts":[fact("State",g.get("state")),fact("Five-session return",pct(g.get("r5"),True),state=tone(g.get("r5")),signed=True),fact("Relative strength",pct(g.get("rs5"),True),state=tone(g.get("rs5")),signed=True)]})
    outlook["sectors"]=section(OUTLOOK["sectors"],meta=rm,rows=sector_rows,notes=["Canonical eleven-sector universe; missing observations remain grey, with no invented momentum."])
    parts=regime_row.get("parts") or {}
    outlook["regime"]["rows"] += [{"id":k,"label":k.replace("_state","").replace("_"," "),"detail":str(v)} for k,v in parts.items() if v is not None]
    futures=market.get("overnight_markets") or {}
    future_rows=[]
    for i,row in enumerate(futures.get("items") or []):
        if not isinstance(row,dict): continue
        fm=source_meta("market_risk.overnight_markets",row.get("as_of"),number(futures.get("stale_after_hours"))*3600 if number(futures.get("stale_after_hours")) is not None else None,now=now,stale=bool(row.get("stale")),reason=row.get("stale_reason"))
        future_rows.append({**fm,"id":str(row.get("symbol") or i),"symbol":row.get("symbol"),"label":str(row.get("label") or row.get("symbol") or "Market"),"facts":[fact("Level",str(row["price"]) if number(row.get("price")) is not None else None),fact("Change",None if row.get("level_only") else pct(row.get("change_pct"),True),state=tone(row.get("change_pct")),signed=True),fact("Session",row.get("session")),fact("Session date",row.get("session_date")),fact("Reference",row.get("reference_date")),fact("Basis",row.get("reference_basis"))]})
    outlook["futures"]=section(OUTLOOK["futures"],meta=rm,rows=future_rows,notes=["Level-only prints do not imply a measured change. Each print retains its session/reference interval."])
    hedge=context.get("hedge") or {}
    hedge_metrics=[]
    for key,label in (("lagging_progress","Lagging sectors"),("exposure_progress","Weakening exposure")):
        raw=hedge.get(key) or {}; val=raw.get("value") if isinstance(raw.get("value"),dict) else {}
        hedge_metrics.append(fact(label,str(val["current"])+" / "+str(val["threshold"])+" "+str(val.get("unit") or "") if number(val.get("current")) is not None and number(val.get("threshold")) is not None and raw.get("state")=="measured" else None,clock=iso(raw.get("as_of")),source=raw.get("source"),qualifier=raw.get("reason")))
    outlook["hedge"]=section(OUTLOOK["hedge"],meta=rm,metrics=hedge_metrics,notes=["Existing engine thresholds only. Independent rotation trigger is not served; progress is descriptive advisory evidence."])
    conflicts=cio.get("conflicts") or {}
    conflict_meta=source_meta("cio.pages.conflicts",conflicts.get("as_of"),now=now,stale=bool(conflicts.get("stale")))
    conflict_rows=[{"id":str(it.get("id") or i),"label":str(it.get("title") or it.get("kind") or "Stored engine finding"),"detail":str(it.get("reason") or it.get("message") or "Stored finding; explanatory text not served"),"source":conflict_meta["source"],"clock":conflict_meta["clock"],"state":"amber"} for i,it in enumerate(conflicts.get("findings") or []) if isinstance(it,dict)]
    outlook["disagreements"]=section(OUTLOOK["disagreements"],meta=conflict_meta,rows=conflict_rows,notes=["Registered engine findings; risk tier is not relabeled as a conflict."])
    scanclock=scanner.get("latest_run_timestamp") or scanner.get("latest_scan_at")
    scanmeta=source_meta("trade_ai_cache.finished_scan",scanclock,now=now)
    today["setups"]=section(TODAY["setups"],meta=scanmeta,metrics=[fact("Run",str(scanner["run_id"]) if scanner.get("run_id") else None),fact("Scanned",str(count(scanner.get("current_run_scanned"))) if count(scanner.get("current_run_scanned")) is not None else None),fact("GO",str(count(scanner.get("latest_run_go_count"))) if count(scanner.get("latest_run_go_count")) is not None else None)],notes=["Stored run receipt; a ranked latest-finished setup population with completed-run proof is not supplied. No ticker is promoted from a different run."])
    scanner_rows=[]
    for bucket, key, reverse in (("Up sample","top_gainers",True),("Down sample","top_losers",False)):
        sample=[g for g in (scanner.get(key) or []) if isinstance(g,dict)]
        sample.sort(key=lambda g:(number(g.get("change_pct")) is None,(-1 if reverse else 1)*(number(g.get("change_pct")) or 0),str(g.get("symbol") or "")))
        for i,g in enumerate(sample[:5]):
            scanner_rows.append({"id":key+":"+str(i),"label":str(g.get("symbol") or "Unknown"),"symbol":g.get("symbol"),"detail":bucket,"source":str(g.get("source") or "trade_ai_cache."+key),"clock":iso(g.get("captured_at")),"state":"grey","facts":[fact("Direction",bucket),fact("Change",pct(g.get("change_pct"),True),signed=True,state=tone(g.get("change_pct"))),fact("Price",money(g.get("price"))),fact("Relative volume",str(g["rvol"]) if number(g.get("rvol")) is not None else None)]})
    outlook["marketMovers"]=section(OUTLOOK["marketMovers"],meta=scanmeta,rows=scanner_rows,notes=["At most five stored gainers and five stored losers; separate scanner population from held/watch and ranked setups.","Down sample not served" if not isinstance(scanner.get("top_losers"),list) else "Down sample follows the stored losers list; missing is not an empty observation."])
    health=health if isinstance(health,dict) else {}
    hm=source_meta("health_agent snapshot",health.get("captured_at"),3*3600,now=now)
    findings=health.get("findings")
    if isinstance(findings,list) and hm["verdict"]!="unknown":
        critical=sum(1 for f in findings if isinstance(f,dict) and str(f.get("severity") or "").upper()=="CRITICAL")
        healthstate="grey" if hm["verdict"]!="known" else "red" if critical else "amber" if findings else "green"
        cells["health"]=cell("Health",str(critical)+" critical / "+str(len(findings))+" total",value={"critical":critical,"total":len(findings)},meta=hm,state=healthstate,tooltip="Same stored Health Agent findings population; snapshot threshold is needs_action.HEALTH_STALE_H=3 hours")
    since=slices.get("since_close") or {}
    bm=source_meta("home.since_close",since.get("generated_at"),now=now,stale=bool((since.get("freshness") or {}).get("stale")))
    brief=since.get("summary") or since.get("brief")
    today["brief"]=section(TODAY["brief"],meta=bm,notes=["Historical saved analysis; figures and text retain their generation snapshot.",str(brief)] if isinstance(brief,str) else ["Historical saved analysis; a typed brief text is not served."],metrics=[fact("Generated",bm["clock"])] if bm["clock"] else [])
    sources={"portfolio":pm,"positions":sm,"temperature":rm,"regime":gm,"vix":vm,"queue":qm,"incidents":im,"brief":bm}
    source_rows=[{"id":k,"label":k,"detail":v["reason"] or "Stored source answered","clock":v["clock"],"source":v["source"],"state":v["state"]} for k,v in sources.items()]
    today["pulse"]=section(TODAY["pulse"],meta=source_meta("Home v2 read coverage",now,now=now),rows=source_rows,notes=["These are Home source-read states, not platform health findings."])
    needs["fix"]=section(NEEDS["fix"],meta=source_meta("Home v2 source gaps",now,now=now),rows=[r for r in source_rows if r["state"]!="green"],notes=["Fix-feed review only; this page does not schedule or mutate jobs."])
    return {"schema":"WealthHome@v2","built_at":iso(now),"queue_total":count(queue.get("total")) if qm["verdict"]=="known" and queue.get("state")!="UNKNOWN" else None,"header":{"schema":"WealthOperatingHeader@v1","as_of":iso(now),"session":session,"poll_after_s":300 if session["key"]=="closed" else 60,"queue_total":count(queue.get("total")) if qm["verdict"]=="known" and queue.get("state")!="UNKNOWN" else None,"cells":cells},"today":today,"outlook":outlook,"needs":needs,"sources":sources}


def collect(ctx, slices, *, now=None):
    """Existing Home producer extension: bounded stored reads, never an inline legacy API build."""
    now=now or datetime.now(UTC)
    from scripts.lib.cc_products import cio_pages_route, product_route
    fetch = cio_pages_route.make_pg_fetch_row(ctx.db_query_raising)
    def stored_file(path):
        try:
            if path.stat().st_size > 8*1024*1024: return {}
            body=json.loads(path.read_bytes())
            return body if isinstance(body,dict) else {}
        except (OSError,ValueError):
            return {}
    cio=cio_pages_route.serve_cio_pages(fetch_row=fetch,now=now)
    market=product_route.serve_market_risk_latest(fetch_row=fetch,now=now)
    runtime = getattr(ctx,"runtime_dir",None)
    overview=stored_file(runtime / "overview_projection.json").get("body") or {} if runtime is not None else {}
    scanner=stored_file(runtime / "trade_ai_cache.json") if runtime is not None else {}
    state_dir=getattr(ctx,"portfolio_state_dir",None)
    health=stored_file(state_dir / "health_agent_status.json") if state_dir is not None else {}
    result=build(cio=cio,market=market,overview=overview,scanner=scanner,slices=slices,health=health,now=now)
    for key, document in (("cio.pages",cio),("market_risk.latest",market)):
        result["sources"][key] = {**{k:v for k,v in (document.get("_product") or {}).items() if k in ("status","greyed","as_of","built_at","seq","reason","stale_after_s","hard_expiry_s")},"source":key}
    # Envelope status qualifies every dependent field, not just the operating header.
    for document, dependencies, cells in ((cio,("portfolio","positions","regime","queue"),("account_value","session_pl","regime")),(market,("temperature",),("temperature",))):
        if (document.get("_product") or {}).get("status") != "OK":
            reason="Stored source product is not current; retained evidence only"
            for key in dependencies: invalidate(result["sources"][key],reason)
            for key in cells: invalidate(result["header"]["cells"][key],reason)
            sources={result["sources"][k]["source"] for k in dependencies}
            for group in ("today","outlook","needs"):
                for panel in result[group].values():
                    if panel.get("source") in sources or (document is cio and panel.get("source","").startswith("cio.pages")) or (document is market and panel.get("source","").startswith("market_risk")): invalidate(panel,reason)
    validate_contract(result)
    return result


def invalidate(item, reason):
    """Retain historical values/signs, withdraw currentness through every nested fact."""
    if not isinstance(item,dict): return
    item.update(verdict="stale",reason=reason)
    if not item.get("signed"): item["state"]="grey"
    item["qualifier"] = reason
    for key in ("metrics","rows","facts"):
        for child in item.get(key) or []: invalidate(child,reason)


def validate_contract(body):
    """Required slice presence gate in the existing Home producer; malformed output never publishes."""
    if body.get("schema") != "WealthHome@v2": raise ValueError("Wealth Home schema missing")
    expected={"session","session_pl","account_value","temperature","regime","vix","operating_mode","health"}
    if set(body.get("header",{}).get("cells",{})) != expected: raise ValueError("Home operating header requires eight cells")
    for group, keys in (("today",TODAY),("outlook",OUTLOOK),("needs",NEEDS)):
        if set(body.get(group,{})) != set(keys): raise ValueError("Home panel coverage missing: "+group)
        for panel in body[group].values():
            if not isinstance(panel.get("rows"),list) or not isinstance(panel.get("metrics"),list): raise ValueError("Home panel rows/metrics malformed")
    for c in body["header"]["cells"].values():
        if c.get("state") not in {"green","amber","red","grey"}: raise ValueError("Home state must be a color")
        if c.get("display") is not None and c.get("value") is None: raise ValueError("Served header display requires typed value")
    return body


def serve(stored, *, now=None, header_only=False):
    """Age stored results and refresh calendar only. Does not call collect/build or any DB/provider."""
    now=now or datetime.now(UTC)
    if not isinstance(stored,dict) or stored.get("schema")!="WealthHome@v2":
        stored={"schema":"WealthHome@v2","header":{"schema":"WealthOperatingHeader@v1","cells":{k:cell(label) for k,label in (("session","Session"),("session_pl","Session P/L estimate"),("account_value","Household value"),("temperature","Temperature"),("regime","Regime"),("vix","VIX"),("operating_mode","Operating mode"),("health","Health"))}},"today":{k:section(v) for k,v in TODAY.items()},"outlook":{k:section(v) for k,v in OUTLOOK.items()},"needs":{k:section(v) for k,v in NEEDS.items()},"sources":{}}
    out=deepcopy(stored)
    product = stored.get("_product") or {}
    product_stale = bool(product) and (product.get("status") != "OK" or product.get("greyed") or product.get("slice_stale"))
    def age(item, inherited_stale=False):
        if not isinstance(item,dict): return
        stale = inherited_stale
        if "verdict" in item and item.get("source"):
            meta=source_meta(item["source"],item.get("clock"),item.get("stale_after_s"),now=now,reason=item.get("reason"),stale=item.get("verdict")=="stale")
            item.update(age_s=meta["age_s"])
            stale = stale or meta["verdict"] in ("unknown","stale")
            if stale:
                item.update(verdict=meta["verdict"],reason=meta["reason"])
                if not item.get("signed"): item["state"]=COLORS[meta["verdict"]]
        if product_stale or inherited_stale:
            invalidate(item,"Stored Home/source product is not current; retained evidence only")
        elif stale:
            item["qualifier"]=item.get("reason") or "Source freshness is unproven"
        for key in ("metrics","rows","facts"):
            for child in item.get(key) or []: age(child,stale)
    for name in ("today","outlook","needs","sources"):
        for item in out.get(name,{}).values(): age(item)
    header=out["header"]
    for item in header["cells"].values(): age(item)
    session=session_clock(now)
    header.update(as_of=iso(now),session=session,poll_after_s=300 if session["key"]=="closed" else 60)
    header["cells"]["session"]=cell("Session",session["label"],value=session,meta=source_meta("NYSE exchange calendar",now,now=now),state="grey",secondary=["Last session "+session["last_session_date"],"Next open "+timestamp(session["next_open"]).astimezone(sessions.ET).strftime("%a %b %d %H:%M ET")])
    return header if header_only else out
