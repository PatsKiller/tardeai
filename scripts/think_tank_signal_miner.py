"""think_tank_signal_miner.py — Multi-source trend signal mining for the think tank.

Sources: Hermes research DB, RSS/news_articles, catalyst_events, Finnhub/API feeds,
SearXNG web probe, RS/RSI leaders (enrichment + snapshots), new-site discovery,
and LLM synthesis over the combined bundle.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent

SEARXNG = "http://127.0.0.1:18888/search"
MAX_SEARX_QUERIES = 3

STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "into", "that", "this", "will", "have", "been",
    "after", "over", "under", "about", "their", "there", "what", "when", "stock", "stocks",
    "shares", "market", "trading", "today", "week", "news", "report", "says", "said",
    "inc", "corp", "ltd", "llc", "plc", "group", "holdings",
})

# Emerging-theme detectors (RSS + research headlines)
TREND_PATTERNS = [
    (r"\b(ai\s+data\s*cent(er|re)|datacenter|hyperscale)\b", "AI datacenter infrastructure"),
    (r"\b(nuclear|smr|small\s+modular\s+reactor)\b", "Nuclear / SMR power"),
    (r"\b(quantum\s+computing|quantum\s+chip)\b", "Quantum computing"),
    (r"\b(tariff|trade\s+war|sanctions)\b", "Geopolitical trade policy"),
    (r"\b(defense|aerospace|pentagon|dod\s+contract)\b", "Defense spending"),
    (r"\b(utility|utilities|grid\s+power|transmission)\b", "Power grid / utilities"),
    (r"\b(semiconductor|chip\s+act|foundry|fab)\b", "Semiconductor supply chain"),
    (r"\b(copper|lithium|uranium|rare\s+earth)\b", "Critical materials"),
    (r"\b(biotech|glp-1|obesity\s+drug|fda)\b", "Biotech / GLP-1"),
    (r"\b(cyber\s*security|zero\s+trust)\b", "Cybersecurity"),
    (r"\b(robotics|humanoid|automation)\b", "Robotics / automation"),
    (r"\b(sector\s+rotation|rotation\s+into|rotation\s+out)\b", "Sector rotation"),
    (r"\b(small\s+cap|russell\s*200|iwm)\b", "Small-cap rotation"),
    (r"\b(crypto|bitcoin|etf\s+flow)\b", "Digital assets"),
]

ROTATION_KWS = ["sector rotation", "money flowing into", "rotation out of", "sector shift",
                "rotating into", "rotating out of"]

# Research topic prefixes that are pipeline metadata, not investable themes
GENERIC_RESEARCH_PREFIXES = frozenset({
    "earnings", "news momentum", "youtube discovery", "regulatory", "backlog",
    "source discovery", "ticker thesis", "momentum catalyst", "topic research",
})

SITE_BLOCKLIST = frozenset({
    "google.com", "news.google.com", "finance.yahoo.com", "yahoo.com", "finnhub.io",
    "reddit.com", "twitter.com", "x.com", "youtube.com", "wikipedia.org", "bing.com",
    "microsoft.com", "linkedin.com", "facebook.com", "instagram.com", "tiktok.com",
    "marketwatch.com", "cnbc.com", "bloomberg.com", "reuters.com", "apnews.com",
})

ENRICHMENT_CACHE_PATHS = (
    ROOT / "data" / "state" / "ticker_enrichment_cache.json",
    ROOT / "data" / "portfolios" / "state" / "ticker_enrichment_cache.json",
)


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]{4,}", (text or "").lower()) if w not in STOPWORDS]


def mine_hermes_research(cur, *, days: int = 7, limit: int = 400) -> list[dict]:
    cur.execute(
        """SELECT research_type, symbol, topic, LEFT(summary, 200) AS summary,
                  tags, strategy_tags, confidence_score
           FROM hermes_research_intelligence
           WHERE created_at > NOW() - (%s || ' days')::interval
             AND status IN ('staged', 'promoted')
             AND research_type IN (
               'momentum_catalyst', 'topic_research', 'youtube_discovery',
               'ticker_thesis_challenge', 'backlog_resolution', 'source_discovery_followup')
           ORDER BY confidence_score DESC NULLS LAST, created_at DESC
           LIMIT %s""",
        (days, limit),
    )
    cluster: Counter = Counter()
    symbols: dict[str, set] = defaultdict(set)
    examples: dict[str, str] = {}
    for rtype, sym, topic, summary, tags, stags, conf in cur.fetchall():
        blob = f"{topic or ''} {summary or ''}"
        for pat, label in TREND_PATTERNS:
            if re.search(pat, blob, re.I):
                cluster[label] += 1
                if sym:
                    symbols[label].add(str(sym).upper())
                examples.setdefault(label, (topic or summary or "")[:120])
        # Topic prefix e.g. "earnings: AAPL"
        if topic and ":" in topic:
            prefix = topic.split(":", 1)[0].strip().lower()
            if len(prefix) > 3 and prefix not in STOPWORDS:
                key = f"research:{prefix}"
                cluster[key] += 1
                if sym:
                    symbols[key].add(str(sym).upper())
    out = []
    for label, n in cluster.most_common(15):
        if n < 2:
            continue
        display = label if not label.startswith("research:") else label.split(":", 1)[1].replace("_", " ")
        out.append({
            "source": "hermes_research",
            "theme": display,
            "count": n,
            "symbols": sorted(symbols.get(label, []))[:12],
            "example": examples.get(label, ""),
        })
    return out


def mine_news_feeds(cur, *, days: int = 3, limit: int = 800) -> dict:
    cur.execute(
        """SELECT title, LEFT(summary, 300) AS summary, source, strategy_type, relevance_score
           FROM news_articles
           WHERE created_at > NOW() - (%s || ' days')::interval
             AND COALESCE(relevance_score, 0) >= 0.25
           ORDER BY relevance_score DESC NULLS LAST, created_at DESC
           LIMIT %s""",
        (days, limit),
    )
    rows = cur.fetchall()
    by_source = Counter()
    by_strategy = Counter()
    theme_hits: Counter = Counter()
    theme_syms: dict[str, set] = defaultdict(set)
    word_freq: Counter = Counter()
    rotation_hits = 0

    for title, summary, source, strategy_type, rel in rows:
        by_source[str(source or "unknown")] += 1
        if strategy_type:
            by_strategy[str(strategy_type)] += 1
        blob = f"{title or ''} {summary or ''}"
        if any(kw in blob.lower() for kw in ROTATION_KWS):
            rotation_hits += 1
        for pat, label in TREND_PATTERNS:
            if re.search(pat, blob, re.I):
                theme_hits[label] += 1
        for w in _words(blob):
            word_freq[w] += 1

    themes = []
    for label, n in theme_hits.most_common(12):
        if n >= 3:
            themes.append({"source": "news_rss", "theme": label, "count": n, "feed": "pattern_match"})

    # High-frequency substantive terms (RSS aggregate)
    for term, n in word_freq.most_common(30):
        if n >= 15 and term not in STOPWORDS:
            themes.append({"source": "news_rss", "theme": term, "count": n, "feed": "term_frequency"})

    return {
        "articles_scanned": len(rows),
        "by_source": dict(by_source.most_common(12)),
        "by_strategy": dict(by_strategy.most_common(8)),
        "sector_rotation_mentions": rotation_hits,
        "themes": themes[:20],
    }


def _domain_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.replace("www.", "").lower()
        return host if host and "." in host else ""
    except Exception:
        return ""


def _is_blocked_domain(domain: str) -> bool:
    d = (domain or "").lower()
    if not d or len(d) < 4:
        return True
    for blocked in SITE_BLOCKLIST:
        if d == blocked or d.endswith("." + blocked):
            return True
    return False


def mine_site_candidates(cur, *, web_probe: list | None = None, days: int = 7) -> list[dict]:
    """Discover new web domains from think-tank web probe, news URLs, and Hermes research."""
    hits: Counter = Counter()
    sources: dict[str, set] = defaultdict(set)

    for row in web_probe or []:
        d = row.get("domain") or _domain_from_url(row.get("url") or "")
        if d and not _is_blocked_domain(d):
            hits[d] += 2
            sources[d].add("searxng_web")

    cur.execute(
        """SELECT source_url FROM news_articles
           WHERE created_at > NOW() - (%s || ' days')::interval
             AND source_url IS NOT NULL AND source_url <> ''
           LIMIT 1200""",
        (days,),
    )
    for (url,) in cur.fetchall():
        d = _domain_from_url(url)
        if d and not _is_blocked_domain(d):
            hits[d] += 1
            sources[d].add("news_rss")

    cur.execute(
        """SELECT source_urls_json FROM hermes_research_intelligence
           WHERE created_at > NOW() - (%s || ' days')::interval
             AND source_urls_json IS NOT NULL
             AND source_urls_json::text NOT IN ('null', '[]', '{}')
           LIMIT 400""",
        (days,),
    )
    for (srcjson,) in cur.fetchall():
        urls = srcjson
        if isinstance(urls, str):
            try:
                urls = json.loads(urls)
            except Exception:
                urls = []
        if isinstance(urls, dict):
            urls = list(urls.values())
        for u in urls or []:
            if not isinstance(u, str) or not u.startswith("http"):
                continue
            d = _domain_from_url(u)
            if d and not _is_blocked_domain(d):
                hits[d] += 1
                sources[d].add("hermes_research")

    cur.execute("SELECT source_name FROM research_sources")
    known = {r[0].lower() for r in cur.fetchall() if r[0]}

    out = []
    for domain, n in hits.most_common(25):
        if domain.lower() in known:
            continue
        if n < 2:
            continue
        out.append({
            "domain": domain,
            "hits": n,
            "sources": sorted(sources.get(domain, [])),
            "status": "new_candidate",
        })
    return out


def register_site_candidates(
    conn,
    candidates: list[dict],
    *,
    apply: bool,
    max_register: int = 12,
) -> dict:
    """Register newly discovered domains into research_sources (inactive candidates)."""
    if not candidates:
        return {"registered": 0, "skipped": 0, "sample": []}

    cur = conn.cursor()
    cur.execute("SELECT source_name FROM research_sources")
    existing = {r[0].lower() for r in cur.fetchall() if r[0]}

    registered = 0
    registered_sample = []
    for c in candidates[:max_register]:
        domain = str(c.get("domain") or "").strip()
        if not domain or domain.lower() in existing:
            continue
        note = json.dumps({
            "think_tank_discovered_at": datetime.now(timezone.utc).isoformat(),
            "discovery_hits": c.get("hits"),
            "discovery_sources": c.get("sources") or [],
            "state": "candidate(think_tank)",
        })
        if apply:
            cur.execute(
                """INSERT INTO research_sources
                   (source_type, source_name, source_url, credibility_score, specialty, active, notes, created_at)
                   VALUES ('web', %s, %s, 0.25, ARRAY['web search'], false, %s, NOW())
                   ON CONFLICT DO NOTHING""",
                (domain, f"https://{domain}", note),
            )
        registered += 1
        existing.add(domain.lower())
        registered_sample.append(domain)
    if apply and registered:
        conn.commit()
    return {"registered": registered, "skipped": len(candidates) - registered, "sample": registered_sample[:8]}


def refresh_site_candidate_hits(conn, candidates: list[dict], *, apply: bool) -> dict:
    """Bump discovery_hits on inactive web sources when think-tank sees them again."""
    if not candidates:
        return {"updated": 0}
    cur = conn.cursor()
    updated = 0
    for c in candidates:
        domain = str(c.get("domain") or "").strip()
        hits = int(c.get("hits") or 0)
        if not domain or hits < 1:
            continue
        cur.execute(
            "SELECT id, notes FROM research_sources WHERE source_name=%s AND source_type='web' AND active=false",
            (domain,),
        )
        row = cur.fetchone()
        if not row:
            continue
        sid, notes = row
        try:
            meta = json.loads(notes or "{}")
        except Exception:
            meta = {}
        prev = int(meta.get("discovery_hits") or 0)
        if hits <= prev:
            continue
        meta["discovery_hits"] = hits
        meta["discovery_sources"] = sorted(set((meta.get("discovery_sources") or []) + (c.get("sources") or [])))
        meta["last_seen_at"] = datetime.now(timezone.utc).isoformat()
        if apply:
            cur.execute("UPDATE research_sources SET notes=%s WHERE id=%s", (json.dumps(meta), sid))
        updated += 1
    if apply and updated:
        conn.commit()
    return {"updated": updated}


def auto_activate_discovered_sites(
    conn,
    *,
    apply: bool,
    min_hits: int = 4,
    limit: int = 6,
) -> dict:
    """Promote think-tank web candidates to active research_sources when hit threshold is met."""
    cur = conn.cursor()
    cur.execute(
        """SELECT id, source_name, notes, active FROM research_sources
           WHERE source_type='web' AND active=false
           ORDER BY created_at DESC
           LIMIT 80"""
    )
    activated = []
    for sid, name, notes, active in cur.fetchall():
        if active or len(activated) >= limit:
            continue
        try:
            meta = json.loads(notes or "{}")
        except Exception:
            continue
        if "think_tank" not in str(meta.get("state", "")).lower() and not meta.get("discovery_hits"):
            continue
        hits = int(meta.get("discovery_hits") or 0)
        if hits < min_hits:
            continue
        meta["auto_activated_at"] = datetime.now(timezone.utc).isoformat()
        meta["auto_activated_by"] = "think_tank_site_discovery"
        meta["active_reason"] = f"discovery_hits>={min_hits}"
        if apply:
            cur.execute(
                "UPDATE research_sources SET active=true, credibility_score=GREATEST(credibility_score, 0.35), notes=%s WHERE id=%s",
                (json.dumps(meta), sid),
            )
        activated.append({"id": sid, "domain": name, "hits": hits})
    if apply and activated:
        conn.commit()
    return {"activated": len(activated), "sample": activated[:6]}


def _load_enrichment_rows() -> list[dict]:
    """Load ticker enrichment cache (newest file wins)."""
    best_path = None
    best_mtime = 0.0
    for p in ENRICHMENT_CACHE_PATHS:
        if p.exists() and p.stat().st_mtime > best_mtime:
            best_mtime = p.stat().st_mtime
            best_path = p
    if not best_path:
        return []
    try:
        raw = json.loads(best_path.read_text())
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    rows = []
    for sym, data in raw.items():
        if not isinstance(data, dict):
            continue
        s = str(sym).upper()
        if not re.match(r"^[A-Z]{1,5}$", s):
            continue
        rows.append({
            "symbol": s,
            "sector": data.get("sector") or "Unknown",
            "perf_week_pct": _f(data.get("perf_week_pct")),
            "perf_month_pct": _f(data.get("perf_month_pct")),
            "rsi": _f(data.get("rsi")),
            "rsi_status": data.get("rsi_status"),
            "source": "enrichment_cache",
        })
    return rows


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _rows_from_snapshot(cur) -> tuple[list[dict], str | None]:
    cur.execute("SELECT max(snapshot_date) FROM ticker_snapshot_daily")
    latest = cur.fetchone()[0]
    if not latest:
        return [], None
    cur.execute(
        """SELECT symbol, perf_week_pct, perf_month_pct, rsi
           FROM ticker_snapshot_daily WHERE snapshot_date=%s""",
        (latest,),
    )
    rows = []
    for sym, pw, pm, rsi in cur.fetchall():
        s = str(sym or "").upper()
        if not re.match(r"^[A-Z]{1,5}$", s):
            continue
        rows.append({
            "symbol": s,
            "sector": "Unknown",
            "perf_week_pct": _f(pw),
            "perf_month_pct": _f(pm),
            "rsi": _f(rsi),
            "source": "ticker_snapshot_daily",
        })
    return rows, str(latest)


def mine_rs_rsi_leaders(cur) -> dict:
    """Relative-strength + RSI clusters from enrichment cache and/or daily snapshots."""
    rows, snap_date = _rows_from_snapshot(cur)
    cache_rows = _load_enrichment_rows()
    # Prefer enrichment cache when snapshot is empty; merge symbols from both
    by_sym: dict[str, dict] = {}
    for r in rows:
        by_sym[r["symbol"]] = r
    for r in cache_rows:
        if r["symbol"] not in by_sym or by_sym[r["symbol"]].get("perf_week_pct") is None:
            by_sym[r["symbol"]] = r
        elif by_sym[r["symbol"]].get("sector") in (None, "", "Unknown") and r.get("sector"):
            by_sym[r["symbol"]]["sector"] = r["sector"]
    universe = [r for r in by_sym.values() if r.get("perf_week_pct") is not None]

    def _sane_weekly(r: dict) -> bool:
        pw = r.get("perf_week_pct")
        return pw is not None and 6.0 <= pw <= 80.0

    weekly_rs = sorted(
        [r for r in universe if _sane_weekly(r)
         and r.get("rsi") is not None and 42 <= r["rsi"] <= 72],
        key=lambda x: x["perf_week_pct"],
        reverse=True,
    )[:10]

    rsi_momentum = sorted(
        [r for r in universe if r.get("rsi") is not None and 58 <= r["rsi"] <= 72
         and _sane_weekly(r) and (r.get("perf_week_pct") or 0) >= 8.0],
        key=lambda x: (x["perf_week_pct"], x["rsi"]),
        reverse=True,
    )[:8]

    rsi_oversold_bounce = sorted(
        [r for r in universe if r.get("rsi") is not None and r["rsi"] <= 34
         and 0 < (r.get("perf_week_pct") or 0) <= 50.0],
        key=lambda x: x["perf_week_pct"],
        reverse=True,
    )[:8]

    sector_perf: dict[str, list[float]] = defaultdict(list)
    sector_syms: dict[str, list[str]] = defaultdict(list)
    for r in universe:
        sec = str(r.get("sector") or "Unknown")
        pw = r.get("perf_week_pct")
        if pw is None:
            continue
        sector_perf[sec].append(pw)
        if pw >= 4.0:
            sector_syms[sec].append(r["symbol"])

    sector_rs = []
    for sec, pcts in sector_perf.items():
        if len(pcts) < 8:
            continue
        avg = sum(pcts) / len(pcts)
        if avg >= 2.5:
            sector_rs.append({
                "sector": sec,
                "avg_perf_week_pct": round(avg, 2),
                "leaders": sector_syms.get(sec, [])[:6],
                "count": len(pcts),
            })
    sector_rs.sort(key=lambda x: x["avg_perf_week_pct"], reverse=True)

    return {
        "data_source": rows[0]["source"] if rows else (cache_rows[0]["source"] if cache_rows else "none"),
        "snapshot_date": snap_date,
        "universe_size": len(universe),
        "weekly_rs_leaders": weekly_rs,
        "rsi_momentum": rsi_momentum,
        "rsi_oversold_bounce": rsi_oversold_bounce,
        "sector_rs": sector_rs[:5],
    }


def themes_from_rs_rsi(rs_data: dict) -> list[dict]:
    """Trend directives from RS/RSI leader clusters."""
    themes = []
    weekly = rs_data.get("weekly_rs_leaders") or []
    if len(weekly) >= 4:
        syms = [r["symbol"] for r in weekly[:8]]
        themes.append({
            "kind": "trend",
            "label": "trend Weekly RS momentum leaders",
            "rationale": f"Top weekly performers ({weekly[0]['perf_week_pct']:+.1f}% lead) "
                         f"with constructive RSI — {len(weekly)} names",
            "spec": {
                "keywords": ["relative strength", "weekly momentum", "RS leaders", "breakout continuation"],
                "seed_symbols": syms,
                "think_tank_source": "rs_weekly_leaders",
            },
        })

    for cluster in rs_data.get("sector_rs") or []:
        sec = cluster.get("sector")
        if not sec or sec == "Unknown":
            continue
        avg = cluster.get("avg_perf_week_pct")
        leaders = cluster.get("leaders") or []
        if not leaders:
            continue
        themes.append({
            "kind": "trend",
            "label": f"trend {sec} sector RS thrust",
            "rationale": f"{sec} avg 1W RS {avg:+.2f}% across {cluster.get('count', 0)} names",
            "spec": {
                "keywords": [f"{sec} relative strength", f"{sec} sector momentum", "sector RS leaders"],
                "seed_symbols": leaders[:8],
                "gics_sector": sec,
                "think_tank_source": "rs_sector_cluster",
            },
        })

    mom = rs_data.get("rsi_momentum") or []
    if len(mom) >= 3:
        themes.append({
            "kind": "trend",
            "label": "trend RSI momentum thrust (50-72 band)",
            "rationale": f"{len(mom)} names with RSI 58-72 and strong weekly RS",
            "spec": {
                "keywords": ["RSI momentum", "relative strength continuation", "trend thrust"],
                "seed_symbols": [r["symbol"] for r in mom[:8]],
                "think_tank_source": "rsi_momentum_thrust",
            },
        })

    bounce = rs_data.get("rsi_oversold_bounce") or []
    if len(bounce) >= 3:
        themes.append({
            "kind": "trend",
            "label": "trend RSI oversold bounce candidates",
            "rationale": f"{len(bounce)} names RSI<=34 with positive weekly RS (reversal setup)",
            "spec": {
                "keywords": ["RSI oversold bounce", "mean reversion", "recovery setup"],
                "seed_symbols": [r["symbol"] for r in bounce[:8]],
                "think_tank_source": "rsi_oversold_bounce",
            },
        })
    return themes


def mine_catalysts(cur, *, days: int = 7) -> list[dict]:
    cur.execute(
        """SELECT catalyst_type, count(*) AS n
           FROM catalyst_events
           WHERE created_at > NOW() - (%s || ' days')::interval
           AND catalyst_type NOT IN ('other', 'news_momentum')
           GROUP BY catalyst_type
           HAVING count(*) >= 5
           ORDER BY n DESC
           LIMIT 12""",
        (days,),
    )
    return [{"source": "catalyst_api", "theme": r[0], "count": r[1]} for r in cur.fetchall()]


def mine_web_searx(seed_themes: list[str]) -> list[dict]:
    """Live web probe via SearXNG — capped queries from top mined themes."""
    if not seed_themes:
        return []
    results = []
    queries = []
    for t in seed_themes[:2]:
        queries.append(f"{t} stock sector trend 2026")
    queries.append("sector rotation investing themes this week")
    for q in queries[:MAX_SEARX_QUERIES]:
        try:
            params = urllib.parse.urlencode({"q": q, "format": "json", "categories": "general"})
            req = urllib.request.Request(
                f"{SEARXNG}?{params}",
                headers={"User-Agent": "ThinkTank/1.0"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read())
            for hit in (data.get("results") or [])[:6]:
                title = hit.get("title") or ""
                snippet = (hit.get("content") or "")[:200]
                url = hit.get("url") or ""
                domain = ""
                if url:
                    m = re.search(r"https?://([^/]+)", url)
                    if m:
                        domain = m.group(1).replace("www.", "")
                results.append({
                    "source": "searxng_web",
                    "query": q,
                    "title": title[:140],
                    "snippet": snippet,
                    "domain": domain,
                })
        except Exception as e:
            results.append({"source": "searxng_web", "query": q, "error": str(e)[:80]})
    return results


def mine_all_signals(conn, *, skip_web: bool = False) -> dict:
    cur = conn.cursor()
    research = mine_hermes_research(cur)
    news = mine_news_feeds(cur)
    catalysts = mine_catalysts(cur)
    rs_rsi = mine_rs_rsi_leaders(cur)
    web = []
    if not skip_web:
        seed_labels = [r["theme"] for r in research[:4]]
        seed_labels += [t["theme"] for t in news.get("themes", [])[:3] if isinstance(t.get("theme"), str)]
        web = mine_web_searx(seed_labels)
    site_candidates = mine_site_candidates(cur, web_probe=web)
    return {
        "mined_at": datetime.now(timezone.utc).isoformat(),
        "hermes_research": research,
        "news_feeds": news,
        "catalysts": catalysts,
        "rs_rsi": rs_rsi,
        "web_probe": web,
        "site_candidates": site_candidates,
    }


def themes_from_signals(signals: dict, *, min_research_count: int = 2, min_news_count: int = 6) -> list[dict]:
    """Rule-based trend directives from mined multi-source signals."""
    themes = []
    for row in signals.get("hermes_research") or []:
        if row.get("count", 0) < min_research_count:
            continue
        label = str(row.get("theme") or "").strip()
        if not label or len(label) < 4:
            continue
        if label.lower() in GENERIC_RESEARCH_PREFIXES:
            continue
        themes.append({
            "kind": "trend",
            "label": f"trend {label}",
            "rationale": f"Hermes research cluster: {row['count']} rows — {row.get('example', '')[:80]}",
            "spec": {
                "keywords": [label, f"{label} stocks", f"{label} catalyst"],
                "seed_symbols": row.get("symbols") or [],
                "think_tank_source": "hermes_research_cluster",
            },
        })
    for row in signals.get("news_feeds", {}).get("themes") or []:
        if row.get("count", 0) < min_news_count:
            continue
        label = str(row.get("theme") or "").strip()
        if len(label) < 4:
            continue
        if row.get("feed") == "term_frequency" and len(label) < 6:
            continue
        themes.append({
            "kind": "trend",
            "label": f"trend {label}",
            "rationale": f"RSS/news feed ({row.get('feed')}): {row['count']} mentions across "
                         f"{signals.get('news_feeds', {}).get('articles_scanned', 0)} articles",
            "spec": {
                "keywords": [label, f"{label} news", f"{label} sector"],
                "think_tank_source": f"news_{row.get('feed', 'rss')}",
            },
        })
    rot = signals.get("news_feeds", {}).get("sector_rotation_mentions") or 0
    if rot >= 5:
        themes.append({
            "kind": "trend",
            "label": "trend Sector rotation (news flow)",
            "rationale": f"{rot} sector-rotation phrases in RSS/news last 3d",
            "spec": {
                "keywords": ["sector rotation", "rotation into", "rotation out of", "sector leadership"],
                "think_tank_source": "news_sector_rotation",
            },
        })
    for row in signals.get("catalysts") or []:
        ctype = str(row.get("theme") or "")
        if row.get("count", 0) < 8:
            continue
        themes.append({
            "kind": "trend",
            "label": f"trend Catalyst wave: {ctype.replace('_', ' ')}",
            "rationale": f"{row['count']} catalyst_events ({ctype}) last 7d",
            "spec": {
                "keywords": [ctype.replace("_", " "), f"{ctype} catalyst"],
                "think_tank_source": "catalyst_events",
            },
        })
    return themes


def llm_themes_from_signals(signals: dict, sector_snap: dict, style: dict) -> list[dict]:
    """LLM synthesis over the full multi-source signal bundle."""
    try:
        import llm_lane
    except Exception:
        return []

    # Compact bundle for prompt (avoid token blowup)
    rs = signals.get("rs_rsi") or {}
    bundle = {
        "hermes_research_top": (signals.get("hermes_research") or [])[:10],
        "news_themes": (signals.get("news_feeds") or {}).get("themes", [])[:12],
        "news_sources": (signals.get("news_feeds") or {}).get("by_source", {}),
        "catalysts": (signals.get("catalysts") or [])[:8],
        "web_titles": [w.get("title") for w in (signals.get("web_probe") or [])[:10] if w.get("title")],
        "new_site_candidates": (signals.get("site_candidates") or [])[:8],
        "weekly_rs_leaders": (rs.get("weekly_rs_leaders") or [])[:8],
        "sector_rs_clusters": (rs.get("sector_rs") or [])[:5],
        "rsi_momentum": (rs.get("rsi_momentum") or [])[:6],
        "sector_rs": (sector_snap.get("sectors") or [])[:11],
        "style_rotation": style,
    }
    prompt = (
        "You are an autonomous investment think tank. Synthesize EMERGING TRADEABLE TRENDS from "
        "ALL signal sources below (Hermes research DB, RSS/news feeds, catalyst API, web search, "
        "new-site candidates, ticker RS/RSI clusters, Finviz sector RS). Propose themes an equity "
        "researcher should monitor for NEW prospects.\n"
        "Avoid retirement/tax/Medicare planning themes. Prefer sector rotations, industry shifts, "
        "policy catalysts, style rotations.\n"
        f"SIGNALS: {json.dumps(bundle, default=str)[:12000]}\n"
        'Reply ONLY JSON: {"themes":[{"kind":"trend"|"sector","label":"trend X or sector Y",'
        '"keywords":["phrase1","phrase2"],"seed_symbols":["TICK"],"finviz_sector":"optional",'
        '"evidence":"which source(s)"}]}'
    )
    SECTOR_ETF = {
        "Technology": "XLK", "Financial": "XLF", "Energy": "XLE", "Healthcare": "XLV",
        "Consumer Cyclical": "XLY", "Industrials": "XLI", "Consumer Defensive": "XLP",
        "Utilities": "XLU", "Real Estate": "XLRE", "Basic Materials": "XLB",
        "Communication Services": "XLC",
    }
    for lane in ("deepseek-flash", "grok", "chatgpt", "local"):
        try:
            if not llm_lane.available(lane):
                continue
            raw = llm_lane.generate(prompt, lane=lane, timeout=120)
            m = re.search(r"\{.*\}", raw or "", re.S)
            if not m:
                continue
            data = json.loads(m.group())
            out = []
            for t in data.get("themes") or []:
                kind = str(t.get("kind") or "trend").lower()
                if kind not in ("trend", "sector"):
                    kind = "trend"
                label = str(t.get("label") or "").strip()
                if not label:
                    continue
                if not label.lower().startswith(kind):
                    label = f"{kind} {label}"
                spec = {
                    "keywords": [k for k in (t.get("keywords") or []) if k][:12],
                    "seed_symbols": [s.upper() for s in (t.get("seed_symbols") or [])
                                     if re.match(r"^[A-Z]{1,5}$", str(s).upper())][:10],
                    "think_tank_source": f"llm_signals:{lane}",
                    "evidence": str(t.get("evidence") or "")[:200],
                }
                if kind == "sector" and t.get("finviz_sector"):
                    sec = str(t["finviz_sector"])
                    spec["finviz_sector"] = sec
                    spec["gics_sector"] = sec
                    spec["etf"] = SECTOR_ETF.get(sec, "")
                out.append({
                    "kind": kind,
                    "label": label[:120],
                    "rationale": f"LLM multi-source synthesis ({lane}): {spec.get('evidence', '')[:100]}",
                    "spec": spec,
                })
            if out:
                return out
        except Exception:
            continue
    return []