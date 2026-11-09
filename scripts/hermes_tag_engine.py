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
  efficacy  hermes_tag_efficacy: per-tag 20-session win rate vs the base rate from the ledger's
            graded outcomes — a tag that underperforms its base credibly (sample, effect size
            and one-sided significance) gets flagged. Tags become falsifiable; "a directive
            was surfaced" is reported as engagement, never scored as a win. Tags the engine
            no longer computes are superseded (flagged cleared, superseded_at set) and hidden
            from consumers — never deleted (LQ-1491).

The 3-axis taxonomy cron is retired with this change (zero readers repo-wide — write-only cost).
Zero paid LLM. Advisory-only; honors data/runtime/HERMES_DISABLED.

  python3 scripts/hermes_tag_engine.py            # preview: writes nothing, but the LLM refine leg still runs
  python3 scripts/hermes_tag_engine.py --dry-run  # LLM-free dry run (n8n fabric shadow lane): no model call,
                                                  # read-only DB session, no DDL; wins over --apply
  python3 scripts/hermes_tag_engine.py --apply    # nightly cron

--dry-run (2026-10-15, n8n fabric process hermes-learning step tag_engine): the rows the live run would send to
the governed cloud classifier are counted (``retag.llm_would_call``) and keep their rule/fallback tag in the
preview; ``generate_cloud`` is never imported or called. The --apply path and the bare preview are unchanged.

Lane receipt (LQ-20261107-298): a real ``--apply`` run writes a LaneRunReceipt@v2 whose ``produced_count`` is the
number of ``hermes_tag_efficacy`` rows it upserted — the lane's declared output_signal is that table's
``updated_at``, so the count and the signal say the same thing. Without it the jobs page graded every live run
UNPROVEN ``output_unverifiable`` (a ``db_max`` signal cannot be read from a receipt, and the run reported no item
count). A dry run writes no receipt; it prints ``receipt_preview`` instead.

Governed route (2026-10-15, n8n fabric cutover prerequisite G5): with TRADEAI_LLM_VIA_BRIDGE=1 (bound by the n8n run
executor from the allowlist ``llm_route`` of lane hermes-learning-tag-engine) the classifier call goes only through the
governed bridge as process ``hermes_tag_engine`` ($0.05/day registry cap); a refusal keeps the rule/fallback tag.
"""
from __future__ import annotations

import argparse
import json
import math
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


#: The registered process (config/llm_process_registry.json, daily_cost_cap_usd 0.05) and its governed-bridge route
#: (scripts/lib/governed_process_routes.py: advisory_desk / hermes_tag_engine).
LLM_PROCESS_ID = "hermes_tag_engine"
#: The flag lib.llm_bridge_route.bridge_enabled reads (scripts/n8n_run_executor.py LLM_BRIDGE_ENV). Read here
#: directly so a failed import with the flag ON can never fall through to the in-process provider path.
VIA_BRIDGE_ENV = "TRADEAI_LLM_VIA_BRIDGE"


def _via_bridge():
    import os
    return os.environ.get(VIA_BRIDGE_ENV, "off").strip().lower() in {"1", "on", "bridge"}


def _tags_from_json(raw, vocab, max_tags):
    """Registry slugs from a classifier reply; anything else (prose, a fence, an unknown slug) is dropped."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    tags = (json.loads(text).get("tags") or [])
    return [t for t in tags if t in vocab][:max_tags]


