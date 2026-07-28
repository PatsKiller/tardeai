"""Active Trader P3 — operator-signed momentum-scalp SESSION CONTROL plane.

SIMULATION / SHADOW ONLY. This module is safety-critical trading-automation
scaffolding that must stay 100% inert:

  * No live broker adapter, no real 2FA, no live credential read.
  * No real order is ever queued, submitted, modified, or cancelled.
  * LIVE activation is *impossible* here — it always returns FEATURE_DISABLED
    (see LIVE_ACTIVATION_ENABLED, hard-wired False).
  * No LLM/agent determines any financial value — every bound limit is an
    operator-supplied number that flows through deterministic code only.
  * No network I/O and no writes to trading/order DB tables. The only optional
    persistence is a JSON snapshot of the session store under data/active_trader/.

This is the server-side CONTROL service (create/validate/authorize/activate the
operator session) and is deliberately SEPARATE from the GET read plane
(read_api.py / read_http.py). It is implemented as pure functions over a small
store abstraction (in-memory dict + optional JSON file). Deterministic given the
same inputs.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

CONTRACT = "active-trader-p3-session-control-v1"

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD — live activation is not implementable in this module.
# There is no code path that flips this True; LIVE always -> FEATURE_DISABLED.
LIVE_ACTIVATION_ENABLED: bool = False
FEATURE_DISABLED = "FEATURE_DISABLED"

# ---------------------------------------------------------------------------
# Lifecycle states
EDITING = "EDITING"
SAVED = "SAVED"
VALIDATED = "VALIDATED"
AUTHORIZATION_REVIEW = "AUTHORIZATION_REVIEW"
TWO_FA_REQUIRED = "TWO_FA_REQUIRED"
AUTHORIZED = "AUTHORIZED"
ACTIVE = "ACTIVE"
ENTRY_CUTOFF = "ENTRY_CUTOFF"
DRAINING = "DRAINING"
CLOSED = "CLOSED"

# Side / terminal states
PAUSED = "PAUSED"
REVOKED = "REVOKED"
KILLED = "KILLED"
FAILED_RECONCILIATION = "FAILED_RECONCILIATION"

# Terminal states — no outbound transitions except (for FAILED_RECONCILIATION)
# an operator kill/close.
TERMINAL_STATES = frozenset({CLOSED, REVOKED, KILLED})

# Modes accepted by activate(). LIVE is accepted as an *input* only so it can be
# explicitly and safely refused.
SIMULATION = "SIMULATION"
SHADOW = "SHADOW"
LIVE = "LIVE"
SAFE_MODES = frozenset({SIMULATION, SHADOW})

# Legal transition map. A transition not present here is illegal.
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    EDITING: frozenset({SAVED, REVOKED, KILLED}),
    SAVED: frozenset({EDITING, VALIDATED, REVOKED, KILLED}),
    VALIDATED: frozenset({EDITING, SAVED, AUTHORIZATION_REVIEW, REVOKED, KILLED}),
    AUTHORIZATION_REVIEW: frozenset({TWO_FA_REQUIRED, EDITING, REVOKED, KILLED}),
    TWO_FA_REQUIRED: frozenset({AUTHORIZED, AUTHORIZATION_REVIEW, EDITING, REVOKED, KILLED}),
    AUTHORIZED: frozenset({ACTIVE, EDITING, PAUSED, REVOKED, KILLED}),
    ACTIVE: frozenset({ENTRY_CUTOFF, PAUSED, DRAINING, REVOKED, KILLED, FAILED_RECONCILIATION}),
    ENTRY_CUTOFF: frozenset({DRAINING, PAUSED, REVOKED, KILLED, FAILED_RECONCILIATION}),
    DRAINING: frozenset({CLOSED, KILLED, FAILED_RECONCILIATION}),
    PAUSED: frozenset({ACTIVE, ENTRY_CUTOFF, DRAINING, REVOKED, KILLED}),
    FAILED_RECONCILIATION: frozenset({KILLED, CLOSED}),
    # Terminal
    CLOSED: frozenset(),
    REVOKED: frozenset(),
    KILLED: frozenset(),
}

# Bound fields of the authorization envelope, in canonical order. These and only
# these are hashed — a material edit to any changes the authorization_hash.
ENVELOPE_FIELDS: tuple[str, ...] = (
    "strategy",
    "setup_ids",
    "setup_versions",
    "registry_hash",
    "brokers",
    "account_ids",
    "symbol_list_or_universe_rule",
    "session_start",
    "entry_cutoff",
    "expiry",
    "allowed_sessions",
    "max_trades",
    "max_concurrent_positions",
    "max_gross_notional",
    "max_notional_per_trade",
    "max_risk_per_trade",
    "max_daily_loss",
    "max_chase_bps",
    "max_order_ttl_sec",
    "allowed_order_types",
    "required_protection",
    "candidate_policy_version",
    "risk_policy_version",
    "operator_identity",
)

# Limit fields that must be present and strictly positive at validation time.
_POSITIVE_LIMIT_FIELDS: tuple[str, ...] = (
    "max_trades",
    "max_concurrent_positions",
    "max_gross_notional",
    "max_notional_per_trade",
    "max_risk_per_trade",
    "max_daily_loss",
    "max_chase_bps",
    "max_order_ttl_sec",
)


# ---------------------------------------------------------------------------
# Errors
class SessionError(Exception):
    """Base class for session-control errors."""


class SessionNotFoundError(SessionError):
    pass


class SessionTransitionError(SessionError):
    """Raised when an illegal lifecycle transition is attempted."""


class SessionValidationError(SessionError):
    pass


# ---------------------------------------------------------------------------
# Canonicalisation + hashing
def _canonical(value: Any) -> Any:
    """Deterministically canonicalise a value for hashing/serialisation.

    Tuples/sets -> sorted-ish lists (order preserved for lists/tuples, sorted for
    sets), mappings -> key-sorted dicts. Everything else stringifies via json's
    default handling."""
    if isinstance(value, Mapping):
        return {str(k): _canonical(value[k]) for k in sorted(value.keys(), key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return [_canonical(v) for v in sorted(value, key=str)]
    return value


def _canonical_json(fields: Mapping[str, Any]) -> str:
    return json.dumps(_canonical(fields), sort_keys=True, separators=(",", ":"), default=str)


def compute_authorization_hash(fields: Mapping[str, Any]) -> str:
    """SHA-256 over the canonical JSON of exactly the bound envelope fields.

    Deterministic and order-independent. Any material edit to a bound field
    yields a different hash."""
    bound = {k: fields.get(k) for k in ENVELOPE_FIELDS}
    payload = _canonical_json(bound).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Immutable authorization envelope
@dataclass(frozen=True)
class AuthorizationEnvelope:
    strategy: str
    setup_ids: tuple[str, ...]
    setup_versions: tuple[str, ...]
    registry_hash: str
    brokers: tuple[str, ...]
    account_ids: tuple[str, ...]
    symbol_list_or_universe_rule: str
    session_start: float
    entry_cutoff: float
    expiry: float
    allowed_sessions: tuple[str, ...]
    max_trades: float
    max_concurrent_positions: float
    max_gross_notional: float
    max_notional_per_trade: float
    max_risk_per_trade: float
    max_daily_loss: float
    max_chase_bps: float
    max_order_ttl_sec: float
    allowed_order_types: tuple[str, ...]
    required_protection: tuple[str, ...]
    candidate_policy_version: str
    risk_policy_version: str
    operator_identity: str
    authorization_hash: str

    def bound_fields(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ENVELOPE_FIELDS}

    def recompute_hash(self) -> str:
        return compute_authorization_hash(self.bound_fields())

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _as_tuple(v: Any) -> tuple[Any, ...]:
    if v is None:
        return tuple()
    if isinstance(v, (list, tuple, set, frozenset)):
        return tuple(v)
    return (v,)


def build_envelope(draft: Mapping[str, Any]) -> AuthorizationEnvelope:
    """Construct an immutable AuthorizationEnvelope from a draft's bound fields.

    Pure: given the same bound values it always yields the same envelope and the
    same authorization_hash. Does NOT authorize anything."""
    _tuple_fields = {
        "setup_ids", "setup_versions", "brokers", "account_ids",
        "allowed_sessions", "allowed_order_types", "required_protection",
    }
    bound: dict[str, Any] = {}
    for k in ENVELOPE_FIELDS:
        raw = draft.get(k)
        bound[k] = _as_tuple(raw) if k in _tuple_fields else raw

    authorization_hash = compute_authorization_hash(bound)
    return AuthorizationEnvelope(authorization_hash=authorization_hash, **bound)


# ---------------------------------------------------------------------------
# Session record
@dataclass
class Session:
    session_id: str
    operator_identity: str
    state: str = EDITING
    mode: Optional[str] = None
    draft: dict[str, Any] = field(default_factory=dict)
    authorized_hash: Optional[str] = None
    envelope: Optional[AuthorizationEnvelope] = None
    created_at: float = 0.0
    updated_at: float = 0.0
    journal: list[dict[str, Any]] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "operator_identity": self.operator_identity,
            "state": self.state,
            "mode": self.mode,
            "draft": dict(self.draft),
            "authorized_hash": self.authorized_hash,
            "envelope": self.envelope.to_dict() if self.envelope else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "journal": [dict(e) for e in self.journal],
            "contract": CONTRACT,
        }


# ---------------------------------------------------------------------------
# Store abstraction: in-memory dict + optional JSON file.
class SessionStore:
    """In-memory session store with optional JSON-file persistence.

    No DB, no trading/order tables. If `path` is given, the full store is written
    as a JSON snapshot under (typically) data/active_trader/ on every put()."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path: Optional[Path] = Path(path) if path else None
        self._sessions: dict[str, Session] = {}
        if self._path and self._path.is_file():
            self._load()

    def get(self, session_id: str) -> Session:
        s = self._sessions.get(session_id)
        if s is None:
            raise SessionNotFoundError(f"unknown session: {session_id!r}")
        return s

    def has(self, session_id: str) -> bool:
        return session_id in self._sessions

    def put(self, session: Session) -> Session:
        self._sessions[session.session_id] = session
        if self._path is not None:
            self._save()
        return session

    def all(self) -> list[Session]:
        return list(self._sessions.values())

    # -- JSON persistence -----------------------------------------------------
    def _save(self) -> None:
        assert self._path is not None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {sid: s.public_dict() for sid, s in self._sessions.items()}
        self._path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")

    def _load(self) -> None:
        assert self._path is not None
        data = json.loads(self._path.read_text(encoding="utf-8"))
        for sid, raw in data.items():
            env_raw = raw.get("envelope")
            envelope = AuthorizationEnvelope(**env_raw) if env_raw else None
            if envelope is not None:
                # normalise sequence fields back to tuples
                envelope = build_envelope(env_raw)
            self._sessions[sid] = Session(
                session_id=raw["session_id"],
                operator_identity=raw.get("operator_identity", ""),
                state=raw.get("state", EDITING),
                mode=raw.get("mode"),
                draft=dict(raw.get("draft") or {}),
                authorized_hash=raw.get("authorized_hash"),
                envelope=envelope,
                created_at=raw.get("created_at", 0.0),
                updated_at=raw.get("updated_at", 0.0),
                journal=list(raw.get("journal") or []),
            )


