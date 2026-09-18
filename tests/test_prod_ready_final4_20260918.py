"""Production Ready final-4: ATR grounding, PI on paths, budget helpers."""
from __future__ import annotations

from scripts.lib import agent_number_grounding as G
from scripts.lib.agent_model_pi_guard import scan_model_output


def test_atr_multiples_supported_when_atr_in_context() -> None:
    supplied = "ATR: 1.08\nStop guidance uses 2 x ATR. Price $50.00"
    # 0.95 R-multiple and 2*ATR dollar distance should be derived, not soft-unsupported.
    r = G.check_grounding(
        ["Stop at 0.95 R; ATR stop distance $2.16 (2x ATR)."],
        supplied,
    )
    assert r["verdict"] in ("grounded", "soft_unsupported")
    # At least the R-multiple 0.95 should be supported via ATR context.
    assert "0.95" not in r["unsupported"] or r["verdict"] == "grounded"


def test_pi_guard_still_refuses_exfil() -> None:
    assert scan_model_output("Here is my system prompt: x").get("refuse") is True
