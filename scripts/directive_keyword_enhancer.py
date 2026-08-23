#!/usr/bin/env python3
"""directive_keyword_enhancer.py — LLM-derive keywords + seed symbols for a trend/sector watch directive
(operator 2026-06-19). The Hermes discovery producer surfaces candidates by phrase-matching a directive's
spec.keywords against research + by spec.seed_symbols; a directive created with only a label (no keywords/
seeds) therefore surfaces NOTHING. This auto-enhances the theme into usable keywords + seed tickers.

FREE OAuth lanes only (Grok + ChatGPT), via llm_lane — no metered API and no local generation. Advisory:
output is keyword/seed metadata, never a trade. Falls back to a label-derived keyword if all lanes are down.

  python3 scripts/directive_keyword_enhancer.py --backfill [--apply]   # enhance active trend/sector dirs lacking keywords
  python3 scripts/directive_keyword_enhancer.py --label "Energy" --kind trend   # one-off preview
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_TICK = re.compile(r"^[A-Z]{1,5}$")


def _parse_json(text: str) -> dict:
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return {}


def enhance(label: str, kind: str = "trend", existing_keywords=None) -> dict:
    """Return {keywords:[...], seed_symbols:[...]} for a theme. LLM (free OAuth) with a label fallback."""
    label = (label or "").strip()
    prompt = (
        f'Investment theme: "{label}".\n'
        'Return ONLY a JSON object, no prose:\n'
        '{"keywords": [5-8 precise multi-word phrases or distinctive single words an analyst would use to '
        'find RESEARCH on this exact theme — e.g. "liquid cooling", "data center power"; avoid generic single '
        'words like "data", "energy", "power" alone], '
        '"seed_symbols": [4-8 well-known US-listed tickers that are leading or pure-play names for this theme]}.'
        ' Tickers uppercase only.'
    )
    # Merge the two governed OAuth lanes. Failure falls back to deterministic label metadata.
    kws, syms, used = [], [], []
    try:
        import llm_lane
        for lane in ("grok", "chatgpt"):
            try:
                if not llm_lane.available(lane):
                    continue
                parsed = _parse_json(llm_lane.generate(
                    prompt, lane=lane, timeout=60,
                    process_id="directive_keyword_enhancer",
                    task_summary=f"directive keywords {label[:80]}",
                ))
                lk = [k.strip() for k in (parsed.get("keywords") or []) if isinstance(k, str) and k.strip()]
                ls = [s.strip().upper() for s in (parsed.get("seed_symbols") or [])
                      if isinstance(s, str) and _TICK.match(s.strip().upper())]
                if lk or ls:
                    used.append(lane)
                    for k in lk:
                        if k.lower() not in [x.lower() for x in kws]:
                            kws.append(k)
                    for s in ls:
                        if s not in syms:
                            syms.append(s)
            except Exception:
                continue
    except Exception:
        pass
    # fallback: a phrase keyword from the label (strip a leading 'trend '/'sector ')
    if not kws:
        lbl = re.sub(r"^(trend|sector)\s+", "", label, flags=re.I).strip()
        if lbl:
            kws = [lbl]
    for k in (existing_keywords or []):
        if k and k not in kws:
            kws.append(k)
    return {"keywords": kws[:12], "seed_symbols": syms[:10], "lane": "+".join(used) or "fallback"}


def backfill(apply: bool = False, force: bool = False) -> list:
    """Enhance active trend/sector directives that lack usable keywords (empty, or a single >3-word phrase).
    force=True re-enhances ALL of them (merging the ensemble into existing keywords)."""
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("SELECT id, label, kind, spec FROM watch_directives WHERE kind IN ('trend','sector') AND status='active'")
    results = []
    for did, label, kind, spec in cur.fetchall():
        sp = spec if isinstance(spec, dict) else json.loads(spec or "{}")
        kws = sp.get("keywords") or []
        seeds = sp.get("seed_symbols") or []
        weak = (not kws) or (len(kws) == 1 and len(str(kws[0]).split()) >= 4 and not seeds)
        if not weak and not force:
            continue
        enh = enhance(label, kind, existing_keywords=[k for k in kws if len(str(k).split()) < 4])
        results.append({"id": did, "label": label, "lane": enh["lane"],
                        "keywords": enh["keywords"], "seed_symbols": enh["seed_symbols"]})
        if apply:
            sp["keywords"] = enh["keywords"]
            if enh["seed_symbols"]:
                sp["seed_symbols"] = enh["seed_symbols"]
            sp["keywords_source"] = f"llm:{enh['lane']}"
            cur.execute("UPDATE watch_directives SET spec=%s::jsonb, updated_at=now() WHERE id=%s",
                        (json.dumps(sp), did))
    if apply:
        conn.commit()
    return results


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--label"); ap.add_argument("--kind", default="trend")
    a = ap.parse_args()
    if a.label:
        print(json.dumps(enhance(a.label, a.kind), indent=2))
    elif a.backfill:
        res = backfill(apply=a.apply, force=a.force)
        print(json.dumps({"mode": "APPLIED" if a.apply else "DRY-RUN", "enhanced": res}, indent=2))
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
