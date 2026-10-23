#!/usr/bin/env python3
"""
Hermes momentum catalyst researcher.
Queries SearXNG for news catalysts on TradeAI momentum candidates.
Writes advisory-only context — NOT a trade signal.

SCALP HOT TIER (operator decision (4), 2026-10-10; inert unless SCALP_HOT_TIER=1, no kill file, AND the search routing
engine is importable — lib/scalp_research_route): every search goes through the routing engine (request class
scalp_priority / scalp_research, shared 20-min (subject, intent) cache in the engine) instead of SearXNG directly;
``--source scalp`` researches only names new to the scalp list or whose last research today is older than 30 min;
``--on-list-advance`` runs the lane only when the scalp list's as_of advanced (lib/scalp_list_trigger, consumer
hermes-scalp-catalyst) and otherwise exits 0 with the gate decision. With the knob off (or no engine) the search path
is the legacy one and ``--on-list-advance`` fires only on the legacy :25 slot.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:18888/search")
MAX_SOURCES_PER_TICKER = 3
MAX_TOTAL_SOURCES = 15
#: 2026-10-16 (operator: AT alerts "should have the same source data"): at most this many Active Trader hot symbols
#: (data broker lib.data_broker.microstructure.live_symbols) are added to a scalp run, after the scalp names.
AT_RESEARCH_SYMBOL_CAP = 8
#: The lane runs under `timeout 5m`; stop starting new tickers after this many seconds so the merge+write always
#: happens inside the timeout (a ticker is <= 3 searches x 10 s + 1.5 s sleep).
RESEARCH_DEADLINE_S = 240.0

_ENV_KEYS = frozenset({"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "SEARXNG_URL"})


def _load_env():
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("\'\"")
                if k in _ENV_KEYS:
                    os.environ.setdefault(k, v)


CATALYST_TYPES = {
    "earnings": ["earnings", "EPS", "revenue", "guidance", "beat", "miss"],
    "analyst": ["upgrade", "downgrade", "price target", "analyst", "rating"],
    "regulatory": ["FDA", "approval", "clearance", "lawsuit", "SEC"],
    "manda": ["acquisition", "merger", "buyout", "takeover"],
    "offering": ["offering", "dilution", "shelf", "ATM offering"],
    "contract": ["contract", "award", "partnership", "deal"],
    "sector": ["sector", "industry", "rotation"],
    "social": ["reddit", "wallstreetbets", "trending", "viral"],
}


def classify_catalyst(text):
    """Classify catalyst type from text."""
    text_lower = text.lower()
    for ctype, keywords in CATALYST_TYPES.items():
        if any(kw.lower() in text_lower for kw in keywords):
            return ctype
    return "news_momentum"


def _hot_research_on():
    """Hot-tier research path: knob on AND the routing engine importable (never a direct provider call)."""
    try:
        from lib import scalp_hot_tier as hot
        from lib import scalp_research_route as route
    except Exception:
        return False
    return hot.enabled() and route.engine_available()


def _routed(symbol, query_suffix, *, caller, dry_run, priority):
    from lib import scalp_research_route as route

    r = route.route(symbol, query_suffix, caller=caller or "hermes_scalp_catalyst", priority=priority,
                    dry_run=dry_run, limit=MAX_SOURCES_PER_TICKER)
    if not r.get("ok"):
        return [{"error": f"routing:{r.get('decision')}:{r.get('denied_reason') or ''}"[:100]}]
    try:
        from hermes_source_policy import filter_search_results
        results = filter_search_results(r.get("results") or [])
    except Exception:
        results = r.get("results") or []
    return [{
        "title": x.get("title", ""),
        "url": x.get("url", ""),
        "content": (x.get("content") or x.get("snippet") or "")[:200],
        "engine": x.get("engine") or r.get("provider") or "",
        "published": x.get("published") or x.get("publishedDate", ""),
        "routed": {"provider": r.get("provider"), "cache_hit": r.get("cache_hit"), "decision": r.get("decision")},
    } for x in results[:MAX_SOURCES_PER_TICKER]]


def _routed_search(symbol, query, candidate=None, caller="hermes_momentum_catalyst", intent=None):
    """Search routing engine path (2026-10-10), or None when SEARCH_ROUTING_ENGINE is off.

    Class catalyst_confirmation, promoted to scalp_priority when scripts/lib/scalp_priority.py marks the
    symbol about to fire (on the scalp list, near the GO line or showing momentum, not researched in 30
    min). The cache is keyed on (symbol, intent) so L708 and L379 share one entry per intent. Same row shape
    as the SearXNG path below, so downstream code is unchanged."""
    try:
        from lib import search_router
    except ImportError:  # pragma: no cover
        from scripts.lib import search_router  # type: ignore
    if not search_router.engine_enabled():
        return None
    out = search_router.route_search(
        query, request_class="scalp_research", caller=caller, subject=symbol, intent=intent or query,
        categories="news", limit=MAX_SOURCES_PER_TICKER, cache_ttl_s=1200,
        candidates=[candidate] if isinstance(candidate, dict) else [])
    if not out["results"]:
        # A declared no_coverage is an honest empty answer; anything else is an error row.
        reason = str(out.get("denied_reason") or "")
        return [] if reason.startswith("NO_COVERAGE") else [{"error": reason[:100]}]
    results = out["results"][:MAX_SOURCES_PER_TICKER]
    try:
        from hermes_source_policy import filter_search_results
        results = filter_search_results(results)
    except Exception:
        pass
    return [{k: r.get(k, "") for k in ("title", "url", "content", "engine", "published")} for r in results]


def search_catalyst(symbol, query_suffix="latest news", *, caller=None, dry_run=False, priority=False,
                    candidate=None):
    """Query a symbol's catalyst. Hot tier on (+ routing engine): Q's routed path; else SEARCH_ROUTING_ENGINE=1:
    the routing engine (class catalyst_confirmation, promotable to scalp_priority); else SearXNG, unchanged."""
    if _hot_research_on():
        return _routed(symbol, query_suffix, caller=caller, dry_run=dry_run, priority=priority)
    query = f"{symbol} stock {query_suffix}"
    try:
        routed = _routed_search(symbol, query, candidate, caller or "hermes_momentum_catalyst", intent=query_suffix)
    except Exception as e:  # noqa: BLE001 — same contract as the SearXNG path: an error row, never a raise
        routed = [{"error": f"router:{type(e).__name__}"}]
    if routed is not None:
        return routed
    params = urllib.parse.urlencode({
        "q": query, "format": "json", "categories": "news",
        "time_range": "day", "engines": "google news,bing news,duckduckgo"
    })
    try:
        req = urllib.request.Request(f"{SEARXNG_URL}?{params}", method="GET")
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        results = data.get("results", [])[:MAX_SOURCES_PER_TICKER]
        try:
            from hermes_source_policy import filter_search_results
            results = filter_search_results(results)
        except Exception:
            pass
        return [{
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", "")[:200],
            "engine": r.get("engine", ""),
            "published": r.get("publishedDate", ""),
        } for r in results]
    except Exception as e:
        return [{"error": str(e)[:100]}]


def research_ticker(symbol, *, dry_run=False, priority=False, caller=None):
    """Research a single ticker for catalysts."""
    queries = [
        "latest news",
        "premarket catalyst",
        "earnings guidance analyst",
    ]
    all_sources = []
    for q in queries:
        if len(all_sources) >= MAX_SOURCES_PER_TICKER:
            break
        sources = search_catalyst(symbol, q, caller=caller, dry_run=dry_run, priority=priority)
        for s in sources:
            if not s.get("error") and s.get("url") not in [x.get("url") for x in all_sources]:
                all_sources.append(s)
        time.sleep(0.5)  # Rate limit

    # Classify
    catalyst_type = "no_clear_catalyst"
    catalyst_summary = "No clear catalyst found"
    confidence = 0.2

    if all_sources and not all_sources[0].get("error"):
        best = all_sources[0]
        catalyst_type = classify_catalyst(best.get("title", "") + " " + best.get("content", ""))
        catalyst_summary = best.get("title", "")[:100]
        confidence = min(0.7, 0.3 + 0.1 * len(all_sources))

    return {
        "symbol": symbol,
        "research_timestamp": datetime.now().isoformat(),
        "catalyst_type": catalyst_type,
        "catalyst_summary": catalyst_summary,
        "catalyst_strength": "high" if confidence >= 0.5 else "low",
        "confidence": confidence,
        "source_count": len([s for s in all_sources if not s.get("error")]),
        "source_domains": list(set(urllib.parse.urlparse(s.get("url", "")).netloc for s in all_sources if s.get("url"))),
        "sources": all_sources,
        "advisory_only": True,
        "not_trade_signal": True,
        "no_execution": True,
    }


def run(candidates, dry_run=True, output_path=None, merge=True, max_total_sources=None, priority=None,
        mirror_path=None, deadline_s=None):
    """Research all candidates. merge=True updates the day's JSONL by symbol instead of clobbering it,
    so the momentum and scalp lanes can share one file without overwriting each other."""
    cap = MAX_TOTAL_SOURCES if max_total_sources is None else max_total_sources
    results = []
    total_sources = 0
    t0 = time.monotonic()

    for c in candidates:
        if total_sources >= cap:
            break
        if deadline_s is not None and time.monotonic() - t0 >= deadline_s:
            print(f"  research deadline {deadline_s:g}s reached; {len(results)} researched, rest deferred")
            break
        sym = c["symbol"] if isinstance(c, dict) else c
        print(f"  Researching {sym}...", end=" ", flush=True)
        result = research_ticker(sym, dry_run=dry_run, priority=sym in (priority or ()),
                                 caller="hermes_scalp_catalyst")
        total_sources += result["source_count"]
        results.append(result)
        status = f"{result['catalyst_type']} ({result['source_count']} sources, conf {result['confidence']:.1f})"
        print(status)

    # Write output (merge by symbol so a second lane doesn't clobber the first)
    if not dry_run and output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        by_symbol = {}
        # First run after the 2026-10-16 move: seed today's merge from the legacy code-root copy.
        seed = output_path if Path(output_path).exists() else mirror_path
        if merge and seed and Path(seed).exists():
            for line in Path(seed).read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    by_symbol[str(rec.get("symbol", "")).upper()] = rec
                except Exception:
                    continue
        for r in results:
            by_symbol[str(r["symbol"]).upper()] = r
        body = "".join(json.dumps(rec, default=str) + "\n" for rec in by_symbol.values())
        tmp = Path(str(output_path) + ".tmp")
        tmp.write_text(body)
        os.replace(tmp, output_path)
        if mirror_path and Path(mirror_path) != Path(output_path):
            # Compat mirror for readers still on ROOT/data/hermes/momentum_catalysts (lib/hermes_catalyst_store).
            try:
                Path(mirror_path).parent.mkdir(parents=True, exist_ok=True)
                mtmp = Path(str(mirror_path) + ".tmp")
                mtmp.write_text(body)
                os.replace(mtmp, mirror_path)
            except OSError as e:
                print(f"  compat mirror write failed: {e}")

    return results


def get_scalp_candidates(max_tickers=15, *, read_errors=None):
    """Today's distinct social-scalp candidates (WAIT/GO) whose GO tier depends on catalyst
    verification — highest score first. Read-only."""
    import psycopg2
    syms = []
    try:
        conn = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
                                dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
                                password=os.getenv("DB_PASSWORD"))
        cur = conn.cursor()
        # Social scouts that are blocked ONLY on catalyst verification come first (2026-10-05:
        # SDEV sat "AWAITING_CATALYST_VERIFICATION" all morning because a score-ranked list of
        # GO/WAIT names never reached it); then the highest-scoring GO/WAIT names.
        cur.execute("""SELECT symbol FROM scalp_scan_results
                       WHERE scanned_at::date = current_date
                         AND route_reason_codes::text LIKE '%%AWAITING_CATALYST_VERIFICATION%%'
                       GROUP BY symbol ORDER BY max(score) DESC NULLS LAST LIMIT %s""", (max_tickers,))
        syms = [r[0] for r in cur.fetchall()]
        cur.execute("""SELECT symbol FROM scalp_scan_results
                       WHERE scanned_at::date = current_date AND decision IN ('GO','WAIT')
                       GROUP BY symbol ORDER BY max(score) DESC NULLS LAST LIMIT %s""", (max_tickers,))
        syms += [r[0] for r in cur.fetchall() if r[0] not in syms]
        syms = syms[:max_tickers]
        conn.close()
    except Exception as e:
        print(f"scalp candidate read failed: {e}")
        if read_errors is not None:
            read_errors.append(type(e).__name__)
    return syms


def researched_today(output_path):
    """{SYMBOL: last research_timestamp (naive local datetime)} from the day's JSONL. Read-only."""
    out = {}
    try:
        lines = Path(output_path).read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
            ts = datetime.fromisoformat(str(rec.get("research_timestamp")))
        except Exception:
            continue
        sym = str(rec.get("symbol") or "").upper()
        if sym and (sym not in out or ts > out[sym]):
            out[sym] = ts.replace(tzinfo=None) if ts.tzinfo is None else ts.astimezone().replace(tzinfo=None)
    return out


