"""Command Center authentication policy (2026-10-14, SPCX incident security review).

Pure policy + config + token store. portfolio_server.py calls :func:`evaluate_request` before any
route runs; nothing here does I/O on the request path except the decision log and an mtime-cached
read of the service-token file.

Trust model (config/cc_auth.yaml has the full rationale):

* ``serve_proxy`` listener (127.0.0.1:7779) — the only target ``tailscale serve`` proxies to.
  ``tailscale serve`` strips client-supplied ``Tailscale-User-*`` headers and sets them from the
  tailnet identity, so here — and ONLY here — ``Tailscale-User-Login`` is trusted.
* ``service`` listener (127.0.0.1:7777) — loopback callers. A per-host service token (0600 file
  outside the repo) is required; ``Tailscale-User-*`` headers are ignored because any local process
  can forge them on a direct connection.
* Step-up: dangerous route classes call :func:`require_step_up`. With ``step_up.totp`` disabled (the
  default) or no enrolled secret it always refuses ("TOTP unlock not yet enabled"). When enabled, a
  verified authenticator code (POST :data:`STEP_UP_ENDPOINT`, scripts/lib/cc_totp.py) grants a short
  unlock bound to the tailnet login AND the action class, on the serve_proxy listener only. The
  service-token listener never satisfies step-up.

Residual risk (documented, out of scope): a process running as the service user (or root) can read
the token file and can connect to the serve_proxy socket and forge the identity header. With
transport: unix (default) other local uids cannot; with transport: tcp any local uid can. Same-uid /
root access is host compromise; the broker read-only lock and Schwab app control are the controls.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import stat
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.header import decode_header, make_header
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from lib import cc_totp as _totp  # noqa: E402
except ImportError:  # pragma: no cover — imported as scripts.lib.cc_auth, or run as a script (cc_curl.sh)
    try:
        from scripts.lib import cc_totp as _totp  # noqa: E402
    except ImportError:
        import cc_totp as _totp  # type: ignore[no-redef]  # noqa: E402  (sys.path[0] = scripts/lib)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ENV = "TRADEAI_CC_AUTH_CONFIG"
ENFORCE_ENV = "TRADEAI_CC_AUTH_ENFORCE"
REPORT_ONLY_ENV = "TRADEAI_CC_AUTH_REPORT_ONLY"
TOKEN_FILE_ENV = "TRADEAI_CC_SERVICE_TOKEN_FILE"

LISTENER_SERVICE = "service"
LISTENER_SERVE_PROXY = "serve_proxy"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

STEP_UP_MESSAGE = "step-up required — TOTP unlock not yet enabled"
STEP_UP_CODE_MESSAGE = "step-up required — enter your authenticator code"
STEP_UP_SERVICE_MESSAGE = "step-up required — the service-token listener never satisfies step-up"
STEP_UP_NOT_UNLOCKABLE_MESSAGE = "step-up required — this action class is not unlockable by TOTP (config)"
STEP_UP_ENDPOINT = "/api/v2/auth/step-up"
STEP_UP_STATUS_ENDPOINT = "/api/v2/auth/step-up/status"
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def default_config_path() -> Path:
    override = os.environ.get(CONFIG_ENV)
    return Path(override).expanduser() if override else REPO_ROOT / "config" / "cc_auth.yaml"


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class StepUpRoute:
    action: str
    methods: frozenset[str]
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class CCAuthConfig:
    enforce: bool
    report_only: bool
    allowed_logins: frozenset[str]
    identity_header: str
    service_host: str
    service_port: int
    serve_proxy_enabled: bool
    serve_proxy_transport: str
    serve_proxy_unix_socket: Path | None
    serve_proxy_host: str
    serve_proxy_port: int
    token_header: str
    token_file: Path | None
    token_min_length: int
    accept_bearer: bool
    service_exempt_paths: frozenset[str]
    decision_log: Path | None
    step_up_mode: str
    step_up_service_token_bypass: bool
    step_up_routes: tuple[StepUpRoute, ...]
    cors_allowed_origins: frozenset[str] = frozenset()
    csrf_allowed_fetch_sites: frozenset[str] = frozenset({"same-origin", "none"})
    csrf_hard_routes: tuple[StepUpRoute, ...] = ()
    csrf_stop_routes: tuple[StepUpRoute, ...] = ()
    csrf_form_routes: tuple[StepUpRoute, ...] = ()
    always_refuse_routes: tuple[StepUpRoute, ...] = ()
    totp: _totp.TotpSettings = field(default_factory=_totp.TotpSettings)
    source: str = ""
    load_error: str = ""


def _path_or_none(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value)).expanduser()


def _socket_path(value: Any) -> Path | None:
    """Expand ~ and $VARS; an unresolved variable yields None (listener then refuses to start)."""
    if value in (None, ""):
        return None
    expanded = os.path.expanduser(os.path.expandvars(str(value)))
    if "$" in expanded or not os.path.isabs(expanded):
        return None
    return Path(expanded)


def _routes(items: Any) -> tuple[StepUpRoute, ...]:
    out = []
    for r in items or []:
        out.append(StepUpRoute(
            action=str(r["action"]),
            methods=frozenset(str(m).upper() for m in (r.get("methods") or ["POST"])),
            pattern=re.compile(str(r["pattern"])),
        ))
    return tuple(out)


def config_from_mapping(raw: Mapping[str, Any], *, source: str = "", load_error: str = "",
                        apply_env: bool = True) -> CCAuthConfig:
    """Build a config from the ``cc_auth`` mapping. Missing keys fail CLOSED (enforce, empty allowlist)."""
    sec = dict(raw.get("cc_auth", raw) or {})
    listeners = dict(sec.get("listeners") or {})
    svc = dict(listeners.get(LISTENER_SERVICE) or {})
    sp = dict(listeners.get(LISTENER_SERVE_PROXY) or {})
    tok = dict(sec.get("service_token") or {})
    su = dict(sec.get("step_up") or {})
    routes = _routes(su.get("routes"))
    csrf = dict(sec.get("csrf") or {})
    enforce = bool(sec.get("enforce", True))
    report_only = bool(sec.get("report_only", False))
    token_file = _path_or_none(tok.get("file"))
    if apply_env:
        e = _env_bool(ENFORCE_ENV)
        if e is not None:
            enforce = e
        r = _env_bool(REPORT_ONLY_ENV)
        if r is not None:
            report_only = r
        if os.environ.get(TOKEN_FILE_ENV):
            token_file = Path(os.environ[TOKEN_FILE_ENV]).expanduser()
    mode = str(su.get("mode", "enforce")).strip().lower()
    if mode not in {"enforce", "report_only", "off"}:
        mode = "enforce"
    return CCAuthConfig(
        enforce=enforce,
        report_only=report_only,
        allowed_logins=frozenset(str(x).strip().lower() for x in (sec.get("allowed_logins") or []) if str(x).strip()),
        identity_header=str(sec.get("identity_header") or "Tailscale-User-Login"),
        service_host=str(svc.get("host") or ""),
        service_port=int(svc.get("port") or 0),
        serve_proxy_enabled=bool(sp.get("enabled", False)),
        serve_proxy_transport=str(sp.get("transport") or "tcp").strip().lower(),
        serve_proxy_unix_socket=_socket_path(sp.get("unix_socket")),
        serve_proxy_host=str(sp.get("host") or ""),
        serve_proxy_port=int(sp.get("port") or 0),
        token_header=str(tok.get("header") or "X-TradeAI-Service-Token"),
        token_file=token_file,
        token_min_length=int(tok.get("min_length") or 32),
        accept_bearer=bool(tok.get("accept_bearer", True)),
        service_exempt_paths=frozenset(str(p) for p in (sec.get("service_exempt_paths") or [])),
        decision_log=_path_or_none(sec.get("decision_log")),
        step_up_mode=mode,
        step_up_service_token_bypass=bool(su.get("service_token_bypass", False)),
        step_up_routes=routes,
        cors_allowed_origins=frozenset(str(o).strip().rstrip("/") for o in (csrf.get("allowed_origins") or []) if str(o).strip()),
        csrf_allowed_fetch_sites=frozenset(str(x).strip().lower() for x in (csrf.get("allowed_fetch_sites") or ["same-origin", "none"])),
        csrf_hard_routes=_routes(csrf.get("hard_routes")),
        csrf_stop_routes=_routes(csrf.get("stop_routes")),
        csrf_form_routes=_routes(csrf.get("form_routes")),
        always_refuse_routes=_routes(sec.get("always_refuse")),
        totp=_totp.settings_from_mapping(su.get("totp")),
        source=source,
        load_error=load_error,
    )


def load_config(path: Path | str | None = None) -> CCAuthConfig:
    p = Path(path).expanduser() if path else default_config_path()
    try:
        import yaml  # noqa: WPS433
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("config root is not a mapping")
        return config_from_mapping(raw, source=str(p))
    except Exception as exc:  # fail CLOSED: enforce, no allowlist, no token => every gated route denied
        return config_from_mapping({}, source=str(p), load_error=f"{type(exc).__name__}: {exc}")


# ── service token ────────────────────────────────────────────────────────────

class ServiceTokenStore:
    """mtime-cached reader for the per-host service-token file. Never logs the value."""

    def __init__(self, path: Path | None, min_length: int = 32):
        self.path = path
        self.min_length = min_length
        self._lock = threading.Lock()
        self._sig: tuple[int, int, int] | None = None
        self._token: str = ""
        self.problem: str = ""

    def token(self) -> str:
        if self.path is None:
            self.problem = "no service_token.file configured"
            return ""
        try:
            st = os.stat(self.path)
        except OSError:
            self.problem = f"service token file missing: {self.path}"
            self._sig, self._token = None, ""
            return ""
        sig = (st.st_mtime_ns, st.st_size, st.st_mode)
        with self._lock:
            if sig == self._sig:
                return self._token
            self._sig = sig
            self._token = ""
            if not stat.S_ISREG(st.st_mode):
                self.problem = "service token path is not a regular file"
                return ""
            if st.st_mode & 0o077:
                self.problem = f"service token file mode {oct(st.st_mode & 0o777)} is group/other accessible; chmod 600"
                return ""
            try:
                value = Path(self.path).read_text(encoding="utf-8").strip()
            except OSError as exc:
                self.problem = f"service token unreadable: {type(exc).__name__}"
                return ""
            if len(value) < self.min_length:
                self.problem = f"service token shorter than {self.min_length} chars"
                return ""
            self.problem = ""
            self._token = value
            return value


def read_service_token(cfg: CCAuthConfig) -> str:
    return ServiceTokenStore(cfg.token_file, cfg.token_min_length).token()


# ── decisions ────────────────────────────────────────────────────────────────

@dataclass
class Decision:
    allowed: bool
    status: int = 200
    reason: str = ""
    listener: str = ""
    principal: str = ""
    would_deny: bool = False
    step_up_action: str | None = None
    kind: str = "auth"  # auth | step_up
    detail: dict = field(default_factory=dict)


def _header_values(headers: Any, name: str) -> list[str]:
    if headers is None:
        return []
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        return [str(v) for v in (get_all(name) or [])]
    for k, v in dict(headers).items():
        if str(k).lower() == name.lower():
            return [str(v)] if not isinstance(v, (list, tuple)) else [str(x) for x in v]
    return []


def decode_identity(value: str) -> str:
    """RFC2047-decode a Tailscale identity header value (Tailscale may Q-encode non-ASCII)."""
    v = (value or "").strip()
    if "=?" in v:
        try:
            v = str(make_header(decode_header(v)))
        except Exception:
            return ""
    return v.strip()


def _norm_path(path: str) -> str:
    p = (path or "").split("?", 1)[0]
    return p.rstrip("/") if p != "/" else p


def _match(routes: tuple[StepUpRoute, ...], method: str, path: str) -> str | None:
    m = (method or "").upper()
    p = _norm_path(path)
    for r in routes:
        if m in r.methods and r.pattern.fullmatch(p):
            return r.action
    return None


def step_up_action(cfg: CCAuthConfig, method: str, path: str) -> str | None:
    return _match(cfg.step_up_routes, method, path)


def refused_action(cfg: CCAuthConfig, method: str, path: str) -> str | None:
    return _match(cfg.always_refuse_routes, method, path)


def csrf_class(cfg: CCAuthConfig, method: str, path: str) -> str:
    """hard (enforced even in report_only / enforce:false) | stop (same-origin only) | normal."""
    if _match(cfg.csrf_hard_routes, method, path):
        return "hard"
    if _match(cfg.csrf_stop_routes, method, path):
        return "stop"
    return "normal"


def cors_allow_origin(cfg: CCAuthConfig, headers: Any) -> str | None:
    """The request Origin when it is on the allowlist (echo it back as ACAO), else None."""
    vals = _header_values(headers, "Origin")
    if len(vals) != 1:
        return None
    o = vals[0].strip().rstrip("/")
    return o if o in cfg.cors_allowed_origins else None


def csrf_check(cfg: CCAuthConfig, listener: str, method: str, path: str, headers: Any) -> tuple[bool, str]:
    """Cross-site request forgery check for state-changing methods (WS4-03).

    tailscale serve stamps the operator's identity on ANY request from the operator's device,
    including one a hostile page forged, so identity alone is not enough:
      * Origin, when present, must be on csrf.allowed_origins ("null" never is);
      * Sec-Fetch-Site, when present, must be same-origin or none;
      * on the serve_proxy listener a request carrying NEITHER header is refused (every modern
        browser sends them on a cross-site POST; a non-browser client belongs on the service listener);
      * a request with a body must be Content-Type: application/json (a cross-site "simple request"
        cannot set it without a preflight). Stop-direction routes skip only this content-type rule.
    """
    m = (method or "").upper()
    if m not in STATE_CHANGING_METHODS:
        return True, ""
    origins = _header_values(headers, "Origin")
    sites = _header_values(headers, "Sec-Fetch-Site")
    if len(origins) > 1 or len(sites) > 1:
        return False, "csrf: duplicate Origin/Sec-Fetch-Site"
    if origins and origins[0].strip().rstrip("/") not in cfg.cors_allowed_origins:
        return False, "csrf: Origin not on allowlist"
    if sites and sites[0].strip().lower() not in cfg.csrf_allowed_fetch_sites:
        return False, "csrf: cross-site request (Sec-Fetch-Site)"
    form_route = _match(cfg.csrf_form_routes, m, path) is not None
    if not origins and not sites and (listener == LISTENER_SERVE_PROXY or form_route):
        return False, "csrf: no Origin or Sec-Fetch-Site on a browser state-changing request"
    if csrf_class(cfg, m, path) != "stop" and _has_body(headers):
        ctype = (_header_values(headers, "Content-Type") or [""])[0].split(";", 1)[0].strip().lower()
        allowed = {"application/json", "application/x-www-form-urlencoded"} if form_route else {"application/json"}
        if ctype not in allowed:
            return False, "csrf: Content-Type must be application/json"
    return True, ""


def _has_body(headers: Any) -> bool:
    if _header_values(headers, "Transfer-Encoding"):
        return True
    cl = (_header_values(headers, "Content-Length") or ["0"])[0].strip()
    try:
        return int(cl) > 0
    except ValueError:
        return True


# ── authenticated principal for the current request thread ─────────────────
# Set by portfolio_server's gate; read by handlers that must attribute an action (e.g. the audit
# actor of a secret write) to the AUTHENTICATED identity, never to a request-body field.
_REQ = threading.local()


def set_request_principal(principal: str | None) -> None:
    _REQ.principal = principal or ""


def current_principal() -> str:
    """Authenticated principal of this request thread ("tailnet:<login>" / "service-token"), or ""."""
    return getattr(_REQ, "principal", "") or ""


def authenticated_principal(d: "Decision") -> str:
    if d.allowed and not d.would_deny and (d.principal.startswith("tailnet:") or d.principal == "service-token"):
        return d.principal
    return ""


_MANAGERS: dict[tuple, "_totp.StepUpManager"] = {}
_MANAGERS_LOCK = threading.Lock()


def step_up_manager(cfg: CCAuthConfig) -> "_totp.StepUpManager":
    """One manager (and so one in-memory unlock table) per TOTP settings + decision log."""
    key = (cfg.totp, str(cfg.decision_log or ""))
    with _MANAGERS_LOCK:
        mgr = _MANAGERS.get(key)
        if mgr is None:
            mgr = _totp.StepUpManager(cfg.totp, log=lambda row, _c=cfg: record_step_up_event(_c, row))
            _MANAGERS[key] = mgr
        return mgr


def _step_up_refusal(action: str) -> Decision:
    """The pre-TOTP refusal, unchanged: used whenever TOTP is disabled or not enrolled."""
    return Decision(allowed=False, status=403, reason=STEP_UP_MESSAGE, step_up_action=action, kind="step_up")


def require_step_up(request: Any, action: str, *, cfg: CCAuthConfig | None = None, listener: str = "",
                    principal: str = "") -> Decision:
    """Step-up hook for dangerous routes.

    Refuses exactly as before (STEP_UP_MESSAGE) unless ``cfg.totp`` is enabled AND an activated secret
    file exists. When active: allowed only on the serve_proxy listener, for an authenticated
    ``tailnet:`` principal holding an unexpired unlock for THIS action class.
    """
    if cfg is None:
        return _step_up_refusal(action)
    mgr = step_up_manager(cfg)
    active, _why = mgr.status()
    if not active:
        return _step_up_refusal(action)
    if listener != LISTENER_SERVE_PROXY:
        return Decision(False, 403, STEP_UP_SERVICE_MESSAGE, step_up_action=action, kind="step_up",
                        detail={"step_up_available": False})
    if action not in cfg.totp.actions:
        return Decision(False, 403, STEP_UP_NOT_UNLOCKABLE_MESSAGE, step_up_action=action, kind="step_up",
                        detail={"step_up_available": False})
    if principal.startswith("tailnet:") and mgr.is_unlocked(principal, action):
        return Decision(True, 200, "step-up unlock", step_up_action=action, kind="step_up",
                        detail={"step_up_used": action,
                                "step_up_unlocked_until": mgr.unlocked_until(principal, action)})
    return Decision(False, 403, STEP_UP_CODE_MESSAGE, step_up_action=action, kind="step_up",
                    detail={"step_up_available": True, "step_up_endpoint": STEP_UP_ENDPOINT})


def _step_up_caller_problem(cfg: CCAuthConfig, listener: str, principal: str) -> str:
    if listener != LISTENER_SERVE_PROXY:
        return STEP_UP_SERVICE_MESSAGE
    if not principal.startswith("tailnet:") or principal[len("tailnet:"):] not in cfg.allowed_logins:
        return "step-up needs an authenticated tailnet login (via tailscale serve)"
    return ""


def handle_step_up(cfg: CCAuthConfig, listener: str, principal: str, body: Any) -> tuple[int, dict]:
    """POST /api/v2/auth/step-up {action, code}. ``principal`` must be authenticated_principal(decision)."""
    b = body if isinstance(body, dict) else {}
    action = str(b.get("action") or "").strip()
    problem = _step_up_caller_problem(cfg, listener, principal)
    if not problem and action not in {r.action for r in cfg.step_up_routes}:
        problem = "unknown step-up action"
    if not problem and action not in cfg.totp.actions:
        problem = STEP_UP_NOT_UNLOCKABLE_MESSAGE
    if problem:
        record_step_up_event(cfg, {"outcome": "refused", "status": 403, "reason": problem, "listener": listener,
                                   "principal": principal, "step_up_action": action or None})
        return 403, {"ok": False, "action": action, "error": problem}
    return step_up_manager(cfg).verify(principal=principal, action=action, code=b.get("code"))


def step_up_status(cfg: CCAuthConfig, listener: str, principal: str, action: str) -> dict:
    """GET /api/v2/auth/step-up/status?action= — says only enabled / unlockable / unlocked-until."""
    mgr = step_up_manager(cfg)
    active, why = mgr.status()
    caller = _step_up_caller_problem(cfg, listener, principal)
    until = mgr.unlocked_until(principal, action) if (active and not caller and action) else 0.0
    return {
        "ok": True,
        "enabled": active,
        "reason": "" if active else why.split(":", 1)[0],
        "action": action,
        "unlockable": bool(action) and action in cfg.totp.actions,
        "available_here": active and not caller,
        "unlocked_until": until or None,
        "unlock_seconds": cfg.totp.unlock_seconds,
    }


def _token_presented(cfg: CCAuthConfig, headers: Any) -> str:
    vals = _header_values(headers, cfg.token_header)
    if len(vals) == 1 and vals[0].strip():
        return vals[0].strip()
    if cfg.accept_bearer:
        auth = _header_values(headers, "Authorization")
        if len(auth) == 1 and auth[0].startswith("Bearer "):
            return auth[0][len("Bearer "):].strip()
    return ""


def _authenticate(cfg: CCAuthConfig, listener: str, method: str, path: str, headers: Any,
                  token_store: ServiceTokenStore) -> Decision:
    if listener == LISTENER_SERVE_PROXY:
        vals = _header_values(headers, cfg.identity_header)
        if len(vals) != 1:
            why = "no tailnet identity (tagged device, Funnel, or not via tailscale serve)" if not vals else "ambiguous identity header"
            return Decision(False, 403, why, listener)
        login = decode_identity(vals[0]).lower()
        if not login or login not in cfg.allowed_logins:
            return Decision(False, 403, "tailnet login not in allowed_logins", listener, principal=login)
        return Decision(True, 200, "tailnet identity allowed", listener, principal=f"tailnet:{login}")

    # service listener (and any unknown role is treated as the stricter service listener)
    p = path.split("?", 1)[0]
    if (method or "").upper() == "GET" and p in cfg.service_exempt_paths:
        return Decision(True, 200, "exempt liveness path", listener, principal="exempt")
    presented = _token_presented(cfg, headers)
    expected = token_store.token()
    if presented and expected and hmac.compare_digest(presented.encode(), expected.encode()):
        return Decision(True, 200, "service token", listener, principal="service-token")
    if not expected:
        reason = f"service token not configured ({token_store.problem})"
    elif presented:
        reason = "service token mismatch"
    else:
        reason = "service token required"
    d = Decision(False, 401, reason, listener)
    if _header_values(headers, cfg.identity_header):
        # Ignored on purpose; recorded so report_only logs reveal proxied traffic still aimed at :7777.
        d.detail["ignored_identity_header"] = True
    return d


REFUSED_MESSAGE = ("refused: secret writes are CLI-only until operator step-up (TOTP) exists — "
                   "no web identity may write credentials")


def evaluate_request(cfg: CCAuthConfig, listener: str, method: str, path: str, headers: Any,
                     token_store: ServiceTokenStore, request: Any = None) -> Decision:
    if (method or "").upper() == "OPTIONS":
        return Decision(True, 200, "CORS preflight", listener, principal="preflight")

    # Hard refusals (WS4-02): independent of enforce, report_only, listener and step-up mode.
    refused = refused_action(cfg, method, path)
    if refused:
        return Decision(False, 403, REFUSED_MESSAGE, listener, step_up_action=refused, kind="refused")

    # CSRF (WS4-03). Hard-class routes are enforced even in report_only and with enforce:false.
    csrf_would_deny = None
    ok, why = csrf_check(cfg, listener, method, path, headers)
    if not ok:
        cls = csrf_class(cfg, method, path)
        d = Decision(False, 403, why, listener, kind="csrf", detail={"csrf_class": cls})
        if cls == "hard" or (cfg.enforce and not cfg.report_only):
            return d
        if cfg.enforce:  # report_only: log, allow, never count as authenticated
            d.allowed, d.would_deny = True, True
            csrf_would_deny = d

    if not cfg.enforce:
        return Decision(True, 200, "cc_auth disabled", listener, principal="disabled")

    auth = _authenticate(cfg, listener, method, path, headers, token_store)
    if not auth.allowed:
        if cfg.report_only:
            auth.would_deny = True
            auth.allowed = True
        else:
            return auth
    if csrf_would_deny is not None and not auth.would_deny:
        csrf_would_deny.principal = auth.principal
        auth = csrf_would_deny  # allowed + logged; would_deny keeps it from counting as authenticated

    action = step_up_action(cfg, method, path)
    if action and cfg.step_up_mode != "off":
        if cfg.step_up_service_token_bypass and auth.principal == "service-token" and not auth.would_deny:
            return auth
        su = require_step_up(request, action, cfg=cfg, listener=listener,
                             principal="" if auth.would_deny else auth.principal)
        su.listener = listener
        su.principal = auth.principal
        if su.allowed:
            auth.step_up_action = action
            auth.detail.update(su.detail)
            return auth
        if cfg.step_up_mode == "report_only":
            su.allowed = True
            su.would_deny = True
        return su
    return auth


# ── decision log ─────────────────────────────────────────────────────────────

_LOG_LOCK = threading.Lock()


def record_decision(cfg: CCAuthConfig, d: Decision, method: str, path: str, client: str = "",
                    user_agent: str = "") -> None:
    """Append non-plain-allow decisions (and step-up unlock uses) as JSONL. Never raises; never logs a token."""
    if d.allowed and not d.would_deny and not d.detail.get("step_up_used"):
        return
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "outcome": "would_deny" if d.would_deny else ("allow_step_up" if d.allowed else "deny"),
        "kind": d.kind,
        "status": d.status,
        "listener": d.listener,
        "method": method,
        "path": path.split("?", 1)[0][:300],
        "reason": d.reason,
        "principal": d.principal,
        "step_up_action": d.step_up_action,
        "client": client,
        "user_agent": (user_agent or "")[:120],
        **d.detail,
    }
    try:
        print(f"  [cc-auth] {row['outcome']} {d.kind} {d.status} {d.listener} {method} {row['path']} — {d.reason}", flush=True)
    except Exception:
        pass
    if cfg.decision_log is None:
        return
    try:
        with _LOG_LOCK:
            cfg.decision_log.parent.mkdir(parents=True, exist_ok=True)
            with open(cfg.decision_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception:
        pass


def record_step_up_event(cfg: CCAuthConfig, row: Mapping[str, Any]) -> None:
    """Step-up verification attempts (unlocked / fail / replay / lockout / refused). Never the code."""
    full = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "step_up_verify",
            "method": "POST", "path": STEP_UP_ENDPOINT, **{k: v for k, v in row.items() if k != "code"}}
    try:
        print(f"  [cc-auth] step-up {full.get('outcome')} {full.get('step_up_action')} {full.get('principal')} "
              f"— {full.get('reason')}", flush=True)
    except Exception:
        pass
    if cfg.decision_log is None:
        return
    try:
        with _LOG_LOCK:
            cfg.decision_log.parent.mkdir(parents=True, exist_ok=True)
            with open(cfg.decision_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(full, sort_keys=True, default=str) + "\n")
    except Exception:
        pass


def denial_body(d: Decision, wants_html: bool) -> tuple[str, bytes]:
    if d.kind == "refused":
        title = "Refused"
        msg = ("Credential writes are not accepted from the Command Center until operator step-up "
               "(TOTP) exists. Use the CLI on the host. Nothing was written.")
    elif d.kind == "csrf":
        title = "Cross-site request refused"
        msg = ("State-changing requests must come from the Command Center page itself (same origin, "
               "JSON body). This one did not, so it was refused and nothing changed.")
    elif d.kind == "step_up" and d.detail.get("step_up_available"):
        title = "Step-up required"
        msg = (f"This action ({d.step_up_action}) needs a second factor. Enter the 6-digit code from "
               "your authenticator in the Command Center prompt, then retry. Nothing was sent anywhere.")
    elif d.kind == "step_up" and d.reason != STEP_UP_MESSAGE:
        title = "Step-up required"
        msg = (f"This action ({d.step_up_action}) needs a second factor this caller cannot provide. "
               "Nothing was sent anywhere.")
    elif d.kind == "step_up":
        title = "Step-up required"
        msg = (f"This action ({d.step_up_action}) needs a second factor. TOTP unlock is not enabled "
               "yet, so it is refused from the Command Center. Nothing was sent anywhere.")
    elif d.status == 401:
        title = "Service token required"
        msg = "Direct loopback callers must send the per-host Command Center service token."
    else:
        title = "Not authorized"
        msg = ("The Command Center only answers requests that arrive through tailscale serve from a "
               "tailnet login on the allowlist. Tagged devices and Funnel traffic carry no identity.")
    if not wants_html:
        body = {"ok": False, "error": d.reason, "auth": d.kind, "step_up_action": d.step_up_action}
        if d.kind == "step_up" and "step_up_available" in d.detail:  # TOTP active; absent when disabled
            body["step_up"] = {"available": bool(d.detail["step_up_available"]),
                               "endpoint": d.detail.get("step_up_endpoint")}
        return "application/json", json.dumps(body).encode()
    import html as _html
    page = (
        "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        f"<title>{_html.escape(title)}</title>"
        "<body style='font:16px system-ui;max-width:36rem;margin:3rem auto;padding:0 1rem'>"
        f"<h1 style='font-size:1.4rem'>{_html.escape(title)}</h1><p>{_html.escape(msg)}</p>"
        f"<p style='color:#666'>Reason: {_html.escape(d.reason)} (HTTP {d.status})</p></body>"
    )
    return "text/html; charset=utf-8", page.encode()


UNIX_SOCKET_MAX_PATH = 104  # portable sun_path limit (Linux 108, macOS 104)


def serve_proxy_bind_ok(cfg: CCAuthConfig) -> bool:
    if not cfg.serve_proxy_enabled:
        return False
    if cfg.serve_proxy_transport == "unix":
        p = cfg.serve_proxy_unix_socket
        return p is not None and len(str(p).encode()) < UNIX_SOCKET_MAX_PATH
    if cfg.serve_proxy_transport == "tcp":
        return cfg.serve_proxy_host in LOOPBACK_HOSTS and cfg.serve_proxy_port > 0
    return False


def serve_proxy_target(cfg: CCAuthConfig) -> str:
    """The exact `tailscale serve` target for this config."""
    if cfg.serve_proxy_transport == "unix":
        return f"unix:{cfg.serve_proxy_unix_socket}"
    return f"http://{cfg.serve_proxy_host}:{cfg.serve_proxy_port}"


def iter_step_up_routes(cfg: CCAuthConfig) -> Iterable[tuple[str, str, str]]:
    for r in cfg.step_up_routes:
        yield r.action, ",".join(sorted(r.methods)), r.pattern.pattern


def _token_status(cfg: CCAuthConfig) -> str:
    store = ServiceTokenStore(cfg.token_file, cfg.token_min_length)
    return "ok" if store.token() else store.problem


def _main(argv: list[str]) -> int:
    """``--client-settings``: header, token-file path, service port (one per line; never the token)."""
    cfg = load_config()
    if argv[1:2] == ["--client-settings"]:
        print(cfg.token_header)
        print(str(cfg.token_file or ""))
        print(cfg.service_port)
        return 0
    if argv[1:2] == ["--describe"]:
        print(json.dumps({
            "source": cfg.source, "load_error": cfg.load_error, "enforce": cfg.enforce,
            "report_only": cfg.report_only, "allowed_logins": sorted(cfg.allowed_logins),
            "service": f"{cfg.service_host}:{cfg.service_port}",
            "serve_proxy": serve_proxy_target(cfg) if cfg.serve_proxy_enabled else None,
            "serve_proxy_bind_ok": serve_proxy_bind_ok(cfg),
            "token_file": str(cfg.token_file), "token_status": _token_status(cfg),
            "step_up_mode": cfg.step_up_mode,
            "step_up_totp": {"enabled_in_config": cfg.totp.enabled,
                             "status": step_up_manager(cfg).status(read_secret=False)[1] or "file present (stat only)",
                             "actions": sorted(cfg.totp.actions), "unlock_seconds": cfg.totp.unlock_seconds},
            "step_up_routes": [list(r) for r in iter_step_up_routes(cfg)],
            "always_refuse": [[r.action, ",".join(sorted(r.methods)), r.pattern.pattern] for r in cfg.always_refuse_routes],
            "cors_allowed_origins": sorted(cfg.cors_allowed_origins),
            "csrf_hard_routes": [[r.action, r.pattern.pattern] for r in cfg.csrf_hard_routes],
            "csrf_stop_routes": [[r.action, r.pattern.pattern] for r in cfg.csrf_stop_routes],
        }, indent=2))
        return 0
    print("usage: cc_auth.py --client-settings | --describe")
    return 2


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(_main(_sys.argv))
