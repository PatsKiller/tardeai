"""cio-prospect-shadow shadow -> canary (2026-10-25; operator directive, verbatim: "You should turn on everything.
It shouldn't need me to turn on anything. Get it working.").

One list for every inventory pin that reads stage / live_arg / effect-key scope (precedent
tests/support/release_train_h0.py). n8n-native dispatcher row (no cron line, no unit), dispatch live,
allowlist live_arg ["--write-shadow"]: a live run atomically REWRITES data/cio/cio_prospect_shadow.json, the
comparison and the receipt (overwrite-only, never an append, send or model call), so there is no cron side to fence
and no effect key. Pins: tests/test_cio_prospect_shadow_readonly_20261023.py.
"""

from __future__ import annotations

LIVE = ("cio-prospect-shadow",)
LIVE_ARG = {"cio-prospect-shadow": ["--write-shadow"]}