def select_hot_candidates(awaiting, scalp_candidates, list_symbols, researched, *, now=None,
                          stale_min=30.0, cap=15):
    """Names new to the list or last researched > stale_min ago, catalyst-awaiting first, then new list arrivals,
    then the rest; capped. Pure."""
    ref = now or datetime.now()
    ordered = []
    for s in list(awaiting) + [x for x in list_symbols if x not in researched] + list(scalp_candidates) + list(
            list_symbols):
        s = str(s).upper()
        if s and s not in ordered:
            ordered.append(s)
    keep = [s for s in ordered
            if s not in researched or (ref - researched[s]).total_seconds() / 60.0 > stale_min]
    return keep[:cap]


def active_trader_hot_symbols(*, now=None, read_errors=None):
    """The Active Trader recorder's live symbols through the Command Center data broker
    (lib.data_broker.microstructure.live_symbols: a published store, zero provider calls). [] when stale/absent."""
    try:
        from lib.data_broker import microstructure as micro
        return [str(s).upper() for s in micro.live_symbols(now=time.time() if now is None else now) if s]
    except Exception as e:  # noqa: BLE001
        if read_errors is not None:
            read_errors.append(f"at_live_symbols:{type(e).__name__}")
        return []


def union_with_at_symbols(candidates, at_symbols, *, cap=AT_RESEARCH_SYMBOL_CAP):
    """Scalp candidates first (unchanged order), then up to ``cap`` AT hot symbols not already present. Pure."""
    out = list(candidates or [])
    seen = {str(c["symbol"] if isinstance(c, dict) else c).upper() for c in out}
    added = 0
    for s in at_symbols or []:
        s = str(s).upper()
        if not s or s in seen or added >= cap:
            continue
        out.append(s)
        seen.add(s)
        added += 1
    return out


