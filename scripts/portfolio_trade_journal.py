"""portfolio_trade_journal.py v2 — Trade AI v12 Portfolio Intelligence"""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

def _iso_week(d):
    try: return datetime.strptime(d[:10],"%Y-%m-%d").strftime("%Y-W%W")
    except: return ""

def _days_between(a,b):
    try: return abs((datetime.strptime(b[:10],"%Y-%m-%d")-datetime.strptime(a[:10],"%Y-%m-%d")).days)
    except: return 999

def _classify(od,cd):
    if od[:10]==cd[:10]: return "DAY"
    if _iso_week(od)==_iso_week(cd): return "SWING"
    if _days_between(od,cd)<=30: return "SHORT"
    return "LONG"

def _parse_min(t):
    if not t: return None
    try:
        p=t.split(":"); return int(p[0])*60+int(p[1])
    except: return None

def _fmt_hold(mins):
    d=int(mins//1440); h=int((mins%1440)//60); m=int(mins%60)
    parts=[]
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m or not parts: parts.append(f"{m}m")
    return " ".join(parts)

def _notes_key(date,symbol,sell_price,account):
    return f"{date}_{symbol}_{sell_price:.4f}_{account}"

def load_notes(state_dir):
    p=state_dir/"trade_notes.json"
    if p.exists():
        try: return json.loads(p.read_text())
        except: return {}
    return {}

def save_note(state_dir,key,note,tags,rating,setup,execution):
    notes=load_notes(state_dir)
    notes[key]={"note":note,"tags":tags,"rating":rating,"setup":setup,
                "execution":execution,"updated":datetime.now().strftime("%Y-%m-%d %H:%M")}
    (state_dir/"trade_notes.json").write_text(json.dumps(notes,indent=2))

def match_trades_fifo(transactions,stops,notes):
    # Normalize: accept both "txn_type" and "action" fields
    for t in transactions:
        if "txn_type" not in t and "action" in t:
            _a = t["action"].lower().strip()
            if _a in ("buy","reinvest","reinvest shares","reinvest dividend","security transfer","journal","journaled shares"):
                t["txn_type"] = "buy"
            elif _a in ("sell","sold","sell short"):
                t["txn_type"] = "sell"
    txns=sorted([t for t in transactions if t.get("txn_type") in ("buy","sell") and t.get("symbol","").strip()],
                key=lambda x:((x.get("datetime_str") or x.get("date","")), 0 if x.get("txn_type")=="buy" else 1))
    lots=defaultdict(list)
    closed=[]
    for txn in txns:
        sym=txn.get("symbol","").upper().strip(); acct=txn.get("account","")
        date=txn.get("date",""); time=txn.get("time",""); dt_s=txn.get("datetime_str","") or date
        qty=abs(txn.get("quantity",0)); price=txn.get("price",0); fees=abs(txn.get("fees",0))
        key=(sym,acct)
        if qty<=0 or price<=0: continue
        if txn.get("txn_type")=="buy":
            lots[key].append({"date":date,"time":time,"dt_str":dt_s,"price":price,"qty":qty,"fee_per":fees/qty if qty>0 else 0})
        elif txn.get("txn_type")=="sell":
            remaining=qty; sfp=fees/qty if qty>0 else 0
            while remaining>0.001 and lots[key]:
                lot=lots[key][0]; matched=min(remaining,lot["qty"])
                cost=matched*lot["price"]+matched*lot.get("fee_per",0)
                proceeds=matched*price-matched*sfp
                pnl=proceeds-cost; pnl_pct=(pnl/cost*100) if cost>0 else 0
                tt=_classify(lot["date"],date)
                sd=stops.get(sym,{}); sp=sd.get("stop",0); rm=None
                if sp and sp>0 and lot["price"]>sp:
                    rps=lot["price"]-sp
                    if rps>0: rm=round((price-lot["price"])/rps,2)
                om=_parse_min(lot.get("time","")); cm=_parse_min(time)
                nkey=_notes_key(date,sym,price,acct); nd=notes.get(nkey,{})
                closed.append({
                    "symbol":sym,"account":acct,
                    "open_date":lot["date"],"open_time":lot.get("time",""),
                    "close_date":date,"close_time":time,
                    "trade_type":tt,"shares":round(matched,4),
                    "buy_price":round(lot["price"],4),"sell_price":round(price,4),
                    "cost_basis":round(cost,2),"proceeds":round(proceeds,2),
                    "pnl":round(pnl,2),"pnl_pct":round(pnl_pct,2),
                    "hold_days":_days_between(lot["date"],date),"week":_iso_week(date),
                    "r_multiple":rm,"stop_used":round(sp,2) if sp else None,
                    "open_min":om,"close_min":cm,
                    "note":nd.get("note",""),"tags":nd.get("tags",[]),
                    "rating":nd.get("rating",0),"setup":nd.get("setup",""),
                    "execution":nd.get("execution",""),"note_key":nkey,
                })
                lot["qty"]-=matched; remaining-=matched
                if lot["qty"]<=0.001: lots[key].pop(0)
            if remaining>0.001:
                nkey=_notes_key(date,sym,price,acct); nd=notes.get(nkey,{})
                closed.append({"symbol":sym,"account":acct,"open_date":"UNKNOWN","close_date":date,
                    "close_time":time,"trade_type":"UNKNOWN","shares":round(remaining,4),
                    "buy_price":0,"sell_price":round(price,4),"cost_basis":0,
                    "proceeds":round(remaining*price-fees,2),"pnl":0,"pnl_pct":0,
                    "hold_days":0,"week":_iso_week(date),"r_multiple":None,"stop_used":None,
                    "open_min":None,"close_min":_parse_min(time),
                    "note":nd.get("note",""),"tags":nd.get("tags",[]),"rating":nd.get("rating",0),
                    "setup":nd.get("setup",""),"execution":nd.get("execution",""),"note_key":nkey})
    return sorted(closed,key=lambda x:x.get("close_date",""),reverse=True)

def get_open_lots(transactions):
    txns=sorted([t for t in transactions if t.get("txn_type") in ("buy","sell") and t.get("symbol","").strip()],
                key=lambda x:((x.get("datetime_str") or x.get("date","")), 0 if x.get("txn_type")=="buy" else 1))
    lots=defaultdict(list)
    for txn in txns:
        sym=txn.get("symbol","").upper().strip(); acct=txn.get("account","")
        date=txn.get("date",""); qty=abs(txn.get("quantity",0)); price=txn.get("price",0); key=(sym,acct)
        if qty<=0 or price<=0: continue
        if txn.get("txn_type")=="buy": lots[key].append({"date":date,"price":price,"qty":qty})
        elif txn.get("txn_type")=="sell":
            rem=qty
            while rem>0.001 and lots[key]:
                lot=lots[key][0]; used=min(rem,lot["qty"]); lot["qty"]-=used; rem-=used
                if lot["qty"]<=0.001: lots[key].pop(0)
    today=datetime.now().strftime("%Y-%m-%d")
    result=[]
    for (sym,acct),lot_list in lots.items():
        for lot in lot_list:
            if lot["qty"]>0.001:
                result.append({"symbol":sym,"account":acct,"open_date":lot["date"],
                    "shares":round(lot["qty"],4),"buy_price":round(lot["price"],4),
                    "cost_basis":round(lot["qty"]*lot["price"],2),
                    "days_held":_days_between(lot["date"],today)})
    return sorted(result,key=lambda x:-x.get("days_held",0))

def compute_equity_curve(trades):
    by_date=defaultdict(float)
    for t in trades: by_date[t.get("close_date","")[:10]]+=t.get("pnl",0)
    dates=sorted(by_date.keys()); cum=0.0; result=[]
    for d in dates:
        cum+=by_date[d]
        result.append({"date":d,"daily_pnl":round(by_date[d],2),"cumulative":round(cum,2)})
    return result

def compute_drawdown(eq):
    peak=0.0; result=[]
    for p in eq:
        cum=p["cumulative"]
        if cum>peak: peak=cum
        dd=cum-peak; ddp=(dd/peak*100) if peak>0 else 0
        result.append({**p,"drawdown":round(dd,2),"drawdown_pct":round(ddp,2),"peak":round(peak,2)})
    return result

def compute_rolling_winrate(trades,window=20):
    st=sorted(trades,key=lambda x:x.get("close_date",""))
    result=[]
    for i in range(len(st)):
        w=st[max(0,i-window+1):i+1]; wins=sum(1 for t in w if t.get("pnl",0)>0)
        wr=(wins/len(w)*100) if w else 0
        result.append({"date":st[i].get("close_date",""),"win_rate":round(wr,1),"n":len(w)})
    return result

def compute_time_scatter(trades):
    result=[]
    for t in trades:
        m=t.get("close_min")
        if m is not None:
            h=m//60; mins=m%60
            result.append({"close_min":m,"time_label":f"{h:02d}:{mins:02d}",
                "pnl":t.get("pnl",0),"symbol":t.get("symbol",""),"is_win":t.get("pnl",0)>0})
    return sorted(result,key=lambda x:x["close_min"])

def compute_stats(trades):
    if not trades: return {}
    pnls=[t["pnl"] for t in trades if t.get("open_date","")!="UNKNOWN"]
    winners=[p for p in pnls if p>0]; losers=[p for p in pnls if p<0]
    by_date=defaultdict(float); by_date_cnt=defaultdict(int)
    for t in trades:
        d=t.get("close_date","")[:10]; by_date[d]+=t.get("pnl",0); by_date_cnt[d]+=1
    dp=list(by_date.values())
    wd=sum(1 for p in dp if p>0); ld=sum(1 for p in dp if p<0); bd=sum(1 for p in dp if p==0)
    cw=cl=cuw=cul=0
    for t in sorted(trades,key=lambda x:x.get("close_date","")):
        if t.get("pnl",0)>0: cuw+=1; cul=0
        elif t.get("pnl",0)<0: cul+=1; cuw=0
        cw=max(cw,cuw); cl=max(cl,cul)
    htw=[t["hold_days"]*1440 for t in trades if t.get("pnl",0)>0 and t.get("hold_days",0)>=0]
    htl=[t["hold_days"]*1440 for t in trades if t.get("pnl",0)<0 and t.get("hold_days",0)>=0]
    hta=[t["hold_days"]*1440 for t in trades if t.get("hold_days",0)>=0]
    ahr=sum(hta)/len(hta) if hta else 0; ahrw=sum(htw)/len(htw) if htw else 0; ahrl=sum(htl)/len(htl) if htl else 0
    rs=[t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    ar=round(sum(rs)/len(rs),2) if rs else None
    by_type={}
    for tt in ("DAY","SWING","SHORT","LONG"):
        ttt=[t for t in trades if t.get("trade_type")==tt]
        if ttt:
            wins=[t for t in ttt if t["pnl"]>0]
            by_type[tt]={"count":len(ttt),"total_pnl":round(sum(t["pnl"] for t in ttt),2),
                "winners":len(wins),"win_rate":round(len(wins)/len(ttt)*100,1),
                "avg_pnl":round(sum(t["pnl"] for t in ttt)/len(ttt),2),
                "best":max(ttt,key=lambda x:x["pnl"]),"worst":min(ttt,key=lambda x:x["pnl"])}
    by_sym={}
    for t in trades:
        s=t.get("symbol","")
        if s not in by_sym: by_sym[s]={"count":0,"total_pnl":0,"wins":0,"rs":[]}
        by_sym[s]["count"]+=1; by_sym[s]["total_pnl"]=round(by_sym[s]["total_pnl"]+t["pnl"],2)
        if t["pnl"]>0: by_sym[s]["wins"]+=1
        if t.get("r_multiple") is not None: by_sym[s]["rs"].append(t["r_multiple"])
    for s,d in by_sym.items():
        d["win_rate"]=round(d["wins"]/d["count"]*100,1) if d["count"] else 0
        d["avg_r"]=round(sum(d["rs"])/len(d["rs"]),2) if d["rs"] else None
        del d["rs"]
    by_acct=defaultdict(lambda:{"count":0,"total_pnl":0,"wins":0})
    for t in trades:
        a=t.get("account",""); by_acct[a]["count"]+=1
        by_acct[a]["total_pnl"]=round(by_acct[a]["total_pnl"]+t["pnl"],2)
        if t["pnl"]>0: by_acct[a]["wins"]+=1
    by_week={}
    for t in trades:
        wk=t.get("week","")
        if wk: by_week[wk]=round(by_week.get(wk,0)+t["pnl"],2)
    eq=compute_equity_curve(trades); dd=compute_drawdown(eq)
    max_dd=min((d["drawdown"] for d in dd),default=0)
    max_ddp=min((d["drawdown_pct"] for d in dd),default=0)
    return {
        "total_trades":len(trades),"total_pnl":round(sum(pnls),2),
        "win_rate":round(len(winners)/len(pnls)*100,1) if pnls else 0,
        "profit_factor":round(sum(winners)/abs(sum(losers)),2) if losers else 0,
        "avg_winner":round(sum(winners)/len(winners),2) if winners else 0,
        "avg_loser":round(sum(losers)/len(losers),2) if losers else 0,
        "trade_expectancy":round(sum(pnls)/len(pnls),2) if pnls else 0,
        "num_winners":len(winners),"num_losers":len(losers),"num_breakeven":len([p for p in pnls if p==0]),
        "total_trading_days":len(by_date),"winning_days":wd,"losing_days":ld,"breakeven_days":bd,
        "avg_daily_pnl":round(sum(dp)/len(dp),2) if dp else 0,
        "avg_winning_day":round(sum(p for p in dp if p>0)/wd,2) if wd else 0,
        "avg_losing_day":round(sum(p for p in dp if p<0)/ld,2) if ld else 0,
        "largest_profit_day":round(max(dp),2) if dp else 0,"largest_loss_day":round(min(dp),2) if dp else 0,
        "max_consec_wins":cw,"max_consec_losses":cl,
        "avg_hold_all":_fmt_hold(ahr),"avg_hold_win":_fmt_hold(ahrw),"avg_hold_lose":_fmt_hold(ahrl),
        "avg_r_multiple":ar,"r_multiple_count":len(rs),
        "best_trade":max(trades,key=lambda x:x["pnl"]) if trades else {},
        "worst_trade":min(trades,key=lambda x:x["pnl"]) if trades else {},
        "by_type":by_type,"by_symbol":dict(sorted(by_sym.items(),key=lambda x:abs(x[1]["total_pnl"]),reverse=True)),
        "by_account":dict(by_acct),"by_week":dict(sorted(by_week.items(),reverse=True)),
        "equity_curve":eq,"drawdown_data":dd,
        "rolling_winrate":compute_rolling_winrate(sorted(trades,key=lambda x:x.get("close_date",""))),
        "time_scatter":compute_time_scatter(trades),
        "max_drawdown":round(max_dd,2),"max_drawdown_pct":round(max_ddp,2),
    }

def build_trade_journal(portfolio,state_dir):
    all_txns=portfolio.get("transactions",[]) or portfolio.get("trade_journal",[])
    if not all_txns:
        return {"closed_trades":[],"open_lots":[],"stats":{},"has_data":False,
                "note":"No transaction history. Export Schwab History CSV to data/portfolios/input/"}
    try:
        from portfolio_stops import load_stops
        stops=load_stops(state_dir)
    except Exception:
        stops={}
    notes=load_notes(state_dir)
    closed=match_trades_fifo(all_txns,stops,notes)
    open_l=get_open_lots(all_txns)
    stats=compute_stats(closed)
    result={"has_data":True,"closed_trades":closed,"open_lots":open_l,
            "day_trades":[t for t in closed if t["trade_type"]=="DAY"],
            "swing_trades":[t for t in closed if t["trade_type"]=="SWING"],
            "stats":stats,"all_symbols":sorted(set(t["symbol"] for t in closed)),
            "all_accounts":sorted(set(t["account"] for t in closed)),
            "last_updated":datetime.now().strftime("%Y-%m-%d %H:%M"),"txn_count":len(all_txns)}
    (state_dir/"trade_journal.json").write_text(json.dumps(result,indent=2,default=str))
    return result
