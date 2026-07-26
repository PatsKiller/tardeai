#!/usr/bin/env python3
"""Account-specific Defense recommendation producer v10.

This is an additive launcher around ``defense_recommendations``. It replaces only the
rotate-in producer and delegates every protect, trim, hedge, stance, ladder, round-trip,
oversight and snapshot path to the established engine.

The launcher is advisory/SHADOW only. It does not change a service, scheduler, broker,
order, approval, 2FA or production configuration. It becomes operational only when an
operator explicitly changes the host-side invocation after review and deployment.
"""
from __future__ import annotations

import json
from pathlib import Path

import defense_recommendations as base
from defense_account_exposure import account_sector_exposure, build_account_sizing
from defense_data_quality import allocation_decision, peer_medians, realized_vol_corr, stock_quality_assessment

ROOT = Path(__file__).resolve().parent.parent
EXPOSURE_POLICY = json.loads((ROOT / "config" / "defense_account_exposure.json").read_text())


def _canonical_fund_map(sectors: list[dict]) -> dict[str, dict]:
    """Return fund weights normalized to the sector engine's canonical names."""
    from fund_lookthrough import _cfg as fund_config

    sector_map = base._sector_map(sectors)
    out: dict[str, dict] = {}
    for symbol, fund in fund_config().items():
        if not isinstance(fund, dict):
            continue
        weights: dict[str, float] = {}
        for raw_sector, raw_weight in (fund.get("weights") or {}).items():
            canonical_row = sector_map.get(raw_sector or "")
            canonical_name = (canonical_row or {}).get("sector") or raw_sector
            if canonical_name:
                weights[canonical_name] = weights.get(canonical_name, 0.0) + float(raw_weight or 0)
        out[symbol] = {**fund, "weights": weights}
    return out


def _account_exposure(sectors: list[dict], cur, enrich: dict) -> dict[str, dict]:
    holdings = base._holdings()
    sector_map = base._sector_map(sectors)
    sector_by_symbol: dict[str, str | None] = {}
    for holding in holdings:
        symbol = holding["symbol"]
        raw_sector = (
            (enrich.get(symbol) or {}).get("sector")
            or (base._profiles_one(cur, symbol) or {}).get("sector")
        )
        canonical_row = sector_map.get(raw_sector or "")
        sector_by_symbol[symbol] = (canonical_row or {}).get("sector") or raw_sector
    return account_sector_exposure(holdings, _canonical_fund_map(sectors), sector_by_symbol)


def _current_account_weight(
    exposure: dict[str, dict], account: str, sector: str, max_unmapped_pct: float,
) -> float | None:
    """Return evidenced account weight, including a proven zero, or fail closed."""
    account_row = exposure.get(account)
    if not account_row:
        return None
    if float(account_row.get("unmapped_pct") or 0) > max_unmapped_pct:
        return None
    sector_row = (account_row.get("sectors") or {}).get(sector)
    return float(sector_row["pct"]) if sector_row else 0.0