def focus_gate(candidates):
    """Operator 2026-10-23: "this should just be critiqued at least the top 20". Scalp-list candidates are cut to the
    scalp FOCUS list (lib/scalp_focus) while a fresh one exists; no fresh list -> unchanged (fail-soft). The Active
    Trader recorder's live symbols (your fills first) are added after this and are not cut. Never raises."""
    try:
        from lib import scalp_focus as sf
        return sf.restrict_to_focus(candidates, cfg=sf.load_config())
    except Exception as e:  # noqa: BLE001
        return list(candidates), {"applied": False, "error": type(e).__name__}


def get_awaiting_catalyst(max_tickers=15, *, read_errors=None):
    """Today's names blocked only on catalyst verification (the scalp_priority class). Read-only."""
    import psycopg2
    try:
        conn = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
                                dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
                                password=os.getenv("DB_PASSWORD"))
        cur = conn.cursor()
        cur.execute("""SELECT symbol FROM scalp_scan_results
                       WHERE scanned_at::date = current_date
                         AND route_reason_codes::text LIKE '%%AWAITING_CATALYST_VERIFICATION%%'
                       GROUP BY symbol ORDER BY max(score) DESC NULLS LAST LIMIT %s""", (max_tickers,))
        syms = [r[0] for r in cur.fetchall()]
        conn.close()
        return syms
    except Exception as e:
        print(f"awaiting-catalyst read failed: {e}")
        if read_errors is not None:
            read_errors.append(type(e).__name__)
        return []


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--source", choices=["momentum", "scalp"], default="momentum",
                    help="Which candidate pool to research: TradeAI momentum lane or today's social-scalp candidates.")
    ap.add_argument("--max-tickers", type=int, default=5)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--on-list-advance", action="store_true",
                    help="scalp hot tier: run only when the scalp list's as_of advanced (event trigger)")
    args = ap.parse_args(argv)


    if args.dry_run:
        print(f"DRY-RUN hermes-momentum-catalyst-scalp: would research {args.source} candidates; max_tickers={args.max_tickers}")
        return 0
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    record = args.apply and args.source == "scalp"
    try:
        _load_env()
        counts = _execute(args)
    except Exception as exc:
        if record:
            write_lane_receipt("hermes-momentum-catalyst-scalp", ok=False, exit_code=1,
                               started_at=started, summary={}, error=type(exc).__name__,
                               output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}})
        raise
    if record:
        failed = bool(counts.get("gate_skipped") or counts.get("candidate_read_failures"))
        write_lane_receipt("hermes-momentum-catalyst-scalp", ok=not failed, exit_code=0,
                           started_at=started, summary=counts,
                           error="gate_skipped" if counts.get("gate_skipped") else ("candidate_read_failed" if failed else None),
                           output=lane_output(counts))
    return 0