# ---------------------------------------------------------------------------
# Transition helper
def _now(now: Optional[float]) -> float:
    return float(now) if now is not None else time.time()


def _journal(session: Session, event: str, detail: Mapping[str, Any] | None = None, *, at: float) -> None:
    session.journal.append({
        "event": event,
        "from_state": session.state,
        "at": at,
        "detail": dict(detail) if detail else {},
    })


def is_legal_transition(from_state: str, to_state: str) -> bool:
    return to_state in LEGAL_TRANSITIONS.get(from_state, frozenset())


def _transition(session: Session, to_state: str, event: str, *, at: float,
                detail: Mapping[str, Any] | None = None) -> Session:
    if not is_legal_transition(session.state, to_state):
        raise SessionTransitionError(
            f"illegal transition {session.state} -> {to_state} (session {session.session_id})"
        )
    _journal(session, event, {**(dict(detail) if detail else {}), "to_state": to_state}, at=at)
    session.state = to_state
    session.updated_at = at
    return session


# ---------------------------------------------------------------------------
# Validation
def validate_bound_fields(draft: Mapping[str, Any],
                          setup_resolver: Callable[[str], bool] | None = None) -> list[str]:
    """Deterministic validation of a draft's bound fields. Returns a list of
    human-readable error strings (empty == valid). Pure; no I/O."""
    errors: list[str] = []

    # Limits present and strictly positive
    for f in _POSITIVE_LIMIT_FIELDS:
        v = draft.get(f)
        if v is None:
            errors.append(f"missing limit: {f}")
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            errors.append(f"non-numeric limit: {f}={v!r}")
            continue
        if fv <= 0:
            errors.append(f"limit must be positive: {f}={fv}")

    # Accounts non-empty
    accounts = _as_tuple(draft.get("account_ids"))
    if not accounts:
        errors.append("account_ids must be non-empty")

    # Setups present + resolvable
    setups = _as_tuple(draft.get("setup_ids"))
    if not setups:
        errors.append("setup_ids must be non-empty")
    elif setup_resolver is not None:
        for sid in setups:
            if not setup_resolver(str(sid)):
                errors.append(f"unresolved setup_id: {sid}")

    # entry_cutoff <= expiry (and both present)
    ec = draft.get("entry_cutoff")
    ex = draft.get("expiry")
    if ec is None:
        errors.append("missing entry_cutoff")
    if ex is None:
        errors.append("missing expiry")
    if ec is not None and ex is not None:
        try:
            if float(ec) > float(ex):
                errors.append("entry_cutoff must be <= expiry")
        except (TypeError, ValueError):
            errors.append("entry_cutoff/expiry must be numeric (epoch seconds)")

    return errors


