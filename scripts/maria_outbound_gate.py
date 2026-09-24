#!/usr/bin/env python3
"""Maria outbound gate bridge — stdin JSON → stdout JSON.

Called by the OpenClaw gateway plugin ``tradeai-maria-gate`` on every Maria
``message_sending`` event. Input::

    {"content": "...", "sessionKey": "agent:maria:…", "channel": "telegram",
     "to": "8797974247", "mode": "observe" | "live"}

Output::

    {"content": "...", "cancel": false, "cancel_reason": null,
     "changed": true, "mode": "live", "receipt": {...}}

Any failure prints ``{"error": "..."}`` and exits 1; the plugin then delivers
the original text with an "unverified" line in live mode (never a silent drop).

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        from scripts.lib.env_bootstrap import load_env  # noqa: PLC0415

        load_env()
        from scripts.lib import comms_editor as CE  # noqa: PLC0415
        from scripts.lib.maria_outbound_gate import handle  # noqa: PLC0415

        out = handle(payload, db_query=CE.default_db_query)
    except Exception as exc:  # noqa: BLE001 — the plugin owns the fallback
        sys.stdout.write(json.dumps({"error": f"{type(exc).__name__}: {str(exc)[:300]}"}) + "\n")
        return 1
    sys.stdout.write(json.dumps(out, default=str, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