def lane_output(counts: dict) -> dict:
    """LaneRunReceipt@v2 output fields (n8n expected_output, unit: ticker catalyst records written to the day's
    momentum_catalysts JSONL). attempted = candidates selected; a candidate read failure is ``dependency_unavailable``;
    no candidate = ``no_new_input``; a list-trigger gate skip = ``nothing_due``."""
    tickers = int(counts.get("tickers") or 0)
    skipped = {"dependency_unavailable": int(counts.get("candidate_read_failures") or 0),
               "source_cap_reached": max(int(counts.get("candidates") or 0) - tickers, 0)}
    reason = None
    if tickers == 0:
        reason = "nothing_due" if counts.get("gate_skipped") else "no_new_input"
    return {"produced_count": tickers, "attempted_count": max(int(counts.get("candidates") or 0), tickers),
            "skipped_reasons": skipped, "empty_reason": reason}


def _execute(args):
    read_errors = []
    today = datetime.now().strftime("%Y-%m-%d")
    from lib import hermes_catalyst_store as store
    out = str(store.day_file(today))
    legacy = str(store.legacy_day_file(today, PROJECT_ROOT))
    hot_research = args.source == "scalp" and _hot_research_on()
    gate = None
    priority = []
    if args.on_list_advance:
        from lib import scalp_list_trigger as trig
        from lib.data_broker import scalp_list as sl
        try:
            list_env = sl.get_scalp_list()
        except Exception as e:
            list_env = {"as_of": None, "symbols": [], "error": str(e)[:200]}
        gate = {"list_env": list_env,
                "decision": trig.decide("hermes-scalp-catalyst", list_env, hot_enabled=hot_research)}
        print(json.dumps({"gate": "scalp_list_trigger", **gate["decision"]}, default=str))
        if not gate["decision"]["fire"]:
            return {"gate_skipped": 1, "tickers": 0, "sources": 0}

    if args.source == "scalp" and hot_research:
        from lib import scalp_hot_tier as hot
        list_syms = list(((gate or {}).get("list_env") or {}).get("symbols") or [])
        if gate is None:
            from lib.data_broker import scalp_list as sl
            list_syms = list(sl.get_scalp_list().get("symbols") or [])
        priority = get_awaiting_catalyst(max_tickers=hot.RESEARCH_SYMBOL_CAP, read_errors=read_errors)
        candidates = select_hot_candidates(priority, get_scalp_candidates(max_tickers=hot.RESEARCH_SYMBOL_CAP, read_errors=read_errors),
                                           list_syms, researched_today(out), stale_min=hot.RESEARCH_STALE_MIN,
                                           cap=hot.RESEARCH_SYMBOL_CAP)
        _cap = 40
        print(f"[hot-tier] {len(candidates)} names new to the list or > {hot.RESEARCH_STALE_MIN:g} min stale "
              f"(priority {len(priority)}); search via routing engine")
    elif args.source == "scalp":
        candidates = get_scalp_candidates(max_tickers=max(args.max_tickers, 15), read_errors=read_errors)
        _cap = 40  # cover ~15 scalp candidates × up to 3 sources
    else:
        from hermes_momentum_candidate_reader import get_momentum_candidates
        candidates = get_momentum_candidates(max_tickers=args.max_tickers)
        _cap = None
    focus_report = None
    if args.source == "scalp":
        candidates, focus_report = focus_gate(candidates)
        if focus_report.get("applied"):
            print(f"[focus] critique limited to the focus list: kept {focus_report.get('kept')}, "
                  f"skipped {len(focus_report.get('dropped') or [])} non-focus names")
    if args.source == "scalp":
        at_syms = active_trader_hot_symbols(read_errors=read_errors)
        before = len(candidates)
        candidates = union_with_at_symbols(candidates, at_syms, cap=AT_RESEARCH_SYMBOL_CAP)
        if at_syms:
            print(f"[at] +{len(candidates) - before} Active Trader hot symbols (of {len(at_syms)}, "
                  f"cap {AT_RESEARCH_SYMBOL_CAP}) via data broker")
    if not candidates:
        print(f"No {args.source} candidates found.")
        if gate is not None and args.apply:
            trig.commit("hermes-scalp-catalyst", gate["list_env"], decision=gate["decision"]["decision"])
        return {"tickers": 0, "sources": 0, "candidate_read_failures": len(read_errors)}

    print(f"Researching {len(candidates)} {args.source} candidates...")

    results = run(candidates, dry_run=not args.apply, output_path=out, merge=True, max_total_sources=_cap,
                  priority=set(priority), mirror_path=legacy, deadline_s=RESEARCH_DEADLINE_S)
    if gate is not None and args.apply:
        trig.commit("hermes-scalp-catalyst", gate["list_env"], decision=gate["decision"]["decision"])

    print(f"\nResults: {len(results)} tickers")
    with_catalyst = sum(1 for r in results if r["catalyst_type"] != "no_clear_catalyst")
    print(f"  With catalyst: {with_catalyst}")
    print(f"  No catalyst: {len(results) - with_catalyst}")
    print(f"  Total sources: {sum(r['source_count'] for r in results)}")
    if not args.apply:
        print("\nDry-run. Use --apply to write.")

    return {"tickers": len(results), "with_catalyst": with_catalyst,
            "sources": sum(r["source_count"] for r in results),
            "candidate_read_failures": len(read_errors), "candidates": len(candidates),
            "focus_gate_applied": bool((focus_report or {}).get("applied")),
            "focus_gate_skipped": len((focus_report or {}).get("dropped") or [])}


if __name__ == "__main__":
    raise SystemExit(main())
