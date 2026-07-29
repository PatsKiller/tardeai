"""Schema-contract test for the sector → industry join. SL-S2 Guard 2.

WHY THIS EXISTS
    SL-S1 tested the card against Energy, it worked, and that read as success.
    Energy is one value of an eleven-valued key. `industry_momentum_state.sector`
    carries FINVIZ names ('Financial Services', 'Consumer Cyclical', 'Basic
    Materials', 'Consumer Defensive', 'Communication Services') while
    `sector_momentum_state.sector` carries ETF labels ('Financials', 'Consumer
    Discretionary', …). Only 6 of 11 match directly. Five sectors would have
    shipped a well-formed card with an empty industries list — which reads as
    "no candidates today", not "the join is broken".

    An empty list is a legitimate answer, so the <Val> null contract cannot catch
    it. Only a test that spans every value of the key can.

WHAT IT ASSERTS
    This is a SCHEMA contract, not a data assertion. It checks that every
    configured sector's name vocabulary resolves against the industry table. It
    must fail when the two tables' key vocabularies diverge, and must NOT fail
    merely because a sector has no qualifying names on a given day.

    Skips (does not fail) when the industry table is empty — that is an engine
    outage, a different defect, and failing here would misattribute it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from sector_leaders_service import _sector_aliases  # noqa: E402

CONFIGURED_SECTORS = sorted(
    json.loads((ROOT / "config" / "sector_momentum.json").read_text())["sectors"].values()
)


def _industry_sector_values() -> set[str]:
    from db_adapter import _get_conn
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT sector FROM industry_momentum_state
                WHERE as_of = (SELECT max(as_of) FROM industry_momentum_state)
                  AND sector IS NOT NULL"""
        )
        return {r[0] for r in cur.fetchall()}


def test_all_eleven_sectors_are_configured():
    # Guards the fixture itself: if the config shrinks, the parameterisation
    # below would silently cover fewer keys.
    assert len(CONFIGURED_SECTORS) == 11, CONFIGURED_SECTORS


@pytest.mark.parametrize("sector", CONFIGURED_SECTORS)
def test_sector_key_vocabulary_resolves_against_industry_table(sector):
    """Every configured sector must resolve to a sector value the industry table
    actually uses. This is the exact check that would have caught the Finviz-vs-
    ETF-label mismatch before it shipped."""
    try:
        live = _industry_sector_values()
    except Exception as exc:                                    # pragma: no cover
        pytest.skip(f"industry_momentum_state unreadable: {str(exc)[:120]}")

    if not live:                                                # pragma: no cover
        pytest.skip("industry_momentum_state is empty — engine outage, not a join defect")

    aliases = _sector_aliases(sector)
    matched = [a for a in aliases if a in live]
    assert matched, (
        f"sector '{sector}' resolves to none of the sector values present in "
        f"industry_momentum_state.\n"
        f"  tried aliases : {aliases}\n"
        f"  table has     : {sorted(live)}\n"
        f"Add the missing alias to config/sector_momentum.json -> sector_aliases. "
        f"Without it this sector renders a card with an empty industries list, "
        f"which looks like 'no candidates' rather than a broken join."
    )