def _llm_tags(text, vocab, timeout, max_tags):
    """Governed cloud classifier constrained to registry slugs.

    2026-10-15 (n8n fabric, hermes-learning cutover prerequisite G5): when the run executor binds the allowlist
    ``llm_route`` (TRADEAI_LLM_VIA_BRIDGE=1, TRADEAI_LLM_PROCESS_ID=hermes_tag_engine), the call goes ONLY through the
    governed bridge (lib.llm_bridge_route.text_via_bridge -> cio-governed-bridge, 127.0.0.1:8766), which holds the
    provider credential and enforces the process's $0.05/day cap, the global cap, routing and deferral server-side.
    A refusal or an unreachable bridge is "no tags" (the row keeps its rule/fallback tag): never a fall-through to an
    in-process provider call. Without the flag (the cron line) the in-process governed path is unchanged."""
    prompt = ("You are a strict classifier for a trading research system. Pick up to "
              f"{max_tags} strategy slugs that genuinely fit this research text, from ONLY "
              "this list (empty list if none fit):\n" + ", ".join(vocab) +
              "\n\nText:\n" + (text or "")[:1500] +
              '\n\nRespond ONLY with JSON: {"tags": ["slug", ...]}')
    if _via_bridge():
        try:
            from lib.llm_bridge_route import text_via_bridge
            raw = text_via_bridge(LLM_PROCESS_ID, prompt, timeout_s=float(timeout))
            return [] if raw is None else _tags_from_json(raw, vocab, max_tags)
        except Exception:
            return []
    try:
        from lib.governed_cloud_generation import generate_cloud
        raw, _lane = generate_cloud(
            prompt, process_id="hermes_tag_engine",
            task_summary="Hermes controlled-vocabulary tagging", timeout=timeout,
            response_json=True, max_tokens=256,
        )
        tags = (json.loads(raw).get("tags") or [])
        return [t for t in tags if t in vocab][:max_tags]
    except Exception:
        return []


def _readonly(conn):
    """A dry run's DB session is READ ONLY at the server (AGENTS.md §6): any write is refused by PostgreSQL."""
    from lib.lane_last_receipt import enforce_readonly
    return enforce_readonly(conn)


def retag(cfg, apply, *, dry_run=False):
    """Two-connection design: the LLM refine batch can queue on the shared GPU for many minutes,
    which kills an idle DB connection — so fetch first, classify with NO connection held, then
    write on a fresh connection. LLM work is additionally wall-clock capped.

    ``dry_run``: never calls the model. A row that would have gone to ``_llm_tags`` is counted in
    ``llm_would_call`` (same budget and eligibility as the live run) and previews as fallback."""
    import time
    r = cfg["retag"]
    fb, mx = cfg["fallback_tag"], int(cfg["max_tags"])
    apply = apply and not dry_run

    conn = _conn()
    if dry_run:
        _readonly(conn)
    cur = conn.cursor()
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

    ruled = llmed = fell_back = would_call = 0
    llm_budget = int(r["llm_batch"])
    llm_deadline = time.monotonic() + int(r.get("llm_wall_clock_s", 240))
    results = []
    for rid, sym, txt in rows:
        tags = _rule_tags(txt, cues, mx)
        how = "rule"
        if not tags and sym and llm_budget > 0 and dry_run:
            would_call += 1  # dry run: the model is never called (no spend, no wall clock)
            llm_budget -= 1
        elif not tags and sym and llm_budget > 0 and time.monotonic() < llm_deadline:
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

    conn = _conn()
    if dry_run:
        _readonly(conn)
    cur = conn.cursor()
    if apply:
        # One write module per store (SoT Phase 9): SQL lives in lib.writers.hermes_research_writer.
        from lib.writers.hermes_research_writer import set_fields_by_id
        for rid, tags in results:
            set_fields_by_id(cur, ids=[rid], fields={"strategy_tags": tags}, producer="hermes_tag_engine")
        conn.commit()
    # fallback share across recent rows (the <15% target metric)
    cur.execute("""SELECT count(*) FILTER (WHERE strategy_tags = %s::text[]) fb, count(*) tot
                   FROM hermes_research_intelligence
                   WHERE created_at > NOW() - interval '30 days'""", ([fb],))
    fbn, tot = cur.fetchone()
    conn.close()
    out = {"batch": len(rows), "rule_tagged": ruled, "llm_tagged": llmed, "fallback": fell_back,
           "fallback_share_30d": round(fbn / tot, 3) if tot else None}
    if dry_run:
        out["llm_would_call"] = would_call
        out["llm_called"] = 0
    return out


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
        # One write module per store (SoT Phase 9): SQL lives in lib.writers.hermes_research_writer.
        from lib.writers.hermes_research_writer import blend_quality_score
        for rt, prior in priors.items():
            rc = blend_quality_score(cur, research_type=rt, blend_existing=be, neutral=neutral,
                                     blend_outcome_prior=bo, prior=prior, producer="hermes_tag_engine")
            updated += rc.rows_written
    # distribution health (the two-point-mass detector)
    cur.execute("""SELECT round(stddev(quality_score)::numeric,4), count(DISTINCT quality_score)
                   FROM hermes_research_intelligence WHERE quality_score IS NOT NULL""")
    sd, distinct = cur.fetchone()
    return {"types_with_prior": len(priors),
            "priors_sample": {t: round(p, 3) for t, p in sorted(priors.items())[:6]},
            "rows_updated": updated, "quality_stddev": float(sd) if sd is not None else None,
            "distinct_values": distinct}


