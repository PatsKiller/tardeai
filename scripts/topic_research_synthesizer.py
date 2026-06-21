#!/usr/bin/env python3
"""topic_research_synthesizer.py — actually RESEARCH the staged topic_research rows with real LLM analysis,
instead of leaving them as placeholder enqueue-markers ("Research topic 'X' from the Registry").

The topic bridge stages a placeholder row; the coordinator only flips its status. Nothing was writing real
research content — so the RetirementHub Planning Research tab showed empty markers. This fills each row with
a genuine, grounded research summary + thesis using the FREE LLM lanes (grok :8645 → chatgpt :8646 → local
gemma), in the operator's planning context. Advisory only; never a trade. Idempotent (skips rows already
synthesized, i.e. model_used != 'topic_monitor_bridge').

DOES BOTH (web + LLM): for each topic it pulls what the crawler (topic_ingestion.py) actually found —
articles tagged symbol=topic_id, or a keyword fallback — and grounds the LLM on those real sources, then
catalogs the sites it used into evidence_json.grounded_on (provenance, surfaced on the RetirementHub).
GRADE FILTER: only grounds on graded-good articles — excludes anything the curator (topic_curator.py)
marked low_quality/blocked or that was demoted — so research never cites garbage.

  python3 scripts/topic_research_synthesizer.py [--max 20] [--apply]   (fill placeholders; default dry-run)
  python3 scripts/topic_research_synthesizer.py --reground [--max 20] --apply   (upgrade rows that
          grounded on 0 articles, once the crawler has since ingested+graded the topic)
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn


def _prompt(topic, context, articles=None):
    ctx = f"\nInvestor context: {context}" if context else ""
    src = ""
    if articles:
        lines = "\n".join(f'- "{a["title"]}" ({a["source"]})' + (f' — {a["summary"][:160]}' if a.get("summary") else "")
                          for a in articles[:8])
        src = ("\n\nRecent sources the research crawler found for this topic (ground your briefing in these, "
               "prefer their specifics over memory, and reconcile any conflicts):\n" + lines)
    return (
        f'Research this topic for an individual investor and write a concise, factual briefing.{ctx}{src}\n\n'
        f'TOPIC: "{topic}"\n\n'
        'Return ONLY a JSON object, no prose:\n'
        '{"summary": "120-180 words: what it is, the key facts/numbers, and why it matters for this '
        'investor", "thesis": "one-sentence actionable takeaway", "considerations": ["3-5 specific points: '
        'rules, thresholds, trade-offs, or risks"], "confidence": 0.0-1.0}\n'
        'Be specific and current (2026). If it involves tax/Medicare/Medicaid/estate law, note that a '
        'professional (elder-law attorney / tax advisor) should confirm. Do not fabricate exact figures you '
        'are unsure of — say "verify current figure".'
    )


def _synthesize(topic, context, articles=None):
    try:
        import llm_lane
    except Exception:
        return None
    for lane in ("grok", "chatgpt", "local"):
        try:
            if not llm_lane.available(lane):
                continue
            raw = llm_lane.generate(_prompt(topic, context, articles), lane=lane, timeout=70)
            m = re.search(r"\{.*\}", raw or "", re.S)
            if not m:
                continue
            d = json.loads(m.group())
            summ = (d.get("summary") or "").strip()
            if len(summ) < 60:
                continue
            cons = d.get("considerations") or []
            if cons:
                summ += "\n\nKey points: " + " · ".join(str(c).strip() for c in cons[:5] if str(c).strip())
            conf = d.get("confidence")
            conf = float(conf) if isinstance(conf, (int, float)) and 0 <= conf <= 1 else 0.6
            return {"summary": summ[:1800], "thesis": (d.get("thesis") or "").strip()[:400],
                    "confidence": round(conf, 2), "lane": lane,
                    "grounded_on": [{"title": a["title"][:140], "source": a["source"],
                                     "url": a.get("source_url")} for a in (articles or [])[:8]]}
        except Exception:
            continue
    return None


def run(apply=False, max_rows=20, reground=False):
    conn = _get_conn(); cur = conn.cursor()
    if reground:
        # upgrade already-synthesized rows that grounded on 0 real articles (synthesized before the
        # crawler had ingested the topic) — re-runs them so they pick up exact crawler sources now.
        cur.execute("""SELECT id, topic, evidence_json FROM hermes_research_intelligence
                       WHERE research_type='topic_research' AND model_used LIKE 'synth:%%'
                         AND COALESCE((evidence_json->>'grounded_count')::int, 0) = 0
                       ORDER BY updated_at ASC LIMIT %s""", (max_rows,))
    else:
        # un-synthesized topic_research rows (still the bridge placeholder)
        cur.execute("""SELECT id, topic, evidence_json FROM hermes_research_intelligence
                       WHERE research_type='topic_research' AND model_used='topic_monitor_bridge'
                         AND summary ILIKE 'Research topic%%'
                       ORDER BY created_at DESC LIMIT %s""", (max_rows,))
    rows = cur.fetchall()
    done, skipped = [], 0
    for rid, topic, ev in rows:
        ev = ev if isinstance(ev, dict) else (json.loads(ev) if ev else {})
        # personal context from the linked topic_monitor row
        ctx = ""
        tmid = ev.get("topic_monitor_id")
        disp = ""
        sq = []
        if tmid:
            cur.execute("SELECT personal_context, display_name, search_queries FROM topic_monitor WHERE topic_id=%s", (tmid,))
            r2 = cur.fetchone()
            if r2:
                ctx = (r2[0] or ""); disp = (r2[1] or "")
                sq = r2[2] if isinstance(r2[2], list) else (json.loads(r2[2]) if r2[2] else [])
        # Distinctive topic tokens — from the topic's OWN (good) search queries + display name,
        # minus generic words. Used below to ground only on ON-topic articles, so generic matches
        # ("2026") and mis-tagged off-topic news (AI/semiconductor) can't pollute retirement research.
        _STOP = {"and", "for", "the", "with", "from", "into", "strategies", "strategy", "ideas",
                 "investment", "investor", "management", "monitoring", "plan", "planning", "tax",
                 "taxes", "income", "market", "markets", "stock", "stocks", "sector", "rules",
                 "best", "top", "2024", "2025", "2026", "2027", "2028"}
        _toks = set()
        for _q in list(sq) + [disp, topic or ""]:
            for _w in re.sub(r"[^a-z0-9 ]", " ", str(_q).lower()).split():
                if len(_w) > 3 and not _w.isdigit() and _w not in _STOP:
                    _toks.add(_w)
        # GROUND on what the crawler actually found: topic-sourced articles are tagged symbol=topic_id;
        # fall back to a keyword match on the topic text so even un-ingested topics pick up related news.
        # GRADE FILTER: never ground on garbage. The curator marks new-site articles
        # low_quality/blocked; exclude those (and demoted), and surface approved before pending.
        GRADE = ("AND COALESCE(rag_status,'pending') NOT IN ('low_quality','blocked') "
                 "AND COALESCE(hygiene_status,'active')='active' AND demoted_at IS NULL")
        GRADE_ORD = "(rag_status='approved') DESC, "
        articles = []
        if tmid:
            cur.execute(f"""SELECT title, summary, source, source_url FROM news_articles
                           WHERE symbol=%s AND title IS NOT NULL {GRADE}
                           ORDER BY {GRADE_ORD} published_at DESC NULLS LAST LIMIT 8""", (tmid,))
            articles = [{"title": a[0], "summary": a[1], "source": a[2], "source_url": a[3]}
                        for a in cur.fetchall()]
        if not articles:
            kw = re.sub(r"[^a-z0-9 ]", " ", (disp or topic or "").lower()).split()
            kw = [w for w in kw if len(w) > 3 and not w.isdigit() and w not in _STOP][:4]
            if kw:
                # OR-match distinctive keywords (e.g. roth/medicaid/ssdi) so existing planning news is found
                ors = " OR ".join(["title ILIKE %s"] * len(kw))
                cur.execute(f"""SELECT title, summary, source, source_url FROM news_articles
                               WHERE ({ors}) AND published_at > now()-interval '60 days' {GRADE}
                               ORDER BY {GRADE_ORD} published_at DESC LIMIT 6""", tuple(f"%{w}%" for w in kw))
                articles = [{"title": a[0], "summary": a[1], "source": a[2], "source_url": a[3]}
                            for a in cur.fetchall()]
        # Relevance gate: ground ONLY on articles matching >=2 distinctive topic tokens (>=1 when the
        # topic has a single distinctive token). Two-token requirement drops both off-topic items
        # (AI/semiconductor news matched by a generic term like "2026") AND keyword homonyms (e.g.
        # "ROTH" Capital conference, debt "conversion") that a single-keyword match would let through.
        # Grounding on nothing (honest "thin sources") beats grounding on off-topic noise.
        if _toks and articles:
            _need = 2 if len(_toks) >= 2 else 1
            def _mc(a):
                blob = f"{a.get('title') or ''} {a.get('summary') or ''}".lower()
                return sum(1 for t in _toks if t in blob)
            _kept = [a for a in articles if _mc(a) >= _need]
            if len(_kept) != len(articles):
                log.info("topic %s: relevance gate kept %d/%d articles (need>=%d tokens)",
                         (topic or "")[:40], len(_kept), len(articles), _need)
            articles = _kept
        res = _synthesize(topic, ctx, articles)
        if not res:
            skipped += 1
            continue
        done.append({"id": rid, "topic": (topic or "")[:50], "lane": res["lane"],
                     "len": len(res["summary"]), "grounded_on": len(res.get("grounded_on") or [])})
        if apply:
            # catalog the sites that informed this research into evidence_json (source provenance)
            ev["grounded_on"] = res.get("grounded_on") or []
            ev["grounded_count"] = len(ev["grounded_on"])
            cur.execute("""UPDATE hermes_research_intelligence
                           SET summary=%s, thesis=%s, confidence_score=%s,
                               model_used=%s, evidence_json=%s, updated_at=now()
                           WHERE id=%s""",
                        (res["summary"], res["thesis"], res["confidence"],
                         f"synth:{res['lane']}", json.dumps(ev), rid))
    if apply:
        conn.commit()
    print(json.dumps({"mode": "APPLIED" if apply else "DRY-RUN", "candidates": len(rows),
                      "synthesized": len(done), "no_lane_result": skipped,
                      "sample": done[:6]}, indent=2))
    return 0


def main():
    from dotenv import load_dotenv
    load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=20)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--reground", action="store_true",
                    help="Re-run already-synthesized rows that grounded on 0 articles, to pick up "
                         "exact crawler sources once the topic has been ingested.")
    a = ap.parse_args()
    return run(apply=a.apply, max_rows=a.max, reground=a.reground)


if __name__ == "__main__":
    raise SystemExit(main())
