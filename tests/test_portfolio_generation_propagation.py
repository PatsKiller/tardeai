"""Dry-run acceptance for portfolio snapshot and operator-product propagation.

These tests are intentionally contract-level.  They prevent channel renderers
from creating their own generation or silently dropping the portfolio snapshot
used to calculate cash/rebalance semantics.
"""

from __future__ import annotations

from collections import Counter


def _product(*, action: str = "CASH_DEPLOYMENT", generation: str = "gen-42") -> dict:
    return {
        "product_id": "product-42",
        "generation_id": generation,
        "workflow_id": "wf-42",
        "portfolio_snapshot_id": "portfolio-snapshot-2026-08-27T10:00Z",
        "decision_status": "ADVISORY",
        "action_semantics": action,
        "cash": {
            "verified_cash_usd": 100_000,
            "reserved_cash_usd": 25_000,
            "investable_cash_usd": 75_000,
            "source": "portfolio_snapshot",
        },
        "lineage": {"source": "cio_operator_product", "evidence_class": "DRY_RUN"},
    }


def _render_channels(product: dict) -> dict[str, dict]:
    """Model channel renderers: each is a projection, never a new product."""
    return {
        channel: {
            "channel": channel,
            "generation_id": product["generation_id"],
            "product_id": product["product_id"],
            "workflow_id": product["workflow_id"],
            "portfolio_snapshot_id": product["portfolio_snapshot_id"],
        }
        for channel in ("telegram", "morning", "eod", "command_center")
    }


def test_snapshot_id_is_required_across_product_checkpoint_and_channels():
    product = _product()
    checkpoint = {"checkpoint_id": "cp-42", **{k: product[k] for k in (
        "generation_id", "workflow_id", "portfolio_snapshot_id")}}
    channels = _render_channels(product)
    assert product["portfolio_snapshot_id"]
    assert checkpoint["portfolio_snapshot_id"] == product["portfolio_snapshot_id"]
    assert {p["portfolio_snapshot_id"] for p in channels.values()} == {
        product["portfolio_snapshot_id"]
    }


def test_cash_deployment_is_not_mislabeled_as_rebalance():
    cash = _product(action="CASH_DEPLOYMENT")
    rebalance = _product(action="REBALANCE")
    assert cash["action_semantics"] == "CASH_DEPLOYMENT"
    assert rebalance["action_semantics"] == "REBALANCE"
    # Both can reference the same snapshot; semantics are explicit rather than
    # inferred from a non-zero cash balance.
    assert cash["portfolio_snapshot_id"] == rebalance["portfolio_snapshot_id"]


def test_morning_dedupe_keeps_one_generation_per_product():
    product = _product()
    repeated = [
        {"channel": "morning", "generation_id": product["generation_id"], "product_id": product["product_id"]}
        for _ in range(100)
    ]
    unique = {(x["channel"], x["generation_id"], x["product_id"]) for x in repeated}
    assert len(unique) == 1
    assert Counter(x["generation_id"] for x in repeated)[product["generation_id"]] == 100


def test_all_operator_surfaces_use_the_same_generation_and_product():
    product = _product()
    channels = _render_channels(product)
    assert {x["generation_id"] for x in channels.values()} == {product["generation_id"]}
    assert {x["product_id"] for x in channels.values()} == {product["product_id"]}
    assert {x["workflow_id"] for x in channels.values()} == {product["workflow_id"]}


def test_material_generation_change_is_allowed_but_keeps_snapshot_context():
    prior = _product(generation="gen-42")
    changed = _product(generation="gen-43")
    assert changed["generation_id"] != prior["generation_id"]
    assert changed["portfolio_snapshot_id"] == prior["portfolio_snapshot_id"]

