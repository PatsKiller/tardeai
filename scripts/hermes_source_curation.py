#!/usr/bin/env python3
"""Hermes Source Curation — Tracks A (self-learning source quality) + B (new-site discovery)
+ registers every source TYPE (web/social/youtube/sec/rss/ai-apis/seeking-alpha) into research_sources.

FULLY AUTONOMOUS — no human ever flips a source active. Each run re-decides `active`:
A: score each web domain by yield = (promoted+embedded)/total of the research it produced
   → promote when total>=2 AND yield>=30%; retire when total>=5 AND yield==0.
B: domains seen for the first time / not-yet-proven → an LLM (free lane: grok→chatgpt→local) validates
   credibility+relevance and auto-promotes the good ones immediately (verdict cached in notes, capped
   per run). This replaces the old manual 'flip to active' gate.
Connectors that need keys (AI APIs, Seeking Alpha) are registered dormant with status in notes.

Read-only to research; only writes the research_sources registry. Idempotent (UPSERT). Cron daily 23:30.
"""
import os
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [source-curation] %(message)s")
log = logging.getLogger("source_curation")
DB = dict(host=os.getenv("DB_HOST", "127.0.0.1"), port=int(os.getenv("DB_PORT", "5432")),
          dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
          password=os.getenv("DB_PASSWORD", ""))

# Connector source types and how they're wired today (status drives the UI badge).
# active=True means it has a live ingestion path; needs_key/dormant are honest "not running" states.
CONNECTOR_TYPES = [
    {"type": "social", "name": "Reddit / Stocktwits / X", "active": True, "specialty": "social sentiment", "note": "live via social_ingest pipeline (Social Scalp)"},
    {"type": "youtube", "name": "YouTube transcripts", "active": True, "specialty": "video transcripts", "note": "live via transcript_processor (cookie-gated)"},
    {"type": "sec", "name": "SEC filings (Form 4)", "active": True, "specialty": "insider filings", "note": "live via sec_form4 ingest"},
    {"type": "rss", "name": "RSS feeds (Yahoo/Benzinga/Google News)", "active": True, "specialty": "news feeds", "note": "live via news_ingestion.py (yahoo_rss/benzinga_rss) + Google News RSS in topic_ingestion (topic_google_news_rss) — 3k+/wk"},
    {"type": "ai_openai", "name": "OpenAI (ChatGPT)", "active": True, "specialty": "AI research", "note": "live via FREE OAuth codex proxy :8646 (no metered key)"},
    {"type": "ai_anthropic", "name": "Anthropic (Claude)", "active": False, "specialty": "AI research", "note": "DORMANT — arbitration only; no free lane"},
    {"type": "ai_xai", "name": "xAI (Grok)", "active": True, "specialty": "AI research", "note": "live via FREE xAI-OAuth proxy :8645 (no metered key)"},
    {"type": "seeking_alpha", "name": "Seeking Alpha", "active": False, "specialty": "equity research", "note": "DORMANT — needs SEEKING_ALPHA_API_KEY (via official API, not cookies)"},
]


def domains_from(srcjson):
    out = []
    try:
        urls = srcjson
        if isinstance(urls, str):
            urls = json.loads(urls)
        if isinstance(urls, dict):
            urls = list(urls.values())
        for u in (urls or []):
            if isinstance(u, str) and u.startswith("http"):
                d = urlparse(u).netloc.replace("www.", "")
                if d:
                    out.append(d)
    except Exception:
        pass
    return out


def _llm_validate_source(domain):
    """Autonomous credibility check for a not-yet-proven domain — replaces the human 'flip to active'.
    Free LLM lanes only. Returns (approve: bool|None, reason: str). None = lanes unavailable (stay candidate)."""
    try:
        import llm_lane
    except Exception:
        return None, "no-llm"
    prompt = (
        f'You are vetting a web domain as a research source for an individual investor whose interests '
        f'include retirement/Medicare/Medicaid/SSDI/estate-tax planning and equity/market research.\n'
        f'DOMAIN: {domain}\n'
        'Is this a credible, substantive source for that research (reputable finance/news/gov/legal/'
        'analysis site), or low-value (spam, content farm, pure forum noise, unrelated, paywalled-stub)?\n'
        'Reply ONLY JSON: {"approve": true|false, "reason": "<=8 words"}'
    )
    for lane in ("grok", "chatgpt", "local"):
        try:
            if not llm_lane.available(lane):
                continue
            raw = llm_lane.generate(prompt, lane=lane, timeout=40)
            m = re.search(r"\{.*\}", raw or "", re.S)
            if not m:
                continue
            d = json.loads(m.group())
            return bool(d.get("approve")), f"LLM:{lane} {str(d.get('reason') or '')[:40]}"
        except Exception:
            continue
    return None, "llm-error"


def upsert_source(cur, stype, name, cred, active, specialty, note, url=None):
    spec = [specialty] if isinstance(specialty, str) else (specialty or [])  # specialty is text[]
    cur.execute("SELECT id FROM research_sources WHERE source_type=%s AND source_name=%s", (stype, name))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE research_sources SET credibility_score=%s, active=%s, specialty=%s, notes=%s WHERE id=%s",
                    (cred, active, spec, note, row[0]))
        return False
    cur.execute("""INSERT INTO research_sources (source_type, source_name, source_url, credibility_score, specialty, active, notes, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s, NOW())""", (stype, name, url, cred, spec, active, note))
    return True


