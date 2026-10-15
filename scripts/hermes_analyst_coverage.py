#!/usr/bin/env python3
"""hermes_analyst_coverage.py — web-grounded analyst-coverage research for thin-Yahoo names.

The card's Street chip / pro-analyst pills read Yahoo consensus only (operator 2026-07-06:
"hermes can research a ticker for analyst reviews"). Yahoo is thin or absent on micro-caps
(MRLN: 2 analysts; no Finviz consensus row at all), so displayed names can carry a "strong
buy" from a sample of 2 with no second opinion. This lane asks the free OAuth models
(Grok / ChatGPT — web-grounded) for CURRENT sell-side coverage and stores a STRUCTURED
consensus row in analyst_consensus_history with source='hermes'. The pro-analyst read model
falls back to these rows when Yahoo has no consensus; they never override Yahoo.

Selection: displayed names (operator-starred / directive / active) whose latest Yahoo snapshot
is missing, stale (>30d) or thin (<= --thin analysts). Dedup: skip names with a hermes-source
row < FRESH_DAYS old. ADVISORY ONLY — research storage, no trading surface.

  python3 scripts/hermes_analyst_coverage.py [--limit 8] [--thin 3] [--symbols MRLN,FTH] [--apply]

Governed bridge (2026-10-15, n8n llm lane batch 2): with TRADEAI_LLM_VIA_BRIDGE=1 (bound by the n8n run executor from
the allowlist ``llm_route`` of lane hermes-analyst-coverage) each symbol is ONE governed-bridge request as process
``hermes_analyst_coverage`` (grok -> chatgpt -> DeepSeek server-side); llm_lane is never imported, there is no
alternate-lane retry, and a refusal is a failed symbol with no INSERT. Without --apply no model is called. The cron
line is unchanged.
"""
from __future__ import annotations
import argparse, json, os, re, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

FRESH_DAYS = 7
#: Registered process + governed-bridge route (advisory_desk / hermes_analyst_coverage).
LLM_PROCESS_ID = "hermes_analyst_coverage"
#: The flag the n8n run executor binds from the allowlist llm_route; read directly.
VIA_BRIDGE_ENV = "TRADEAI_LLM_VIA_BRIDGE"


def _via_bridge():
    return os.environ.get(VIA_BRIDGE_ENV, "off").strip().lower() in {"1", "on", "bridge"}
RECOM_SCORE = {"strong_buy": 1.0, "buy": 2.0, "hold": 3.0, "underperform": 4.0, "sell": 5.0}

