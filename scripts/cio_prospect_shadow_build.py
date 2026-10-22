#!/usr/bin/env python3
"""CIO prospect shadow build — one prospect per security_guid, assembled from the existing stores.

    .venv/bin/python scripts/cio_prospect_shadow_build.py --dry-run              # print a summary, write nothing
    .venv/bin/python scripts/cio_prospect_shadow_build.py --dry-run --with-db    # + read-only DB inputs
    .venv/bin/python scripts/cio_prospect_shadow_build.py --dry-run --compare \
        --watch-surface-json <captured /api/v3/data-broker/watch-intelligence?view=top_ideas> --report-md <out.md>
    .venv/bin/python scripts/cio_prospect_shadow_build.py --write-shadow         # canary/live only (§23.21)

AGENTS.md §26 (18.0.0, ACTIVE); docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md §7 P1 "Shadow".
n8n lane ``cio-prospect-shadow`` (stage shadow: the dispatcher runs ``--dry-run`` only; live_arg null).

``--dry-run`` (the default) writes NOTHING: no store, no shadow artifact, no receipt. ``--report-md`` and
``--out`` write only the path the caller names (an operator/agent report outside any store). ``--write-shadow``
writes the shadow artifact the ``cio_prospect`` projection serves while the store is not live
(data/cio/cio_prospect_shadow.json), the comparison (data/cio/cio_prospect_shadow_compare.json) and the lane
receipt (data/runtime/cio-prospect-shadow_last.json); it never writes ``cio_prospect`` and never calls
InstrumentRecordStore — the shadow is not the store.

Never: a broker call, a positions_current read (the held set comes from the positions_context projection),
a model call, a send, a write to any input store. MBI_BEHAVIOR = 0.

Exit codes: 0 built; 1 built but no prospect could be assembled (empty output is a failure, not a
success); 2 could not run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib import cio_prospect_builder as builder  # noqa: E402

LANE_ID = "cio-prospect-shadow"
SHADOW_REL = "data/cio/cio_prospect_shadow.json"
COMPARE_REL = "data/cio/cio_prospect_shadow_compare.json"
RECEIPT_REL = "data/runtime/cio-prospect-shadow_last.json"


def _state_root(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    from scripts.lib.canonical_store_registry import production_state_root
    return Path(production_state_root())


def _readonly_db_query():
    """A read-only ``db_query(sql) -> rows`` (server-enforced READ ONLY session)."""
    import psycopg2.extras

    from scripts.lib.lane_last_receipt import enforce_readonly
    from scripts.session13_db import get_conn

    conn = enforce_readonly(get_conn())

    def q(sql: str, params: tuple | None = None) -> list[dict]:
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.rollback()          # every read ends its transaction, so one failed SELECT never poisons the next
    return q, conn


def _watch_list(path: str | None) -> tuple[list[str] | None, str | None]:
    if not path:
        return None, None
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    items = doc.get("items") or []
    syms = [str(i.get("symbol")).upper() for i in items if isinstance(i, dict) and i.get("symbol")]
    return syms, (f"captured {Path(path).name} (rank_version {doc.get('rank_version')}, generated_at "
                  f"{doc.get('generated_at')}, {len(syms)} top ideas)")


def summary(doc: dict, top: int = 15) -> dict:
    return {
        "schema": doc["schema"], "as_of": doc["as_of"], "mode": doc["mode"], "writes": doc["writes"],
        "store_status": {k: doc["store_status"][k] for k in ("live", "mode", "reasons")},
        "counts": doc["counts"],
        "sources": {n: {"status": s["status"], "count": s["count"], "as_of": s["as_of"]}
                    for n, s in doc["sources"].items()},
        "held": doc["held"],
        "watchlist_curation": doc["watchlist_curation"],
        "top": [{"symbol": r["symbol"], "stage": r["stage"], "stance": r["stance"], "conviction": r["conviction"],
                 "conflicts": [c["field"] for c in r["conflicts"]]} for r in doc["prospects"][:top]],
        "errors": doc["errors"][:10],
    }


def render_md(doc: dict, cmp: dict) -> str:
    s, c = cmp["summary"], doc["counts"]
    L = [
        "# CIO prospect shadow build — comparison vs today's surfaces",
        "",
        "```",
        "Status:      SHADOW — evidence for the operator's §17 decisions; nothing here is live",
        f"as_of:       {doc['as_of']}",
        "Measured at: scripts/cio_prospect_shadow_build.py --dry-run --compare (read-only; no store written)",
        "```",
        "",
        f"Store status: **{doc['store_status']['mode']}** ({', '.join(doc['store_status']['reasons']) or 'live'}). "
        "The prospects below are the shadow build, not the store.",
        "",
        "## Build",
        "",
        f"- universe {c['universe']} symbols → **{c['prospects']} prospects** (one per security_guid); "
        f"{c['identity_unresolved']} identity unresolved (no prospect, by rule); {c['duplicate_guid']} duplicate GUID "
        f"aliases; {c['errors']} errors",
        f"- by stage: {json.dumps(c['by_stage'], sort_keys=True)}",
        f"- **{c['with_conflicts']} prospects carry {c['conflicts']} recorded conflicts** (shown, never resolved)",
        f"- held set: {doc['held'].get('symbols')} symbols from `{doc['held'].get('source')}`"
        f" (as_of {doc['held'].get('as_of')}); a held symbol without a CONFIRMED GUID has no prospect",
        f"- watchlist curation (proposed, nothing written): {json.dumps(doc['watchlist_curation']['summary'])}; "
        f"by stage {json.dumps(doc['watchlist_curation']['by_stage'], sort_keys=True)}",
        "",
        "Sources read:",
        "",
        "| source | status | rows | as_of |",
        "|---|---|---|---|",
    ]
    for n, src in doc["sources"].items():
        L.append(f"| {n} | {src['status']} | {src['count']} | {src['as_of']} |")
    L += [
        "",
        f"## Comparison — top {cmp['top_n']} shadow prospects + Home best opportunities + Watch top ideas",
        "",
        f"- subjects compared: {s['subjects']} — **agree {s['agree']}, differ {s['differ']}**",
        f"- stance differences {s['stance_differences']}; conviction differences (≥10 pts) "
        f"{s['conviction_differences']}; subjects whose inputs disagree {s['with_input_conflicts']}",
        f"- shadow top {cmp['top_n']} ∩ Home (opportunity rank) top {cmp['top_n']}: {s['shadow_top_vs_home_top_overlap']}",
        f"- Home best opportunities (preset top5): {s['home_best_opportunities']} — in shadow top: "
        f"{s['home_best_in_shadow_top']}",
        f"- Watch top ideas ({cmp['surfaces']['watch']['source']}): {s['watch_top_ideas']} — in shadow top: "
        f"{s['watch_in_shadow_top']}",
        f"- Telegram conviction line: {cmp['surfaces']['telegram']['source']} "
        f"(projection age {cmp['surfaces']['telegram']['projection_age_h']} h)",
        "",
        "| symbol | shadow rank · stage · stance · conviction | Home rank · stance · conviction | Watch | "
        "Telegram line | verdict |",
        "|---|---|---|---|---|---|",
    ]
    for r in cmp["rows"]:
        sh = r["shadow"]
        sh_s = "—" if sh is None else f"#{sh['rank']} · {sh['stage']} · {sh['stance']} · {sh['conviction']}"
        h = r["home"]
        h_s = "—" if h is None else (f"#{h['rank']} · {h['stance']} · {h['conviction']}"
                                     + (" · **best**" if h["in_best_opportunities"] else ""))
        w = r["watch"]
        w_s = "n/c" if w is None else (f"#{w['top_idea_rank']}" if w["top_idea_rank"] else "—")
        t_s = r["telegram"].get("conviction_line") or f"none ({r['telegram'].get('why')})"
        v = "agree" if r["agrees"] else "; ".join(r["differences"])
        L.append(f"| {r['symbol']} | {sh_s} | {h_s} | {w_s} | {t_s} | {v} |")
    L += position_sections(doc)
    L += ["", "MBI_BEHAVIOR = 0: stance is posture and priority; reference levels are information, never orders.", ""]
    return "\n".join(L)


def position_sections(doc: dict) -> list[str]:
    """Exited positions in full (origin, lifecycle, review, re-entry); held positions in one line each."""
    rows = [r for r in doc["prospects"] if r.get("position_lifecycle")]
    if not rows:
        return []
    L = ["", "## Positions — origin, lifecycle, post-exit review, re-entry (same record)", ""]
    for r in [r for r in rows if r["position_lifecycle"].get("status") == "closed"]:
        o, life = r.get("origin") or {}, r["position_lifecycle"]
        rev, adv = r.get("post_exit_review") or {}, r.get("reentry_advice") or {}
        lk = o.get("linkage") or {}
        L += [f"### {r['symbol']} — stage `{r['stage']}` / `{r.get('stage_phase')}`, stance {r['stance']}", "",
              f"- **Origin: {o.get('classification')}** — {o.get('summary')}. Link: `{lk.get('rec_id')}` "
              f"({lk.get('link_confidence')}, {lk.get('distance_pct')}% from the plan zone {lk.get('plan_entry_zone')}).",
              "- What the surfaces showed before the entry fill "
              f"({(o.get('at_entry') or {}).get('entry_fill_at')} at {(o.get('at_entry') or {}).get('entry_fill_price')}):"]
        for s in (o.get("at_entry") or {}).get("surfaces") or []:
            vals = ", ".join(f"{k} {s[k]}" for k in ("rank", "conviction", "rr", "stance", "state", "entry_zone",
                                                     "price", "text") if s.get(k) is not None)
            L.append(f"  - {s['surface']}: {'shown' if s.get('shown') else 'not shown'} — {vals} "
                     f"(`{s.get('record')}`, {s.get('at')})")
        st = life.get("observed_stops") or {}
        exc = life.get("excursion") or {}
        pnl = life.get("pnl") or {}
        ef, xf = life.get("entry_fill") or {}, life.get("exit_fill") or {}
        L += [f"- Fills: entry {ef.get('price')} at {ef.get('at')} → exit {xf.get('price')} at {xf.get('at')} "
              f"({life.get('hold_days')} days); "
              f"P/L ${pnl.get('net_pnl_usd')} ({pnl.get('pnl_pct')}%); R {pnl.get('r_multiple')} on the linked plan, "
              f"{pnl.get('r_on_initial_observed_stop')} on the initial observed stop, "
              f"{pnl.get('r_on_plan_invalidation_at_entry')} on the plan invalidation at entry "
              f"({pnl.get('plan_invalidation_at_entry')}).",
              f"- Observed stops: {' → '.join(str(p['stop_price_observed']) for p in st.get('path') or [])} "
              f"({st.get('ratchets_up')} ratchets; last {'FILLED' if st.get('filled') else 'not filled'}).",
              f"- Excursion ({exc.get('basis')}): MFE {exc.get('mfe_pct')}% ({exc.get('mfe_price')} on "
              f"{exc.get('mfe_at')}), MAE {exc.get('mae_pct')}% ({exc.get('mae_price')} on {exc.get('mae_at')}).",
              "- Conviction while held: " + "; ".join(f"{c['at']} {c['stance']} {c['conviction']} #{c['rank']}"
                                                       for c in life.get("conviction_while_held") or []) + ".",
              f"- **Exit cause: {(life.get('exit_cause') or {}).get('class')}** — "
              f"{(life.get('exit_cause') or {}).get('evidence')}.",
              f"- **Post-exit review: {(rev.get('noise_vs_trend') or {}).get('verdict')}** — "
              f"{(rev.get('noise_vs_trend') or {}).get('basis')}. Prose: {rev.get('prose_status')}.",
              f"- **Re-entry: {adv.get('state')}** ({adv.get('action')}). Conditions: "
              + "; ".join(f"{c['id']} {'met' if c['met'] else ('not met' if c['met'] is False else 'unknown')}"
                          for c in adv.get("conditions") or [])
              + ". Alert levels: " + ", ".join(f"{a['reference']} {a['level']}" for a in adv.get("alert_levels") or [])
              + f". Lane: {adv.get('lane')}; one alert `{(adv.get('one_alert') or {}).get('dedupe_key')}` (not sent).",
              "- Conflicts on the record: " + "; ".join(
                  f"{c['field']}: " + " vs ".join(f"{v['value']} ({v['source']})" for v in c["values"])
                  for c in r.get("conflicts") or []) + ".",
              f"- Events (append-only, one per fact): {len(r.get('lifecycle_events') or [])} — "
              + ", ".join(sorted({e['event_type'] for e in r.get('lifecycle_events') or []})) + ".", ""]
    held = [r for r in rows if r["position_lifecycle"].get("status") == "open"]
    if held:
        L.append(f"Held positions with a lifecycle on the record: {len(held)} — "
                 + ", ".join(f"{r['symbol']} ({(r.get('origin') or {}).get('classification') or 'origin n/a'})"
                             for r in held[:30]) + ". An open position's origin needs its buy fill "
                 "(trade_transactions, read with --with-db); 'origin n/a' means the fills were not read in this run.")
    return L


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CIO prospect shadow build (read-only)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default: build and print; write nothing")
    mode.add_argument("--write-shadow", action="store_true", help="write the shadow artifact + receipt (canary+)")
    ap.add_argument("--state-root", help="persistent state root (default: production_state_root())")
    ap.add_argument("--with-db", action="store_true", help="also read DB inputs through a READ ONLY session")
    ap.add_argument("--compare", action="store_true", help="add the comparison vs Home / Watch / Telegram")
    ap.add_argument("--watch-surface-json", help="a captured Watch top-ideas response to compare against")
    ap.add_argument("--captured-inputs", help="JSON of lifecycle rows captured read-only elsewhere (round_trips, "
                    "fills, stop_history, rec_links, bars) — a report run where this process opens no database")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--out", help="write the full build JSON to this path (a report, not a store)")
    ap.add_argument("--report-md", help="write the comparison as Markdown to this path")
    args = ap.parse_args(argv)
    write_shadow = bool(args.write_shadow)
    now = datetime.now(timezone.utc)
    try:
        state_root = _state_root(args.state_root)
        db_query, conn = (None, None)
        if args.with_db:
            db_query, conn = _readonly_db_query()
        try:
            captured = json.loads(Path(args.captured_inputs).read_text(encoding="utf-8")) \
                if args.captured_inputs else None
            doc = builder.build(state_root, db_query=db_query, now=now, captured=captured)
        finally:
            if conn is not None:
                conn.close()
        cmp = None
        if args.compare or write_shadow or args.report_md:
            watch, wsrc = _watch_list(args.watch_surface_json)
            cmp = builder.compare(doc, state_root, watch_top_ideas=watch, watch_source=wsrc, top_n=args.top, now=now)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}), file=sys.stderr)
        return 2

    out = {"ok": doc["counts"]["prospects"] > 0, "lane": LANE_ID,
           "mode": "write_shadow" if write_shadow else "dry_run", "summary": summary(doc)}
    if cmp is not None:
        out["comparison"] = cmp["summary"]
    if args.out:
        Path(args.out).write_text(json.dumps({**doc, "comparison": cmp}, indent=2, default=str), encoding="utf-8")
    if args.report_md and cmp is not None:
        Path(args.report_md).write_text(render_md(doc, cmp), encoding="utf-8")
    if write_shadow:
        from scripts.lib.data_broker.atomic_json import atomic_write_json
        atomic_write_json(state_root / SHADOW_REL, doc)
        atomic_write_json(state_root / COMPARE_REL, cmp)
        atomic_write_json(state_root / RECEIPT_REL, {
            "lane": LANE_ID, "ok_at": now.isoformat(), "produced_count": doc["counts"]["prospects"],
            "conflicts": doc["counts"]["conflicts"], "shadow": SHADOW_REL, "run_id": os.environ.get("TRADEAI_RUN_ID"),
            "store_status": doc["store_status"]["mode"]})
        out["wrote"] = [SHADOW_REL, COMPARE_REL, RECEIPT_REL]
    else:
        out["wrote"] = [p for p in (args.out, args.report_md) if p]
        out["would_write"] = [SHADOW_REL, COMPARE_REL, RECEIPT_REL]
    print(json.dumps(out, indent=2, default=str))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
