"""HTTP dispatcher for the ActiveTrader SESSION CONTROL plane (P3) + simulation run (P4).

SEPARATE from the GET-only read plane: this service accepts POST to mutate SESSION-AUTHORIZATION state
(drafts, validation, authorization, simulation activation) and to run the SIMULATION execution engine.
It NEVER touches money: no live adapter, no real 2FA (a fake test verifier only), no live credential,
no real order. Live activation is categorically FEATURE_DISABLED (enforced in session_control.activate).
Gated by feature_flags.active_trader_session_builder_enabled.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Mapping

import active_trader.session_control as sc
import active_trader.sim_execution as se

PREFIX = "/api/v3/active-trader"
SESSION_PREFIXES = (PREFIX + "/session-drafts", PREFIX + "/sessions")


def is_session_path(path: str) -> bool:
    p = (path or "").rstrip("/") or "/"
    return any(p == pre or p.startswith(pre + "/") or p == pre for pre in SESSION_PREFIXES)


def _fake_verifier(_session, _envelope) -> bool:
    """Injected TEST 2FA check — always passes. NEVER a real second factor / credential."""
    return True


def _as_json(r: Any) -> Any:
    if dataclasses.is_dataclass(r):
        return dataclasses.asdict(r)
    if isinstance(r, Mapping):
        return dict(r)
    if hasattr(r, "public_dict"):
        return r.public_dict()
    return {"result": str(r)}


def _env(kind: str, data: Any, status: int = 200) -> tuple[int, dict[str, Any]]:
    return status, {
        "contract": sc.CONTRACT,
        "read_only": False,          # this service writes SESSION-authorization state (never money)
        "write": True,
        "live": False, "live_session_enabled": False, "mode_default": "SIMULATION", "real_order": False,
        "kind": kind, "data": data,
        "authority": {"order": False, "financial_action": False, "live": False,
                      "session_authorize": "simulation_only", "canary": False},
    }


def dispatch(store: "sc.SessionStore", engine: "se.SimExecutionEngine", method: str, path: str,
             query: Mapping[str, Any] | None, body: Mapping[str, Any] | None, flags=None) -> tuple[int, dict[str, Any]]:
    method = (method or "GET").upper()
    body = dict(body or {})
    if flags is not None and not getattr(flags, "active_trader_session_builder_enabled", False):
        return _env("feature_disabled", {"reason": "session builder disabled"}, 403)

    suffix = (path or "").rstrip("/")[len(PREFIX):].lstrip("/")
    parts = [p for p in suffix.split("/") if p]

    try:
        if method == "POST" and suffix == "session-drafts":
            s = sc.create_draft(store, str(body.get("operator_identity") or "operator"), body.get("draft"))
            return _env("draft_created", s.public_dict(), 201)

        if parts and parts[0] == "session-drafts" and len(parts) >= 2:
            sid, op = parts[1], (parts[2] if len(parts) > 2 else "")
            if method == "POST" and op == "save":
                return _env("draft_saved", sc.save_draft(store, sid, body.get("updates") or body).public_dict())
            if method == "POST" and op == "validate":
                return _env("validated", sc.validate_draft(store, sid))
            if method == "POST" and op == "authorization-preview":
                return _env("authorization_preview", sc.authorization_preview(store, sid))

        if parts and parts[0] == "sessions" and len(parts) >= 2:
            sid, op = parts[1], (parts[2] if len(parts) > 2 else "")
            if method == "GET" and op == "":
                return _env("session", sc.get_session(store, sid))
            if method == "GET" and op == "journal":
                return _env("journal", sc.session_journal(store, sid))
            if method == "POST" and op == "authorize":
                return _env("authorized", sc.authorize(store, sid, _fake_verifier))
            if method == "POST" and op == "activate":
                mode = str(body.get("mode") or "SIMULATION").upper()   # LIVE → FEATURE_DISABLED inside activate()
                return _env("activate", sc.activate(store, sid, mode))
            if method == "POST" and op == "pause":
                return _env("paused", sc.pause(store, sid).public_dict())
            if method == "POST" and op == "revoke":
                return _env("revoked", sc.revoke(store, sid, reason=str(body.get("reason") or "")).public_dict())
            if method == "POST" and op == "kill":
                return _env("killed", sc.kill(store, sid, reason=str(body.get("reason") or "")).public_dict())
            if method == "POST" and op == "simulate-event":
                ctx = dict(body.get("context") or {})
                try:
                    ctx.setdefault("session", sc.get_session(store, sid))
                except Exception:
                    pass
                result = engine.process(body.get("event") or {}, ctx)
                return _env("simulation_result", {"outcome": _as_json(result), "intent_count": engine.intent_count()})

        return _env("not_found", {"detail": f"unknown session path: {suffix or '/'}"}, 404)
    except sc.SessionNotFoundError as e:
        return _env("not_found", {"error": str(e)}, 404)
    except sc.SessionValidationError as e:
        return _env("validation_error", {"error": str(e)}, 422)
    except sc.SessionTransitionError as e:
        return _env("conflict", {"error": str(e)}, 409)
    except sc.SessionError as e:
        return _env("error", {"error": str(e)}, 400)
    except Exception:
        return _env("error", {"error": "session operation failed"}, 500)