def main():
    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    cur = conn.cursor()

    # ── A: web-domain yield scoring (+ B: new-domain discovery) ──
    cur.execute("""SELECT source_urls_json, status,
                          EXISTS(SELECT 1 FROM hermes_embedding_queue q WHERE q.source_research_id = r.id AND q.embedding_status='completed') AS embedded
                   FROM hermes_research_intelligence r
                   WHERE source_urls_json IS NOT NULL AND source_urls_json::text NOT IN ('null','[]','{}')""")
    agg = {}
    for srcjson, status, embedded in cur.fetchall():
        for d in set(domains_from(srcjson)):
            a = agg.setdefault(d, {"total": 0, "promoted": 0, "embedded": 0})
            a["total"] += 1
            if status == "promoted":
                a["promoted"] += 1
            if embedded:
                a["embedded"] += 1
    # AUTONOMOUS source lifecycle — NO human flip. Each run re-decides `active`:
    #   • promote (data) → total>=2 AND yield>=30%   (proved relevant → preferred source)
    #   • promote (LLM)  → not-yet-proven domain that an LLM validates as credible+relevant
    #                      (free lane). This replaces the old "human flips to active" gate.
    #   • retire         → total>=5 AND yield==0      (sampled enough, never useful → off)
    # active flips both ways every run, so decayed sources self-demote with no operator.
    # LLM verdicts are cached in notes ("LLM:") so we don't re-spend lanes on already-judged domains;
    # cap new validations per run to stay polite to the free lanes.
    cur.execute("SELECT source_name, notes FROM research_sources WHERE source_type='web'")
    prior = {n: (notes or "") for n, notes in cur.fetchall()}
    LLM_CAP = 25
    new_count = validated = 0
    for d, a in agg.items():
        yield_pct = round(100 * (a["promoted"] + a["embedded"]) / max(a["total"], 1))
        retired = (a["total"] >= 5 and yield_pct == 0)
        proven = (a["total"] >= 2 and yield_pct >= 30)
        # Phase 3 (2026-07-02): an OUTCOME_LEDGER verdict outranks this pipeline-throughput
        # yield — a domain retired on graded outcomes stays retired until the outcome loop
        # (hermes_outcome_learning.py) reinstates it, however much of its research the
        # pipeline promoted/embedded.
        outcome_markers = re.findall(r"OUTCOME_LEDGER (retired|reinstated)", prior.get(d, ""))
        if outcome_markers and outcome_markers[-1] == "retired":
            active, state = False, "outcome-retired"
        elif proven:
            active, state = True, "active(yield)"
        elif retired:
            active, state = False, "auto-retired"
        else:
            prev = prior.get(d, "")
            if "LLM:" in prev and "approved" in prev:      # cached approve
                active, state = True, "active(LLM-cached)"
            elif "LLM:" in prev and "rejected" in prev:    # cached reject
                active, state = False, "LLM-rejected"
            elif validated < LLM_CAP:                      # never judged → validate now
                ok, why = _llm_validate_source(d)
                validated += 1
                if ok is True:
                    active, state = True, f"active(LLM-approved {why})"
                elif ok is False:
                    active, state = False, f"LLM-rejected {why}"
                else:
                    active, state = False, "candidate(pending-LLM)"
            else:
                active, state = False, "candidate(pending-LLM)"
        note = f"yield {yield_pct}% ({a['promoted']}p/{a['embedded']}e of {a['total']}) — {state}"
        # preserve outcome-ledger markers across the note rewrite (they carry the verdict state)
        prior_outcome = " | ".join(re.findall(r"OUTCOME_LEDGER [^|]+", prior.get(d, "")))
        if prior_outcome:
            note = f"{note} | {prior_outcome}"
        if upsert_source(cur, "web", d, yield_pct, active, "web search", note, url=f"https://{d}"):
            new_count += 1
    log.info("web domains scored: %d (%d new, %d LLM-validated) — autonomous, no human flip",
             len(agg), new_count, validated)

    # ── Register connector source types (honest status: active / dormant / needs-key) ──
    for c in CONNECTOR_TYPES:
        # auto-activate AI/SeekingAlpha if a key is actually present
        active = c["active"]
        note = c["note"]
        key_env = {"ai_openai": "OPENAI_API_KEY", "ai_anthropic": "ANTHROPIC_API_KEY", "ai_xai": "XAI_API_KEY", "seeking_alpha": "SEEKING_ALPHA_API_KEY"}.get(c["type"])
        if key_env and os.environ.get(key_env):
            active = True
            note = f"ACTIVE — {key_env} present"
        upsert_source(cur, c["type"], c["name"], 50 if active else 0, active, c["specialty"], note)
    log.info("connector types registered: %d", len(CONNECTOR_TYPES))

    try:
        import hermes_source_registry as hsr
        removed = hsr.cleanup_orphan_rss_rows(cur)
        if removed:
            log.info("removed %d orphan RSS stub row(s)", removed)
    except Exception as e:
        log.warning("RSS stub cleanup skipped: %s", e)

    cur.execute("SELECT COUNT(*) FILTER (WHERE active), COUNT(*) FROM research_sources")
    a, t = cur.fetchone()
    log.info("research_sources: %d active / %d total", a, t)
    try:
        import hermes_source_policy as hsp
        hsp.invalidate_cache()
    except Exception:
        pass
    conn.close()


if __name__ == "__main__":
    main()
