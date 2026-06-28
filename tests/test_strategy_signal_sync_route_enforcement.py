#!/usr/bin/env python3
"""P0-6: durable route/actionability overrides loose YAML/fallback in strategy_signal_sync."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from strategy_signal_sync import route_enforced_strategy  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # 1. route=momentum_scalp + GO → momentum_scalp allowed.
    sid, _ = route_enforced_strategy(
        {"route": "momentum_scalp", "route_actionability": "GO", "catalyst_verified": True},
        "momentum_scalp")
    check("route=momentum_scalp/GO → momentum_scalp", sid == "momentum_scalp")

    # 2. route=watch_only → no momentum_scalp signal.
    sid, _ = route_enforced_strategy(
        {"route": "watch_only", "route_actionability": "WAIT"}, "momentum_scalp")
    check("route=watch_only blocks momentum_scalp", sid is None)

    # 3. route=watch_only → no signal at all (even for another proposed strategy).
    sid, _ = route_enforced_strategy({"route": "watch_only"}, "gap_and_go")
    check("route=watch_only blocks any signal", sid is None)

    # 4. route=large_float_social_scout must not create momentum_scalp.
    sid, _ = route_enforced_strategy(
        {"route": "large_float_social_scout", "route_actionability": "MANUAL_REVIEW"}, "momentum_scalp")
    check("scout route blocks momentum_scalp", sid is None)

    # 5. route=large_float_social_scout proposed as itself → allowed (its own signal).
    sid, _ = route_enforced_strategy(
        {"route": "large_float_social_scout", "route_actionability": "MANUAL_REVIEW"},
        "large_float_social_scout")
    check("scout route allows scout signal", sid == "large_float_social_scout")

    # 6. route=meme_squeeze_momentum blocks momentum_scalp.
    sid, _ = route_enforced_strategy(
        {"route": "meme_squeeze_momentum", "route_actionability": "MANUAL_REVIEW"}, "momentum_scalp")
    check("meme route blocks momentum_scalp", sid is None)

    # 7. social source + catalyst_verified false → never momentum_scalp (even without route fields).
    sid, _ = route_enforced_strategy(
        {"source": "social", "catalyst_verified": False}, "momentum_scalp")
    check("social unverified blocks momentum_scalp", sid is None)

    # 8. No durable route → proposed strategy passes through (strict YAML/fallback handles it).
    sid, _ = route_enforced_strategy({"catalyst_verified": True}, "momentum_scalp")
    check("no route → strict yaml/fallback passthrough", sid == "momentum_scalp")

    # 9. route=momentum_scalp but actionability WAIT (not GO) → blocked.
    sid, _ = route_enforced_strategy(
        {"route": "momentum_scalp", "route_actionability": "WAIT"}, "momentum_scalp")
    check("momentum_scalp/WAIT blocks momentum_scalp", sid is None)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
