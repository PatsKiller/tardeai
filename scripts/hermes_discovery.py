#!/usr/bin/env python3
"""hermes_discovery.py — Discovery & Watchlist Builder (D-1). Turn a sector/theme/company/supply-chain/
free-form query into a ranked list of relevant PUBLIC companies via the FREE Grok/ChatGPT OAuth lanes,
then (optionally) add them to the watchlist where the existing enrichment + Hermes scoring (H-1..H-7)
take over. Advisory; no execution; no API keys (OAuth only).

  python3 scripts/hermes_discovery.py --query "companies that supply NVIDIA" [--lane grok] [--apply]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
from cio_agent_contract import build_discovery_evidence_footer

REL_TYPES = {"supplier", "customer", "partner", "competitor", "ecosystem", "enabling", "direct exposure", "indirect"}
EXPOSURE = {"high", "medium", "low"}


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _detect_mode(q):
    ql = q.lower()
    if any(w in ql for w in ("suppl", "partners of", "partner of", "vendor", "who supplies", "supply chain", "customers of", "makes parts")):
        return "supply_chain"
    if any(w in ql for w in ("sector", "semiconductor", "biotech", "utilities", "financials", "industrials", "materials")):
        return "sector"
    if len(q.split()) == 1 and q.strip().isupper() and 1 <= len(q.strip()) <= 5:
        return "company"
    return "theme"


def _prompt(query, mode):
    extra = {"supply_chain": " Focus on the actual supply chain: suppliers, manufacturers, equipment/component makers, and key customers — label the relationship precisely.",
             "company": " Treat the input as a company and map its ecosystem: suppliers, customers, partners, and direct competitors.",
             "sector": " Cover the leaders plus credible secondary and emerging names in the sector.",
             "theme": " Cover core beneficiaries, secondary/exposure plays, and enabling/infrastructure names."}.get(mode, "")
    return (
        f'You are an elite equity research analyst. For the query: "{query}".{extra}\n'
        "Identify relevant PUBLIC, currently-listed companies (prefer US-listed; give the real exchange ticker). "
        "Return ONLY a JSON array (no prose, no markdown fences), 10-18 items, ordered by relevance descending. "
        "Each item EXACTLY: "
        '{"ticker":"NVDA","company_name":"NVIDIA","relevance_score":0-100,'
        '"relationship_type":"direct exposure|supplier|customer|partner|competitor|ecosystem|enabling",'
        '"exposure_strength":"high|medium|low","reason":"one concise sentence on why it matches"}. '
        "Tickers must be real and tradable. Do not invent tickers. relevance_score reflects strength + directness of the link."
    ) + build_discovery_evidence_footer()


def _call_lane(lane, prompt):
    import hermes_external_researcher as h
    if lane == "grok":
        cfg = h.LANE_CFG["grok"]
        return h.call_xai_proxy(cfg["url"], cfg["default_model"], prompt, max_tokens=2600)
    if lane == "chatgpt":
        return h.call_codex_cli(h.LANE_CFG["chatgpt"]["default_model"], prompt)
    raise ValueError(f"unknown lane {lane}")


def _parse(raw):
    if not raw:
        return []
    raw = re.sub(r"```(json)?", "", raw)
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return []
    out = []
    for it in arr if isinstance(arr, list) else []:
        if not isinstance(it, dict):
            continue
        t = str(it.get("ticker", "")).upper().strip()
        if not re.match(r"^[A-Z][A-Z.\-]{0,6}$", t):
            continue
        try:
            rs = max(0.0, min(100.0, float(it.get("relevance_score", 50))))
        except Exception:
            rs = 50.0
        rel = str(it.get("relationship_type", "")).lower().strip()
        exp = str(it.get("exposure_strength", "")).lower().strip()
        out.append({"ticker": t, "company_name": str(it.get("company_name", ""))[:120],
                    "relevance_score": round(rs, 1),
                    "relationship_type": rel if rel in REL_TYPES else "ecosystem",
                    "exposure_strength": exp if exp in EXPOSURE else "medium",
                    "reason": str(it.get("reason", ""))[:300]})
    # dedup by ticker, keep highest relevance
    seen, dedup = {}, []
    for r in sorted(out, key=lambda x: -x["relevance_score"]):
        if r["ticker"] in seen:
            continue
        seen[r["ticker"]] = 1; dedup.append(r)
    return dedup


def _verify(conn, tickers):
    if not tickers:
        return set()
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT symbol FROM market_quotes WHERE symbol = ANY(%s)
                   UNION SELECT DISTINCT display_name FROM intelligence_entities WHERE display_name = ANY(%s)""",
                (tickers, tickers))
    return {r[0] for r in cur.fetchall()}


def run(query, lane="deepseek-flash", mode=None, apply=False, created_by="operator"):
    mode = mode or _detect_mode(query)
    conn = _conn(); cur = conn.cursor()
    qid = None
    if apply:
        cur.execute("INSERT INTO discovery_queries (query, mode, lane, status, created_by) VALUES (%s,%s,%s,'running',%s) RETURNING id",
                    (query, mode, lane, created_by))
        qid = cur.fetchone()[0]; conn.commit()
    try:
        raw = _call_lane(lane, _prompt(query, mode))
        results = _parse(raw)
    except Exception as e:
        if apply and qid:
            cur.execute("UPDATE discovery_queries SET status='error' WHERE id=%s", (qid,)); conn.commit()
        return {"query": query, "mode": mode, "error": str(e)[:160], "results": []}
    verified = _verify(conn, [r["ticker"] for r in results])
    for r in results:
        r["verified"] = r["ticker"] in verified
    if apply and qid:
        for r in results:
            cur.execute("""INSERT INTO discovery_results (query_id, ticker, company_name, relevance_score,
                             relationship_type, exposure_strength, reason, verified)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (qid, r["ticker"], r["company_name"], r["relevance_score"], r["relationship_type"],
                         r["exposure_strength"], r["reason"], r["verified"]))
        cur.execute("UPDATE discovery_queries SET status='done', result_count=%s WHERE id=%s", (len(results), qid))
        conn.commit()
    return {"query_id": qid, "query": query, "mode": mode, "lane": lane, "count": len(results), "results": results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--lane", default="deepseek-flash", choices=["deepseek-flash", "grok", "chatgpt"])
    ap.add_argument("--mode", default=None)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(a.query, a.lane, a.mode, a.apply), indent=2))


if __name__ == "__main__":
    main()
