#!/usr/bin/env python3
"""Defense v3 WS-R acceptance: the field guard (complete-or-absent) + short rails."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from defense_recommendations import validate, REQUIRED, CFG  # noqa: E402


def run():
    base = {
        "id": "t-1", "group": "get_into", "title": "T",
        "instruments": [{"symbol": "XLE", "kind": "sector ETF", "note": "n"}],
        "accounts": ["schwab_taxable"], "direction": "long", "size_band": "2-4%",
        "entry_logic": "e", "invalidation": "i",
        "factors": [{"name": "f", "value": 1}], "as_of": "2026-07-18", "mode": "SHADOW",
    }
    assert validate(base) is None
    print("✓ complete card passes")

    # EVERY required field, missing or empty → the card must not render
    for f in REQUIRED:
        broken = dict(base)
        del broken[f]
        assert validate(broken) == f, f"missing {f} not caught"
        empty = dict(base)
        empty[f] = [] if isinstance(base[f], list) else ""
        assert validate(empty) == f, f"empty {f} not caught"
    print(f"✓ all {len(REQUIRED)} required fields guard (missing AND empty)")

    # factor entries must be name+value pairs (values shown, not vibes)
    bad = dict(base)
    bad["factors"] = [{"name": "sector state"}]  # no value
    assert validate(bad) == "factors"
    print("✓ factor without a value rejected")

    # short rails are config, not code
    ts = CFG["taxable_short"]
    assert ts["min_price"] >= 5 and ts["max_stop_distance_pct"] <= 15
    assert ts["max_short_float_pct"] <= 10.0  # anti-squeeze
    assert ts["size_cap_pct_of_book"] <= 2.0  # the hard cap the operator set
    print("✓ short rails present in config (min_price, stop distance, anti-squeeze, 2% cap)")
    print("ALL FIELD-GUARD TESTS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(run())
