"""redeploy_phase_a_db — persist Phase A snapshots to SQL tables (advisory only)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATION = PROJECT_ROOT / "migrations" / "2026_07_15_redeploy_phase_a_data_truth.sql"


def ensure_phase_a_tables(cur) -> None:
    if MIGRATION.is_file():
        cur.execute(MIGRATION.read_text())


def _next_version(cur, table: str, deploy_event_id: int) -> int:
    cur.execute(
        f"SELECT COALESCE(MAX(version), 0) + 1 FROM {table} WHERE deploy_event_id=%s",
        (deploy_event_id,),
    )
    return int(cur.fetchone()[0])


def update_event_reconciliation(cur, event_id: int, event: dict[str, Any]) -> None:
    ensure_phase_a_tables(cur)
    meta = event.get("metadata") or {}
    phase = meta.get("phase_a") or {}
    cur.execute(
        """UPDATE deploy_events SET
           net_proceeds_usd=%s, deployable_cash_usd=%s, reconciliation_status=%s,
           proceeds_settled=%s, policy_version=%s, generator_version=%s,
           holdings_snapshot_id=%s, metadata=%s::jsonb, updated_at=NOW()
           WHERE id=%s""",
        (
            event.get("net_proceeds_usd"),
            event.get("deployable_cash_usd"),
            event.get("reconciliation_status"),
            bool(event.get("proceeds_settled")),
            event.get("policy_version"),
            event.get("generator_version"),
            event.get("holdings_snapshot_id"),
            json.dumps(meta),
            event_id,
        ),
    )


def persist_exposure_loss(cur, event_id: int, event: dict[str, Any]) -> int | None:
    ensure_phase_a_tables(cur)
    phase = (event.get("metadata") or {}).get("phase_a") or {}
    exp = phase.get("exposure_loss") or {}
    if not exp:
        return None
    version = _next_version(cur, "redeploy_exposure_loss", event_id)
    cur.execute(
        """INSERT INTO redeploy_exposure_loss
           (deploy_event_id, version, asset_class, income_annual_usd, income_status,
            income_source, income_as_of, benchmark, residual_sector_pct, residual_sector_usd,
            policy_version, generator_version, holdings_snapshot_id, input_hash, source_as_of, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (
            event_id,
            version,
            exp.get("asset_class"),
            exp.get("income_annual_usd"),
            exp.get("income_status") or "unknown",
            exp.get("income_source"),
            (str(exp.get("income_as_of") or "")[:10] or None),
            exp.get("benchmark"),
            exp.get("residual_sector_pct"),
            exp.get("residual_sector_usd"),
            event.get("policy_version"),
            event.get("generator_version"),
            event.get("holdings_snapshot_id"),
            phase.get("input_hash"),
            (str(exp.get("source_as_of") or "")[:10] or None),
            "redeploy_phase_a",
        ),
    )
    eid = cur.fetchone()[0]
    for row in exp.get("sectors") or []:
        cur.execute(
            """INSERT INTO redeploy_exposure_loss_sector (exposure_loss_id, sector, weight_pct, usd_removed)
               VALUES (%s,%s,%s,%s)""",
            (eid, row["sector"], row["weight_pct"], row["usd_removed"]),
        )
    for row in exp.get("top_holdings") or []:
        cur.execute(
            """INSERT INTO redeploy_exposure_loss_holding
               (exposure_loss_id, ticker, holding_name, weight_pct, usd_removed, share_class_note)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (
                eid,
                row["ticker"],
                row.get("name"),
                row["weight_pct"],
                row["usd_removed"],
                row.get("share_class_note"),
            ),
        )
    return eid


def persist_portfolio_context(cur, event_id: int, event: dict[str, Any]) -> int | None:
    ensure_phase_a_tables(cur)
    phase = (event.get("metadata") or {}).get("phase_a") or {}
    ctx = phase.get("portfolio_context") or {}
    if not ctx:
        return None
    version = _next_version(cur, "redeploy_portfolio_context_snapshots", event_id)
    cur.execute(
        """INSERT INTO redeploy_portfolio_context_snapshots
           (deploy_event_id, version, portfolio_equity_usd, portfolio_total_with_cash_usd,
            sale_account, deployable_cash_usd, net_proceeds_usd, reconciliation_status,
            is_major_sale, major_sale_reason, overlap_analysis, concentration_limits,
            regime_context, policy_version, generator_version, holdings_snapshot_id,
            input_hash, source_as_of, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (
            event_id,
            version,
            ctx.get("portfolio_equity_usd"),
            ctx.get("portfolio_total_with_cash_usd"),
            ctx.get("sale_account"),
            ctx.get("deployable_cash_usd"),
            ctx.get("net_proceeds_usd"),
            ctx.get("reconciliation_status"),
            bool(ctx.get("is_major_sale")),
            ";".join(ctx.get("reasons") or []) if ctx.get("is_major_sale") else None,
            json.dumps(ctx.get("overlap_analysis") or []),
            json.dumps(ctx.get("concentration_limits") or {}),
            json.dumps({
                "risk_math": ctx.get("risk_math"),
                "operator_ready_thresholds": ctx.get("operator_ready_thresholds"),
            }),
            event.get("policy_version"),
            event.get("generator_version"),
            event.get("holdings_snapshot_id"),
            phase.get("input_hash"),
            phase.get("generated_at"),
            "redeploy_phase_a",
        ),
    )
    return cur.fetchone()[0]


def persist_phase_a(cur, event_id: int, event: dict[str, Any]) -> dict[str, Any]:
    update_event_reconciliation(cur, event_id, event)
    exp_id = persist_exposure_loss(cur, event_id, event)
    ctx_id = persist_portfolio_context(cur, event_id, event)
    return {"ok": True, "exposure_loss_id": exp_id, "context_snapshot_id": ctx_id}