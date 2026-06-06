#!/usr/bin/env python3
"""backfill_trade_lineage.py — Step-1 exact-match backfill of execution lineage.

For existing paper_trades with an exact proposal_id link, fill missing lineage fields from the proposal
(via trade_lineage.extract_lineage_from_proposal). Also fill proposal.paper_trade_id reverse pointer ONLY
where exactly one paper_trade maps to the proposal (skip ambiguous). No symbol/date fuzzy inference.

  python3 scripts/backfill_trade_lineage.py            # dry-run (counts only)
  python3 scripts/backfill_trade_lineage.py --apply    # apply exact backfill
"""
import os, sys, json, psycopg2, psycopg2.extras
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trade_lineage import extract_lineage_from_proposal

LINEAGE_COLS = ["signal_id", "source_signal_id", "source_strategy_card_id", "strategy_card_id",
                "candidate_id", "execution_account", "execution_broker", "execution_environment"]


def _conn():
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])


def coverage(cur):
    cur.execute("select count(*) c from paper_trades")
    tot = cur.fetchone()["c"]
    out = {"total": tot}
    for col in ["proposal_id", "signal_id", "source_signal_id", "strategy_card_id", "source_strategy_card_id",
                "candidate_id", "execution_account", "execution_broker", "execution_environment", "lineage_stamped_at"]:
        cur.execute(f"select count(*) c from paper_trades where {col} is not null")
        n = cur.fetchone()["c"]
        out[col] = f"{n}/{tot} ({100*n/tot:.0f}%)" if tot else "0"
    return out


def main():
    apply = "--apply" in sys.argv
    c = _conn()
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    before = coverage(cur)
    cur.execute("select id, proposal_id from paper_trades where proposal_id is not null")
    rows = cur.fetchall()
    backfilled = skipped_no_prop = 0
    for r in rows:
        lin = extract_lineage_from_proposal(c, r["proposal_id"])
        if lin["lineage_confidence"] == "missing":
            skipped_no_prop += 1
            continue
        sets, vals = [], []
        for col in LINEAGE_COLS:
            key = "source_strategy_card_id" if col == "source_strategy_card_id" else col
            v = lin.get("strategy_card_id" if col in ("strategy_card_id", "source_strategy_card_id") else col)
            sets.append(f"{col}=COALESCE({col}, %s)")  # only fill when currently NULL
            vals.append(v)
        sets += ["source_proposal_id=COALESCE(source_proposal_id,%s)",
                 "lineage_source=COALESCE(lineage_source,%s)", "lineage_confidence=COALESCE(lineage_confidence,%s)",
                 "lineage_stamped_at=COALESCE(lineage_stamped_at, NOW())", "lineage_notes=COALESCE(lineage_notes,%s)"]
        vals += [str(r["proposal_id"]), "backfill_exact_proposal", "exact", json.dumps(lin.get("lineage_notes") or {})]
        if apply:
            cur.execute(f"update paper_trades set {', '.join(sets)} where id=%s", vals + [r["id"]])
        backfilled += 1
    # reverse pointer: proposal.paper_trade_id where exactly one paper_trade maps
    cur.execute("""select proposal_id, count(*) n, min(id) pt from paper_trades
                   where proposal_id is not null group by proposal_id""")
    rev_set = rev_ambig = 0
    for r in cur.fetchall():
        cur.execute("select paper_trade_id from paper_trade_proposals where id=%s", (r["proposal_id"],))
        pr = cur.fetchone()
        if pr is None or pr["paper_trade_id"] is not None:
            continue
        if r["n"] == 1:
            if apply:
                cur.execute("update paper_trade_proposals set paper_trade_id=%s where id=%s and paper_trade_id is null",
                            (r["pt"], r["proposal_id"]))
            rev_set += 1
        else:
            rev_ambig += 1
    if apply:
        c.commit()
    after = coverage(cur)
    print(json.dumps({"mode": "apply" if apply else "dry-run", "before": before, "after": after,
                      "paper_trades_backfilled": backfilled, "skipped_no_proposal": skipped_no_prop,
                      "reverse_links_set": rev_set, "reverse_skipped_ambiguous": rev_ambig}, indent=2))
    c.close()


if __name__ == "__main__":
    main()
