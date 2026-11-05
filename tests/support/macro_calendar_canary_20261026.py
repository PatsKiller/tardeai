"""macro-calendar-refresh shadow -> canary (2026-10-26; operator decision, verbatim: "1. macro-calendar job: switch
it from test mode to live … yes.").

One list for every inventory pin that reads stage / live_arg / effect-key scope (precedent
tests/support/cio_prospect_canary_20261025.py). n8n-native dispatcher row (no cron line, no unit), dispatch live,
allowlist live_arg [] (the script default): a live run atomically REWRITES data/runtime/macro_calendar.json and the
receipt (overwrite-only, never an append, send or model call), so there is no cron side to fence and no effect key.
Pins: tests/test_macro_calendar_20261021.py.
"""

from __future__ import annotations

LIVE = ("macro-calendar-refresh",)
#: live_arg is the script default ([]), so nothing joins N8N_NATIVE_CANARY_LIVE_ARG (non-default live runs only).
LIVE_ARG: dict[str, list[str]] = {}
