#!/usr/bin/env python3
"""One-off diagnostic: why do certain retirement topic_research rows ground on 0 sources?"""
import sys, re, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _execute

THEMES = [r"\broth\b|conversion|golden window|\brmd\b|backdoor|qualified charitable",
          r"medicare|irmaa|medigap|part [bd]\b",
          r"medicaid|\bmapt\b|asset protection|spend.?down|look.?back|estate recovery|special needs|supplemental needs",
          r"estate|\btrust\b|probate|life estate|beneficiar|\bwill\b|inheritance",
          r"\bssdi\b|social security|disability|\bmagi\b|tax.?loss|tax-efficient|tax strateg|\bqcd\b|\bhsa\b|earnings test|substantial gainful",
          r"dividend income|covered call|bond ladder|tips|fixed.?income|annuit|drawdown|income sleeve|monthly income|dividend aristocrat|income strateg|bucket strateg|\bcef\b|\bpty\b|\bnav\b"]
TRADING = re.compile(r"swing|momentum|sector rotation|option|greeks|iron condor|earnings season|technical|breakout|scalp|reddit|chart|implied vol|theta|premium sell|datacenter|data center|semiconductor|ai chip|nvidia|defense|aerospace|materials sector|geopolitical|glp-1|weight.?loss|hot topics|controvers|collar|sentiment-driven|emerging sector|infrastructure buildout|hedging|catalyst|energy sector|utilities sector|consumer (defensive|staples)|healthcare rotation|trending|hype", re.I)
_STOP = {"and","for","the","with","from","into","strategies","strategy","ideas","investment","investor","management","monitoring","plan","planning","tax","taxes","income","market","markets","stock","stocks","sector","rules","best","top","2024","2025","2026","2027","2028"}

rows = _execute("SELECT topic, evidence_json FROM hermes_research_intelligence WHERE research_type='topic_research' AND model_used LIKE 'synth:%%'", fetch="all") or []
zero = []
for r in rows:
    t = r['topic'] or ''
    if TRADING.search(t) or not any(re.search(rx, t, re.I) for rx in THEMES):
        continue
    ev = r['evidence_json']; ev = ev if isinstance(ev, dict) else (json.loads(ev) if ev else {})
    if not (ev.get('grounded_on') or []):
        zero.append((t, ev.get('topic_monitor_id')))

print(f"=== {len(zero)} zero-grounded retirement topics ===")
for t, tmid in zero:
    tm = _execute("SELECT last_searched, last_found_count FROM topic_monitor WHERE topic_id=%s", (tmid,), fetch="one") if tmid else None
    prim = _execute("SELECT count(*) c FROM news_articles WHERE symbol=%s", (tmid,), fetch="one")['c'] if tmid else 0
    kw = [w for w in re.sub(r"[^a-z0-9 ]", " ", t.lower()).split() if len(w) > 3 and not w.isdigit() and w not in _STOP][:4]
    fb = []
    if kw:
        ors = " OR ".join(["title ILIKE %s"] * len(kw))
        fb = _execute(f"SELECT title FROM news_articles WHERE ({ors}) AND published_at>now()-interval '60 days' ORDER BY published_at DESC LIMIT 6", tuple(f'%{w}%' for w in kw), fetch="all") or []
    diag = "NO candidates (ingestion found nothing)" if (prim == 0 and not fb) else "candidates exist but OFF-TOPIC (gated out)"
    print(f"\n- {t[:46]}  [{diag}]")
    print(f"    symbol-tagged news={prim} | fallback kw {kw} -> {len(fb)} cands | last_found={tm['last_found_count'] if tm else '?'}")
    for a in fb[:3]:
        print(f"        cand: {(a['title'] or '')[:54]}")
