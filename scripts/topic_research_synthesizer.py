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
NO SOURCES, NO BRIEF: a topic whose articles all fail the relevance gate is refused rather than written
from the model's memory, and a brief whose claims trace to none of its cited sources is refused too. A
stored synth brief with grounded_count 0 is withheld by the Research Intelligence desk (2026-11-07
DATA TRUTH: hermes:44896 was synthesized on nothing, promoted, and asserted a false SSDI/MAGI rule).

  python3 scripts/topic_research_synthesizer.py [--max 20] [--apply]   (fill placeholders; default dry-run)
  python3 scripts/topic_research_synthesizer.py --reground [--max 20] --apply   (upgrade rows that
          grounded on 0 articles, once the crawler has since ingested+graded the topic)
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from cio_agent_contract import build_topic_research_json_schema, parse_hermes_topic_result
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
        'Be specific and current (2026). If it involves tax/Medicare/Medicaid/estate law, note that a '
        'professional (elder-law attorney / tax advisor) should confirm. Do not fabricate exact figures you '
        'are unsure of — say "verify current figure". Date every figure precisely (the source article\'s '
        'date or an exact date like "as of 2026-07-16") — never vague dating like "as of mid-2026".\n\n'
        + build_topic_research_json_schema()
    )


#: Registered in config/llm_process_registry.json (lane repair 2026-10-15). Before this the call named no
#: process_id, so llm_lane.generate skipped the consumption gate entirely: no registration check, no process
#: or global cap, no consumption log row -- the RI overnight topic_synth (--max 40) and reground (--max 25)
#: steps and the hourly synth line spent with nothing counting them.
PROCESS_ID = "topic_research_synthesizer"

#: Words that carry no topic signal, used both by the relevance gate below and by the claim trace.
_STOP = {"and", "for", "the", "with", "from", "into", "strategies", "strategy", "ideas",
         "investment", "investor", "management", "monitoring", "plan", "planning", "tax",
         "taxes", "income", "market", "markets", "stock", "stocks", "sector", "rules",
         "best", "top", "2024", "2025", "2026", "2027", "2028"}

#: Refusal reasons recorded on the run summary. A reason, never a silent skip: the caller must be able
#: to tell "the model had nothing to read" from "the model did not answer".
NO_SOURCES = "no_sources"
NO_TRACEABLE_CLAIMS = "no_traceable_claims"


def _claim_tokens(text):
    """Distinctive lowercase words in a claim (same token shape the relevance gate uses)."""
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", str(text or "").lower()).split()
            if len(w) > 3 and not w.isdigit() and w not in _STOP}


def _claim_traces(claim, articles):
    """True when a claim shares at least two distinctive tokens with ONE cited source.

    A trace, not a proof: it answers "did the model read a source that says this?" Two tokens from a
    single article is the bar because one token is how a homonym slips through (see the relevance gate)
    and zero is how an unsourced assertion gets published (2026-11-07, hermes:44896).
    """
    toks = _claim_tokens(claim)
    if not toks:
        return False
    for a in articles or []:
        blob = f"{a.get('title') or ''} {a.get('summary') or ''}".lower()
        if sum(1 for t in toks if t in blob) >= 2:
            return True
    return False


def _claim_trace(result, articles):
    """Count the brief's claims that trace back to the sources the model was grounded on.

    Claims are the ``evidence[]`` entries plus the summary's own substantive sentences — the false
    SSDI/MAGI sentence that reached the desk was summary prose, not an evidence row, so evidence alone
    is not enough to check.
    """
    claims = [str(e.get("text") or "").strip() for e in (result.get("evidence") or [])
              if isinstance(e, dict)]
    for sent in re.split(r"(?<=[.!?])\s+", str(result.get("summary") or "")):
        sent = sent.strip()
        if len(_claim_tokens(sent)) >= 4:
            claims.append(sent)
    seen, uniq = set(), []
    for c in claims:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    traced = [c for c in uniq if _claim_traces(c, articles)]
    untraced = [c for c in uniq if c not in traced]
    return {"claims": len(uniq), "traced": len(traced), "untraced": len(untraced),
            "untraced_samples": [c[:160] for c in untraced[:3]]}


def _synthesize(topic, context, articles=None):
    try:
        from lib.governed_cloud_generation import generate_cloud
    except Exception:
        return None
    # 2026-10-15 (n8n llm lane batch 1): on the governed-bridge path (TRADEAI_LLM_VIA_BRIDGE, bound from the allowlist
    # llm_route of run-research-intelligence-overnight) generate_cloud makes ONE bridge request and the bridge walks
    # grok -> chatgpt -> DeepSeek itself, so the per-lane loop collapses to one attempt (no second request on a
    # refusal); the cron path's grok-then-chatgpt loop is unchanged.
    via_bridge = os.environ.get("TRADEAI_LLM_VIA_BRIDGE", "off").strip().lower() in {"1", "on", "bridge"}
    for lane in (("bridge",) if via_bridge else ("grok", "chatgpt")):  # local generation is refused by policy
        try:
            raw, _used = generate_cloud(_prompt(topic, context, articles), process_id=PROCESS_ID,
                                        task_summary=f"topic research {str(topic)[:80]}", timeout=70,
                                        lanes=(lane,))
            d = parse_hermes_topic_result(raw)
            if not d:
                continue
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
                    "evidence": d.get("evidence", []), "data_i_doubt": d.get("data_i_doubt"),
                    "agent_contract": d.get("agent_contract"),
                    "grounded_on": [{"title": a["title"][:140], "source": a["source"],
                                     "url": a.get("source_url")} for a in (articles or [])[:8]]}
        except Exception:
            continue
    return None