def _normal_sf(z: float) -> float:
    """P(Z > z) for a standard normal — the one-sided tail without scipy."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def efficacy_stats(rows: list[dict], *, min_n: int, min_effect: float,
                   alpha: float) -> dict:
    """Per-tag efficacy on REALIZED outcomes, not on internal consumption.

    A hit is a research row whose 20-session outcome return is positive; a row
    with no graded outcome is neither a win nor a loss (unknown is not zero).
    ``actioned``/``directive_hits`` are reported beside it: "a directive was
    surfaced" is engagement, not an outcome, and until 2026-11-07 it was counted
    as a hit — 97% of rows scored as hits and tags were flagged on a 0.3-1.2
    point lift that is pure noise (LQ-20261107-133b).

    A tag is flagged only when the evidence is credible: at least ``min_n``
    graded outcomes, a win-rate gap of at least ``min_effect`` BELOW the base
    rate, and a one-sided two-proportion z-test p-value <= ``alpha``.
    """
    # Row keys are produced by tag_efficacy() from the SQL counts and are all required;
    # a missing key is an error, never a zero (a count of wins is not "unknown wins").
    total_wins = sum(int(r["wins"]) for r in rows)
    total_n = sum(int(r["outcome_n"]) for r in rows)
    base = (total_wins / total_n) if total_n else None
    out = {"base_rate": round(base, 3) if base is not None else None,
           "metric": "win_rate_20d", "min_effect": min_effect, "alpha": alpha,
           "tags": [], "flagged": []}
    for r in sorted(rows, key=lambda x: -int(x["ledger_n"])):
        tag = str(r["tag"])
        n = int(r["outcome_n"])
        wins = int(r["wins"])
        wr = (wins / n) if n else None
        lift = (wr - base) if (wr is not None and base is not None) else None
        p_value = None
        rest_n = total_n - n
        if wr is not None and base is not None and 0 < n and 0 < rest_n:
            se = math.sqrt(wr * (1 - wr) / n + base * (1 - base) / rest_n)
            if se > 0:
                # left tail: P(the tag is really WORSE than base), not P(it is better)
                p_value = _normal_sf(-lift / se)
        reasons = []
        if n < min_n:
            reasons.append(f"n<{min_n}")
        if lift is None or lift > -min_effect:
            reasons.append(f"lift>-{min_effect}")
        if p_value is None or p_value > alpha:
            reasons.append(f"p>{alpha}")
        flagged = not reasons
        out["tags"].append({
            "tag": tag, "ledger_n": int(r["ledger_n"]),
            "n": n, "hits": wins, "hit_rate": round(wr, 3) if wr is not None else None,
            "base_rate": out["base_rate"],
            "lift": round(lift, 3) if lift is not None else None,
            "p_value": round(p_value, 4) if p_value is not None else None,
            "actioned": int(r["actioned_hits"]),
            "directive_hits": int(r["directive_hits"]),
            "flagged": flagged,
            "flag_reason": None if flagged else "not_credible: " + ", ".join(reasons),
        })
        if flagged:
            out["flagged"].append(tag)
    return out


#: Prefer ``active_efficacy_predicate(cur)`` in consumers (LQ-1491). This literal is
#: only valid once the column exists (first ``hermes_tag_engine --apply`` after deploy).
ACTIVE_EFFICACY_PREDICATE = "superseded_at IS NULL"
SUPERSEDE_REASON = "not in current compute set"
SUPERSEDE_FLAG_REASON = "superseded: not in current compute set"

#: Cached probe: None = unknown, True/False = column present. Cleared after DDL that
#: adds the column, and by ``reset_efficacy_superseded_col_cache`` in tests.
_efficacy_has_superseded_col: bool | None = None


def reset_efficacy_superseded_col_cache() -> None:
    """Drop the cached information_schema probe (tests / after DDL)."""
    global _efficacy_has_superseded_col
    _efficacy_has_superseded_col = None


def efficacy_has_superseded_column(cur) -> bool:
    """True when ``hermes_tag_efficacy.superseded_at`` exists.

    The column is added only by ``tag_efficacy`` on ``--apply``. Consumers that fold
    before the next 10:50 slot must not reference it yet (LQ-1491 rework).
    """
    global _efficacy_has_superseded_col
    if _efficacy_has_superseded_col is not None:
        return _efficacy_has_superseded_col
    cur.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'hermes_tag_efficacy'
                     AND column_name = 'superseded_at'""")
    _efficacy_has_superseded_col = cur.fetchone() is not None
    return _efficacy_has_superseded_col


