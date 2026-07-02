#!/usr/bin/env python3
"""hermes_outcome_learning.py — Phase 3: every Hermes learning loop, outcome-gated
(docs/design/HERMES_MATURITY_5_DESIGN.md §3). Reads ONLY hermes_outcome_ledger.

  weights    per-factor predictiveness from GRADED outcomes (not 6-hour drift), additive
             clamped suggestions, shadow-vs-live check → hermes_weight_calibration rows
             tagged OUTCOME_LEDGER (the only rows self-tune will graft)
  promotion  per-research_type precision → hermes_promotion_thresholds (coordinator gate);
             types below the floor get a hard confidence gate, unmeasured types stay ungated
  sources    per-domain outcome yield (actioned share) → retire/reinstate research_sources
             web domains; LLM taste check remains the floor, this adds performance decay
  lanes      per-lane hit-rate from graded external recs → hermes_lane_usefulness
             (research_scheduler weights its external rotation by it)

Every loop no-ops below its sample gate and says so. Zero LLM. Advisory-only; honors
data/runtime/HERMES_DISABLED. All rails in config/hermes_outcome_learning.yaml.

  python3 scripts/hermes_outcome_learning.py            # dry-run
  python3 scripts/hermes_outcome_learning.py --apply    # nightly cron (after the grader)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

KILL_SWITCH = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"
CFG_FILE = PROJECT_ROOT / "config" / "hermes_outcome_learning.yaml"
WEIGHTS_FILE = PROJECT_ROOT / "config" / "hermes_score_weights.yaml"
FACTORS = ["technical_momentum", "setup_quality", "analyst", "social_sentiment",
           "sector_strength", "news_catalyst", "risk_reward"]
MARKER = "OUTCOME_LEDGER"


def _cfg():
    import yaml
    return yaml.safe_load(CFG_FILE.read_text())


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _live_weights():
    import yaml
    return {k: float(v) for k, v in (yaml.safe_load(WEIGHTS_FILE.read_text()) or {}).get("weights", {}).items()}


# ── 3.1 weights ───────────────────────────────────────────────────────────────
def _pairs(cur, trade_weight):
    """(components, outcome) pairs from the ledger. Price claims use 20d excess; trades use
    realized R (weighted). Each outcome standardized within its type so units mix sanely."""
    cur.execute("""SELECT components, outcome_ret_20d::float FROM hermes_outcome_ledger
                   WHERE subject_type IN ('promotion','external_rec')
                     AND components IS NOT NULL AND outcome_ret_20d IS NOT NULL""")
    price = [(c, float(o)) for c, o in cur.fetchall()]
    cur.execute("""SELECT components, realized_r::float FROM hermes_outcome_ledger
                   WHERE subject_type='trade' AND components IS NOT NULL AND realized_r IS NOT NULL""")
    trades = [(c, float(o)) for c, o in cur.fetchall()]

    def z(rows):
        if len(rows) < 2:
            return []
        vals = [o for _c, o in rows]
        mu = sum(vals) / len(vals)
        sd = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
        return [(c, (o - mu) / sd) for c, o in rows]

    return z(price) + z(trades) * int(trade_weight)


def _composite(comp, weights):
    present = {f: comp[f]["score"] for f in FACTORS
               if isinstance(comp.get(f), dict) and comp[f].get("score") is not None}
    if not present:
        return None
    wsum = sum(weights.get(f, 0) for f in present) or 1.0
    return sum(weights.get(f, 0) * float(s) for f, s in present.items()) / wsum


def _spread(pairs, weights, q):
    """top-q vs bottom-q mean outcome under a weight set — 'does this ranking find winners?'"""
    scored = [(c_out, comp_score) for comp, c_out in pairs
              if (comp_score := _composite(comp, weights)) is not None]
    if len(scored) < 20:
        return None
    scored.sort(key=lambda x: x[1])
    k = max(1, int(len(scored) * q))
    bottom = [o for o, _s in scored[:k]]
    top = [o for o, _s in scored[-k:]]
    return sum(top) / len(top) - sum(bottom) / len(bottom)


def calibrate_weights(cur, cfg, apply):
    w = cfg["weights"]
    pairs = _pairs(cur, w["trade_weight"])
    live = _live_weights()
    pred, gated = {}, []
    for f in FACTORS:
        hi, lo = [], []
        for comp, out in pairs:
            d = comp.get(f) if isinstance(comp, dict) else None
            sc = d.get("score") if isinstance(d, dict) else None
            if sc is None:
                continue
            (hi if float(sc) >= 60 else lo if float(sc) <= 40 else []).append(out)
        if len(hi) >= w["min_hi"] and len(lo) >= w["min_lo"]:
            pred[f] = sum(hi) / len(hi) - sum(lo) / len(lo)
        else:
            gated.append(f"{f}(hi={len(hi)},lo={len(lo)})")
    if not pred:
        return {"status": "gated_insufficient_samples", "pairs": len(pairs), "factors_below_gate": gated}

    mx = max(abs(v) for v in pred.values()) or 1.0
    sugg = dict(live)
    for f, p in pred.items():
        step = max(-w["max_step"], min(w["max_step"], w["max_step"] * (p / mx)))
        sugg[f] = max(0.01, live.get(f, 0) + step)
    tot = sum(sugg.values()) or 1.0
    sugg = {k: round(v / tot, 4) for k, v in sugg.items()}

    live_spread = _spread(pairs, live, w["quantile"])
    shadow_spread = _spread(pairs, sugg, w["quantile"])
    eligible = (live_spread is not None and shadow_spread is not None and shadow_spread >= live_spread)

    if apply:
        for f in FACTORS:
            cur.execute("""INSERT INTO hermes_weight_calibration
                           (factor, current_weight, suggested_weight, predictiveness, sample_n, rationale)
                           VALUES (%s,%s,%s,%s,%s,%s)""",
                        (f, live.get(f), sugg.get(f), pred.get(f), len(pairs),
                         f"{MARKER}|eligible={1 if eligible else 0}|live_spread={live_spread}|shadow_spread={shadow_spread}"))
    return {"status": "ok", "pairs": len(pairs), "factors_measured": sorted(pred),
            "factors_below_gate": gated, "live_spread": live_spread, "shadow_spread": shadow_spread,
            "graft_eligible": eligible,
            "suggested": {f: sugg[f] for f in sorted(sugg)}}


# ── 3.2 promotion thresholds ─────────────────────────────────────────────────
def tune_promotion(cur, cfg, apply):
    p = cfg["promotion"]
    cur.execute("""SELECT COALESCE(hri.research_type,'unknown') rtype,
                          count(*) FILTER (WHERE l.verdict='hit') hits,
                          count(*) FILTER (WHERE l.verdict='miss') misses
                   FROM hermes_outcome_ledger l
                   JOIN hermes_research_intelligence hri
                     ON hri.id = (SELECT pa.target_id FROM hermes_promotion_audit pa WHERE pa.id = l.subject_id)
                   WHERE l.subject_type='promotion' AND l.verdict IN ('hit','miss')
                   GROUP BY 1""")
    rows = cur.fetchall()
    tot_h = sum(r[1] for r in rows); tot_m = sum(r[2] for r in rows)
    baseline = tot_h / (tot_h + tot_m) if (tot_h + tot_m) else None
    out = {"baseline_precision": round(baseline, 3) if baseline is not None else None,
           "graded_total": tot_h + tot_m, "types": []}
    for rtype, hits, misses in rows:
        n = hits + misses
        if n < p["min_samples_per_type"]:
            decision = (p["default_min_confidence"], f"n={n}<gate — ungated (directive B preserved)")
        else:
            prec = hits / n
            if prec < p["precision_floor"]:
                decision = (p["floor_min_confidence"], f"precision {prec:.2f} < floor {p['precision_floor']}")
            elif baseline is not None and prec < baseline - p["baseline_margin"]:
                decision = (p["soft_min_confidence"], f"precision {prec:.2f} < baseline-{p['baseline_margin']}")
            else:
                decision = (p["default_min_confidence"], f"precision {prec:.2f} ok")
        out["types"].append({"research_type": rtype, "n": n, "hits": hits,
                             "min_confidence": decision[0], "reason": decision[1]})
        if apply:
            cur.execute("""INSERT INTO hermes_promotion_thresholds
                           (research_type, min_confidence, precision_measured, sample_n, reason, updated_at)
                           VALUES (%s,%s,%s,%s,%s,NOW())
                           ON CONFLICT (research_type) DO UPDATE SET
                             min_confidence=EXCLUDED.min_confidence,
                             precision_measured=EXCLUDED.precision_measured,
                             sample_n=EXCLUDED.sample_n, reason=EXCLUDED.reason, updated_at=NOW()""",
                        (rtype, decision[0], round(hits / n, 4) if n else None, n, decision[1]))
    if apply:
        cur.execute("""UPDATE hermes_research_intelligence SET status='archived'
                       WHERE status='staged'
                         AND created_at < NOW() - make_interval(days => %s)""",
                    (p["stale_staged_archive_days"],))
        out["stale_staged_archived"] = cur.rowcount
    return out


# ── 3.3 sources on outcome yield ─────────────────────────────────────────────
def _domains(srcjson):
    out = set()
    try:
        urls = srcjson
        if isinstance(urls, str):
            urls = json.loads(urls)
        if isinstance(urls, dict):
            urls = list(urls.values())
        for u in urls or []:
            if isinstance(u, str) and u.startswith("http"):
                out.add(urlparse(u).netloc.replace("www.", ""))
    except Exception:
        pass
    return out


def curate_sources(cur, cfg, apply):
    s = cfg["sources"]
    cur.execute("""SELECT hri.source_urls_json, l.actioned
                   FROM hermes_outcome_ledger l
                   JOIN hermes_research_intelligence hri ON hri.id = l.subject_id
                   WHERE l.subject_type='research_row' AND l.actioned IS NOT NULL
                     AND hri.source_urls_json IS NOT NULL""")
    stats: dict[str, list[int]] = {}
    for srcjson, actioned in cur.fetchall():
        for d in _domains(srcjson):
            stats.setdefault(d, [0, 0])
            stats[d][0] += 1
            if actioned != "none":
                stats[d][1] += 1
    measured = {d: (t, a / t) for d, (t, a) in stats.items() if t >= s["min_samples_per_domain"]}
    if not measured:
        return {"status": "gated_insufficient_samples",
                "domains_seen": len(stats), "domains_measured": 0}
    yields = [y for _t, y in measured.values()]
    mu = sum(yields) / len(yields)
    sd = (sum((y - mu) ** 2 for y in yields) / len(yields)) ** 0.5
    retire_below = mu - s["retire_sigma"] * sd
    out = {"domains_measured": len(measured), "baseline_yield": round(mu, 3),
           "retire_below": round(retire_below, 3), "retired": [], "reinstated": []}
    for d, (t, y) in sorted(measured.items()):
        # exact source_name match — a substring ILIKE let 'marketindex.com' reinstate
        # 'marketindex.com.au' in the same run
        if y < retire_below:
            out["retired"].append(f"{d} (n={t}, yield={y:.2f})")
            if apply:
                cur.execute("""UPDATE research_sources SET active=false,
                               notes = COALESCE(notes,'') || %s
                               WHERE source_type=%s AND source_name=%s AND active""",
                            (f" | {MARKER} retired {datetime.now(timezone.utc).date()} yield={y:.2f}<{retire_below:.2f} n={t}",
                             s["scope_source_type"], d))
        elif y >= mu + s["reinstate_margin"]:
            if apply:
                cur.execute("""UPDATE research_sources SET active=true,
                               notes = COALESCE(notes,'') || %s
                               WHERE source_type=%s AND source_name=%s AND NOT active
                                 AND COALESCE(notes,'') NOT ILIKE '%%llm%%reject%%'""",
                            (f" | {MARKER} reinstated {datetime.now(timezone.utc).date()} yield={y:.2f}>=baseline n={t}",
                             s["scope_source_type"], d))
                if cur.rowcount:
                    out["reinstated"].append(f"{d} (n={t}, yield={y:.2f})")
    return out


# ── 3.4 lane usefulness ──────────────────────────────────────────────────────
def lane_usefulness(cur, cfg, apply):
    cur.execute("""SELECT REPLACE(claim,'rec:','') lane,
                          count(*) FILTER (WHERE verdict='hit') h,
                          count(*) FILTER (WHERE verdict='miss') m,
                          count(*) FILTER (WHERE verdict='neutral') nt
                   FROM hermes_outcome_ledger
                   WHERE subject_type='external_rec' AND verdict IN ('hit','miss','neutral')
                   GROUP BY 1""")
    rows = cur.fetchall()
    total = sum(r[1] + r[2] + r[3] for r in rows)
    out = {"graded_total": total, "gate": cfg["lanes"]["min_total_graded"], "lanes": []}
    for lane, h, m, nt in rows:
        n = h + m + nt
        hr = h / (h + m) if (h + m) else None
        out["lanes"].append({"lane": lane, "n": n, "hit_rate": round(hr, 3) if hr is not None else None})
        if apply:
            cur.execute("""INSERT INTO hermes_lane_usefulness (lane, n, hits, misses, neutrals, hit_rate, updated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,NOW())
                           ON CONFLICT (lane) DO UPDATE SET n=EXCLUDED.n, hits=EXCLUDED.hits,
                             misses=EXCLUDED.misses, neutrals=EXCLUDED.neutrals,
                             hit_rate=EXCLUDED.hit_rate, updated_at=NOW()""",
                        (lane, n, h, m, nt, hr))
    if total < cfg["lanes"]["min_total_graded"]:
        out["status"] = "below_gate_uniform_rotation"
    return out


def run(apply=False):
    if KILL_SWITCH.exists():
        out = {"ok": False, "reason": "HERMES_DISABLED kill switch present — learning idle"}
        print(json.dumps(out))
        return out
    cfg = _cfg()
    conn = _conn(); cur = conn.cursor()
    out = {"ok": True, "apply": apply}
    out["weights"] = calibrate_weights(cur, cfg, apply)
    out["promotion"] = tune_promotion(cur, cfg, apply)
    out["sources"] = curate_sources(cur, cfg, apply)
    out["lanes"] = lane_usefulness(cur, cfg, apply)
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