PROMPT = """You are a sell-side research librarian. Report the CURRENT professional analyst coverage
for {symbol} ({company}), the {industry} company. Use what you know from recent web coverage —
ratings pages (TipRanks, MarketBeat, Benzinga, WSJ), broker notes, upgrade/downgrade news.

Rules:
- ONLY real, attributable coverage of THIS company (verify ticker + company name match; do not
  confuse it with similarly named companies). If you find none, say so — do not invent firms.
- Prefer actions from the last 12 months. Include the firm name for every rating you report.

Respond with ONLY a JSON object, no prose:
{{"coverage_found": true|false,
  "consensus_label": "strong_buy|buy|hold|underperform|sell|null",
  "analyst_count": <int or null>,
  "mean_target": <number or null>,
  "ratings": [{{"firm": "...", "rating": "...", "target": <number or null>, "as_of": "YYYY-MM or null"}}],
  "sources": ["..."],
  "note": "<=200 chars — anything material (coverage initiated/dropped, disputed data)"}}"""


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _candidates(cur, limit, thin, symbols=None):
    if symbols:
        cur.execute("""SELECT DISTINCT ON (wi.symbol) wi.symbol, sp.description_1s, sp.industry
                       FROM watchlist_items wi
                       LEFT JOIN symbol_profiles sp ON upper(sp.symbol)=upper(wi.symbol)
                       WHERE upper(wi.symbol) = ANY(%s) AND wi.status <> 'removed'
                       ORDER BY wi.symbol""", (sorted({s.upper() for s in symbols}),))
        return cur.fetchall()
    cur.execute("""SELECT DISTINCT ON (wi.symbol) wi.symbol, sp.description_1s, sp.industry,
                     EXISTS (SELECT 1 FROM operator_starred_symbols s
                             WHERE upper(s.symbol)=upper(wi.symbol)) AS _starred, wi.hermes_rank
                   FROM watchlist_items wi
                   LEFT JOIN symbol_profiles sp ON upper(sp.symbol)=upper(wi.symbol)
                   LEFT JOIN LATERAL (SELECT number_of_analyst_opinions n, created_at
                                      FROM yahoo_analyst_targets_history y
                                      WHERE y.symbol = wi.symbol
                                      ORDER BY created_at DESC LIMIT 1) ya ON true
                   WHERE wi.symbol ~ '^[A-Z]{1,5}$' AND wi.status <> 'removed'
                     AND (wi.in_directive_watch=true OR wi.status='active'
                          OR EXISTS (SELECT 1 FROM operator_starred_symbols s
                                     WHERE upper(s.symbol)=upper(wi.symbol)))
                     -- thin/absent/stale Yahoo coverage only
                     AND (ya.n IS NULL OR ya.n <= %s OR ya.created_at < now() - interval '30 days')
                     -- dedup: one hermes read per symbol per week
                     AND NOT EXISTS (SELECT 1 FROM analyst_consensus_history ach
                                     WHERE ach.symbol = wi.symbol AND ach.source = 'hermes'
                                       AND ach.created_at > now() - make_interval(days => %s))
                   ORDER BY wi.symbol""", (thin, FRESH_DAYS))
    rows = cur.fetchall()
    rows.sort(key=lambda r: (not r["_starred"], r["hermes_rank"] is None, r["hermes_rank"] or 1e9))
    return rows[:limit]


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def run(limit=8, thin=3, symbols=None, apply=False):
    import psycopg2.extras
    via_bridge = _via_bridge()
    if via_bridge:
        from lib.llm_bridge_route import require_text_via_bridge
        llm_lane, lane = None, "bridge"
    else:
        import llm_lane
    conn = _conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if not via_bridge:
        lane = "grok" if llm_lane.available("grok") else ("chatgpt" if llm_lane.available("chatgpt") else None)
    if lane is None:
        print(json.dumps({"error": "no OAuth lane available — coverage research needs web-grounded models"}))
        return 1
    rows = _candidates(cur, limit, thin, symbols)
    done = skipped = failed = 0
    for r in rows:
        sym = r["symbol"]
        company = (r.get("description_1s") or "").split(",")[0].split(".")[0].strip() or sym
        prompt = PROMPT.format(symbol=sym, company=company, industry=r.get("industry") or "unknown-industry")
        if not apply:
            print(f"  {sym}: dry-run (company={company})"); skipped += 1; continue
        if via_bridge:
            try:
                out = require_text_via_bridge(LLM_PROCESS_ID, prompt, timeout_s=120)
            except Exception:  # noqa: BLE001 -- a refusal is a failed symbol, never another lane
                out = None
        else:
            try:
                out = llm_lane.generate(prompt, lane=lane, timeout=120)
            except Exception:
                alt = "chatgpt" if lane == "grok" else "grok"
                try:
                    out = llm_lane.generate(prompt, lane=alt, timeout=120) if llm_lane.available(alt) else None
                except Exception:
                    out = None
        p = _parse(out) if out else None
        if not p:
            print(f"  {sym}: unparseable/lane error"); failed += 1; continue
        found = bool(p.get("coverage_found"))
        label = (p.get("consensus_label") or "").strip().lower() or None
        if label not in RECOM_SCORE:
            label = None
        tgt = p.get("mean_target")
        try:
            tgt = round(float(tgt), 2) if tgt is not None else None
        except Exception:
            tgt = None
        # store even "no coverage found" (found=false) — it answers the question and feeds the dedup,
        # but only rows WITH a rating or target are usable by the read model
        cur.execute("""INSERT INTO analyst_consensus_history
                         (snapshot_date, symbol, recom_raw, recom_score, analyst_rating,
                          target_price, source, data)
                       VALUES (current_date, %s, %s, %s, %s, %s, 'hermes', %s)""",
                    (sym, label, RECOM_SCORE.get(label), label, tgt, json.dumps(p)))
        conn.commit()
        done += 1
        print(f"  {sym}: {'consensus ' + label if label else ('no rated coverage' if not found else 'coverage w/o consensus')}"
              f"{f' · mean target {tgt}' if tgt else ''} · {len(p.get('ratings') or [])} firms · lane {lane}")
    print(json.dumps({"lane": lane, "candidates": len(rows), "stored": done, "failed": failed,
                      "dry_run_skipped": skipped, "note": "ADVISORY — research storage only"}))
    return 1 if failed else 0


def _execute():
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--thin", type=int, default=3)
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    sys.exit(run(limit=a.limit, thin=a.thin,
                 symbols=a.symbols.split(",") if a.symbols else None, apply=a.apply))


def main(argv=None) -> int:
    """Strict offline inspection before the legacy business execution path."""
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--thin", type=int, default=3)
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="offline source plan")
    a = ap.parse_args(argv)
    args = a
    lane = "hermes-analyst-coverage"
    if args.dry_run:
        print(f"DRY-RUN {lane}: would research analyst consensus for selected symbols and store advisory consensus rows; options={vars(args)}; inputs NOT_MEASURED")
        return 0
    try:
        from scripts.lib.lane_last_receipt import now_iso, write_lane_receipt
    except ImportError:
        from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    previous = sys.argv
    sys.argv = [previous[0], *argv]
    try:
        result = _execute()
        rc = int(result) if isinstance(result, int) else 0
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        write_lane_receipt(lane, ok=rc == 0, exit_code=rc, started_at=started, script="hermes_analyst_coverage.py", summary={"completed": rc == 0})
        raise
    except Exception as exc:
        write_lane_receipt(lane, ok=False, exit_code=1, started_at=started, script="hermes_analyst_coverage.py", error=type(exc).__name__)
        raise
    finally:
        sys.argv = previous
    write_lane_receipt(lane, ok=rc == 0, exit_code=rc, started_at=started, script="hermes_analyst_coverage.py", summary={"completed": rc == 0})
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