# ---------------------------------------------------------------------------
# Operations (pure/store-backed)
_SEQ = {"n": 0}


def _gen_id(now: float) -> str:
    _SEQ["n"] += 1
    return f"at-sess-{int(now)}-{_SEQ['n']:04d}"


def create_draft(store: SessionStore, operator_identity: str,
                 draft: Mapping[str, Any] | None = None, *,
                 session_id: str | None = None, now: float | None = None) -> Session:
    """Create a new EDITING session owned by operator_identity."""
    at = _now(now)
    sid = session_id or _gen_id(at)
    if store.has(sid):
        raise SessionError(f"session already exists: {sid!r}")
    session = Session(
        session_id=sid,
        operator_identity=str(operator_identity),
        state=EDITING,
        draft=dict(draft or {}),
        created_at=at,
        updated_at=at,
    )
    _journal(session, "create_draft", {"operator_identity": operator_identity}, at=at)
    return store.put(session)


def save_draft(store: SessionStore, session_id: str, updates: Mapping[str, Any], *,
               now: float | None = None) -> Session:
    """Merge updates into the draft and move to SAVED.

    A material edit to a bound field on an already-AUTHORIZED (or VALIDATED)
    session sends it back to EDITING first, invalidating any prior authorization."""
    at = _now(now)
    session = store.get(session_id)

    touches_bound = any(k in ENVELOPE_FIELDS for k in updates.keys())

    # If authorization/validation already happened, a bound edit invalidates it:
    # walk back to EDITING before applying.
    if touches_bound and session.state in (VALIDATED, AUTHORIZATION_REVIEW,
                                           TWO_FA_REQUIRED, AUTHORIZED):
        # Invalidate prior authorization.
        session.authorized_hash = None
        session.envelope = None
        _transition(session, EDITING, "invalidate_on_edit", at=at,
                    detail={"changed": sorted(k for k in updates if k in ENVELOPE_FIELDS)})

    if session.state not in (EDITING, SAVED):
        raise SessionTransitionError(
            f"cannot save_draft from state {session.state}")

    session.draft.update(dict(updates))
    if session.state == EDITING:
        _transition(session, SAVED, "save_draft", at=at,
                    detail={"fields": sorted(updates.keys())})
    else:  # already SAVED — record the edit without a state change
        _journal(session, "save_draft", {"fields": sorted(updates.keys())}, at=at)
        session.updated_at = at
    return store.put(session)


