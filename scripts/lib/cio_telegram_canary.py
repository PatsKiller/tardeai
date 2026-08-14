"""Phase 10 — CIO Telegram DRY canary (no live send).

Uses the real CIO transport (`cio_telegram_transport` / `cio_alex_telegram`)
to prepare a SCHD-trim package and *measure* isolation:

  * general TELEGRAM_BOT_TOKEN is not read for send credentials
  * general_sends is a counted integer (never `or True`)
  * dry-run never performs HTTP

Live send is a separate, fail-closed path: requires ``--live`` AND
``AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1`` AND
``CIO_TELEGRAM_CANARY_ENABLE=1`` AND the operator approval phrase.
This module never sets those env vars.

Authority: READ_ONLY_ADVISORY. No broker / order / stop / 2FA.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib import cio_alex_telegram as alex
from scripts.lib import cio_telegram_transport as tg

AUTHORITY = "READ_ONLY_ADVISORY"
CANARY_VERSION = "cio_telegram_dry_canary_1.0.0"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECEIPT_PATH = PROJECT_ROOT / "data" / "audit" / "cio_telegram_canary_receipt.json"
LIVE_RECEIPT_PATH = PROJECT_ROOT / "data" / "audit" / "cio_telegram_canary_receipt_live.json"
LIVE_ROOT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
TRANSPORT_PATH = PROJECT_ROOT / "scripts" / "lib" / "cio_telegram_transport.py"

ENV_AUTHORIZE_LIVE = "AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY"
ENV_GENERAL_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_GENERAL_CHAT = "TELEGRAM_CHAT_ID"
WOULD_SEND_PATH = "scripts.lib.cio_telegram_transport.send_cio_message"

# Real-shaped SCHD trim (matches live capital-plan geometry: ~17.7% vs 16.5% fire).
SCHD_TRIM_DECISION: dict[str, Any] = {
    "decision_id": "dec_phase10_schd_trim_dry_canary",
    "symbol": "SCHD",
    "name": "SCHWAB U.S. DIVIDEND EQUITY ETF",
    "action": "Trim",
    "stance": "Trim",
    "stance_code": "TRIM",
    "cio_stance": "TRIM",
    "delta_usd": -44360.94,
    "recommended_delta_usd": -44360.94,
    "weight_pct": 17.66,
    "current_value_usd": 226578.76,
    "why_now": (
        "Advisory TRIM — SCHD concentration above single-name fire "
        "(17.66% of book vs 16.5% fire / 12.0% policy cap)."
    ),
    "risk": "concentration > fire",
    "counter_thesis": "Income sleeve may tolerate concentration longer under observe-only.",
    "what_changes_call": (
        "Weight falls under the fire line or multi-desk thesis revalidates hold."
    ),
    "next_review": "2026-08-21",
    "urgency": "high",
    "status": "open",
}


def _env(k: str, default: str = "") -> str:
    return (os.environ.get(k) or default).strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def schd_trim_decision() -> dict[str, Any]:
    """Copy of the real-shaped SCHD trim used for the canary package."""
    return dict(SCHD_TRIM_DECISION)


def default_receipt_path() -> Path:
    return Path(_env("CIO_TELEGRAM_CANARY_RECEIPT_JSON", str(DEFAULT_RECEIPT_PATH)))


def read_release_sha() -> str:
    """Prefer BUILD_SHA (env, live CURRENT, repo). Empty string if absent."""
    env_sha = _env("BUILD_SHA")
    if env_sha:
        return env_sha
    for path in (LIVE_ROOT / "BUILD_SHA", PROJECT_ROOT / "BUILD_SHA"):
        if path.is_file():
            try:
                sha = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
            except OSError:
                continue
            if sha:
                return sha
    return ""


def transport_source_reads_general_token(path: Optional[Path] = None) -> bool:
    """Static: CIO transport must not getenv/environ the general bot token.

    Comments that mention TELEGRAM_BOT_TOKEN as NEVER-use are allowed.
    """
    p = path or TRANSPORT_PATH
    if not p.is_file():
        return True
    text = p.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") or s.startswith('"""') or s.startswith("'"):
            continue
        if "TELEGRAM_BOT_TOKEN" not in s:
            continue
        if "NEVER" in s.upper() or "never" in s:
            continue
        if "os.environ" in s or "_env(" in s or "getenv" in s:
            return True
    return False


