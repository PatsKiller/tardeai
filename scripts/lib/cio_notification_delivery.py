"""
CIO Notification Delivery Worker — Polls outbox for PENDING notifications and delivers them.

P-2.7 component. In shadow mode, uses FakeDeliveryAdapter (no live Telegram).
In live mode (requires AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY), uses real Telegram adapter.

The delivery worker polls the notification outbox, claims PENDING notifications,
delivers through the transport adapter, and records receipts. Never executes trades,
changes risk limits, or performs infrastructure remediation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

log = logging.getLogger("tradeai.cio_notification_delivery")


class DeliveryAdapter(Protocol):
    """Protocol for notification transport adapters."""

    def send(self, notification: dict[str, Any]) -> dict[str, Any]:
        """Send a notification. Returns delivery result."""
        ...

    @property
    def is_live(self) -> bool:
        """Whether this adapter sends real messages."""
        ...


class FakeDeliveryAdapter:
    """Shadow-mode delivery adapter — logs but never sends real messages."""

    def send(self, notification: dict[str, Any]) -> dict[str, Any]:
        nid = notification.get("notification_id", "unknown")
        channel = notification.get("channel_targets", ["unknown"])[0]
        log.info("Shadow delivery: notification %s to %s (not sent)", nid, channel)
        return {
            "delivered": True,
            "delivery_method": "shadow",
            "delivered_at": datetime.now(timezone.utc).isoformat(),
            "notification_id": nid,
        }

    @property
    def is_live(self) -> bool:
        return False


class RealTelegramAdapter:
    """Live Telegram adapter — sends real messages. Requires authorization.

    When credentials are missing, delivery is blocked — no silent fallback
    to FakeDeliveryAdapter.  FakeDeliveryAdapter exists only for explicit
    shadow/test mode (set mode="shadow" on CIONotificationDeliveryWorker).
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or ""
        self.chat_id = chat_id or ""
        self._live = bool(bot_token and chat_id)

    def send(self, notification: dict[str, Any]) -> dict[str, Any]:
        """Send a notification via Telegram.

        Returns `delivered=False` with `DELIVERY_BLOCKED_CREDENTIALS` when
        bot_token or chat_id is missing.  Never silently falls back to fake
        delivery.
        """
        nid = notification.get("notification_id", "unknown")

        if not self._live:
            log.error(
                "Telegram delivery blocked for %s: credentials not configured "
                "(token=%s, chat_id=%s)",
                nid,
                "SET" if self.bot_token else "MISSING",
                "SET" if self.chat_id else "MISSING",
            )
            return {
                "delivered": False,
                "error": "DELIVERY_BLOCKED_CREDENTIALS",
                "reason": "Telegram bot_token or chat_id not configured",
                "notification_id": nid,
                "delivery_method": "telegram",
            }

        # Construct and send message via Telegram Bot API
        body = notification.get("body", "")
        subject = notification.get("subject", "")

        try:
            import urllib.request
            import urllib.error

            message = f"{subject}\n\n{body}" if subject else body
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = json.dumps({
                "chat_id": self.chat_id,
                "text": message[:4096],  # Telegram limit
                "parse_mode": "HTML",
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_data = json.loads(resp.read().decode())
                if resp_data.get("ok"):
                    return {
                        "delivered": True,
                        "delivery_method": "telegram",
                        "message_id": resp_data.get("result", {}).get("message_id"),
                        "delivered_at": datetime.now(timezone.utc).isoformat(),
                        "notification_id": nid,
                    }
                else:
                    error_msg = resp_data.get("description", str(resp_data))
                    log.error("Telegram API error for %s: %s", nid, error_msg)
                    return {
                        "delivered": False,
                        "delivery_method": "telegram",
                        "error": error_msg,
                        "notification_id": nid,
                        "telegram_ok": False,
                    }

        except urllib.error.HTTPError as e:
            log.error("Telegram HTTP %s for %s: %s", e.code, nid, e.reason)
            return {
                "delivered": False,
                "delivery_method": "telegram",
                "error": f"HTTP {e.code}: {e.reason}",
                "notification_id": nid,
            }
        except Exception as e:
            log.exception("Telegram delivery error for %s", nid)
            return {
                "delivered": False,
                "delivery_method": "telegram",
                "error": str(e),
                "notification_id": nid,
            }

    @property
    def is_live(self) -> bool:
        return self._live


class CIONotificationDeliveryWorker:
    """Polls the notification outbox and delivers pending notifications.

    In shadow mode: uses FakeDeliveryAdapter (no real messages).
    In live mode: uses RealTelegramAdapter (requires authorization).
    """

    def __init__(
        self,
        notification_outbox: Any,
        adapter: Optional[DeliveryAdapter] = None,
        mode: str = "shadow",
    ):
        self.outbox = notification_outbox
        self.mode = mode

        if adapter is not None:
            self.adapter = adapter
        elif mode == "live":
            bot_token = self._read_token_from_env()
            chat_id = self._read_chat_id_from_env()
            self.adapter = RealTelegramAdapter(bot_token=bot_token, chat_id=chat_id)
        else:
            self.adapter = FakeDeliveryAdapter()

    @staticmethod
    def _read_token_from_env() -> Optional[str]:
        import os
        return os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TRADE_AI_TELEGRAM_TOKEN")

    @staticmethod
    def _read_chat_id_from_env() -> Optional[str]:
        import os
        return os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("TRADE_AI_CHAT_ID")

    def poll_and_deliver(self, max_deliveries: int = 10) -> dict[str, Any]:
        """Poll for pending notifications and deliver them.

        Returns a summary of deliveries.
        """
        notifications = self.outbox.list_notifications(status="PENDING")
        delivered: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        for notif in notifications[:max_deliveries]:
            nid = notif.get("notification_id", "")

            # Skip expired notifications
            expires_at = notif.get("expires_at")
            if expires_at:
                try:
                    exp_dt = datetime.fromisoformat(expires_at)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    if exp_dt < datetime.now(timezone.utc):
                        log.info("Notification %s expired, skipping", nid)
                        self.outbox.expire(nid) if hasattr(self.outbox, "expire") else None
                        continue
                except (ValueError, TypeError):
                    pass

            # Dedupe check — if already delivered, skip
            current = self.outbox.get_notification(nid) if hasattr(self.outbox, "get_notification") else None
            if current and current.get("current_status") in ("DELIVERED", "DEAD_LETTERED"):
                continue

            # Claim
            try:
                claim_token = str(uuid.uuid4())
                channel = notif.get("channel_targets", ["telegram"])[0]
                claim_result = self.outbox.claim(
                    nid, channel, "cio_delivery_worker", claim_token
                )
            except ValueError:
                continue

            # Deliver
            try:
                result = self.adapter.send(notif)
                if result.get("delivered"):
                    channel = notif.get("channel_targets", ["telegram"])[0]
                    ext_id = str(result.get("message_id", ""))
                    receipt_hash = hashlib.sha256(
                        f"{nid}:{channel}:{datetime.now(timezone.utc).isoformat()}".encode()
                    ).hexdigest()
                    self.outbox.confirm(
                        nid, channel, claim_token, "cio_delivery_worker",
                        ext_id, receipt_hash,
                    )
                    delivered.append(result)
                else:
                    log.warning("Delivery failed for %s: %s", nid, result.get("error"))
                    failed.append({"notification_id": nid, "error": result.get("error")})
            except Exception as e:
                log.exception("Delivery exception for %s", nid)
                failed.append({"notification_id": nid, "error": str(e)})

        return {
            "delivered_count": len(delivered),
            "failed_count": len(failed),
            "delivered": delivered,
            "failed": failed,
            "mode": self.mode,
            "adapter_live": self.adapter.is_live,
        }
