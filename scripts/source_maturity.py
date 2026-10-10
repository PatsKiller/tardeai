#!/usr/bin/env python3
"""source_maturity.py — Gate 2 of Hermes source maturity. Blends the four existing source signals into one
maturity_score (0-100) + tier per source. ADVISORY-ONLY, read-only; writes data/runtime/source_maturity_latest.json.

Signals blended:
  - precision  (source_performance.go_signals / total_signals)  — does the source surface symbols the scalp
                engine later flags GO/WAIT? strongest currently-available quality signal.
  - outcome    (source_performance win_rate when trades_matched >= MIN_TRADES) — real edge (sparse today).
  - yield      (source_learning_scores: candidates_promoted / signals_seen, minus duplicates/stale/false).
  - health     (data_source_health.status / degraded).
  - credibility(research_sources.credibility_score) — curated baseline.

Tiers: core | trusted | probationary | candidate | demoted. "core" is computed but operator-gated for
activation (Gate 4 ladder). Never mutates trades/scoring/holdings.

--dry-run reads on a READ ONLY session and returns BEFORE write_out() (the only file write) is
reachable. A real run writes data/runtime/source_maturity_last.json (LaneRunReceipt@v1; ok_at only on
success) and exits 1 on failure. data/runtime resolves through lib.persistent_state_root (the served
copy), not the checkout the code runs from (AGENTS.md §9.4).
"""
import os, sys, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def runtime_dir() -> Path:
    """Served data/runtime (persistent state root when provisioned, else the checkout)."""
    try:
        from lib.persistent_state_root import resolve_durable_dir

        return resolve_durable_dir("data/runtime", ROOT)
    except Exception:  # noqa: BLE001 -- helper unavailable: the checkout path (release symlinks it)
        return ROOT / "data" / "runtime"


OUT = runtime_dir() / "source_maturity_latest.json"
MIN_TRADES = 5
MIN_VOLUME = 20  # signals needed before precision is fully trusted
RECEIPT_NAME = "source_maturity"
if (ROOT / ".env").exists():  # absent in a bare checkout/test tree; the served release symlinks it
    for ln in (ROOT / ".env").read_text().splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
import psycopg2
import psycopg2.extras


def _db():
    return psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                            password=os.getenv("DB_PASSWORD"), cursor_factory=psycopg2.extras.RealDictCursor)