def validate_draft(store: SessionStore, session_id: str, *,
                   setup_resolver: Callable[[str], bool] | None = None,
                   now: float | None = None) -> dict[str, Any]:
    """Run deterministic checks. On success move SAVED -> VALIDATED. On failure
    the session stays put and the errors are returned."""
    at = _now(now)
    session = store.get(session_id)
    if session.state not in (SAVED, VALIDATED):
        raise SessionTransitionError(f"cannot validate from state {session.state}")

    errors = validate_bound_fields(session.draft, setup_resolver=setup_resolver)
    if errors:
        _journal(session, "validate_failed", {"errors": errors}, at=at)
        session.updated_at = at
        store.put(session)
        return {"ok": False, "state": session.state, "errors": errors,
                "session": session.public_dict()}

    if session.state == SAVED:
        _transition(session, VALIDATED, "validate_ok", at=at)
    else:
        _journal(session, "validate_ok", None, at=at)
        session.updated_at = at
    store.put(session)
    return {"ok": True, "state": session.state, "errors": [],
            "session": session.public_dict()}


def authorization_preview(store: SessionStore, session_id: str, *,
                          now: float | None = None) -> dict[str, Any]:
    """Build the immutable envelope from the current draft and move
    VALIDATED -> AUTHORIZATION_REVIEW. Read-only preview: authorizes nothing."""
    at = _now(now)
    session = store.get(session_id)
    if session.state not in (VALIDATED, AUTHORIZATION_REVIEW):
        raise SessionTransitionError(
            f"cannot preview authorization from state {session.state}")

    envelope = build_envelope(session.draft)
    session.envelope = envelope
    if session.state == VALIDATED:
        _transition(session, AUTHORIZATION_REVIEW, "authorization_preview", at=at,
                    detail={"authorization_hash": envelope.authorization_hash})
    else:
        _journal(session, "authorization_preview",
                 {"authorization_hash": envelope.authorization_hash}, at=at)
        session.updated_at = at
    store.put(session)
    return {
        "state": session.state,
        "authorization_hash": envelope.authorization_hash,
        "envelope": envelope.to_dict(),
        "session": session.public_dict(),
    }


