#!/usr/bin/env python3
"""directive_keyword_enhancer.py — LLM-derive keywords + seed symbols for a trend/sector watch directive
(operator 2026-06-19). The Hermes discovery producer surfaces candidates by phrase-matching a directive's
spec.keywords against research + by spec.seed_symbols; a directive created with only a label (no keywords/
seeds) therefore surfaces NOTHING. This auto-enhances the theme into usable keywords + seed tickers.

FREE OAuth lanes only (Grok + ChatGPT), via llm_lane — no metered API and no local generation. Advisory:
output is keyword/seed metadata, never a trade. Falls back to a label-derived keyword if all lanes are down.

  python3 scripts/directive_keyword_enhancer.py --backfill [--apply]   # enhance active trend/sector dirs lacking keywords
  python3 scripts/directive_keyword_enhancer.py --label "Energy" --kind trend   # one-off preview

Governed bridge (2026-10-15, n8n llm lane batch 1): with TRADEAI_LLM_VIA_BRIDGE=1 (bound by the n8n run executor from
the allowlist ``llm_route`` of lane directive-keyword-enhancer) each theme is ONE governed-bridge request as process
``directive_keyword_enhancer`` (grok -> chatgpt -> DeepSeek server-side) instead of the grok+chatgpt ensemble;
llm_lane is never imported. A refusal or an empty answer is NO output: the directive is left untouched (no
label-derived fallback keyword is written on this path) and reported with lane ``bridge_refused``. --dry-run makes no
model call. The cron line is unchanged.
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_TICK = re.compile(r"^[A-Z]{1,5}$")
#: Registered process + governed-bridge route (advisory_desk / directive_keyword_enhancer).
LLM_PROCESS_ID = "directive_keyword_enhancer"
#: The flag the n8n run executor binds from the allowlist llm_route; read directly (a failed import with the flag ON
#: raises, it never falls through to the in-process ensemble).
VIA_BRIDGE_ENV = "TRADEAI_LLM_VIA_BRIDGE"
BRIDGE_REFUSED_LANE = "bridge_refused"


def _via_bridge() -> bool:
    return os.environ.get(VIA_BRIDGE_ENV, "off").strip().lower() in {"1", "on", "bridge"}


def _merge(parsed: dict, kws: list, syms: list) -> bool:
    lk = [k.strip() for k in (parsed.get("keywords") or []) if isinstance(k, str) and k.strip()]
    ls = [s.strip().upper() for s in (parsed.get("seed_symbols") or [])
          if isinstance(s, str) and _TICK.match(s.strip().upper())]
    for k in lk:
        if k.lower() not in [x.lower() for x in kws]:
            kws.append(k)
    for s in ls:
        if s not in syms:
            syms.append(s)
    return bool(lk or ls)


def _enhance_via_bridge(prompt: str, label: str, existing_keywords) -> dict:
    """ONE governed-bridge request. No answer = no output (lane bridge_refused, nothing to write)."""
    from lib.llm_bridge_route import require_text_via_bridge

    kws, syms = [], []
    try:
        ok = _merge(_parse_json(require_text_via_bridge(LLM_PROCESS_ID, prompt, timeout_s=60)), kws, syms)
    except Exception:  # noqa: BLE001 -- a refusal is no output, never another provider
        ok = False
    if not ok:
        return {"keywords": [], "seed_symbols": [], "lane": BRIDGE_REFUSED_LANE}
    for k in (existing_keywords or []):
        if k and k not in kws:
            kws.append(k)
    return {"keywords": kws[:12], "seed_symbols": syms[:10], "lane": "bridge"}


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
    if _via_bridge():
        return _enhance_via_bridge(prompt, label, existing_keywords)
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
        if enh["lane"] == BRIDGE_REFUSED_LANE:
            continue  # governed bridge refused: the directive is left exactly as it was
        if apply:
            sp["keywords"] = enh["keywords"]
            if enh["seed_symbols"]:
                sp["seed_symbols"] = enh["seed_symbols"]
            sp["keywords_source"] = f"llm:{enh['lane']}"
            from lib.writers.watch_directives_writer import update_watch_directive
            update_watch_directive(cur, did, source="directive_keyword_enhancer", spec=sp)
    if apply:
        conn.commit()
    return results


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--label"); ap.add_argument("--kind", default="trend")
    ap.add_argument("--dry-run", action="store_true", help="offline plan; no DB, model or writes")
    a = ap.parse_args(argv)
    if a.dry_run:
        action = f"enhance label={a.label!r} kind={a.kind}" if a.label else "backfill active trend/sector directives"
        print(f"DRY-RUN directive-keyword-enhancer: would {action}; apply={a.apply} force={a.force}; no DB, model, network or writes")
        return 0
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    if a.label:
        print(json.dumps(enhance(a.label, a.kind), indent=2))
    elif a.backfill:
        try:
            res = backfill(apply=a.apply, force=a.force)
        except Exception as exc:
            write_lane_receipt("directive-keyword-enhancer", ok=False, exit_code=1,
                               started_at=started, error=type(exc).__name__)
            raise
        if a.apply:
            write_lane_receipt("directive-keyword-enhancer", ok=True, exit_code=0,
                               started_at=started, summary={"enhanced": len(res), "force": a.force})
        print(json.dumps({"mode": "APPLIED" if a.apply else "DRY-RUN", "enhanced": res}, indent=2))
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
