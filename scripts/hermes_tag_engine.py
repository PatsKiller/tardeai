#!/usr/bin/env python3
"""hermes_tag_engine.py — Phase 4: tags that earn their keep
(docs/design/HERMES_MATURITY_5_DESIGN.md §4). The single owner of Hermes tagging.

  retag     strategy_tags on the STRATEGY-REGISTRY vocabulary (one source of truth, no ad-hoc
            regex families). Rules from config synonyms decide first (free); the local LLM
            (temp 0, constrained to registry slugs) refines only undecided symbol-linked rows,
            capped per run; the rest stay general_research — target <15% fallback (was 50%).
  quality   quality_score v2: continuous blend of the existing rule score and the outcome
            ledger's per-research_type prior (Bayesian-shrunk). Kills the 0.30/0.62
            two-point-mass "grade".
  efficacy  hermes_tag_efficacy: per-tag hit-rate vs base rate from the ledger — a tag that
            doesn't out-predict its base rate gets flagged. Tags become falsifiable.

The 3-axis taxonomy cron is retired with this change (zero readers repo-wide — write-only cost).
Zero paid LLM. Advisory-only; honors data/runtime/HERMES_DISABLED.

  python3 scripts/hermes_tag_engine.py            # dry-run
  python3 scripts/hermes_tag_engine.py --apply    # nightly cron
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

KILL_SWITCH = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"
CFG_FILE = PROJECT_ROOT / "config" / "hermes_tag_engine.yaml"


def _cfg():
    import yaml
    return yaml.safe_load(CFG_FILE.read_text())


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _vocab(cur):
    cur.execute("SELECT strategy_type FROM strategy_registry WHERE active ORDER BY 1")
    return [r[0] for r in cur.fetchall()]


def _cues(cfg, vocab):
    """slug -> list of lowercase cue phrases (slug tokens + config synonyms)."""
    cues = {}
    syn = cfg.get("synonyms") or {}
    for slug in vocab:
        base = [slug.replace("_", " ")]
        cues[slug] = [str(c).lower() for c in base + list(syn.get(slug) or [])]
    return cues


def _rule_tags(text, cues, max_tags):
    t = (text or "").lower()
    hits = []
    for slug, phrases in cues.items():
        score = sum(1 for p in phrases if p in t)
        if score:
            hits.append((score, slug))
    hits.sort(key=lambda x: (-x[0], x[1]))
    return [s for _n, s in hits[:max_tags]]


def _llm_tags(text, vocab, timeout, max_tags):
    """Local LLM, temp 0, constrained to registry slugs. Returns [] on any failure."""
    try:
        from local_llm_config import get_local_llm_base_url, get_local_llm_model
        prompt = ("You are a strict classifier for a trading research system. Pick up to "
                  f"{max_tags} strategy slugs that genuinely fit this research text, from ONLY "
                  "this list (empty list if none fit):\n" + ", ".join(vocab) +
                  "\n\nText:\n" + (text or "")[:1500] +
                  '\n\nRespond ONLY with JSON: {"tags": ["slug", ...]}')
        body = json.dumps({"model": get_local_llm_model(), "prompt": prompt, "stream": False,
                           "format": "json", "options": {"temperature": 0}}).encode()
        req = urllib.request.Request(get_local_llm_base_url().rstrip("/") + "/api/generate",
                                     data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
        tags = (json.loads(resp.get("response", "{}")).get("tags") or [])
        return [t for t in tags if t in vocab][:max_tags]
    except Exception:
        return []


def retag(cfg, apply):
    """Two-connection design: the LLM refine batch can queue on the shared GPU for many minutes,
    which kills an idle DB connection — so fetch first, classify with NO connection held, then
    write on a fresh connection. LLM work is additionally wall-clock capped."""
    import time
    r = cfg["retag"]
    fb, mx = cfg["fallback_tag"], int(cfg["max_tags"])

    conn = _conn(); cur = conn.cursor()
    vocab = _vocab(cur)
    cues = _cues(cfg, vocab)
    # eligible: fallback-only or empty tags; newest first (fresh research matters most)
    cur.execute("""SELECT id, symbol, COALESCE(topic,'')||' '||COALESCE(summary,'')||' '||
                          COALESCE(thesis,'')||' '||COALESCE(research_type,'') AS txt
                   FROM hermes_research_intelligence
                   WHERE strategy_tags IS NULL OR strategy_tags = '{}'
                      OR strategy_tags = %s::text[]
                   ORDER BY created_at DESC LIMIT %s""", ([fb], r["backlog_batch"]))
    rows = cur.fetchall()
    conn.close()

    ruled = llmed = fell_back = 0
    llm_budget = int(r["llm_batch"])
    llm_deadline = time.monotonic() + int(r.get("llm_wall_clock_s", 240))
    results = []
    for rid, sym, txt in rows:
        tags = _rule_tags(txt, cues, mx)
        how = "rule"
        if not tags and sym and llm_budget > 0 and time.monotonic() < llm_deadline:
            tags = _llm_tags(txt, vocab, int(r["llm_timeout_s"]), mx)
            llm_budget -= 1
            how = "llm" if tags else how
        if not tags:
            tags, how = [fb], "fallback"
        results.append((rid, tags))
        if how == "rule":
            ruled += 1
        elif how == "llm":
            llmed += 1
        else:
            fell_back += 1

    conn = _conn(); cur = conn.cursor()
    if apply:
        for rid, tags in results:
            cur.execute("UPDATE hermes_research_intelligence SET strategy_tags=%s WHERE id=%s",
                        (tags, rid))
        conn.commit()
    # fallback share across recent rows (the <15% target metric)
    cur.execute("""SELECT count(*) FILTER (WHERE strategy_tags = %s::text[]) fb, count(*) tot
                   FROM hermes_research_intelligence
                   WHERE created_at > NOW() - interval '30 days'""", ([fb],))
    fbn, tot = cur.fetchone()
    conn.close()
    return {"batch": len(rows), "rule_tagged": ruled, "llm_tagged": llmed, "fallback": fell_back,
            "fallback_share_30d": round(fbn / tot, 3) if tot else None}


def quality_v2(cur, cfg, apply):
    q = cfg["quality"]
    # outcome prior per research_type from the ledger (research rows: actioned = hit)
    cur.execute("""SELECT COALESCE(hri.research_type,'unknown') rtype,
                          count(*) FILTER (WHERE l.actioned IS NOT NULL AND l.actioned <> 'none') a,
                          count(*) FILTER (WHERE l.actioned IS NOT NULL) n
                   FROM hermes_outcome_ledger l
                   JOIN hermes_research_intelligence hri ON hri.id = l.subject_id
                   WHERE l.subject_type='research_row'
                   GROUP BY 1""")
    k, neutral = float(q["shrink_k"]), float(q["neutral"])
    priors = {rt: (a + k * neutral) / (n + k) for rt, a, n in cur.fetchall() if n}
    be, bo = float(q["blend_existing"]), float(q["blend_outcome_prior"])
    updated = 0
    if apply:
        for rt, prior in priors.items():
            cur.execute("""UPDATE hermes_research_intelligence
                           SET quality_score = ROUND((%s * COALESCE(quality_score, %s) + %s * %s)::numeric, 3)
                           WHERE COALESCE(research_type,'unknown') = %s""",
                        (be, neutral, bo, prior, rt))
            updated += cur.rowcount
    # distribution health (the two-point-mass detector)
    cur.execute("""SELECT round(stddev(quality_score)::numeric,4), count(DISTINCT quality_score)
                   FROM hermes_research_intelligence WHERE quality_score IS NOT NULL""")
    sd, distinct = cur.fetchone()
    return {"types_with_prior": len(priors),
            "priors_sample": {t: round(p, 3) for t, p in sorted(priors.items())[:6]},
            "rows_updated": updated, "quality_stddev": float(sd) if sd is not None else None,
            "distinct_values": distinct}


def tag_efficacy(cur, cfg, apply):
    cur.execute("""CREATE TABLE IF NOT EXISTS hermes_tag_efficacy (
                     tag TEXT PRIMARY KEY, n INT, hits INT, hit_rate NUMERIC,
                     base_rate NUMERIC, lift NUMERIC, flagged BOOLEAN, updated_at TIMESTAMPTZ)""")
    cur.execute("ALTER TABLE hermes_tag_efficacy ADD COLUMN IF NOT EXISTS trade_n INT")
    cur.execute("ALTER TABLE hermes_tag_efficacy ADD COLUMN IF NOT EXISTS avg_realized_r NUMERIC")
    cur.execute("""SELECT unnest(hri.strategy_tags) tag,
                          count(*) FILTER (WHERE l.actioned <> 'none') hits, count(*) n
                   FROM hermes_outcome_ledger l
                   JOIN hermes_research_intelligence hri ON hri.id = l.subject_id
                   WHERE l.subject_type='research_row' AND l.actioned IS NOT NULL
                     AND hri.strategy_tags IS NOT NULL
                   GROUP BY 1""")
    rows = cur.fetchall()
    # R-multiple by tag: trades in the ledger joined to prior tagged research on the same symbol
    # (research within 30d before entry). Answers "does research tagged X precede money?"
    cur.execute("""SELECT tag, count(*) trade_n, avg(realized_r) avg_r FROM (
                     SELECT DISTINCT lt.subject_id, unnest(hri.strategy_tags) tag, lt.realized_r
                     FROM hermes_outcome_ledger lt
                     JOIN hermes_research_intelligence hri
                       ON UPPER(hri.symbol) = lt.symbol
                      AND hri.created_at BETWEEN lt.emitted_at - interval '30 days' AND lt.emitted_at
                     WHERE lt.subject_type='trade' AND lt.realized_r IS NOT NULL
                       AND hri.strategy_tags IS NOT NULL) x
                   GROUP BY tag""")
    r_by_tag = {r[0]: (r[1], float(r[2])) for r in cur.fetchall()}
    tot_h = sum(r[1] for r in rows); tot_n = sum(r[2] for r in rows)
    base = tot_h / tot_n if tot_n else None
    min_n = int(cfg["efficacy"]["min_samples_per_tag"])
    out = {"base_rate": round(base, 3) if base is not None else None, "tags": [], "flagged": []}
    for tag, hits, n in sorted(rows, key=lambda r: -r[2]):
        hr = hits / n if n else None
        lift = (hr - base) if (hr is not None and base is not None) else None
        flagged = bool(n >= min_n and lift is not None and lift <= 0)
        tn, avg_r = r_by_tag.get(tag, (0, None))
        out["tags"].append({"tag": tag, "n": n, "hit_rate": round(hr, 3),
                            "lift": round(lift, 3) if lift is not None else None,
                            "trade_n": tn, "avg_realized_r": round(avg_r, 3) if avg_r is not None else None})
        if flagged:
            out["flagged"].append(tag)
        if apply:
            cur.execute("""INSERT INTO hermes_tag_efficacy (tag, n, hits, hit_rate, base_rate, lift,
                                                            flagged, trade_n, avg_realized_r, updated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                           ON CONFLICT (tag) DO UPDATE SET n=EXCLUDED.n, hits=EXCLUDED.hits,
                             hit_rate=EXCLUDED.hit_rate, base_rate=EXCLUDED.base_rate,
                             lift=EXCLUDED.lift, flagged=EXCLUDED.flagged,
                             trade_n=EXCLUDED.trade_n, avg_realized_r=EXCLUDED.avg_realized_r,
                             updated_at=NOW()""",
                        (tag, n, hits, hr, base, lift, flagged, tn, avg_r))
    return out


def run(apply=False):
    if KILL_SWITCH.exists():
        out = {"ok": False, "reason": "HERMES_DISABLED kill switch present — tag engine idle"}
        print(json.dumps(out))
        return out
    cfg = _cfg()
    out = {"ok": True, "apply": apply}
    out["retag"] = retag(cfg, apply)   # manages its own connections (LLM batch is slow)
    conn = _conn(); cur = conn.cursor()
    out["quality"] = quality_v2(cur, cfg, apply)
    out["efficacy"] = tag_efficacy(cur, cfg, apply)
    if apply:
        conn.commit()
    out["ts"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(out, indent=2, default=str))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    run(apply=ap.parse_args().apply)


if __name__ == "__main__":
    main()