def run(apply=False, max_rows=20, reground=False, ids=None):
    conn = _get_conn(); cur = conn.cursor()
    if ids:
        # Engine Room v1 (WS-2): targeted regeneration of QA-lint-flagged briefs —
        # re-synthesize in place with the universe guard + precise-dating prompt live.
        cur.execute("""SELECT id, topic, evidence_json FROM hermes_research_intelligence
                       WHERE research_type='topic_research' AND id = ANY(%s)""", (list(ids),))
    elif reground:
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
    done, skipped, no_sources, untraced = [], 0, 0, 0
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
            cur.execute(  # nosemgrep: tq-py-sql-fstring -- GRADE/GRADE_ORD literals; tmid bound
                f"""SELECT title, summary, source, source_url FROM news_articles
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
                cur.execute(  # nosemgrep: tq-py-sql-fstring -- literal ILIKE %s list + literals; kw bound
                    f"""SELECT title, summary, source, source_url FROM news_articles
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
                print(f"  [relevance] {(topic or '')[:40]}: kept {len(_kept)}/{len(articles)} "
                      f"articles (need>={_need} tokens)")
            articles = _kept
        # Zero sources is a refusal, not an invitation to write from memory. On 2026-11-07 a brief with
        # sources=[] was synthesized, promoted and labelled "wire"; it asserted that SSDI is excluded from
        # MAGI, which is false. Nothing is written here: the row stays a placeholder (or, on --reground,
        # keeps its stored text, which the desk withholds because grounded_count is 0), and the run
        # repeats cheaply once the crawler has something real for this topic.
        if not articles:
            print(f"  [{NO_SOURCES}] {(topic or '')[:60]}: no source article passed the relevance gate; "
                  f"refusing to synthesize")
            no_sources += 1
            continue
        res = _synthesize(topic, ctx, articles)
        if not res:
            skipped += 1
            continue
        # Every claim must trace to a source the model actually read. A brief whose claims trace to
        # nothing is the same lie as a sourceless one, only harder to see, so it is not written either.
        res["claim_trace"] = _claim_trace(res, articles)
        if res["claim_trace"]["claims"] and not res["claim_trace"]["traced"]:
            print(f"  [{NO_TRACEABLE_CLAIMS}] {(topic or '')[:60]}: none of "
                  f"{res['claim_trace']['claims']} claims traces to a cited source; refusing to write")
            untraced += 1
            continue
        if res["claim_trace"]["untraced"]:
            note = (f"{res['claim_trace']['untraced']} of {res['claim_trace']['claims']} claims could not "
                    f"be traced to the cited sources — verify before acting")
            prior = (res.get("data_i_doubt") or "").strip()
            res["data_i_doubt"] = note if prior in ("", "none") else f"{prior}; {note}"
        done.append({"id": rid, "topic": (topic or "")[:50], "lane": res["lane"],
                     "len": len(res["summary"]), "grounded_on": len(res.get("grounded_on") or []),
                     "claim_trace": res["claim_trace"]})
        if apply:
            # catalog the sites that informed this research into evidence_json (source provenance)
            ev["grounded_on"] = res.get("grounded_on") or []
            ev["grounded_count"] = len(ev["grounded_on"])
            ev["cio_evidence"] = res.get("evidence") or []
            ev["claim_trace"] = res.get("claim_trace")
            ev["data_i_doubt"] = res.get("data_i_doubt")
            ev["agent_contract"] = res.get("agent_contract")
            # Engine Room v1 (WS-3): universe guard at generation — resolve every entity
            # the LLM named against the tracked reference; disclose unknowns in the brief
            # and demote confidence rather than shipping unverifiable names silently.
            try:
                from lib.universe_guard import known_reference, check_prose, disclosure_line
                def _dbq(sql, params=None):
                    cur.execute(sql, params or ())
                    cs = [d[0] for d in cur.description]
                    return [dict(zip(cs, r)) for r in cur.fetchall()]
                _syms, _names = known_reference(_dbq)
                own = [a.get("title") or "" for a in (articles or [])] + [disp, topic or ""]
                guard = check_prose(f"{res['summary']} {res['thesis']}",
                                    known_symbols=_syms, known_names_blob=_names,
                                    own_entities=own)
                ev["universe_guard"] = guard
                disc = disclosure_line(guard)
                if disc:
                    res["summary"] = (res["summary"] + "\n\n" + disc)[:1900]
                    res["confidence"] = min(res["confidence"], 0.5)
            except Exception as _e:
                print(f"  [universe-guard] skipped: {_e}")
            # One write module per store (SoT Phase 9): SQL lives in lib.writers.hermes_research_writer.
            from lib.writers.hermes_research_writer import set_fields_by_id
            set_fields_by_id(cur, ids=[rid], fields={
                "summary": res["summary"], "thesis": res["thesis"], "confidence_score": res["confidence"],
                "model_used": f"synth:{res['lane']}", "evidence_json": ev,
            }, touch_updated_at=True, producer="topic_research_synthesizer")
    if apply:
        conn.commit()
    print(json.dumps({"mode": "APPLIED" if apply else "DRY-RUN", "candidates": len(rows),
                      "synthesized": len(done), "no_lane_result": skipped,
                      "refused_no_sources": no_sources, "refused_untraceable": untraced,
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
    ap.add_argument("--ids", type=str, default=None,
                    help="Comma-separated hermes_research_intelligence ids to re-synthesize in place")
    a = ap.parse_args()
    ids = [int(x) for x in a.ids.split(",") if x.strip()] if a.ids else None
    return run(apply=a.apply, max_rows=a.max, reground=a.reground, ids=ids)


if __name__ == "__main__":
    raise SystemExit(main())
