"""hermes-watchlist-scorer n8n canary (2026-10-21; packet docs/ops/packets/hermes-scorer-canary-20261021/).

One list for every inventory pin that reads stage / live_arg / effect-key counts, as tests/support/
registry_runtime_truth_lane.py does for its lane. LIVE: hermes-watchlist-scorer, a cron row (L451, */15) at stage
canary / dispatch live with allowlist live_arg [] and the cron line's flock lock /tmp/hermes_scorer.lock, under an
operator-REVIEWED health contract. Operator waiver 2026-10-21, verbatim: "push live now" (no 3-market-day shadow wait).
It appends hermes_score_history rows, so it carries a STAGED effect key (cron_claim false, n8n_claim false) that the
cutover arms. Pins: tests/test_hermes_scorer_n8n_canary_20261021.py.
"""
from __future__ import annotations

LIVE = ("hermes-watchlist-scorer",)
