"""Ops -> Controls Command Center routes: /api/v2/ops/controls/* (contract: docs/ops/OPS_CONTROLS_API.md).

AGENTS.md 19.0.0 §27.2-§27.3 (PROPOSED). This handler records and authorises change requests; it never applies a
host change itself (crontab, live list, settings, grants and the kill switch are applied only by the host applier,
scripts/ops/operator_controls_applier.py). The only in-process effects are the two safe release-train requests (the
same writers the existing STOP button and ReleaseControl use) and the passkey store.

Order of refusals on every POST: POLICY_NOT_ACTIVE (19.0.0 not ACTIVE, read at request time) -> AGENT_CALLER_REFUSED
(anything but a tailnet operator identity on the serve_proxy listener; the service token is refused) -> CSRF_REFUSED
(handler-side same-origin check, enforced whatever report_only says) -> STORE_NOT_MIGRATED -> the route's own checks.
GET routes skip only the policy check. AUTHORITY: OPERATOR_ONLY. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import sys as _sys

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in _sys.path:  # one module identity (scripts.lib.*) whether served as lib.* or imported in tests
    _sys.path.append(_ROOT)

from scripts.lib import ops_controls_auth as A  # noqa: E402
from scripts.lib import ops_controls_core as C  # noqa: E402
from scripts.lib import ops_controls_store as S  # noqa: E402

PREFIX = "/api/v2/ops/controls"
SCHEMA_STATE = "OpsControlsState@v1"
ROUTE_RE = re.compile(r"^/requests/(opsreq_[0-9a-f]{20})(/[a-z/-]+)?$")
IDEM_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,100}$")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
SERVE_PROXY = "serve_proxy"


# ── context (tests build their own) ────────────────────────────────────────────────────────────────────────────────


@dataclass
class Ctx:
    cfg: dict
    store: Any
    hosts: C.Hosts
    verifier: Any
    principal: Callable[[], str]
    listener: Callable[[], Optional[str]]
    csrf: Callable[[str, str], tuple[bool, str]]
    allowed_logins: frozenset
    hmac_key: Callable[[], Optional[bytes]]
    totp_secret: Callable[[], Optional[str]]
    agents_path: Optional[Path] = None
    clock: Callable[[], datetime] = C.utc_now
    notify: Callable[[str, str, Optional[str]], dict] = field(default=lambda s, b, r: {"queued": False})


def _default_ctx() -> Ctx:
    try:
        from lib import cc_auth  # type: ignore
    except ImportError:  # pragma: no cover
        from scripts.lib import cc_auth  # type: ignore
    try:
        import db_adapter  # type: ignore
    except ImportError:  # pragma: no cover
        from scripts import db_adapter  # type: ignore
    cfg = C.load_config()
    auth_cfg = cc_auth.load_config()
    wa = cfg["webauthn"]

    def listener() -> Optional[str]:
        ctx = cc_auth.current_request_context()
        return (ctx or {}).get("listener")

    def totp_secret() -> Optional[str]:
        raw = A.read_private_file(C.expand(cfg["secrets"]["totp_secret_file"]))
        return raw.decode("utf-8").strip() if raw else None

    return Ctx(cfg=cfg, store=S.PgStore(db_adapter.ensure_conn), hosts=C.Hosts(cfg),
               verifier=A.PasskeyVerifier(rp_id=wa["rp_id"], rp_name=wa["rp_name"], origins=wa["origins"]),
               principal=cc_auth.current_principal, listener=listener,
               csrf=lambda m, p: cc_auth.command_csrf_check(auth_cfg, m, p),
               allowed_logins=auth_cfg.allowed_logins,
               hmac_key=lambda: A.load_hmac_key(C.expand(cfg["secrets"]["hmac_key_file"])),
               totp_secret=totp_secret, notify=lambda s, b, r: notify_host(cfg, s, b, r))


def notify_host(cfg: dict, subject: str, summary: str, request_id: Optional[str]) -> dict:
    """Telegram is notification only: queue one host comms intent (never a send, never a confirmation)."""
    n = cfg.get("notify") or {}
    try:
        from scripts.check_registry_runtime_truth import queue_host_intent

        out = queue_host_intent(producer=n["producer"], domain=n["domain"], kind=n["kind"], subject=subject,
                                summary=summary, execution_id=request_id or "ops", node="ops-controls",
                                ledger_path=C.expand(n["ledger"]))
        return {"queued": True, "detail": str(out.get("status") or out.get("outcome") or "accepted")[:80]}
    except Exception as exc:  # noqa: BLE001 — a notification failure never blocks or fakes an action
        return {"queued": False, "detail": f"{type(exc).__name__}: {str(getattr(exc, 'args', [''])[0])[:80]}"}


_CTX: Optional[Ctx] = None


def context() -> Ctx:
    global _CTX
    if _CTX is None:
        _CTX = _default_ctx()
    return _CTX


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def _err(status: int, code: str, detail: str = "") -> tuple[int, dict]:
    return status, {"ok": False, "error": code, "detail": detail}


def _ts(v: Any) -> Any:
    return C.iso(v) if isinstance(v, datetime) else v


def _aware(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def public_request(r: Optional[dict]) -> Optional[dict]:
    if not r:
        return None
    spec = C.KINDS.get(r.get("kind") or "")
    out = {k: _ts(r.get(k)) for k in ("request_id", "kind", "direction", "executor", "params", "phrase", "preview",
                                       "expected_state_digest", "status", "status_at", "created_at", "approved_at",
                                       "applied_at", "actor", "result", "undo_of", "undone_by", "stepup_expires_at",
                                       "stepup_factor")}
    out["label"] = spec.label if spec else r.get("kind")
    res = r.get("result") or {}
    undo = res.get("undo") if isinstance(res, dict) else None
    if r.get("status") == "APPLIED" and undo and not r.get("undone_by"):
        us = C.KINDS.get(undo.get("kind") or "")
        out["undo"] = {"available": bool(us and us.supported), "kind": undo.get("kind"),
                       "direction": us.direction if us else None, "reason": None if us and us.supported else
                       (us.reason if us else "unknown kind")}
    else:
        reason = (res.get("undo_reason") if isinstance(res, dict) else None) or (
            "already undone" if r.get("undone_by") else "only an applied change can be undone")
        out["undo"] = {"available": False, "kind": None, "direction": None, "reason": reason}
    return out


def _audit(ctx: Ctx, action: str, outcome: str, *, kind: Optional[str] = None, request_id: Optional[str] = None,
           detail: Optional[dict] = None, actor: Optional[str] = None) -> None:
    try:
        if ctx.store.tables_status().get("state") == "OK":
            ctx.store.append_audit(actor=actor or ctx.principal() or "unknown", action=action, kind=kind,
                                   request_id=request_id, outcome=outcome, detail=detail or {})
    except Exception:  # noqa: BLE001 — the refusal itself still stands
        pass


def _operator(ctx: Ctx) -> Optional[str]:
    """The tailnet operator login when this request comes from one, else None. Server-derived; never the body."""
    p = ctx.principal() or ""
    if not p.startswith("tailnet:") or ctx.listener() != SERVE_PROXY:
        return None
    login = p[len("tailnet:"):].strip().lower()
    return p if login and login in ctx.allowed_logins else None


# ── entry point ─────────────────────────────────────────────────────────────────────────────────────────────────────


def handle(path: str, method: str, body: Any = None, query: Any = None, *, ctx: Optional[Ctx] = None):
    base = (path or "").split("?", 1)[0].rstrip("/")
    if not (base == PREFIX or base.startswith(PREFIX + "/")):
        return None
    sub = base[len(PREFIX):] or "/"
    m = (method or "GET").upper()
    try:
        ctx = ctx or context()
    except Exception as exc:  # noqa: BLE001
        return _err(503, "CONFIG_UNAVAILABLE", type(exc).__name__)
    try:
        if m == "GET":
            op = _operator(ctx)
            if not op:
                return _err(403, "AGENT_CALLER_REFUSED", "Ops Controls answer only the operator's tailnet identity; "
                                                         "agents, n8n and the service token are refused")
            if sub == "/state":
                return 200, build_state(ctx, op)
            mm = ROUTE_RE.match(sub)
            if mm and not mm.group(2):
                r = ctx.store.get_request(mm.group(1))
                return (200, {"ok": True, "request": public_request(r)}) if r else _err(404, "NOT_FOUND")
            return _err(404, "NOT_FOUND")
        if m != "POST":
            return _err(405, "METHOD_NOT_ALLOWED")
        return _post(ctx, base, sub, body if isinstance(body, dict) else {})
    except C.OpsError as exc:
        return _err(exc.status, exc.code, exc.detail)
    except A.AuthError as exc:
        return _err(exc.status, exc.code, exc.detail)
    except S.StoreError as exc:
        return _err(exc.status, exc.code, exc.detail)


def _post(ctx: Ctx, base: str, sub: str, body: dict):
    pol = C.policy_state(ctx.agents_path)
    if pol["state"] != C.POLICY_ACTIVE:
        return _err(409, "POLICY_NOT_ACTIVE", f"AGENTS.md {pol['required']} is not ACTIVE ({pol['detail']}); Ops "
                                              "Controls are inert")
    op = _operator(ctx)
    if not op:
        _audit(ctx, "refused.caller", "refused", detail={"path": sub, "principal": (ctx.principal() or "")[:60]},
               actor=ctx.principal() or "unknown")
        return _err(403, "AGENT_CALLER_REFUSED", "only the operator's tailnet identity may change controls; agents, "
                                                 "n8n and the service token never call these routes (§27.2)")
    ok, why = ctx.csrf("POST", base)
    if not ok:
        _audit(ctx, "refused.csrf", "refused", detail={"path": sub, "why": why})
        return _err(403, "CSRF_REFUSED", why)
    st = ctx.store.tables_status()
    if st["state"] != "OK":
        return _err(503, "STORE_NOT_MIGRATED" if st["state"] == "NOT_MIGRATED" else "STORE_UNAVAILABLE",
                    st.get("reason") or "")
    if sub == "/requests":
        return create_request(ctx, op, body)
    if sub == "/passkeys/register/options":
        return passkey_register_options(ctx, op, body)
    if sub == "/passkeys/register/verify":
        return passkey_register_verify(ctx, op, body)
    mm = ROUTE_RE.match(sub)
    if not mm:
        return _err(404, "NOT_FOUND")
    rid, action = mm.group(1), (mm.group(2) or "")
    req = ctx.store.get_request(rid)
    if not req:
        return _err(404, "NOT_FOUND")
    if action == "/approve":
        return approve(ctx, op, req, body)
    if action == "/step-up/options":
        return step_up_options(ctx, op, req)
    if action == "/step-up/verify":
        return step_up_verify(ctx, op, req, body)
    if action == "/step-up/totp":
        return step_up_totp(ctx, op, req, body)
    if action == "/cancel":
        r = ctx.store.transition(rid, ("PREVIEWED", "AWAITING_STEP_UP", "STEP_UP_VERIFIED", "APPROVED"), "CANCELLED")
        if not r:
            return _err(409, "STATE_CONFLICT", f"request is {req['status']}")
        _audit(ctx, "request.cancelled", "ok", kind=req["kind"], request_id=rid)
        return 200, {"ok": True, "request": public_request(r)}
    if action == "/undo":
        return undo(ctx, op, req, body)
    return _err(404, "NOT_FOUND")


# ── requests ────────────────────────────────────────────────────────────────────────────────────────────────────────


def create_request(ctx: Ctx, op: str, body: dict, *, undo_of: Optional[str] = None):
    kind = body.get("kind")
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    idem = body.get("idempotency_key")
    if not isinstance(idem, str) or not IDEM_RE.fullmatch(idem):
        return _err(400, "IDEMPOTENCY_KEY_REQUIRED", "idempotency_key: 8-100 of [A-Za-z0-9_.:-]")
    spec = C.kind_spec(kind)
    if not spec.supported:
        _audit(ctx, "refused.kind_not_supported", "refused", kind=kind)
        return _err(409, "KIND_NOT_SUPPORTED", spec.reason or "")
    rid = C.new_request_id()
    try:
        plan = C.plan_change(spec.kind, params, ctx.hosts, ctx.store, request_id=rid, actor=op)
    except C.OpsError as exc:
        _audit(ctx, "refused.preview", "refused", kind=spec.kind, detail={"code": exc.code, "detail": exc.detail})
        raise
    today = ctx.clock().astimezone(timezone.utc).strftime("%Y-%m-%d")
    row = {"request_id": rid, "idempotency_key": idem, "kind": spec.kind, "direction": spec.direction,
           "executor": spec.executor, "params": plan.params, "phrase": C.phrase_for(spec.kind, plan.params, today),
           "preview": plan.public(), "expected_state_digest": plan.digest, "actor": op,
           "status": "PREVIEWED" if spec.direction == C.SAFE else "AWAITING_STEP_UP", "created_at": ctx.clock(),
           "status_at": ctx.clock(), "undo_of": undo_of}
    saved, created = ctx.store.create_request(row)
    if not created:
        if saved.get("kind") != spec.kind or C.canonical(saved.get("params")) != C.canonical(plan.params):
            return _err(409, "IDEMPOTENCY_CONFLICT", "that idempotency_key belongs to a different request")
        return 200, {"ok": True, "replayed": True, "request": public_request(saved)}
    _audit(ctx, "request.created", "ok", kind=spec.kind, request_id=rid,
           detail={"direction": spec.direction, "summary": plan.summary, "undo_of": undo_of})
    if body.get("one_click") is True:
        if spec.direction != C.SAFE:
            return 200, {"ok": True, "request": public_request(saved),
                         "note": "one_click ignored: a risky kind needs a passkey and the typed phrase"}
        return approve(ctx, op, saved, {})
    return 200, {"ok": True, "request": public_request(saved)}


def _sign_and_approve(ctx: Ctx, req: dict, from_status: str, **fields: Any) -> Optional[dict]:
    approved_at = ctx.clock()
    candidate = dict(req, approved_at=approved_at, **fields)
    key = ctx.hmac_key()
    if req["executor"] == C.EXEC_APPLIER and not key:
        raise C.OpsError("SECRET_MISSING", "the approval HMAC key file is missing or not 0600; the applier would "
                                           "refuse an unsigned approval (docs/ops/OPS_CONTROLS.md, activation)", 503)
    sig = A.sign_approval(key, candidate) if key else None
    return ctx.store.transition(req["request_id"], (from_status,), "APPROVED", approved_at=approved_at,
                                approval_sig=sig, **fields)


def approve(ctx: Ctx, op: str, req: dict, body: dict):
    rid = req["request_id"]
    if req["actor"] != op:
        return _err(403, "ACTOR_MISMATCH", "approve your own request")
    if req["direction"] == C.SAFE:
        r = _sign_and_approve(ctx, req, "PREVIEWED")
        if not r:
            return _err(409, "STATE_CONFLICT", f"request is {req['status']}")
    else:
        token = body.get("step_up_token")
        if not isinstance(token, str) or not token:
            _audit(ctx, "refused.step_up_required", "refused", kind=req["kind"], request_id=rid)
            return _err(403, "STEP_UP_REQUIRED", "a risky change needs a passkey assertion and the typed phrase")
        if req["status"] != "STEP_UP_VERIFIED" or req.get("stepup_used_at"):
            code = "STEP_UP_REPLAYED" if req.get("stepup_used_at") else "STEP_UP_REQUIRED"
            _audit(ctx, f"refused.{code.lower()}", "refused", kind=req["kind"], request_id=rid)
            return _err(403, code, f"request is {req['status']}")
        if not A.hmac.compare_digest(A.token_hash(token), req.get("stepup_token_hash") or ""):
            _audit(ctx, "refused.step_up_invalid", "refused", kind=req["kind"], request_id=rid)
            return _err(403, "STEP_UP_INVALID", "that step-up token is not bound to this request")
        exp = _aware(req.get("stepup_expires_at"))
        if not exp or exp <= ctx.clock():
            ctx.store.transition(rid, ("STEP_UP_VERIFIED",), "EXPIRED")
            _audit(ctx, "refused.step_up_expired", "refused", kind=req["kind"], request_id=rid)
            return _err(403, "STEP_UP_EXPIRED", "the step-up expired (2 minutes); start again")
        r = _sign_and_approve(ctx, req, "STEP_UP_VERIFIED", stepup_used_at=ctx.clock())
        if not r:
            return _err(403, "STEP_UP_REPLAYED", "the step-up token was already used")
    _audit(ctx, "request.approved", "ok", kind=r["kind"], request_id=rid,
           detail={"factor": r.get("stepup_factor") or "one_click", "executor": r["executor"]})
    if r["executor"] == C.EXEC_CC and r["kind"] in ("release_train.stop", "release_train.pause", "passkey.revoke"):
        r = execute_cc(ctx, op, r)
    elif r["executor"] == C.EXEC_APPLIER:
        ctx.notify(f"Ops Controls: {r['kind']} approved", f"{(r.get('preview') or {}).get('summary', '')} — by "
                   f"{op}; the host applier applies it within 2 minutes", rid)
    return 200, {"ok": True, "request": public_request(r)}


def execute_cc(ctx: Ctx, op: str, r: dict) -> dict:
    """The CC-executed kinds: release-train STOP/pause (existing writers) and passkey revocation."""
    rid = r["request_id"]
    r2 = ctx.store.transition(rid, ("APPROVED",), "APPLYING")
    if not r2:
        return r
    try:
        if r["kind"] == "passkey.revoke":
            ok = ctx.store.credential_revoke(r["params"]["credential_id"], actor=op, request_id=rid)
            result = {"outcome": "APPLIED" if ok else "FAILED", "verify": {"revoked": ok}, "undo": None,
                      "undo_reason": "register a new passkey instead"}
        else:
            result = C.apply_change(r["kind"], r["params"], r.get("expected_state_digest"), ctx.hosts, ctx.store,
                                    request_id=rid, actor=op)
    except (C.OpsError, A.AuthError, S.StoreError) as exc:
        result = {"outcome": "REFUSED", "code": exc.code, "detail": exc.detail}
    except Exception as exc:  # noqa: BLE001
        result = {"outcome": "FAILED", "code": type(exc).__name__, "detail": str(exc)[:200]}
    return finish(ctx, r, result, actor=op)


def finish(ctx: Ctx, r: dict, result: dict, *, actor: str) -> dict:
    status = result.get("outcome") if result.get("outcome") in ("APPLIED", "FAILED", "REFUSED") else "FAILED"
    rid = r["request_id"]
    done = ctx.store.transition(rid, ("APPLYING",), status, result=result,
                                applied_at=ctx.clock() if status == "APPLIED" else None) or r
    if status == "APPLIED" and r.get("undo_of"):
        ctx.store.set_fields(r["undo_of"], undone_by=rid)
    note = ctx.notify(f"Ops Controls: {r['kind']} {status}", f"{(r.get('preview') or {}).get('summary', '')} — "
                      f"{actor}", rid)
    ctx.store.append_audit(actor=actor, action=f"request.{status.lower()}", kind=r["kind"], request_id=rid,
                           outcome="ok" if status == "APPLIED" else status.lower(),
                           detail={"result": {k: result.get(k) for k in ("outcome", "code", "detail", "backup_ref",
                                                                          "verify")}, "notify": note})
    return done


def undo(ctx: Ctx, op: str, req: dict, body: dict):
    pub = public_request(req) or {}
    u = pub.get("undo") or {}
    if not u.get("available"):
        return _err(409, "UNDO_NOT_AVAILABLE", u.get("reason") or "")
    undo_spec = (req.get("result") or {}).get("undo") or {}
    return create_request(ctx, op, {"kind": undo_spec.get("kind"), "params": undo_spec.get("params") or {},
                                    "idempotency_key": body.get("idempotency_key")}, undo_of=req["request_id"])


# ── step-up ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def _active_credentials(ctx: Ctx) -> list[dict]:
    return [c for c in ctx.store.credentials_list() if not c.get("revoked_at")]


def step_up_options(ctx: Ctx, op: str, req: dict):
    if req["direction"] != C.RISKY or req["status"] != "AWAITING_STEP_UP":
        return _err(409, "STATE_CONFLICT", f"request is {req['direction']} / {req['status']}")
    if req["actor"] != op:
        return _err(403, "ACTOR_MISMATCH", "step up for your own request")
    creds = _active_credentials(ctx)
    if not creds:
        return _err(409, "PASSKEY_REQUIRED", "no passkey is enrolled; add one with TOTP recovery (passkey.register)")
    challenge = secrets.token_bytes(32)
    ttl = int(ctx.cfg["webauthn"].get("challenge_ttl_s", 120))
    ctx.store.challenge_put(request_id=req["request_id"], purpose="step_up", challenge=A.b64url(challenge),
                            expires_at=ctx.clock() + timedelta(seconds=ttl))
    opts = ctx.verifier.authentication_options(challenge=challenge, allow_ids=[c["credential_id"] for c in creds])
    return 200, {"ok": True, "options": opts, "expires_at": C.iso(ctx.clock() + timedelta(seconds=ttl))}


def _issue_token(ctx: Ctx, req: dict, *, factor: str, credential_id: Optional[str]):
    token = A.new_step_up_token()
    ttl = int(ctx.cfg["step_up"].get("ttl_s", 120))
    exp = ctx.clock() + timedelta(seconds=ttl)
    r = ctx.store.transition(req["request_id"], ("AWAITING_STEP_UP",), "STEP_UP_VERIFIED",
                             stepup_token_hash=A.token_hash(token), stepup_expires_at=exp, stepup_factor=factor,
                             stepup_credential_id=credential_id)
    if not r:
        return _err(409, "STATE_CONFLICT", "request is no longer awaiting a step-up")
    _audit(ctx, "step_up.verified", "ok", kind=req["kind"], request_id=req["request_id"],
           detail={"factor": factor, "credential_id8": (credential_id or "")[:8] or None})
    return 200, {"ok": True, "step_up_token": token, "expires_at": C.iso(exp), "request": public_request(r)}


def step_up_verify(ctx: Ctx, op: str, req: dict, body: dict):
    rid = req["request_id"]
    if req["direction"] != C.RISKY or req["status"] != "AWAITING_STEP_UP":
        return _err(409, "STATE_CONFLICT", f"request is {req['direction']} / {req['status']}")
    if req["actor"] != op:
        return _err(403, "ACTOR_MISMATCH", "step up for your own request")
    credential = body.get("credential")
    cid = A.credential_id_of(credential)
    cred = ctx.store.credential_get(cid)
    if not cred or cred.get("revoked_at"):
        _audit(ctx, "refused.passkey_unknown", "refused", kind=req["kind"], request_id=rid)
        return _err(403, "PASSKEY_UNKNOWN", "that passkey is not enrolled or was revoked")
    ch = ctx.store.challenge_take(request_id=rid, purpose="step_up", challenge=A.client_challenge_of(credential))
    try:
        v = ctx.verifier.verify_assertion(credential=credential, challenge=A.b64url_decode(ch["challenge"]),
                                          public_key=cred["public_key"], sign_count=int(cred.get("sign_count") or 0))
    except A.AuthError as exc:
        _audit(ctx, "refused.assertion", "refused", kind=req["kind"], request_id=rid, detail={"code": exc.code})
        raise
    if not v.user_verified or v.credential_id.rstrip("=") != cid:
        return _err(403, "ASSERTION_INVALID", "user verification is required")
    if not ctx.store.credential_touch(cid, old_count=int(cred.get("sign_count") or 0), new_count=v.new_sign_count):
        return _err(403, "ASSERTION_INVALID", "passkey state changed during verification")
    if not C.phrase_matches(body.get("phrase"), req.get("phrase")):
        _audit(ctx, "refused.phrase", "refused", kind=req["kind"], request_id=rid)
        return _err(403, "PHRASE_MISMATCH", "type the phrase exactly as shown; authenticate again")
    return _issue_token(ctx, req, factor="passkey", credential_id=cid)


def step_up_totp(ctx: Ctx, op: str, req: dict, body: dict):
    rid = req["request_id"]
    if req["kind"] != "passkey.register" or req["status"] != "AWAITING_STEP_UP":
        _audit(ctx, "refused.totp_not_allowed", "refused", kind=req["kind"], request_id=rid)
        return _err(403, "TOTP_NOT_ALLOWED", "TOTP is recovery only: it may only register a passkey when none is "
                                             "active (§27.3)")
    if req["actor"] != op:
        return _err(403, "ACTOR_MISMATCH", "step up for your own request")
    if _active_credentials(ctx):
        _audit(ctx, "refused.totp_not_allowed", "refused", kind=req["kind"], request_id=rid)
        return _err(403, "TOTP_NOT_ALLOWED", "a passkey is active; add the new one with an existing passkey")
    row = ctx.store.totp_get()
    secret = ctx.totp_secret()
    if not row or not secret or A.totp_fingerprint(secret) != row.get("secret_fingerprint"):
        return _err(409, "TOTP_NOT_ENROLLED", "enrol TOTP recovery at the host terminal: "
                                              "scripts/ops/operator_controls_applier.py totp-enroll")
    step = A.totp_verify(secret, body.get("code"), now=ctx.clock().timestamp())
    if step is None or not ctx.store.totp_mark_step(int(row["id"]), step):
        _audit(ctx, "refused.totp", "refused", kind=req["kind"], request_id=rid)
        return _err(403, "TOTP_INVALID", "wrong, expired or already-used code")
    if not C.phrase_matches(body.get("phrase"), req.get("phrase")):
        _audit(ctx, "refused.phrase", "refused", kind=req["kind"], request_id=rid)
        return _err(403, "PHRASE_MISMATCH", "type the phrase exactly as shown")
    return _issue_token(ctx, req, factor="totp", credential_id=None)


# ── passkey registration ───────────────────────────────────────────────────────────────────────────────────────────


def _user_handle(ctx: Ctx, op: str) -> bytes:
    return hashlib.sha256(f"{ctx.cfg['webauthn']['rp_id']}|{op}".encode("utf-8")).digest()[:32]


def _approved_register(ctx: Ctx, op: str, body: dict) -> dict:
    rid = body.get("request_id")
    req = ctx.store.get_request(rid) if isinstance(rid, str) else None
    if not req or req["kind"] != "passkey.register":
        raise C.OpsError("NOT_FOUND", "no passkey.register request", 404)
    if req["actor"] != op:
        raise C.OpsError("ACTOR_MISMATCH", "register under your own request", 403)
    if req["status"] != "APPROVED":
        raise C.OpsError("STEP_UP_REQUIRED", f"request is {req['status']}; step up and approve it first", 403)
    approved = _aware(req.get("approved_at"))
    if not approved or approved + timedelta(seconds=int(ctx.cfg["step_up"].get("ttl_s", 120))) <= ctx.clock():
        ctx.store.transition(req["request_id"], ("APPROVED",), "EXPIRED")
        raise C.OpsError("STEP_UP_EXPIRED", "the approval expired (2 minutes); start again", 403)
    return req


def passkey_register_options(ctx: Ctx, op: str, body: dict):
    req = _approved_register(ctx, op, body)
    challenge = secrets.token_bytes(32)
    ttl = int(ctx.cfg["webauthn"].get("challenge_ttl_s", 120))
    ctx.store.challenge_put(request_id=req["request_id"], purpose="register", challenge=A.b64url(challenge),
                            expires_at=ctx.clock() + timedelta(seconds=ttl))
    opts = ctx.verifier.registration_options(
        challenge=challenge, user_handle=_user_handle(ctx, op), user_name=ctx.cfg["webauthn"].get("user_name", "op"),
        exclude_ids=[c["credential_id"] for c in _active_credentials(ctx)])
    return 200, {"ok": True, "options": opts, "expires_at": C.iso(ctx.clock() + timedelta(seconds=ttl))}


def passkey_register_verify(ctx: Ctx, op: str, body: dict):
    req = _approved_register(ctx, op, body)
    rid = req["request_id"]
    credential = body.get("credential")
    ch = ctx.store.challenge_take(request_id=rid, purpose="register", challenge=A.client_challenge_of(credential))
    v = ctx.verifier.verify_registration(credential=credential, challenge=A.b64url_decode(ch["challenge"]))
    r = ctx.store.transition(rid, ("APPROVED",), "APPLYING")
    if not r:
        return _err(409, "STATE_CONFLICT", "request is no longer approved")
    ctx.store.credential_add({"credential_id": v.credential_id, "name": req["params"]["name"],
                              "public_key": v.public_key, "sign_count": v.sign_count, "transports": v.transports,
                              "aaguid": v.aaguid, "user_handle": A.b64url(_user_handle(ctx, op)), "created_by": op,
                              "created_request_id": rid})
    done = finish(ctx, r, {"outcome": "APPLIED", "verify": {"credential_id8": v.credential_id[:8]},
                           "undo": {"kind": "passkey.revoke", "params": {"credential_id": v.credential_id,
                                                                         "name": req["params"]["name"]}}}, actor=op)
    return 200, {"ok": True, "request": public_request(done),
                 "passkey": {"credential_id8": v.credential_id[:8], "name": req["params"]["name"]}}


# ── GET /state ──────────────────────────────────────────────────────────────────────────────────────────────────────


def _section(fn: Callable[[], dict]) -> dict:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — unreadable is UNAVAILABLE, never empty-green
        code = getattr(exc, "code", None) or type(exc).__name__
        return {"state": "UNAVAILABLE", "reason": f"{code}: {str(getattr(exc, 'detail', '') or exc)[:160]}"}


def jobs_view(ctx: Ctx) -> dict:
    text = ctx.hosts.crontab_read()
    lines = text.split("\n")
    active = [ln for ln in lines if C._is_active_cron(ln)]
    paused = [(ln, C.PAUSED_RE.match(ln.strip())) for ln in lines if C.PAUSED_RE.match(ln.strip())]
    matched: set[str] = set()
    rows = []
    for r in ctx.hosts.lane_registry().get("lanes") or []:
        s = r.get("scheduler") or {}
        if s.get("kind") != "cron":
            continue
        match = str(s.get("match") or "").strip()
        a = [ln for ln in active if match and match in ln]
        p = [(ln, m) for ln, m in paused if match and match in m.group(3)]
        matched.update(a)
        if len(a) == 1:
            st, line, pm = "ACTIVE", a[0], None
        elif len(a) > 1 or (not a and len(p) > 1):
            st, line, pm = "AMBIGUOUS", None, None
        elif len(p) == 1:
            st, line, pm = "PAUSED", p[0][0], p[0][1]
        else:
            st, line, pm = "ABSENT", None, None
        cmd = pm.group(3) if pm else line
        tokens = C.broker_tokens(cmd) if cmd else []
        rows.append({"lane_id": r.get("lane_id"), "registry_state": r.get("state"), "scheduler_kind": "cron",
                     "cron_state": st, "schedule": C.cron_schedule(cmd) if cmd else s.get("expression"),
                     "line_sha256": C.sha256_text(line) if line else None,
                     "display": C.redact(line) if line else None,
                     "paused_on": pm.group(1) if pm else None, "paused_note": pm.group(2) if pm else None,
                     "broker_class": bool(tokens), "broker_tokens": tokens, "note": (r.get("note") or "")[:200]})
    return {"state": "OK", "reason": None, "as_of": C.iso(ctx.clock()), "rows": rows,
            "unmatched_active_lines": len([ln for ln in active if ln not in matched])}


def n8n_view(ctx: Ctx) -> dict:
    from scripts.check_registry_runtime_truth import parse_live_lanes

    path = ctx.hosts.live_list_path
    try:
        live = parse_live_lanes(path.read_text(encoding="utf-8"))
        live_state, reason = "OK", None
    except OSError as exc:
        live, live_state, reason = [], "UNAVAILABLE", f"{path}: {type(exc).__name__}"
    rows = []
    for r in ctx.hosts.lane_registry().get("lanes") or []:
        s, d = r.get("scheduler") or {}, r.get("dispatch") or {}
        if not d and s.get("kind") != "n8n":
            continue
        rows.append({"lane_id": r.get("lane_id"), "stage": s.get("stage"), "mode": d.get("mode"),
                     "on_live_list": r.get("lane_id") in live if live_state == "OK" else None,
                     "workflow": s.get("workflow_id") or s.get("expression"), "registry_state": r.get("state")})
    return {"state": live_state, "reason": reason, "live_list_path": str(path), "live_lanes": live, "rows": rows}


def settings_view(ctx: Ctx, store_ok: bool) -> dict:
    cur = ctx.store.settings_all() if store_ok else {}
    rows = []
    for e in ctx.cfg.get("settings_catalog") or []:
        c = cur.get(e["key"]) or {}
        active = bool(c.get("active"))
        rows.append({"key": e["key"], "label": e.get("label"), "type": e.get("type"), "default": e.get("default"),
                     "default_source": e.get("default_source"), "current": c.get("value") if active else None,
                     "overridden": active, "min": e.get("min"), "max": e.get("max"), "choices": e.get("choices"),
                     "wired": bool(e.get("wired")), "consumer": e.get("consumer"),
                     "updated_at": _ts(c.get("updated_at")), "updated_by": c.get("updated_by")})
    hist = [{k: _ts(h.get(k)) for k in ("key", "op", "old_value", "new_value", "actor", "at", "request_id")}
            for h in (ctx.store.settings_history(50) if store_ok else [])]
    return {"state": "OK" if store_ok else "NOT_MIGRATED", "reason": None if store_ok else "migration not applied",
            "rows": rows, "history": hist}


def grants_view(ctx: Ctx) -> dict:
    tiers = ctx.hosts.guard_tiers()
    rc, out, err = ctx.hosts.guard("show")
    if rc != 0:
        raise C.OpsError("GUARD_SHOW_FAILED", (err or f"rc {rc}")[:160], 503)
    active = []
    for ln in ANSI_RE.sub("", out).splitlines():
        m = re.match(r"^\s+([a-z][a-z0-9-]+)\s+(\S+)\s+uses\s+(-?\d+)m left\s+id=(\S+)\s+—\s*(.*)$", ln)
        if m and m.group(1) in tiers:
            full = ctx.hosts.guard_id(m.group(1))
            active.append({"tier": m.group(1), "uses": m.group(2), "minutes_left": int(m.group(3)),
                           "grant_id8": m.group(4)[:8], "grant_id": full, "reason": m.group(5)[:200]})
    return {"state": "OK", "reason": None, "tiers": tiers, "active": active}


def data_approvals_view(ctx: Ctx) -> dict:
    doc = json.loads((ctx.hosts.code_root / C.AUTHORITY_REL).read_text(encoding="utf-8"))
    rows = [{"domain": p.get("domain"), "title": p.get("title"), "status": p.get("status")}
            for p in doc.get("proposed_domains") or []]
    return {"state": "OK", "rows": rows, "note": "Registry grants are a reviewed PR (§26.6); this tab is read-only."}


def release_view(ctx: Ctx) -> dict:
    from scripts.lib import release_control as RC

    v = RC.ReleaseControl(ctx.hosts.release_dir).view()
    return {"state": "OK", "mode": v.mode, "epoch": v.epoch, "latch": v.latch_state}


def applier_view(ctx: Ctx) -> dict:
    p = C.expand(ctx.cfg["applier"]["heartbeat_file"])
    try:
        hb = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "ABSENT", "heartbeat_at": None, "age_s": None,
                "reason": "no heartbeat: the applier unit is not installed or not running"}
    at = _aware(hb.get("at"))
    age = int((ctx.clock() - at).total_seconds()) if at else None
    stale = age is None or age > int(ctx.cfg["applier"].get("heartbeat_stale_s", 60))
    return {"state": "STALE" if stale else "OK", "heartbeat_at": hb.get("at"), "age_s": age,
            "reason": hb.get("note"), "policy": hb.get("policy")}


def build_state(ctx: Ctx, op: str) -> dict:
    store = _section(ctx.store.tables_status)
    store_ok = store.get("state") == "OK"
    creds = (_active_credentials(ctx) if store_ok else []) if True else []
    try:
        all_creds = ctx.store.credentials_list() if store_ok else []
    except Exception:  # noqa: BLE001
        all_creds = []
    try:
        totp_row = ctx.store.totp_get() if store_ok else None
    except Exception:  # noqa: BLE001
        totp_row = None
    audit_rows: list[dict] = []
    requests: list[dict] = []
    if store_ok:
        reqs = {r["request_id"]: r for r in ctx.store.list_requests(50)}
        for a in ctx.store.list_audit(200):
            rq = reqs.get(a.get("request_id") or "")
            pr = public_request(rq) if rq and a.get("action") == "request.applied" else None
            audit_rows.append({"seq": a["seq"], "at": _ts(a["at"]), "actor": a["actor"], "action": a["action"],
                               "kind": a.get("kind"), "request_id": a.get("request_id"), "outcome": a["outcome"],
                               "detail": a.get("detail") or {},
                               "undo_available": bool(pr and (pr.get("undo") or {}).get("available"))})
        requests = [public_request(r) for r in list(reqs.values())[:20]]
    return {
        "ok": True, "schema": SCHEMA_STATE, "as_of": C.iso(ctx.clock()), "operator": op,
        "policy": C.policy_state(ctx.agents_path), "store": store, "applier": _section(lambda: applier_view(ctx)),
        "factors": {"webauthn_library": "available" if A.webauthn_available() else "missing",
                    "hmac_key": "present" if ctx.hmac_key() else "missing",
                    "totp": "enrolled" if totp_row and ctx.totp_secret() else "not_enrolled",
                    "passkeys_active": len(creds)},
        "kinds": C.kinds_view(),
        "jobs": _section(lambda: jobs_view(ctx)),
        "n8n": _section(lambda: n8n_view(ctx)),
        "settings": _section(lambda: settings_view(ctx, store_ok)),
        "grants": _section(lambda: grants_view(ctx)),
        "data_approvals": _section(lambda: data_approvals_view(ctx)),
        "release_train": _section(lambda: release_view(ctx)),
        "passkeys": [{"credential_id": c["credential_id"], "credential_id8": c["credential_id"][:8],
                      "name": c["name"], "created_at": _ts(c.get("created_at")),
                      "last_used_at": _ts(c.get("last_used_at")), "revoked_at": _ts(c.get("revoked_at"))}
                     for c in all_creds],
        "audit": {"state": store.get("state"), "rows": audit_rows},
        "requests": requests,
    }
