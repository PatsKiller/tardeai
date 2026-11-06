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
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

log = logging.getLogger("tradeai.cio_notification_delivery")

# Legacy raw product dump: "Material CIO product change · …" plus bullet lines
# like "- reentry_added …" / "- opportunity_…" / "- action_…".
_RAW_DUMP_PREFIX = "Material CIO product change ·"
_RAW_DUMP_BULLET_RE = re.compile(r"^-\s*(reentry_|opportunity_|action_)")


def is_raw_product_dump_body(text: str) -> bool:
    """True when body looks like the pre-IIC raw product what_changed dump.

    Detects either the historical subject/title prefix, or ≥2 legacy bullet
    lines of the form ``- reentry_*`` / ``- opportunity_*`` / ``- action_*``.
    """
    body = text or ""
    if _RAW_DUMP_PREFIX in body:
        return True
    hits = sum(1 for line in body.splitlines() if _RAW_DUMP_BULLET_RE.match(line))
    return hits >= 2


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
    """Live CIO Telegram adapter — CIO-only credentials, never Maria/general bot.

    Phase 1: reads TELEGRAM_CIO_BOT_TOKEN + TELEGRAM_CIO_CHAT_IDS only.
    When credentials are missing, delivery is blocked — no silent fallback
    to FakeDeliveryAdapter or general TELEGRAM_BOT_TOKEN.
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        # Prefer explicit args; else CIO-only env (never general token/chat)
        if bot_token is None or chat_id is None:
            try:
                from scripts.lib.cio_telegram_transport import cio_bot_token, cio_chat_ids
            except ImportError:
                from lib.cio_telegram_transport import cio_bot_token, cio_chat_ids  # type: ignore
            bot_token = bot_token if bot_token is not None else cio_bot_token()
            if chat_id is None:
                chats = cio_chat_ids()
                chat_id = chats[0] if chats else ""
                self.chat_ids = chats
            else:
                self.chat_ids = [chat_id] if chat_id else []
        else:
            self.chat_ids = [chat_id] if chat_id else []
        self.bot_token = bot_token or ""
        self.chat_id = (self.chat_ids[0] if self.chat_ids else "") or (chat_id or "")
        self._live = bool(self.bot_token and self.chat_ids)

    def send(self, notification: dict[str, Any]) -> dict[str, Any]:
        """Send a notification via CIO-only Telegram transport."""
        nid = notification.get("notification_id", "unknown")
        body = notification.get("body", "")
        subject = notification.get("subject", "")
        message = f"{subject}\n\n{body}" if subject else body

        # Belt-and-suspenders: never deliver pre-IIC raw product dumps.
        if is_raw_product_dump_body(message) or is_raw_product_dump_body(str(body or "")):
            log.warning(
                "SUPPRESSED_RAW_PRODUCT_DUMP notification_id=%s subject=%s",
                nid,
                (subject or "")[:80],
            )
            return {
                "delivered": False,
                "error": "SUPPRESSED_RAW_PRODUCT_DUMP",
                "reason": "raw_product_dump_body",
                "notification_id": nid,
                "delivery_method": "telegram_cio",
            }

        try:
            from scripts.lib.cio_telegram_transport import send_cio_message, network_interdicted
        except ImportError:
            from lib.cio_telegram_transport import send_cio_message, network_interdicted  # type: ignore

        if network_interdicted():
            return {
                "delivered": False,
                "error": "DELIVERY_INTERDICTED",
                "reason": "pytest_or_CIO_TELEGRAM_INTERDICT",
                "notification_id": nid,
                "delivery_method": "telegram_cio",
            }

        if not self._live:
            log.error(
                "CIO Telegram delivery blocked for %s: CIO credentials not configured "
                "(token=%s, chat_ids=%s)",
                nid,
                "SET" if self.bot_token else "MISSING",
                "SET" if self.chat_ids else "MISSING",
            )
            return {
                "delivered": False,
                "error": "DELIVERY_BLOCKED_CREDENTIALS",
                "reason": "TELEGRAM_CIO_BOT_TOKEN or TELEGRAM_CIO_CHAT_IDS not configured",
                "notification_id": nid,
                "delivery_method": "telegram_cio",
            }

        reply_markup = notification.get("reply_markup")
        if reply_markup is not None and not isinstance(reply_markup, dict):
            reply_markup = None
        raw_parse = notification.get("parse_mode")
        parse_mode = raw_parse if raw_parse in ("HTML", None) else None
        if raw_parse not in ("HTML", None):
            log.warning(
                "Ignoring unsupported parse_mode=%r for notification %s",
                raw_parse,
                nid,
            )
        res = send_cio_message(
            message,
            kind=str(notification.get("message_class") or "cio_advisory"),
            require_live_auth=True,
            reply_markup=reply_markup,
            decision_id=(
                str(notification.get("object_id") or notification.get("decision_id") or "")
                or None
            ),
            parse_mode=parse_mode,
        )
        if res.get("delivered"):
            return {
                "delivered": True,
                "delivery_method": "telegram_cio",
                "message_id": (res.get("message_ids") or [None])[0],
                "delivered_at": datetime.now(timezone.utc).isoformat(),
                "notification_id": nid,
            }
        return {
            "delivered": False,
            "delivery_method": "telegram_cio",
            "error": res.get("reason") or "send_failed",
            "notification_id": nid,
            "telegram_ok": False,
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
        """CIO-only token — never general TELEGRAM_BOT_TOKEN (Phase 1)."""
        try:
            from scripts.lib.cio_telegram_transport import cio_bot_token
        except ImportError:
            from lib.cio_telegram_transport import cio_bot_token  # type: ignore
        return cio_bot_token() or None

    @staticmethod
    def _read_chat_id_from_env() -> Optional[str]:
        """CIO allowlist first chat — never general TELEGRAM_CHAT_ID (Phase 1)."""
        try:
            from scripts.lib.cio_telegram_transport import cio_chat_ids
        except ImportError:
            from lib.cio_telegram_transport import cio_chat_ids  # type: ignore
        chats = cio_chat_ids()
        return chats[0] if chats else None

    def _expire_overdue(self, notifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Expire PENDING notes past ``expires_at``, every class, at most the configured cap per run.

        Until 2026-10-31 the expiry call passed no ``reason`` (``expire()`` requires one), the TypeError was
        swallowed, and nothing ever expired. A failure here is logged, never swallowed silently.
        """
        cap = int(_delivery_config().get("max_expiries_per_run", 0))
        now = datetime.now(timezone.utc)
        out: list[dict[str, Any]] = []
        for notif in notifications:
            if len(out) >= cap:
                break
            if not _is_overdue(notif, now):
                continue
            nid = notif.get("notification_id", "")
            try:
                self.outbox.expire(nid, reason=f"expires_at {notif.get('expires_at')} passed before delivery")
                out.append({"notification_id": nid, "message_class": notif.get("message_class")})
            except ValueError as exc:  # already terminal or claimed by another worker
                log.warning("expire %s refused: %s", nid, exc)
        return out

    def poll_and_deliver(self, max_deliveries: int = 10) -> dict[str, Any]:
        """Poll for pending notifications and deliver them.

        Returns a summary of deliveries.
        """
        # Every PENDING note, not the newest 50: the old default limit was applied before the advisory hold, so 50
        # held advisory notes hid everything older, and nothing ever expired (2026-10-31: 1,208 PENDING, 0 delivered).
        notifications = self.outbox.list_notifications(status="PENDING", limit=None)
        delivered: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        expired = self._expire_overdue(notifications)
        if expired:
            expired_ids = {e["notification_id"] for e in expired}
            notifications = [n for n in notifications if n.get("notification_id") not in expired_ids]

        # 2026-10-08 operator: CIO advisory notes (re-entry notes, CIO advisory actions) wait for the 10:00 / 15:00 /
        # 17:00 advice digest, which delivers them and marks them DELIVERED. They stay PENDING here (nothing lost).
        # Rollback: config/advice_digest.yaml holds.cio_advisory_outbox.
        try:
            try:
                from scripts.lib.advice_digest import hold as _advice_hold
            except ImportError:  # pragma: no cover
                from lib.advice_digest import hold as _advice_hold  # type: ignore
            if _advice_hold("cio_advisory_outbox"):
                notifications = [n for n in notifications if str(n.get("message_class") or "") != "advisory"]
        except Exception:
            pass
        for notif in notifications[:max_deliveries]:
            nid = notif.get("notification_id", "")

            # Expired notes past the per-run expiry cap are skipped now and expired on a later run.
            if _is_overdue(notif, datetime.now(timezone.utc)):
                continue

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
            "expired_count": len(expired),
            "pending_seen": len(notifications),
            "delivered": delivered,
            "failed": failed,
            "mode": self.mode,
            "adapter_live": self.adapter.is_live,
        }


_DELIVERY_CONFIG = Path(__file__).resolve().parents[2] / "config" / "cio_delivery.json"


def _delivery_config() -> dict[str, Any]:
    """config/cio_delivery.json (thresholds live in config, never in code)."""
    try:
        return json.loads(_DELIVERY_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("cio delivery config unreadable (%s); expiry disabled this run", exc)
        return {}


def _is_overdue(notif: dict[str, Any], now: datetime) -> bool:
    raw = notif.get("expires_at")
    if not raw:
        return False
    try:
        exp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < now