def active_efficacy_predicate(cur) -> str:
    """SQL boolean for a live efficacy row — safe to embed in WHERE/AND.

    Returns ``superseded_at IS NULL`` when the column exists; otherwise ``TRUE`` so
    consumers do not crash with ``column does not exist`` between release and the
    first engine ``--apply``. Only these two fixed literals are ever returned.
    """
    return ACTIVE_EFFICACY_PREDICATE if efficacy_has_superseded_column(cur) else "TRUE"


def list_absent_efficacy_tags(cur, current_tags: list[str]) -> list[dict]:
    """Active ``hermes_tag_efficacy`` rows whose tag this run did not compute.

    Before the ``superseded_at`` column exists (first apply after deploy), every
    row is treated as active. Already-superseded rows are omitted. Pure read.
    Two constant SQL forms (no f-string) so a missing column cannot be referenced.
    """
    tags = list(current_tags)
    if efficacy_has_superseded_column(cur):
        cur.execute("""SELECT tag, flagged FROM hermes_tag_efficacy
                       WHERE superseded_at IS NULL AND NOT (tag = ANY(%s))
                       ORDER BY tag""", (tags,))
    else:
        cur.execute("""SELECT tag, flagged FROM hermes_tag_efficacy
                       WHERE NOT (tag = ANY(%s))
                       ORDER BY tag""", (tags,))
    return [{"tag": str(t), "flagged": bool(f)} for t, f in cur.fetchall()]