def compute(dry_run=False):
    """Read-only: returns the full source_maturity_latest document (never writes)."""
    c = _db()
    if dry_run:
        c.set_session(readonly=True)
    cur = c.cursor()
    cur.execute("SELECT * FROM source_performance")
    perf = {r["source_id"]: r for r in cur.fetchall()}
    cur.execute("SELECT source_key, signals_seen, duplicates, stale_items, false_catalysts, candidates_promoted FROM source_learning_scores")
    yld = {}
    for r in cur.fetchall():
        yld.setdefault(r["source_key"], {"seen": 0, "promoted": 0, "dup": 0, "stale": 0, "false": 0})
        y = yld[r["source_key"]]
        y["seen"] += r["signals_seen"] or 0; y["promoted"] += r["candidates_promoted"] or 0
        y["dup"] += r["duplicates"] or 0; y["stale"] += r["stale_items"] or 0; y["false"] += r["false_catalysts"] or 0
    cur.execute("SELECT source_key, status, degraded FROM data_source_health")
    health = {r["source_key"]: r for r in cur.fetchall()}
    cur.execute("SELECT source_name, credibility_score, notes FROM research_sources WHERE credibility_score IS NOT NULL")
    cred, core_approved = {}, set()
    for r in cur.fetchall():
        cred[r["source_name"]] = float(r["credibility_score"])
        try:
            if r["notes"] and json.loads(r["notes"]).get("operator_core_approved"):
                core_approved.add(r["source_name"])
        except Exception:
            pass
    c.close()

    def health_for(src):
        for k, v in health.items():
            if k and (k in src.lower() or src.lower() in k):
                return v
        return None

    rows = []
    for src, p in perf.items():
        total = p["total_signals"] or 0
        go = p["go_signals"] or 0
        go_rate = (go / total) if total else 0.0
        vol_factor = min(1.0, total / MIN_VOLUME)
        precision = min(50.0, go_rate * 200) * vol_factor          # 0-50

        tm = p["trades_matched"] or 0
        wr = float(p["win_rate"]) if p["win_rate"] is not None else None  # numeric col → cast to float
        outcome = 0.0
        if tm >= MIN_TRADES and wr is not None:
            outcome = max(-20.0, min(20.0, (wr - 50) * 0.8))       # -20..+20
        y = yld.get(src) or next((yld[k] for k in yld if k and (k in src.lower() or src.lower() in k)), None)
        yield_pts = 0.0
        if y and y["seen"] >= 10:
            yr = y["promoted"] / y["seen"]
            penalty = (y["dup"] + y["stale"] + 2 * y["false"]) / max(1, y["seen"])
            yield_pts = max(0.0, min(15.0, yr * 30 - penalty * 15))  # 0-15
        h = health_for(src)
        health_pts = -20.0 if (h and (h.get("degraded") or h.get("status") in ("failed", "down", "stale"))) else 0.0
        cred_pts = cred.get(src, 0.0) * 15                          # 0-15

        score = round(precision + outcome + yield_pts + health_pts + cred_pts, 1)
        score = max(0.0, min(100.0, score))

        # tiering (core is operator-gated: auto-core needs score+outcome/credibility; or an explicit
        # operator core-approval override pins it core regardless of formula).
        if src in core_approved:
            tier = "core"  # operator-approved override
        elif total >= 100 and go_rate < 0.01:
            tier = "demoted"  # high volume, ~zero precision = noise
        elif health_pts < 0:
            tier = "demoted"
        elif score >= 70 and (tm >= MIN_TRADES and (wr or 0) >= 55 or cred.get(src, 0) >= 0.8):
            tier = "core"
        elif score >= 50:
            tier = "trusted"
        elif score >= 30:
            tier = "probationary"
        else:
            tier = "candidate"

        rows.append({"source": src, "maturity_score": score, "tier": tier,
                     "total_signals": total, "go_signals": go, "go_rate": round(go_rate, 4),
                     "trades_matched": tm, "win_rate": wr,
                     "components": {"precision": round(precision, 1), "outcome": round(outcome, 1),
                                    "yield": round(yield_pts, 1), "health": health_pts, "credibility": round(cred_pts, 1)},
                     "outcome_proven": tm >= MIN_TRADES})
    rows.sort(key=lambda r: -r["maturity_score"])
    from collections import Counter
    tier_counts = dict(Counter(r["tier"] for r in rows))
    return {"updated_at": datetime.now(timezone.utc).isoformat(), "min_trades": MIN_TRADES,
            "tier_counts": tier_counts, "source_count": len(rows), "sources": rows}


def write_out(out, path=None):
    """The only writer. Never called by a dry run."""
    target = Path(path) if path else OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, default=str))
    return target


def run(dry_run=False):
    out = compute(dry_run=dry_run)
    rows, tier_counts = out["sources"], out["tier_counts"]
    if dry_run:
        print(json.dumps({"dry_run": True, "would_write": str(OUT), "tier_counts": tier_counts,
                          "top10": [{k: r[k] for k in ("source", "maturity_score", "tier", "go_rate", "total_signals")} for r in rows[:10]]}, indent=2))
    else:
        target = write_out(out)
        print(f"wrote {target}  tiers={tier_counts}")
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--dry-run" in argv:
        run(dry_run=True)
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started = now_iso()
    try:
        out = run()
    except Exception as exc:  # noqa: BLE001 -- recorded in the receipt, then a non-zero exit
        write_receipt(RECEIPT_NAME, ok=False, error=f"{type(exc).__name__}: {exc}", started_at=started)
        print(f"source_maturity FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    write_receipt(RECEIPT_NAME, ok=True, started_at=started,
                  summary={"source_count": out["source_count"], "tier_counts": out["tier_counts"]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
