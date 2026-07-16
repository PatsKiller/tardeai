#!/usr/bin/env python3
"""trade_lineage.py — broker/account-neutral EXECUTION LINEAGE extraction.

Returns the lineage a trade record should carry at submit time, sourced from the approved proposal
(broker/account from the proposal's routing + the broker/account model, NOT hardcoded to Alpaca).
First consumer is `paper_trades`; the shape is generic for future Schwab/Fidelity/etc. execution.

Read-only. No broker/order writes.
"""


def _account_broker_env(conn, account):
    """Resolve (broker, environment) for an account from the broker/account model (broker_accounts),
    falling back to the legacy accounts table, then to a conservative inference. Never hardcoded."""
    if not account:
        return None, None
    cur = conn.cursor()
    try:
        cur.execute("SELECT broker, environment FROM broker_accounts WHERE account_key=%s", (account,))
        r = cur.fetchone()
        if r and r[0]:
            return r[0], r[1]
    except Exception:
        conn.rollback()
    try:
        cur.execute("SELECT broker, mode FROM accounts WHERE account_label=%s", (account,))
        r = cur.fetchone()
        if r and r[0]:
            return r[0], r[1]
    except Exception:
        conn.rollback()
    # conservative inference from the account label (display only; not execution-enabling)
    a = account.lower()
    for b in ("alpaca", "schwab", "fidelity", "tos", "tradier"):
        if b in a:
            return b, ("paper" if "paper" in a else "live")
    return None, ("paper" if "paper" in a else None)


def extract_lineage_from_proposal(conn, proposal_id):
    """Broker/account-neutral lineage dict for an approved proposal. confidence='exact' when sourced
    directly from the proposal row, 'missing' when the proposal can't be found."""
    base = {"proposal_id": str(proposal_id) if proposal_id is not None else None,
            "signal_id": None, "source_signal_id": None, "strategy_card_id": None, "candidate_id": None,
            "execution_account": None, "execution_broker": None, "execution_environment": None,
            "lineage_confidence": "missing", "lineage_source": "missing", "lineage_notes": {}}
    if proposal_id is None:
        return base
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT * FROM paper_trade_proposals WHERE id=%s", (proposal_id,))
        p = cur.fetchone()
    except Exception:
        conn.rollback()
        p = None
    if not p:
        return base
    acct = p.get("target_account") or p.get("final_account") or p.get("proposed_account")
    broker, env = _account_broker_env(conn, acct)
    sig = p.get("source_signal_id")
    card = p.get("source_strategy_card_id")
    cand = p.get("source_record_id") or p.get("discovery_source")
    notes = {"discovery_source": p.get("discovery_source"), "primary_strategy_id": p.get("primary_strategy_id"),
             "source_table": p.get("source_table"), "account_field": ("target_account" if p.get("target_account")
             else "final_account" if p.get("final_account") else "proposed_account" if p.get("proposed_account") else None)}
    return {"proposal_id": str(proposal_id), "signal_id": (str(sig) if sig is not None else None),
            "source_signal_id": (str(sig) if sig is not None else None),
            "strategy_card_id": (str(card) if card is not None else None),
            "candidate_id": (str(cand) if cand is not None else None),
            # Watch Desk v4 (F3): discovery trace threads proposal→fill verbatim (never inferred)
            "discovery_trace_id": p.get("discovery_trace_id"),
            "execution_account": acct, "execution_broker": broker, "execution_environment": env,
            "lineage_confidence": "exact", "lineage_source": "proposal",
            "lineage_notes": {k: v for k, v in notes.items() if v is not None}}


if __name__ == "__main__":
    import os, sys, json, psycopg2
    conn = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    pid = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(extract_lineage_from_proposal(conn, pid), indent=2, default=str))