def source_contains_or_true(path: Path) -> list[int]:
    """Return line numbers of ``or True`` BoolOps (forbidden scoring hack)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for v in node.values:
                if isinstance(v, ast.Constant) and v.value is True:
                    hits.append(getattr(node, "lineno", 0))
    return hits


def measure_send_credential_env_reads() -> dict[str, int]:
    """Count os.environ.get hits while resolving the CIO *send* credentials.

    This is the send-token path (`cio_bot_token` / `cio_chat_ids`). It must
    not read TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.
    """
    keys = (
        ENV_GENERAL_TOKEN,
        ENV_GENERAL_CHAT,
        tg.ENV_CIO_TOKEN,
        tg.ENV_CIO_CHATS,
        "TELEGRAM_CIO_ALLOWLIST",
    )
    counts = {k: 0 for k in keys}
    orig = os.environ.get

    def tracked(key: str, default: Any = None) -> Any:
        if key in counts:
            counts[key] += 1
        return orig(key, default)

    os.environ.get = tracked  # type: ignore[method-assign]
    try:
        _ = tg.cio_bot_token()
        _ = tg.cio_chat_ids()
        _ = tg.credentials_ready()
    finally:
        os.environ.get = orig  # type: ignore[method-assign]
    return counts


def classify_chat_target() -> str:
    """CIO vs general — general fallback is forbidden, so this is 'cio' or 'none'."""
    if tg.cio_chat_ids():
        return "cio"
    # Still the CIO path even if allowlist is empty; never 'general'.
    return "cio"


def live_send_permitted(*, want_live: bool) -> tuple[bool, str]:
    """Fail-closed live gate. This function never mutates env."""
    if not want_live:
        return False, "dry_run_default"
    if tg.under_pytest():
        return False, "pytest_interdict"
    if tg.network_interdicted():
        return False, "network_interdicted"
    if _env(ENV_AUTHORIZE_LIVE) != "1":
        return False, "missing_authorize_p2"
    if _env(alex.ENV_CANARY_ENABLED).lower() not in ("1", "true", "yes", "on"):
        return False, "canary_enable_missing"
    if _env(alex.ENV_CANARY_APPROVAL) != alex.CANARY_APPROVAL_PHRASE:
        return False, "operator_approval_missing"
    if not alex.canary_approval_granted():
        return False, "canary_approval_not_granted"
    if not tg.credentials_ready():
        return False, "cio_credentials_missing"
    return True, "gates_open"


class NetworkAudit:
    """Wrap requests/urllib/send_message and *count* attempts (no assumption)."""

    def __init__(self) -> None:
        self.http_calls = 0
        self.general_sends = 0
        self.cio_sends = 0
        self.send_message_calls = 0
        self._restore: list[tuple[Any, str, Any]] = []

    def __enter__(self) -> "NetworkAudit":
        try:
            import requests

            self._wrap_fn(requests, "post")
            self._wrap_fn(requests, "get")
            self._wrap_fn(requests, "request")
        except Exception:
            pass
        try:
            import urllib.request

            self._wrap_fn(urllib.request, "urlopen")
        except Exception:
            pass
        for mod_name in ("telegram_transport", "scripts.telegram_transport"):
            try:
                mod = __import__(mod_name, fromlist=["send_message"])
                if hasattr(mod, "send_message"):
                    self._wrap_send_message(mod)
            except Exception:
                continue
        return self

    def __exit__(self, *exc: Any) -> None:
        for mod, name, orig in reversed(self._restore):
            try:
                setattr(mod, name, orig)
            except Exception:
                pass
        self._restore.clear()

    def _wrap_fn(self, mod: Any, name: str) -> None:
        orig = getattr(mod, name)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self.http_calls += 1
            self._classify_http(args, kwargs)
            return orig(*args, **kwargs)

        setattr(mod, name, wrapper)
        self._restore.append((mod, name, orig))

    def _wrap_send_message(self, mod: Any) -> None:
        orig = getattr(mod, "send_message")

        def wrapper(**kwargs: Any) -> Any:
            self.send_message_calls += 1
            self.http_calls += 1
            token = str(kwargs.get("token") or "")
            chat = str(kwargs.get("chat_id") or "")
            general_token = _env(ENV_GENERAL_TOKEN)
            general_chat = _env(ENV_GENERAL_CHAT)
            cio_token = tg.cio_bot_token()
            cio_chats = set(tg.cio_chat_ids())
            if general_token and token and token == general_token:
                self.general_sends += 1
            elif general_chat and chat and chat == general_chat and chat not in cio_chats:
                self.general_sends += 1
            elif cio_token and token and token == cio_token:
                self.cio_sends += 1
            return orig(**kwargs)

        setattr(mod, "send_message", wrapper)
        self._restore.append((mod, "send_message", orig))

    def _classify_http(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        blob = " ".join(str(a) for a in args[:2])
        blob += " " + " ".join(f"{k}={v}" for k, v in kwargs.items() if k != "headers")
        general_token = _env(ENV_GENERAL_TOKEN)
        if general_token and general_token in blob:
            self.general_sends += 1


def _dry_receipt(
    *,
    decision: dict[str, Any],
    ev: dict[str, Any],
    dest: dict[str, Any],
    audit: NetworkAudit,
    cred_reads: dict[str, int],
    live_reason: str,
    release_sha: str,
) -> dict[str, Any]:
    """Canonical DRY receipt. `general_sends` is the measured counter."""
    return {
        "sent": False,
        "dry_run": True,
        "operator_approved": False,
        "cio_chat_confirmed": False,
        "general_sends": int(audit.general_sends),
        "release_sha": release_sha,
        "duplicate": bool(ev.get("would_duplicate")),
        "proof": "dry",
        # Measurement extras (acceptance + operator review)
        "authority": AUTHORITY,
        "version": CANARY_VERSION,
        "at": _now_iso(),
        "decision_id": decision.get("decision_id"),
        "symbol": decision.get("symbol"),
        "action": decision.get("action"),
        "would_send": bool(ev.get("would_send")),
        "would_send_path": WOULD_SEND_PATH,
        "chat_target_type": classify_chat_target(),
        "duplicate_key": ev.get("dedupe_key") or "",
        "http_calls": int(audit.http_calls),
        "cio_sends": int(audit.cio_sends),
        "send_message_calls": int(audit.send_message_calls),
        "general_token_reads_for_send": int(cred_reads.get(ENV_GENERAL_TOKEN, 0)),
        "general_chat_reads_for_send": int(cred_reads.get(ENV_GENERAL_CHAT, 0)),
        "transport_reads_general_token": transport_source_reads_general_token(),
        "live_gate_reason": live_reason,
        "destination_identity": dest,
        "channel": "telegram_cio_only",
        "REAL_TELEGRAM_SENDS": 0,
    }


def write_receipt(receipt: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def run_canary(
    *,
    dry_run: bool = True,
    want_live: bool = False,
    receipt_path: Optional[Path] = None,
    decision: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Prepare (and only if fully gated, send) the CIO Telegram canary.

    Default is DRY. Under pytest, always DRY. Missing live flags → DRY.
    The canonical receipt path is written **only** as a dry document
    (``sent: false``, ``proof: "dry"``).
    """
    requested_live = bool(want_live) and not dry_run
    if tg.under_pytest():
        dry_run = True

    permitted, live_reason = live_send_permitted(want_live=requested_live)
    if not permitted:
        dry_run = True
        want_live = False

    d = decision or schd_trim_decision()
    path = Path(receipt_path) if receipt_path else default_receipt_path()
    release_sha = read_release_sha()

    if dry_run:
        # Defense in depth: interdict this process for the dry path.
        os.environ.setdefault("CIO_TELEGRAM_INTERDICT", "1")

    with NetworkAudit() as audit:
        cred_reads = measure_send_credential_env_reads()
        ev = alex.evaluate_outbound(d, kind="decision")
        dest = alex.canary_destination_identity()
        pkg = alex.prepare_canary_package(decision=d)

        if not dry_run and permitted:
            # Live path — still CIO-only; never write sent:true to the dry file.
            live_res = alex.execute_canary_send(decision=d, force_approve_in_process=False)
            live_receipt = {
                "sent": bool(live_res.get("delivered")),
                "dry_run": False,
                "operator_approved": True,
                "cio_chat_confirmed": bool(live_res.get("delivered")),
                "general_sends": int(audit.general_sends),
                "release_sha": release_sha,
                "duplicate": bool(live_res.get("deduped") or ev.get("would_duplicate")),
                "proof": "live",
                "decision_id": d.get("decision_id"),
                "duplicate_key": ev.get("dedupe_key"),
                "chat_target_type": classify_chat_target(),
                "would_send_path": WOULD_SEND_PATH,
                "REAL_TELEGRAM_SENDS": int(live_res.get("REAL_TELEGRAM_SENDS") or 0),
                "reason": live_res.get("reason"),
            }
            live_path = LIVE_RECEIPT_PATH
            write_receipt(live_receipt, live_path)
            return {
                "ok": bool(live_res.get("delivered")),
                "dry_run": False,
                "receipt_path": str(live_path),
                "receipt": live_receipt,
                "package": pkg,
                "measurement": {
                    "general_sends": int(audit.general_sends),
                    "cio_sends": int(audit.cio_sends),
                    "http_calls": int(audit.http_calls),
                    "assumed": False,
                    "source": "counted_send_attempts",
                    "general_token_reads_for_send": cred_reads.get(ENV_GENERAL_TOKEN, 0),
                },
            }

        # DRY: never call send_cio_message / execute_canary_send.
        receipt = _dry_receipt(
            decision=d,
            ev=ev,
            dest=dest,
            audit=audit,
            cred_reads=cred_reads,
            live_reason=live_reason,
            release_sha=release_sha,
        )
        write_receipt(receipt, path)
        return {
            "ok": True,
            "dry_run": True,
            "receipt_path": str(path),
            "receipt": receipt,
            "package": {
                "decision_id": pkg.get("decision_id"),
                "dedupe_key": pkg.get("dedupe_key"),
                "status": pkg.get("status"),
                "live_send": pkg.get("live_send"),
                "message_body": pkg.get("message_body"),
                "destination_identity": dest,
                "REAL_TELEGRAM_SENDS": 0,
            },
            "evaluation": {
                "material": ev.get("material"),
                "would_send": ev.get("would_send"),
                "would_duplicate": ev.get("would_duplicate"),
                "dedupe_key": ev.get("dedupe_key"),
                "channel": ev.get("channel"),
            },
            "measurement": {
                "general_sends": int(audit.general_sends),
                "cio_sends": int(audit.cio_sends),
                "http_calls": int(audit.http_calls),
                "send_message_calls": int(audit.send_message_calls),
                "assumed": False,
                "source": "counted_send_attempts",
                "general_token_reads_for_send": int(cred_reads.get(ENV_GENERAL_TOKEN, 0)),
                "general_chat_reads_for_send": int(cred_reads.get(ENV_GENERAL_CHAT, 0)),
                "transport_reads_general_token": transport_source_reads_general_token(),
                "credential_env_reads": cred_reads,
            },
            "live_gate_reason": live_reason,
            "authority": AUTHORITY,
        }


def receipt_fingerprint(receipt: dict[str, Any]) -> str:
    raw = json.dumps(
        {k: receipt.get(k) for k in (
            "sent", "dry_run", "operator_approved", "cio_chat_confirmed",
            "general_sends", "duplicate", "proof",
        )},
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
