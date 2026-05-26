"""
scalp_ws_client.py

Helper module for scalping pipelines to push updates to scalp_ws_server.py
and write to a JSON ringbuffer file for HTTP polling fallback.
Called by: continuous_runner.py, social_scalp_scanner.py, trade_ai_news_monitor.py
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PUSH_HOST = "127.0.0.1"
PUSH_PORT = 7779

_PROJECT_ROOT = Path(__file__).parent.parent
_SIGNAL_FILE = _PROJECT_ROOT / "data" / "scalp_live_signals.json"
_MAX_SIGNALS = 50


def _write_signal_file(signal_data: dict):
    """Append signal to JSON ringbuffer file for HTTP polling. Non-fatal."""
    try:
        signals = []
        if _SIGNAL_FILE.exists():
            try:
                signals = json.loads(_SIGNAL_FILE.read_text())
            except Exception:
                signals = []

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": signal_data,
        }
        signals.insert(0, entry)
        signals = signals[:_MAX_SIGNALS]

        _SIGNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SIGNAL_FILE.write_text(json.dumps(signals))
    except Exception as e:
        logger.warning("Signal file write failed: %s", e)


def broadcast_scalp_update(signal_data: dict):
    """Push a scalp signal to WS server + write to polling file.
    Always non-fatal — logs warning on failure, never raises."""
    # Always write to file (polling fallback)
    _write_signal_file(signal_data)

    # Try WS push (may fail if server not running)
    try:
        import websockets
        import asyncio

        payload = json.dumps(signal_data)

        async def _send():
            try:
                async with websockets.connect(
                    f"ws://{PUSH_HOST}:{PUSH_PORT}",
                    open_timeout=2,
                    close_timeout=2
                ) as ws:
                    await ws.send(payload)
            except Exception as e:
                logger.warning("WS push failed for %s: %s", signal_data.get('symbol', '?'), e)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_send())
        except RuntimeError:
            asyncio.run(_send())

    except Exception as e:
        logger.warning("Scalp broadcast skipped for %s: %s", signal_data.get('symbol', '?'), e)
