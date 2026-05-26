"""
scalp_ws_server.py

Standalone WebSocket server for real-time scalping signal broadcast.
Called by: systemd service / manual launch
Consumers: command-center-v2 ScalpLiveFeed, future OpenClaw scalping dashboard
Producers: continuous_runner.py, social_scalp_scanner.py, trade_ai_news_monitor.py
           push via scalp_ws_client.broadcast()
"""

import sys
import json
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import websockets

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [scalp_ws] %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

WS_HOST = "0.0.0.0"
WS_PORT = 7778

# Internal push port — producers connect here to send updates
PUSH_HOST = "127.0.0.1"
PUSH_PORT = 7779

connected_clients: set = set()


async def client_handler(websocket):
    """Handle a frontend WebSocket client connection."""
    client_id = websocket.remote_address
    logger.info(f"Client connected: {client_id}")
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            if message.strip() == "ping":
                await websocket.send(json.dumps({
                    "type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }))
    except websockets.ConnectionClosed:
        pass
    except Exception as e:
        logger.warning(f"Client {client_id} error: {e}")
    finally:
        connected_clients.discard(websocket)
        logger.info(f"Client disconnected: {client_id}")


async def broadcast(payload: str):
    """Send payload to all connected frontend clients. Non-fatal per client."""
    if not connected_clients:
        return
    dead = []
    for client in list(connected_clients):
        try:
            await client.send(payload)
        except Exception:
            dead.append(client)
    for d in dead:
        connected_clients.discard(d)


async def push_handler(websocket):
    """Handle internal push connections from scalping pipelines.
    Producers send JSON payloads here; we broadcast to all frontend clients."""
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                payload = json.dumps({
                    "type": "scalping_update",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": data
                })
                await broadcast(payload)
                symbol = data.get("symbol", "unknown")
                logger.info(f"Broadcast scalp update: {symbol}")
            except json.JSONDecodeError:
                logger.warning("Push received non-JSON message, ignoring")
    except websockets.ConnectionClosed:
        pass
    except Exception as e:
        logger.warning(f"Push handler error: {e}")


async def main():
    """Start both servers: frontend WS on 7778, internal push on 7779."""
    logger.info(f"Starting scalp WS server — clients on :{WS_PORT}, push on :{PUSH_PORT}")

    async with websockets.serve(client_handler, WS_HOST, WS_PORT):
        async with websockets.serve(push_handler, PUSH_HOST, PUSH_PORT):
            logger.info("Scalp WS server running")
            await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scalp WS server stopped")