def authorize(store: SessionStore, session_id: str,
              verifier: Callable[[Session, AuthorizationEnvelope], bool], *,
              now: float | None = None) -> dict[str, Any]:
    """Authorize the session using a caller-supplied verifier.

    SAFETY: `verifier` is a plain injected callable (a FAKE/test 2FA check).
    This module NEVER performs real 2FA, reads no credential, and calls no
    broker. On a passing verifier the session moves through TWO_FA_REQUIRED to
    AUTHORIZED and the authorized_hash is pinned; on failure it returns to
    AUTHORIZATION_REVIEW."""
    at = _now(now)
    session = store.get(session_id)
    if session.state != AUTHORIZATION_REVIEW:
        raise SessionTransitionError(
            f"cannot authorize from state {session.state}")
    if session.envelope is None:
        session.envelope = build_envelope(session.draft)

    envelope = session.envelope
    _transition(session, TWO_FA_REQUIRED, "two_fa_required", at=at)

    passed = bool(verifier(session, envelope))
    if not passed:
        _transition(session, AUTHORIZATION_REVIEW, "two_fa_failed", at=at)
        store.put(session)
        return {"ok": False, "state": session.state, "session": session.public_dict()}

    session.authorized_hash = envelope.authorization_hash
    _transition(session, AUTHORIZED, "authorized", at=at,
                detail={"authorization_hash": envelope.authorization_hash})
    store.put(session)
    return {"ok": True, "state": session.state,
            "authorization_hash": envelope.authorization_hash,
            "session": session.public_dict()}


