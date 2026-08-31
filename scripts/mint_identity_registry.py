#!/usr/bin/env python3
"""Mint durable entity identities for every symbol the system reasons about.

Phase A of the identity/memory advisory. Reads the symbols already flowing
through the system, resolves each once through the existing
`security_identity.resolve_identity_spine()`, and persists the result to the
`identity.registry` store so it can be read back instead of recomputed.

    python scripts/mint_identity_registry.py            # dry run (default)
    python scripts/mint_identity_registry.py --json
    python scripts/mint_identity_registry.py --apply    # write the registry

Scope is holdings and the watch universe — the symbols decisions are actually
made about. The 6,000+ symbols in `ticker_prices` are deliberately excluded:
minting an identity for a ticker nothing reasons about produces a registry that
is mostly noise, and the spine can always be resolved on demand for a symbol
that later becomes interesting.

Nothing here invents an identifier. A symbol with only a name resolves to a
CANDIDATE issuer identity; a symbol with a CUSIP/ISIN/FIGI resolves to a
CONFIRMED one; a symbol with neither is registered honestly as
UNRESOLVED_WITH_REASON against its ticker alias. Upgrades preserve the old GUID
as a superseded alias so history stays traversable — see `identity_registry`.

AUTHORITY: READ_ONLY_ADVISORY. Identity only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib.identity_registry import load, lookup_symbol, register_all  # noqa: E402
from scripts.lib.security_identity import normalize_symbol  # noqa: E402


def _holdings_rows() -> list[dict]:
    """Positions carry `name` for every row, which yields a CANDIDATE issuer."""
    try:
        from scripts.lib.canonical_store_registry import resolve_store
        path = Path(resolve_store("portfolio.holdings.current")["path"])
    except Exception:
        path = Path.home() / "trade-ai-releases" / "persistent-state" / "data" / "portfolios" / "state" / "holdings.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    positions = doc.get("holdings") or doc.get("positions") or []
    if isinstance(positions, dict):
        positions = list(positions.values())
    rows = []
    for p in positions:
        if not isinstance(p, dict) or p.get("is_cash"):
            continue
        sym = normalize_symbol(p.get("symbol"))
        if not sym:
            continue
        ids = {k: p[k] for k in ("cusip", "isin", "figi") if p.get(k)}
        rows.append({
            "symbol": sym,
            "company": p.get("company") or p.get("name"),
            "cik": p.get("cik"),
            "exchange": p.get("exchange"),
            "identifiers": ids,
            "source": "holdings",
        })
    return rows


def _watchlist_rows() -> list[dict]:
    """Watch universe the system still reasons about. No Postgres, no rows.

    Scope is every status except `removed`: 360 `active` plus 5,113
    `researched`. Phase A took `active` only, which left a name the system had
    researched -- and might re-enter tomorrow -- with no durable identity, and an
    identity minted at the moment of re-entry is exactly the fragmentation the
    registry exists to prevent.

    `removed` (7,198) stays out. Those are names explicitly dropped; minting them
    buries the working universe under twice its own volume in ticker aliases.
    A removed symbol that returns comes back under another status and is picked
    up on the next run -- registration is incremental and idempotent.
    """
    try:
        from price_db_sync import _get_conn  # type: ignore
        conn = _get_conn()
    except Exception:
        return []
    rows = []
    try:
        cur = conn.cursor()
        cur.execute("""SELECT DISTINCT symbol FROM watchlist_items
                       WHERE symbol IS NOT NULL AND symbol <> ''
                         AND COALESCE(status, '') <> 'removed'""")
        for (sym,) in cur.fetchall():
            s = normalize_symbol(sym)
            if s:
                rows.append({"symbol": s, "source": "watchlist"})
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return rows


def _decision_surface_rows() -> list[dict]:
    """Symbols carried by decision surfaces other than the watchlist table.

    Re-entry candidates and anything ever traded are names the system forms
    positions about, and neither is guaranteed to hold an `active` watchlist row
    -- 43 re-entry symbols and 117 traded symbols had no registry entry at all.
    `watchlist_symbol_master` is the durable symbol catalogue behind the desks.

    A missing table contributes nothing rather than failing the mint: these are
    additive sources, and the registry must still build from whatever exists.
    """
    try:
        from price_db_sync import _get_conn  # type: ignore
        conn = _get_conn()
    except Exception:
        return []
    sources = (
        ("reentry_directive_hits_staging", "reentry"),
        ("trade_transactions", "traded"),
        ("watchlist_symbol_master", "symbol_master"),
    )
    rows = []
    try:
        for table, source in sources:
            try:
                cur = conn.cursor()
                cur.execute(
                    f"SELECT DISTINCT symbol FROM {table} "  # noqa: S608 — fixed literals above
                    "WHERE symbol IS NOT NULL AND symbol <> ''"
                )
                for (sym,) in cur.fetchall():
                    norm = normalize_symbol(sym)
                    if norm:
                        rows.append({"symbol": norm, "source": source})
            except Exception:
                # One absent table must not cost us the others.
                try:
                    conn.rollback()
                except Exception:
                    pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return rows


def _identifier_rows() -> list[dict]:
    """Durable identifiers the brokers already gave us and nothing consumed.

    Schwab e-confirms carry a real CUSIP per traded symbol. That is exactly what
    lifts an entity from a name-derived CANDIDATE identity to a CONFIRMED one, and
    it has been sitting in `econfirm_evidence` unused. Read it rather than ask a
    vendor for something we already hold.
    """
    try:
        from price_db_sync import _get_conn  # type: ignore
        conn = _get_conn()
    except Exception:
        return []
    rows = []
    try:
        cur = conn.cursor()
        cur.execute("""SELECT DISTINCT UPPER(symbol), cusip FROM econfirm_evidence
                       WHERE symbol IS NOT NULL AND symbol <> ''
                         AND cusip IS NOT NULL AND cusip <> ''""")
        for sym, cusip in cur.fetchall():
            rows.append({"symbol": sym, "identifiers": {"cusip": str(cusip).strip()},
                         "source": "econfirm"})
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return rows


def _broker_reference_rows() -> list[dict]:
    """Durable identifiers swept from the broker's instrument reference.

    E-confirms only cover symbols we have traded, which left the active watch
    universe with no identifier at all. `sweep_schwab_instruments.py` fills that
    from Schwab's instrument reference; this reads whatever it has written. No
    sweep yet means no rows, never a guess.
    """
    try:
        from scripts.lib.schwab_instrument_evidence import identifier_rows
        return identifier_rows()
    except Exception:
        return []


def collect_rows() -> list[dict]:
    """Holdings first: a held position's richer row should win the merge."""
    merged: dict[str, dict] = {}
    for row in (_holdings_rows() + _watchlist_rows() + _decision_surface_rows()
                + _identifier_rows() + _broker_reference_rows()):
        sym = row["symbol"]
        if sym in merged:
            for k, v in row.items():
                if k == "identifiers" and isinstance(v, dict):
                    # Union, never replace: holdings supply the name, e-confirms
                    # supply the CUSIP, and an entity needs both to reach CONFIRMED.
                    merged[sym].setdefault("identifiers", {}).update(
                        {ik: iv for ik, iv in v.items() if iv}
                    )
                elif v and not merged[sym].get(k):
                    merged[sym][k] = v
        else:
            merged[sym] = dict(row)
    return list(merged.values())


