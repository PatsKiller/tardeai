#!/usr/bin/env python3
"""enrich_proposal_technicals.py — keep the moving-average / entry-helper technicals fresh for every
ACTIVE (and recently-expired) broker proposal symbol.

The card's "Entry helper" strip (SMA20/50/200 vs live price, RSI, RVOL, ATR%) reads the Finviz
technical enrichment cache (data/state/ticker_enrichment_cache.json). Watchlist/income proposals are
never momentum-scanned, so without this refresh their technicals stay blank. This pulls Finviz views
141 (RVOL/volatility) + 171 (RSI/SMA20-50-200/ATR — no cookie needed) for those symbols.

Cron (every 2h, flock-guarded single-flight):
    /usr/bin/flock -n /tmp/enrich_proposal_tech.lock .venv/bin/python scripts/enrich_proposal_technicals.py
"""
from __future__ import annotations

import sys as _dr_sys

if __name__ == "__main__" and "--dry-run" in _dr_sys.argv[1:]:
    # n8n onboarding (lane disposition 2026-10-15, MIGRATE_N8N): --dry-run is an OFFLINE plan and wins over every
    # live flag (the bare scheduled run). It returns here, before the .env load, any DB/LLM/network/sender import and any file
    # write; it prints the plan and one LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run).
    import os as _dr_os

    _dr_sys.path.insert(0, _dr_os.path.join(_dr_os.path.dirname(_dr_os.path.abspath(__file__))))
    from lib.lane_output import emit as _dr_emit, output_block as _dr_block

    _dr_lane = "enrich-proposal-technicals"
    _dr_would = (
        "pull Finviz views 141 + 171 for every active / recently expired proposal symbol and merge the "
        "technicals into the ticker enrichment cache"
    )
    print(f"DRY-RUN {_dr_lane}: would {_dr_would}; argv={_dr_sys.argv[1:]!r}; dry-run wins over live flags; "
          "nothing read from env/DB/network, no model call, no send, no file write")
    _dr_emit(_dr_lane, "dry_run", _dr_block(produced=0, attempted=0, empty_reason="dry_run", unit="proposal_symbol"))
    raise SystemExit(0)

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

#: Registry lane id and the repo-relative script path, for the LaneRunReceipt (state root resolves the path).
LANE_ID = "enrich-proposal-technicals"
SCRIPT_REL = "scripts/enrich_proposal_technicals.py"


def main(argv=None) -> int:
    # LaneRunReceipt: the registry output_signal for this lane is this receipt's ok_at (LQ-20261107-20
    # overnight onboarding). A real run writes it -- a failed one too, carrying the previous ok_at forward so a
    # broken lane goes stale instead of green. The --dry-run branch returns above, before this point.
    from lib.lane_last_receipt import now_iso, write_lane_receipt

    started_at = now_iso()
    try:
        symbols, refreshed, failed = _run()
    except Exception as exc:  # noqa: BLE001 — the receipt must record the failure before it propagates
        write_lane_receipt(LANE_ID, ok=False, started_at=started_at, script=SCRIPT_REL,
                           error=f"{type(exc).__name__}: {exc}")
        raise
    outcome, reason = receipt_outcome(symbols, refreshed, failed, _FINVIZ_GOT.get("n"))
    ok = outcome != "error"
    write_lane_receipt(LANE_ID, ok=ok, started_at=started_at, script=SCRIPT_REL,
                       summary={"symbols": symbols, "refreshed": refreshed, "failed": failed},
                       error=None if ok else f"source_error:{reason}", outcome=outcome, outcome_reason=reason)
    return 0 if ok else 1


#: Filled by _run: how many symbols the Finviz call answered for (None = not reached / unknown).
_FINVIZ_GOT: dict = {}


def receipt_outcome(symbols: int, refreshed: int, failed: int, finviz_got=None) -> tuple[str, str | None]:
    """ok | empty | error for one run (LQ-192). No active proposal symbols is a true empty; a Finviz call that
    answered for none of the symbols, or every snapshot failing, is an ERROR (unknown, not "nothing to do")."""
    if not symbols:
        return "empty", "no_active_proposal_symbols"
    if finviz_got == 0:
        return "error", "finviz_returned_no_symbols"
    if refreshed == 0:
        return "error", "every_snapshot_failed"
    return "ok", (f"partial_failures:{failed}" if failed else None)


def _run() -> tuple[int, int, int]:
    """Refresh the Finviz technicals and the per-proposal snapshot; return (symbols, refreshed, failed)."""
    from db_adapter import _execute, _get_conn
    from finviz_enrichment import enrich_tickers

    rows = _execute(
        """SELECT id, symbol, catalyst, catalyst_verified FROM paper_trade_proposals
           WHERE status IN ('PENDING','APPROVED_FOR_PAPER_TEST','PROPOSED','MODIFIED','BROKER_SUBMITTED')
           ORDER BY updated_at DESC NULLS LAST
           LIMIT 40""",
        None, fetch="all") or []
    syms = sorted({(r["symbol"] or "").upper() for r in rows if r.get("symbol")})
    if not syms:
        print("[enrich_proposal_technicals] no active proposal symbols")
        return (0, 0, 0)
    got = enrich_tickers(syms, project_root=str(ROOT), views=[141, 171], skip_fundamentals=True)
    _FINVIZ_GOT["n"] = len(got) if hasattr(got, "__len__") else None
    print(f"[enrich_proposal_technicals] refreshed finviz technicals for {len(syms)} symbol(s)")

    conn = _get_conn()
    import proposal_enrichment_bridge as peb
    from proposal_technical_snapshot import generate_snapshot

    refreshed = failed = 0
    for row in rows:
        pid = int(row["id"])
        sym = str(row["symbol"] or "").upper()
        try:
            generate_snapshot(conn, proposal_id=pid, symbol=sym)
            ir = peb.compute_proposal_intel_readiness(
                sym, conn,
                catalyst=row.get("catalyst"),
                catalyst_verified=bool(row.get("catalyst_verified")),
                has_technical_snapshot=True,
            )
            conn.cursor().execute(
                "UPDATE paper_trade_proposals SET intel_readiness=%s, updated_at=NOW() WHERE id=%s",
                (ir, pid),
            )
            conn.commit()
            refreshed += 1
            print(f"  {sym} #{pid}: snapshot + intel_readiness={ir}")
        except Exception as e:
            failed += 1
            print(f"  {sym} #{pid}: snapshot failed — {e}")
            try:
                conn.rollback()
            except Exception:
                pass
    return (len(syms), refreshed, failed)


if __name__ == "__main__":
    sys.exit(main())