def is_authorization_valid(session: Session,
                           envelope: AuthorizationEnvelope | None = None) -> bool:
    """True only if the session is authorized and the (current) envelope's hash
    still matches the pinned authorized_hash. Any material edit to a bound field
    changes the envelope hash and makes this False."""
    if session.authorized_hash is None:
        return False
    env = envelope if envelope is not None else session.envelope
    if env is None:
        return False
    # The envelope must be internally consistent AND match what was authorized.
    if env.authorization_hash != env.recompute_hash():
        return False
    return env.authorization_hash == session.authorized_hash


def activate(store: SessionStore, session_id: str, mode: str, *,
             now: float | None = None) -> dict[str, Any]:
    """Activate an AUTHORIZED session.

    HARD GUARD: mode LIVE (or LIVE_ACTIVATION_ENABLED being False, which it
    always is) returns {'status': 'FEATURE_DISABLED'} and changes NO state — no
    live order path exists in this module. SIMULATION/SHADOW move the session to
    ACTIVE. An unauthorized, invalidated, or expired session cannot activate."""
    at = _now(now)
    session = store.get(session_id)

    # --- live is categorically refused -------------------------------------
    if mode == LIVE or not LIVE_ACTIVATION_ENABLED and mode not in SAFE_MODES:
        _journal(session, "activate_feature_disabled", {"mode": mode}, at=at)
        session.updated_at = at
        store.put(session)
        return {"status": FEATURE_DISABLED, "mode": mode,
                "reason": "live activation is disabled in this module",
                "session": session.public_dict()}

    if mode not in SAFE_MODES:  # defensive: only SIMULATION/SHADOW proceed
        _journal(session, "activate_feature_disabled", {"mode": mode}, at=at)
        session.updated_at = at
        store.put(session)
        return {"status": FEATURE_DISABLED, "mode": mode,
                "reason": "unsupported activation mode",
                "session": session.public_dict()}

    # --- must be authorized -------------------------------------------------
    if session.state != AUTHORIZED:
        return {"status": "ERROR", "reason": f"not authorized (state={session.state})",
                "session": session.public_dict()}

    if not is_authorization_valid(session):
        return {"status": "ERROR", "reason": "authorization invalid or superseded",
                "session": session.public_dict()}

    # --- expiry check -------------------------------------------------------
    env = session.envelope
    if env is not None and env.expiry is not None and at > float(env.expiry):
        return {"status": "ERROR", "reason": "authorization expired",
                "session": session.public_dict()}

    session.mode = mode
    _transition(session, ACTIVE, "activate", at=at, detail={"mode": mode})
    store.put(session)
    return {"status": ACTIVE, "mode": mode, "session": session.public_dict()}


def pause(store: SessionStore, session_id: str, *, now: float | None = None) -> Session:
    """Pause a running session (ACTIVE/ENTRY_CUTOFF -> PAUSED)."""
    at = _now(now)
    session = store.get(session_id)
    _transition(session, PAUSED, "pause", at=at)
    return store.put(session)


def revoke(store: SessionStore, session_id: str, *, reason: str = "",
           now: float | None = None) -> Session:
    """Revoke a session -> REVOKED (terminal)."""
    at = _now(now)
    session = store.get(session_id)
    _transition(session, REVOKED, "revoke", at=at, detail={"reason": reason})
    return store.put(session)


def kill(store: SessionStore, session_id: str, *, reason: str = "",
         now: float | None = None) -> Session:
    """Emergency kill -> KILLED (terminal)."""
    at = _now(now)
    session = store.get(session_id)
    _transition(session, KILLED, "kill", at=at, detail={"reason": reason})
    return store.put(session)


def get_session(store: SessionStore, session_id: str) -> dict[str, Any]:
    return store.get(session_id).public_dict()


def session_journal(store: SessionStore, session_id: str) -> list[dict[str, Any]]:
    return [dict(e) for e in store.get(session_id).journal]