def _profile_row(symbol: str) -> dict | None:
    """Verify a symbol against the known ticker universe (symbol_profiles)."""
    try:
        from price_db_sync import _get_conn  # type: ignore
        conn = _get_conn()
    except Exception:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT upper(symbol) AS symbol, description_1s, sector
                 FROM symbol_profiles WHERE upper(symbol)=%s LIMIT 1""",
            (normalize_symbol(symbol),),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"symbol": row[0], "description_1s": row[1], "sector": row[2]}
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def propose_catalyst_registry_gap(*, limit: int = 200) -> dict:
    """E3 propose-list: real catalyst symbols in symbol_profiles but not registered.

    Does not mint. Does not widen any rule. Operator verifies one-at-a-time via
    `--register-symbol SYM` (dry-run default).
    """
    try:
        from scripts.lib.hermes_discovery.symbol_validation import is_research_directive_slug
    except Exception:
        def is_research_directive_slug(sym: str) -> bool:  # type: ignore
            return "_" in str(sym or "")

    doc = load()
    try:
        from price_db_sync import _get_conn  # type: ignore
        conn = _get_conn()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "proposed": []}

    proposed: list[dict] = []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT upper(ce.symbol) AS sym, count(*) AS n
              FROM catalyst_events ce
              JOIN symbol_profiles sp ON upper(sp.symbol) = upper(ce.symbol)
             WHERE ce.symbol IS NOT NULL AND btrim(ce.symbol) <> ''
             GROUP BY 1
             ORDER BY n DESC
            """
        )
        for sym, n in cur.fetchall():
            s = normalize_symbol(sym)
            if not s or is_research_directive_slug(s):
                continue
            if lookup_symbol(doc, s):
                continue
            proposed.append({"symbol": s, "catalyst_rows": int(n), "in_symbol_profiles": True})
            if len(proposed) >= limit:
                break
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return {
        "ok": True,
        "mode": "propose",
        "proposed_count": len(proposed),
        "proposed": proposed,
        "applied": False,
        "note": (
            "Propose only. Register deliberately with "
            "`--register-symbol SYM` (dry-run) then `--register-symbol SYM --apply`."
        ),
    }