def rotate_in_v10(sectors, cur, enrich, as_of, equities=None) -> list:
    """Build governed rotate-in cards using account-specific exposure and capacity."""
    cfg = base.CFG
    rotate_cfg = cfg["rotate_in"]
    max_unmapped_pct = float(EXPOSURE_POLICY["max_unmapped_pct"])
    minimum_action_pct = float(EXPOSURE_POLICY["minimum_action_pct"])

    ranked = sorted(
        [row for row in sectors
         if row.get("state") in ("LEADING", "IMPROVING") and not row.get("quarantined")],
        key=lambda row: -(row.get("rs20") or 0),
    )
    lean = (cfg.get("rotation_pairs") or {}).get("defensive_lean") or {}
    if lean.get("enabled"):
        ranked = [row for row in ranked if row["sector"] in lean.get("defensive_sectors", [])]

    industry_snapshot = base._load("industry_momentum_latest.json")
    industry_close = industry_snapshot.get("capture_kind") == "close"
    industry_rows = {
        row.get("industry"): row
        for row in industry_snapshot.get("industries", [])
        if not row.get("quarantined")
    }
    exposure = _account_exposure(sectors, cur, enrich)
    account_equities = equities or {
        account: row.get("account_equity_dollars", 0)
        for account, row in exposure.items()
    }

    cards: list[dict] = []
    for sector_row in ranked:
        risk = realized_vol_corr(cur, sector_row["etf"], cfg.get("benchmark", "SPY"))
        decisions = {
            account: allocation_decision(
                cfg,
                sector=sector_row["sector"],
                current_weight_pct=_current_account_weight(
                    exposure, account, sector_row["sector"], max_unmapped_pct,
                ),
                risk_context=risk,
                account=account,
            )
            for account in sorted(base.CAPS)
        }
        account_sizing = build_account_sizing(
            decisions,
            account_equities,
            rotate_cfg["size_band_pct"],
            minimum_action_pct=minimum_action_pct,
        )
        accounts = sorted(account_sizing)
        if not accounts:
            continue

        cur.execute(
            """SELECT DISTINCT ON (h.symbol) h.symbol, h.composite_score
                 FROM hermes_score_history h
                 JOIN trade_ai_scans t ON t.symbol = h.symbol
                WHERE t.sector = ANY(%s)
                  AND h.scored_at > now() - interval '3 days'
                ORDER BY h.symbol, h.scored_at DESC""",
            ([sector_row["sector"]] + base._sector_aliases(sector_row["sector"]),),
        )
        scored = sorted(
            [(symbol, float(score)) for symbol, score in cur.fetchall() if score is not None],
            key=lambda item: -item[1],
        )
        aliases = set([sector_row["sector"]] + base._sector_aliases(sector_row["sector"]))
        peers = peer_medians([
            value for value in enrich.values() if (value or {}).get("sector") in aliases
        ])
        prices = base._prices(cur, [symbol for symbol, _ in scored[:60]])
        picks: list[dict] = []
        for symbol, legacy_rank in scored[:60]:
            evidence = enrich.get(symbol) or {}
            price = prices.get(symbol) or 0
            dollar_volume_m = (
                (evidence.get("avg_vol_m") or 0) * 1000 * price / 1e6 if price else 0
            )
            profile = base._profiles_one(cur, symbol)
            industry = evidence.get("industry")
            industry_row = industry_rows.get(industry) or {}
            quality = stock_quality_assessment(evidence, peers, cfg)
            if dollar_volume_m < rotate_cfg["constituent_min_dollar_vol_m"]:
                continue
            if (evidence.get("sma50_pct") or 0) > rotate_cfg["constituent_max_ext_above_sma50_pct"]:
                continue
            if base._earnings_soon(profile, rotate_cfg["earnings_blackout_days"]):
                continue
            if cfg.get("stock_quality", {}).get("requires_close_confirmed_industry") and (
                not industry_close
                or industry_row.get("state") not in ("LEADING", "IMPROVING")
            ):
                continue
            if not quality["passed"]:
                continue
            picks.append({
                "symbol": symbol,
                "legacy_rank": round(legacy_rank, 1),
                "institutional_quality": quality,
                "industry": industry,
            })
            if len(picks) >= rotate_cfg["top_constituents"]:
                break

        etf_price = base._prices(cur, [sector_row["etf"]]).get(sector_row["etf"])
        etf_evidence = enrich.get(sector_row["etf"]) or {}
        sma20_level = (
            round(etf_price / (1 + (etf_evidence.get("sma20_pct") or 0) / 100), 2)
            if etf_price else None
        )
        instruments = [{
            "symbol": sector_row["etf"],
            "kind": "sector ETF",
            "note": "account-specific policy and risk capacity qualified",
            "price": etf_price,
        }]
        instruments.extend({
            "symbol": pick["symbol"],
            "kind": "constituent",
            "note": (
                f"institutional quality {pick['institutional_quality']['score']:.0f}; "
                f"{pick['industry']}"
            ),
            "price": prices.get(pick["symbol"]),
            "quality": pick["institutional_quality"],
        } for pick in picks)
        if not picks:
            instruments[0]["note"] += (
                " — ETF only; no stock passed complete close-industry and evidence rails"
            )

        capacity_line = "; ".join(
            f"{cfg['account_labels'].get(account, account)} current "
            f"{decisions[account]['current_account_weight_pct']:.2f}% → target "
            f"{decisions[account]['risk_target_pct']:.2f}% · capacity "
            f"{decisions[account]['capacity_pct']:.2f}% · act "
            f"{account_sizing[account]['pct_band'][0]:.2f}–"
            f"{account_sizing[account]['pct_band'][1]:.2f}%"
            for account in accounts
        )
        dollars_by_account = {
            account: row["dollar_band"] for account, row in account_sizing.items()
        }
        account_exposure_summary = {
            account: {
                "account_equity_dollars": exposure[account]["account_equity_dollars"],
                "mapped_pct": exposure[account]["mapped_pct"],
                "unmapped_pct": exposure[account]["unmapped_pct"],
                "current_sector_pct": decisions[account]["current_account_weight_pct"],
            }
            for account in accounts
        }
        cards.append({
            "id": f"rotatein-{sector_row['etf']}-{as_of}",
            "group": "get_into",
            "title": (
                f"ROTATE-IN · {sector_row['sector']} "
                f"({sector_row['state']}, RS20 {sector_row['rs20']:+.1f})"
            ),
            "instruments": instruments,
            "accounts": accounts,
            "direction": "long",
            "size_band": "account-specific — see account_sizing",
            "entry_logic": (
                "stagger only on pullbacks toward the 20DMA; each account is capped by "
                "its own exposure, volatility, correlation and mandate"
            ),
            "invalidation": (
                f"{sector_row['sector']} exits {sector_row['state']} on a two-close "
                "confirmation or the target account's capacity falls below 1%"
            ),
            "factors": [
                {"name": "sector state", "value": sector_row["state"]},
                {"name": "RS20 vs SPY", "value": f"{sector_row['rs20']:+.2f}%"},
                {
                    "name": "covered-universe breadth",
                    "value": (
                        f"{sector_row.get('breadth_pct')}% over exact 20-session measure"
                    ),
                },
                {
                    "name": "realized volatility",
                    "value": f"{risk.get('annualized_vol_pct')}%",
                },
                {"name": "correlation to SPY", "value": str(risk.get("correlation"))},
                {"name": "account-specific capacity", "value": capacity_line},
            ],
            "as_of": as_of,
            "mode": "SHADOW",
            "levels": {
                "price": etf_price,
                "entry_zone": (
                    f"pullback toward 20DMA ≈ ${sma20_level}"
                    if sma20_level else "stagger on pullbacks"
                ),
                "stop": (
                    f"thesis stop: {sector_row['sector']} exits "
                    f"{sector_row['state']} (two-close)"
                ),
            },
            "account_sizing": account_sizing,
            "dollars_by_account": dollars_by_account,
            "impact_dollars": max(
                (row["dollar_band"][1] for row in account_sizing.values()), default=0,
            ),
            "allocation_policy": decisions,
            "account_exposure": account_exposure_summary,
            "risk_context": risk,
            "quality_gate": {
                "industry_capture_kind": industry_snapshot.get("capture_kind"),
                "stock_picks_passed": len(picks),
                "max_account_unmapped_pct": max_unmapped_pct,
                "version": base.RECOMMENDATION_CALC_VERSION,
            },
            "routes": {
                "proposal": "watch-directive path — operator approves; nothing self-executes"
            },
        })
        if len(cards) >= rotate_cfg["max_cards"]:
            break
    return cards


def install() -> None:
    """Install only the v10 rotate-in producer into the established engine."""
    base.rotate_in = rotate_in_v10


def main() -> int:
    install()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