def tag_efficacy(cur, cfg, apply, *, dry_run=False):
    if not dry_run:  # DDL is a write: a read-only dry-run session refuses it (the SELECTs below never read this table)
        cur.execute("""CREATE TABLE IF NOT EXISTS hermes_tag_efficacy (
                         tag TEXT PRIMARY KEY, n INT, hits INT, hit_rate NUMERIC,
                         base_rate NUMERIC, lift NUMERIC, flagged BOOLEAN, updated_at TIMESTAMPTZ)""")
        cur.execute("ALTER TABLE hermes_tag_efficacy ADD COLUMN IF NOT EXISTS trade_n INT")
        # One ALTER carries the prior migration's column and this one's: the statement count on the
        # apply path stays at three (CREATE + 2 ALTERs), which the cutover pin in
        # tests/test_hermes_learning_unblock_20261015.py asserts.
        # superseded_* hide tags this run no longer computes (LQ-1491); never DELETE.
        cur.execute("""ALTER TABLE hermes_tag_efficacy
                         ADD COLUMN IF NOT EXISTS avg_realized_r NUMERIC,
                         ADD COLUMN IF NOT EXISTS ledger_n INT,
                         ADD COLUMN IF NOT EXISTS outcome_n INT,
                         ADD COLUMN IF NOT EXISTS actioned_hits INT,
                         ADD COLUMN IF NOT EXISTS directive_hits INT,
                         ADD COLUMN IF NOT EXISTS p_value NUMERIC,
                         ADD COLUMN IF NOT EXISTS flag_reason TEXT,
                         ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMPTZ,
                         ADD COLUMN IF NOT EXISTS superseded_reason TEXT""")
        # Consumers may have probed before this ALTER in the same process.
        reset_efficacy_superseded_col_cache()
    apply = apply and not dry_run
    # n is the number of GRADED outcomes a tag's rate is computed on; ledger_n is
    # every row that carries the tag. wins = the 20-session return was positive.
    cur.execute("""SELECT unnest(hri.strategy_tags) tag,
                          count(*) ledger_n,
                          count(*) FILTER (WHERE l.actioned IN ('proposal','trade')) actioned_hits,
                          count(*) FILTER (WHERE l.actioned = 'directive_hit') directive_hits,
                          count(*) FILTER (WHERE l.outcome_ret_20d IS NOT NULL) outcome_n,
                          count(*) FILTER (WHERE l.outcome_ret_20d > 0) wins
                   FROM hermes_outcome_ledger l
                   JOIN hermes_research_intelligence hri ON hri.id = l.subject_id
                   WHERE l.subject_type='research_row' AND l.actioned IS NOT NULL
                     AND hri.strategy_tags IS NOT NULL
                   GROUP BY 1""")
    rows = [{"tag": t, "ledger_n": ln, "actioned_hits": a, "directive_hits": d,
             "outcome_n": on, "wins": w}
            for t, ln, a, d, on, w in cur.fetchall()]
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
    eff = cfg.get("efficacy") or {}
    out = efficacy_stats(rows,
                         min_n=int(eff.get("min_samples_per_tag", 15)),
                         min_effect=float(eff.get("min_effect", 0.05)),
                         alpha=float(eff.get("alpha", 0.05)))
    current_tags = [t["tag"] for t in out["tags"]]
    for t in out["tags"]:
        tn, avg_r = r_by_tag.get(t["tag"], (0, None))
        t["trade_n"] = tn
        t["avg_realized_r"] = round(avg_r, 3) if avg_r is not None else None
        if apply:
            # Returning to the compute set clears any prior supersede marker.
            cur.execute("""INSERT INTO hermes_tag_efficacy (tag, n, hits, hit_rate, base_rate, lift,
                                                            flagged, trade_n, avg_realized_r, ledger_n,
                                                            outcome_n, actioned_hits, directive_hits,
                                                            p_value, flag_reason, superseded_at,
                                                            superseded_reason, updated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,NOW())
                           ON CONFLICT (tag) DO UPDATE SET n=EXCLUDED.n, hits=EXCLUDED.hits,
                             hit_rate=EXCLUDED.hit_rate, base_rate=EXCLUDED.base_rate,
                             lift=EXCLUDED.lift, flagged=EXCLUDED.flagged,
                             trade_n=EXCLUDED.trade_n, avg_realized_r=EXCLUDED.avg_realized_r,
                             ledger_n=EXCLUDED.ledger_n, outcome_n=EXCLUDED.outcome_n,
                             actioned_hits=EXCLUDED.actioned_hits,
                             directive_hits=EXCLUDED.directive_hits,
                             p_value=EXCLUDED.p_value, flag_reason=EXCLUDED.flag_reason,
                             superseded_at=NULL, superseded_reason=NULL,
                             updated_at=NOW()""",
                        (t["tag"], t["n"], t["hits"], t["hit_rate"], out["base_rate"],
                         t["lift"], t["flagged"], t["trade_n"], t["avg_realized_r"],
                         t["ledger_n"], t["n"], t["actioned"], t["directive_hits"],
                         t["p_value"], t["flag_reason"]))
    # Tags the engine no longer computes stay in the table for audit but must not
    # surface as live flags (LQ-1491 / old LQ-133b remainder). Never DELETE.
    absent = list_absent_efficacy_tags(cur, current_tags)
    out["would_supersede"] = [a["tag"] for a in absent]
    out["would_supersede_flagged"] = [a["tag"] for a in absent if a.get("flagged")]
    if apply and absent:
        cur.execute("""UPDATE hermes_tag_efficacy
                          SET flagged = FALSE,
                              flag_reason = %s,
                              superseded_at = NOW(),
                              superseded_reason = %s,
                              updated_at = NOW()
                        WHERE superseded_at IS NULL
                          AND NOT (tag = ANY(%s))""",
                    (SUPERSEDE_FLAG_REASON, SUPERSEDE_REASON, current_tags))
        # len(absent) is the intended set; rowcount is only a driver echo.
        out["superseded"] = len(absent)
    else:
        out["superseded"] = 0
    return out


# ───────────────────── lane receipt (n8n output verdict) ─────────────────────
#: Lane id on the n8n fabric (config/n8n_run_allowlist.json; health contract ``expected_output``).
LANE_ID = "hermes-learning-tag-engine"