def register_one_verified(symbol: str, *, apply: bool = False) -> dict:
    """E3 deliberate one-at-a-time mint. Requires universe verification.

    Refuses research-directive slugs and symbols absent from symbol_profiles.
    Dry-run default — never silent-mints junk.
    """
    try:
        from scripts.lib.hermes_discovery.symbol_validation import is_research_directive_slug
    except Exception:
        def is_research_directive_slug(sym: str) -> bool:  # type: ignore
            return "_" in str(sym or "")

    sym = normalize_symbol(symbol)
    if not sym:
        return {"ok": False, "symbol": sym, "error": "empty symbol", "applied": False}
    if is_research_directive_slug(sym):
        return {
            "ok": False,
            "symbol": sym,
            "error": "research-directive / topic slug — refuse mint",
            "applied": False,
        }
    profile = _profile_row(sym)
    if not profile:
        return {
            "ok": False,
            "symbol": sym,
            "error": "not in symbol_profiles — refuse mint (do not widen a rule)",
            "applied": False,
        }

    existing = lookup_symbol(load(), sym)
    if existing:
        return {
            "ok": True,
            "symbol": sym,
            "already_registered": True,
            "subject_guid": existing.get("subject_guid"),
            "identity_status": existing.get("identity_status"),
            "applied": False,
        }

    row = {
        "symbol": sym,
        "company": (profile.get("description_1s") or "").split(",")[0][:80] or None,
        "source": "deliberate_catalyst_gap",
    }
    summary = register_all([row], apply=apply)
    after = lookup_symbol(load(), sym) if apply else None
    return {
        "ok": True,
        "symbol": sym,
        "already_registered": False,
        "verified_against": "symbol_profiles",
        "would_register": not apply,
        "applied": bool(apply),
        "register_summary": {
            "entities_added": summary.get("entities_added"),
            "path": summary.get("path"),
        },
        "subject_guid": (after or {}).get("subject_guid"),
        "identity_status": (after or {}).get("identity_status"),
        "authority": "READ_ONLY_ADVISORY",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Mint the durable identity registry (Phase A)")
    ap.add_argument("--apply", action="store_true", help="write the registry (default: dry run)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--symbol", default=None, help="show the registered identity for one symbol")
    ap.add_argument(
        "--propose-catalyst-gap",
        action="store_true",
        help="E3: list catalyst symbols in symbol_profiles but not in the registry (propose only)",
    )
    ap.add_argument(
        "--register-symbol",
        default=None,
        metavar="SYM",
        help="E3: deliberate one-at-a-time mint; verifies against symbol_profiles; dry-run unless --apply",
    )
    args = ap.parse_args()

    if args.propose_catalyst_gap:
        report = propose_catalyst_registry_gap()
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"PROPOSE catalyst registry gap — {report.get('proposed_count', 0)} symbol(s)")
            for row in report.get("proposed") or []:
                print(f"  {row['symbol']:<8}  catalyst_rows={row['catalyst_rows']}")
            print(report.get("note", ""))
        return 0 if report.get("ok") else 1

    if args.register_symbol:
        report = register_one_verified(args.register_symbol, apply=args.apply)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"{'APPLY' if args.apply else 'DRY RUN'} — register-symbol {report.get('symbol')}")
            if not report.get("ok"):
                print(f"  REFUSED: {report.get('error')}")
                return 1
            if report.get("already_registered"):
                print(f"  already registered  status={report.get('identity_status')}  "
                      f"guid={(report.get('subject_guid') or '')[:8]}")
            else:
                print(f"  verified against symbol_profiles")
                print(f"  entities_added={report.get('register_summary', {}).get('entities_added')}")
                if not args.apply:
                    print("\nnothing written. re-run with --register-symbol SYM --apply.")
        return 0 if report.get("ok") else 1

    if args.symbol:
        ent = lookup_symbol(load(), args.symbol)
        print(json.dumps(ent, indent=2, sort_keys=True) if ent
              else f"{normalize_symbol(args.symbol)}: not registered")
        return 0

    rows = collect_rows()
    summary = register_all(rows, apply=args.apply)

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"{'APPLY' if args.apply else 'DRY RUN'} — {summary['rows_seen']} symbol(s)")
        print(f"  entities   {summary['entities_before']} → {summary['entities_after']}"
              f"  (+{summary['entities_added']})")
        print(f"  by status  {summary['by_identity_status']}")
        print(f"  symbols    {summary['symbols_indexed']} indexed")
        print(f"  registry   {summary['path']}")
        if not args.apply:
            print("\nnothing written. re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
