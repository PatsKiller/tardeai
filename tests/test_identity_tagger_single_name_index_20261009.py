"""The inbound tagger must read the same company-name index the sweep refreshes.

2026-10-09: CI shard 7 failed test_sentinel_one_spaced_and_lowercase_bind_guid on four PRs.
inbound_identity_tagger imported `lib.company_name_index` while every refresher (the sweep, the
tests) uses `scripts.lib.company_name_index` -- two module objects, two _build() caches. An
earlier test in the chunk cached the bare copy with no instruments; refresh() cleared only the
other copy, so tag_inbound kept reading the stale index. Locally the stale copy happened to hold
the live instrument sweep (gitignored), which is why it never reproduced on the host.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _instruments(path: Path, instruments: dict) -> None:
    from scripts.lib.schwab_instrument_evidence import SCHEMA

    path.write_text(json.dumps({"schema": SCHEMA, "instruments": instruments}), encoding="utf-8")


def test_tagger_follows_a_scripts_lib_refresh_even_after_the_bare_copy_was_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_HOUSE_NAMES_DB", "0")
    monkeypatch.delenv("TRADEAI_IPO_LOCKUPS", raising=False)

    # An earlier caller in the same process cached the bare `lib.` copy with an empty sweep.
    empty = tmp_path / "empty.json"
    _instruments(empty, {})
    monkeypatch.setenv("TRADEAI_SCHWAB_INSTRUMENT_EVIDENCE", str(empty))
    import lib.company_name_index as bare

    bare.refresh()
    bare._build()

    # The sweep lands and is refreshed the documented way.
    full = tmp_path / "full.json"
    _instruments(full, {"S": {"description": "SENTINELONE INC A", "identifiers": {"cusip": "T-S1"}}})
    monkeypatch.setenv("TRADEAI_SCHWAB_INSTRUMENT_EVIDENCE", str(full))
    from scripts.lib import company_name_index as cni
    from scripts.lib.inbound_identity_tagger import tag_inbound

    cni.refresh()
    reg = {
        "entities": {"s-s": {"ticker_alias": "S", "aliases": ["S"], "subject_guid": "g-s",
                             "security_guid": "g-s", "issuer_guid": "i-s",
                             "identity_status": "CONFIRMED"}},
        "by_symbol": {"S": "s-s"},
    }
    try:
        tag = tag_inbound("give me perspective on sentinel one", registry=reg)
        assert [r["symbol"] for r in tag["resolved"]] == ["S"], tag
    finally:
        cni.refresh()
        bare.refresh()