def lane_output(result: dict) -> dict:
    """LaneRunReceipt@v2 output fields for one REAL ``--apply`` run (LQ-20261107-298).

    ``produced_count`` is the number of ``hermes_tag_efficacy`` rows this run wrote — one upsert per tag in
    ``tag_efficacy``. The lane's registry ``output_signal`` is ``db_max hermes_tag_efficacy.updated_at``, so this
    count is exactly the rows whose ``updated_at`` the run moved: zero means that column did not advance and the
    lane produced nothing measurable, which the contract's ``min_produced`` rule must see as an empty, not as an
    exit-0 success. (Before this, the lane wrote no receipt at all: the jobs page graded every live run UNPROVEN
    ``output_unverifiable`` because a ``db_max`` signal is not readable from a receipt and the run reported no item
    count.)

    The retag and quality legs are reported beside the count in ``output_evidence``, never folded into it: the
    contract's declared unit is efficacy rows, and a run that retagged research but wrote no efficacy row has not
    advanced the declared output.
    """
    eff = result.get("efficacy") or {}
    tags = [t for t in (eff.get("tags") or []) if isinstance(t, dict)]
    produced = len(tags)
    retag = result.get("retag") or {}
    quality = result.get("quality") or {}
    evidence = [{"kind": "store_rows", "ref": "hermes_tag_efficacy", "upserted": produced}]
    if isinstance(retag.get("batch"), int):
        evidence.append({"kind": "store_rows", "ref": "hermes_research_intelligence.strategy_tags",
                         "rows_tagged": retag["batch"]})
    if isinstance(quality.get("rows_updated"), int):
        evidence.append({"kind": "store_rows", "ref": "hermes_research_intelligence.quality_score",
                         "rows_updated": quality["rows_updated"]})
    return {"produced_count": produced, "attempted_count": produced, "skipped_reasons": {},
            "empty_reason": None if produced else "no_tags_to_score",
            "output_evidence": evidence}


def _write_receipt(ok: bool, started: str, *, result: dict | None = None, error: str | None = None) -> None:
    """Best-effort LaneRunReceipt@v2. Never raises; a real ``--apply`` run only, never a dry run (AGENTS.md §6)."""
    try:
        try:
            from lib.lane_last_receipt import write_lane_receipt
        except ImportError:
            from scripts.lib.lane_last_receipt import write_lane_receipt
        res = result or {}
        if res.get("ok") is False:  # the kill switch: the lane did its job by standing down, and says so
            ok, error = False, "HERMES_DISABLED"
        out = lane_output(res) if ok else {
            "produced_count": 0, "attempted_count": 0,
            "skipped_reasons": ({"disabled": 1} if error == "HERMES_DISABLED" else {"dependency_unavailable": 1})}
        write_lane_receipt(LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=started,
                           script="hermes_tag_engine.py", error=error,
                           summary={"apply": bool(res.get("apply"))}, output=out)
    except Exception as exc:  # noqa: BLE001 -- the run's own result comes first
        print(f"  WARN lane receipt not written: {type(exc).__name__}: {exc}", file=sys.stderr)


def run(apply=False, dry_run=False):
    if KILL_SWITCH.exists():
        out = {"ok": False, "reason": "HERMES_DISABLED kill switch present — tag engine idle"}
        print(json.dumps(out))
        return out
    cfg = _cfg()
    if dry_run:
        apply = False  # --dry-run wins over --apply
        out = {"ok": True, "apply": False, "mode": "dry_run"}
        out["retag"] = retag(cfg, False, dry_run=True)
        conn = _readonly(_conn()); cur = conn.cursor()
        out["quality"] = quality_v2(cur, cfg, False)
        out["efficacy"] = tag_efficacy(cur, cfg, False, dry_run=True)
        conn.close()
        # What a live --apply of this same state would write. The dry run writes no receipt (nothing to attest).
        out["receipt_preview"] = {"lane_id": LANE_ID,
                                  "would_write_produced_count": lane_output(out)["produced_count"],
                                  "unit": "rows upserted into hermes_tag_efficacy",
                                  "note": "a dry run writes nothing; the live --apply run writes this receipt"}
        out["ts"] = datetime.now(timezone.utc).isoformat()
        print(json.dumps(out, indent=2, default=str))
        return out
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
    ap.add_argument("--dry-run", action="store_true",
                    help="LLM-free dry run: no model call, read-only DB session, no DDL; wins over --apply")
    a = ap.parse_args()
    apply = a.apply and not a.dry_run
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = run(apply=apply, dry_run=a.dry_run)
    except Exception as exc:
        # A raised real run still leaves its failed receipt (LaneRunReceipt@v2): the attempt existed and failed.
        if apply:
            _write_receipt(False, started, error=type(exc).__name__)
        raise
    if apply:
        _write_receipt(True, started, result=result)


if __name__ == "__main__":
    main()
