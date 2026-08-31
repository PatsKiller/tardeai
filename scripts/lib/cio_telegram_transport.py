"""CIO-only Telegram transport — single outbound path for Alex/CIO messages.

HARD RULES (Phase 1 notification containment):
  * Credentials ONLY from TELEGRAM_CIO_BOT_TOKEN + TELEGRAM_CIO_CHAT_IDS
    (or TELEGRAM_CIO_ALLOWLIST). Never TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.
  * Never send under pytest (PYTEST_CURRENT_TEST) or when
    CIO_TELEGRAM_INTERDICT=1 / ENABLE_TELEGRAM=false.
  * Live send requires AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1 AND mode live.
  * Semantic dedupe for thesis / advisory bodies (short window).
  * Materiality gate for low-signal thesis noise.

Authority: READ_ONLY_ADVISORY. No broker/order/stop/2FA.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("tradeai.cio_telegram_transport")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEDUPE_PATH = PROJECT_ROOT / "data" / "cio" / "cio_outbound_dedupe.jsonl"
DEDUPE_TTL_SECONDS = 6 * 3600  # same semantic body within 6h → suppress

# Env names — documented; never log values
ENV_CIO_TOKEN = "TELEGRAM_CIO_BOT_TOKEN"
ENV_CIO_CHATS = "TELEGRAM_CIO_CHAT_IDS"  # or TELEGRAM_CIO_ALLOWLIST
ENV_AUTHORIZE_LIVE = "AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY"
ENV_INTERDICT = "CIO_TELEGRAM_INTERDICT"
ENV_THESIS_NOTIFY = "CIO_THESIS_TELEGRAM"  # 0=off (default), 1=allow material only


def _env(k: str, default: str = "") -> str:
    return (os.environ.get(k) or default).strip()


def under_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("PYTEST_VERSION"))


def network_interdicted() -> bool:
    """True when any live Telegram HTTP must not run."""
    if under_pytest():
        return True
    if _env(ENV_INTERDICT, "0").lower() in ("1", "true", "yes", "on"):
        return True
    if _env("ENABLE_TELEGRAM", "true").lower() in ("0", "false", "no", "off"):
        return True
    # CI / explicit shadow
    if _env("CI", "").lower() in ("1", "true") and _env(ENV_AUTHORIZE_LIVE) != "1":
        return True
    return False


def live_authorized() -> bool:
    return _env(ENV_AUTHORIZE_LIVE) == "1"


# Delivery-mode classification (P1-6). This is a flag readout, NOT an isolation proof.
MODE_INTERDICTED = "INTERDICTED"
MODE_PREPARE_ONLY = "PREPARE_ONLY"
MODE_CIO_ONLY_LIVE = "CIO_ONLY_LIVE"


def cio_delivery_mode() -> str:
    """Classify intended CIO Telegram delivery from process flags.

    Returns one of: INTERDICTED | PREPARE_ONLY | CIO_ONLY_LIVE.

    Inputs: CIO_TELEGRAM_INTERDICT, ENABLE_TELEGRAM, AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY.
    Pytest is treated as INTERDICTED so unit tests cannot open a live path.

    INTERDICTED is not an isolation-pass. Isolation-pass is a *measured* canary
    proof (CIO-only token/chat, general_sends==0). INTERDICTED != isolation-pass
    and does not by itself mean live delivery is impossible in every process —
    another process with different flags can still be CIO_ONLY_LIVE.
    CIO_ONLY_LIVE is the only mode that may perform live CIO delivery.
    This helper never mutates env.
    """
    if under_pytest():
        return MODE_INTERDICTED
    if _env(ENV_INTERDICT, "0").lower() in ("1", "true", "yes", "on"):
        return MODE_INTERDICTED
    if _env("ENABLE_TELEGRAM", "true").lower() in ("0", "false", "no", "off"):
        return MODE_INTERDICTED
    if not live_authorized():
        return MODE_PREPARE_ONLY
    return MODE_CIO_ONLY_LIVE


def cio_bot_token() -> str:
    return _env(ENV_CIO_TOKEN)


def cio_chat_ids() -> list[str]:
    """CIO allowlist only — never fall back to general TELEGRAM_CHAT_ID."""
    raw = _env(ENV_CIO_CHATS) or _env("TELEGRAM_CIO_ALLOWLIST")
    return [c.strip() for c in raw.split(",") if c.strip()]


def credentials_ready() -> bool:
    return bool(cio_bot_token() and cio_chat_ids())


def semantic_body_key(body: str, *, kind: str = "cio") -> str:
    """Normalize body for semantic dedupe (strip whitespace/case noise)."""
    norm = " ".join((body or "").strip().lower().split())
    # Drop version pins that change without changing meaning for fixtures
    for noise in ("@v1", "@v2", "@v3", "@v4", "@v5"):
        norm = norm.replace(noise, "")
    digest = hashlib.sha256(f"{kind}|{norm}".encode()).hexdigest()[:32]
    return digest


def _dedupe_path() -> Path:
    return Path(_env("CIO_OUTBOUND_DEDUPE_PATH", str(DEFAULT_DEDUPE_PATH)))


def was_recently_sent(dedupe_key: str, *, ttl: int = DEDUPE_TTL_SECONDS) -> bool:
    path = _dedupe_path()
    if not path.is_file() or not dedupe_key:
        return False
    now = time.time()
    try:
        # B4, 2026-08-31: this was `.splitlines()[-500:]`. The file stood at 429
        # lines -- 71 sends from silently dropping its own history, at which
        # point a key older than the last 500 lines but younger than the TTL
        # would read as "never sent" and a duplicate would go out with nothing
        # reporting it. The file is now bounded by TTL on write (see mark_sent),
        # so reading all of it is bounded too, and correctness no longer depends
        # on a line count that has no relationship to the window.
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("key") == dedupe_key and (now - float(rec.get("ts", 0))) < ttl:
                return True
    except OSError:
        return False
    return False


def mark_sent(dedupe_key: str, *, meta: Optional[dict] = None) -> None:
    path = _dedupe_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "key": dedupe_key,
            "ts": time.time(),
            "at": datetime.now(timezone.utc).isoformat(),
            "meta": meta or {},
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        _prune_expired(path)
    except OSError as e:
        log.warning("dedupe mark failed: %s", type(e).__name__)



def _prune_expired(path, *, ttl: int = DEDUPE_TTL_SECONDS) -> None:
    """Drop entries older than the TTL so the file stays bounded by time.

    B4. Bounding by a line count is what created the hazard: 500 lines has no
    relationship to the dedupe window, so at any send rate high enough the oldest
    still-valid key falls off the end and a duplicate goes out silently. Bounding
    by the same TTL the reader uses makes the two agree by construction.

    Best-effort and non-fatal: a prune that fails leaves a longer file, which is
    safe. A prune that failed silently AND shortened the file would not be.
    """
    try:
        cutoff = time.time() - ttl
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        kept = []
        for line in lines:
            if not line.strip():
                continue
            try:
                if float(json.loads(line).get("ts", 0)) >= cutoff:
                    kept.append(line)
            except (json.JSONDecodeError, TypeError, ValueError):
                kept.append(line)   # unparseable: keep, never silently discard
        if len(kept) != len(lines):
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            tmp.replace(path)
    except OSError as e:
        log.warning("dedupe prune skipped: %s", type(e).__name__)


def thesis_notify_enabled() -> bool:
    """Thesis version bumps do NOT proactively Telegram by default (Phase 1)."""
    return _env(ENV_THESIS_NOTIFY, "0").lower() in ("1", "true", "yes", "on")


def is_material_thesis_summary(summary: str) -> bool:
    """Materiality gate: reject empty/stub/test fixture noise."""
    s = (summary or "").strip()
    low = s.lower()
    # Explicit Phase 1 fixtures / production noise that must never page the operator
    banned_exact = {
        "a", "b", "des", "test", "ok", "update", "updated",
        "living desk thesis", "fixture a", "fixture b", "test thesis",
        "pytest", "unit test", "spam", "cio thesis updated",
    }
    if low in banned_exact:
        return False
    if low.startswith("living desk thesis"):
        return False
    if low in {"a", "b"} or low.startswith("fixture "):
        return False
    # Truncated production noise: "des" alone or near-empty
    if len(s) < 24:
        return False
    if len(s.replace(".", "").replace("-", "").replace(" ", "").strip()) < 16:
        return False
    return True


def send_cio_message(
    body: str,
    *,
    subject: str = "",
    kind: str = "cio_advisory",
    require_live_auth: bool = True,
    force: bool = False,
    dedupe_key: Optional[str] = None,
    decision_id: Optional[str] = None,
    reply_markup: Optional[dict[str, Any]] = None,
    parse_mode: Optional[str] = None,
) -> dict[str, Any]:
    """Send via CIO-only bot/allowlist. Never uses general Maria credentials.

    Phase 9: optional `dedupe_key` / `decision_id` for decision-state dedupe
    (preferred over body-only fingerprint when provided).

    Optional `parse_mode` (e.g. ``\"HTML\"``) is passed through to the low-level
    transport. Default ``None`` keeps plain-text behavior for legacy callers
    (Markdown would eat underscores in ``dec_…`` / ``ACT_NOW``).

    Returns a structured result; never raises for delivery failures.
    """
    text = f"{subject}\n\n{body}".strip() if subject else (body or "").strip()
    result: dict[str, Any] = {
        "delivered": False,
        "channel": "telegram_cio",
        "kind": kind,
        "interdicted": False,
        "deduped": False,
        "reason": "",
        "decision_id": decision_id,
    }

    if not text:
        result["reason"] = "empty_body"
        return result

    if network_interdicted() and not force:
        result["interdicted"] = True
        result["reason"] = "network_interdicted_pytest_or_flag"
        log.info("CIO telegram interdicted (%s): %s", result["reason"], text[:80])
        return result

    if require_live_auth and not live_authorized() and not force:
        result["interdicted"] = True
        result["reason"] = "live_not_authorized"
        return result

    if not credentials_ready():
        result["reason"] = "cio_credentials_missing"
        log.error(
            "CIO telegram blocked: token=%s chats=%s",
            "SET" if cio_bot_token() else "MISSING",
            "SET" if cio_chat_ids() else "MISSING",
        )
        return result

    dkey = dedupe_key or semantic_body_key(text, kind=kind)
    result["dedupe_key"] = dkey
    if was_recently_sent(dkey) and not force:
        result["deduped"] = True
        result["reason"] = "semantic_dedupe"
        return result

    # Actual HTTP — only via low-level transport with CIO token
    try:
        # Import late; interdiction for pytest also patches this in tests
        from telegram_transport import send_message
    except ImportError:
        try:
            from scripts.telegram_transport import send_message  # type: ignore
        except ImportError:
            result["reason"] = "transport_import_failed"
            return result

    token = cio_bot_token()
    ok_any = False
    errors: list[str] = []
    message_ids: list[Any] = []
    for cid in cio_chat_ids():
        try:
            # Default plain text: Markdown parse_mode eats underscores in
            # dec_… / ACT_NOW. Callers may opt into HTML for IIC cards.
            resp = send_message(
                token=token, chat_id=cid, text=text[:4000],
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            if resp.get("ok"):
                ok_any = True
                mid = (resp.get("response") or {}).get("result", {}).get("message_id")
                if mid is not None:
                    message_ids.append(mid)
            else:
                errors.append(f"chat={cid}:status={resp.get('status_code')}")
        except Exception as e:
            errors.append(f"chat={cid}:{type(e).__name__}")

    if ok_any:
        mark_sent(dkey, meta={"kind": kind, "decision_id": decision_id})
        result["delivered"] = True
        result["reason"] = "sent"
        result["message_ids"] = message_ids
    else:
        result["reason"] = "send_failed"
        result["errors"] = errors[:5]
    return result


def notify_thesis_published(
    thesis_id: str,
    version: int,
    summary: str,
) -> dict[str, Any]:
    """Thesis publish hook: OFF by default; material + CIO-only when enabled.

    Persistence must never depend on this. Never uses general send_telegram.
    """
    out: dict[str, Any] = {
        "attempted": False,
        "delivered": False,
        "reason": "",
        "thesis_id": thesis_id,
        "version": version,
    }
    if not thesis_notify_enabled():
        out["reason"] = "thesis_telegram_disabled_default"
        return out
    if not is_material_thesis_summary(summary):
        out["reason"] = "not_material"
        return out
    body = (summary or "").strip().replace("\n", " ")[:240]
    msg = f"🧠 CIO thesis updated — {thesis_id}@v{version}\n{body}"
    out["attempted"] = True
    res = send_cio_message(msg, kind="cio_thesis", require_live_auth=True)
    out.update({k: res.get(k) for k in (
        "delivered", "reason", "interdicted", "deduped", "dedupe_key",
    ) if k in res})
    return out
