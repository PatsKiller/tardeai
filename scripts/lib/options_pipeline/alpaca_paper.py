"""alpaca_paper.py — Alpaca PAPER-ONLY options order layer (Stage 2, Parts C/D).

Wraps the Alpaca paper-trading API for single-contract, LIMIT-only options
orders driven by rows in options_approval_queue, and owns the queue's Alpaca
lifecycle state machine (migrations/2026_07_06_options_queue_alpaca_states.sql).

HARD INVARIANTS (test-enforced in tests/test_alpaca_paper_options_executor.py):
  • PAPER-LOCKED endpoint. The base URL comes ONLY from ALPACA_PAPER_BASE_URL
    and its hostname must be exactly 'paper-api.alpaca.markets'. Any other host
    (including live api.alpaca.markets, or a spoof host that merely embeds the
    paper hostname in its path/subdomain) raises PaperEndpointError. There is
    NO default URL: env missing → refuse. Any live-indicating env var
    (ALPACA*/APCA* name containing LIVE, non-empty) → refuse.
  • LIMIT orders only — order_type must be the literal 'limit'; anything else
    raises OrderPolicyError. Market/stop/bracket types do not exist here.
  • 1-contract cap — qty is hard-capped at 1; requesting more raises
    OrderPolicyError (no silent clamp-and-send of a bigger order).
  • BUY-to-open only — this lane opens long single-leg contracts (max loss =
    debit paid). Closes happen on the Alpaca side; reconcile_fills() detects
    them read-only.
  • NO automatic submits. submit_ready_proposal() requires confirm=True
    (executor CLI passes it only when the operator supplies --confirm), and the
    scanner/generator never import this module (test-enforced grep).
  • State machine is legality-checked with compare-and-swap updates.
    READY_FOR_ALPACA_PAPER and READY_FOR_LIVE_REVIEW are operator-only marks:
    they raise OperatorActionRequiredError unless operator_actor contains
    'operator'. READY_FOR_LIVE_REVIEW is reachable ONLY from OUTCOME_RECORDED
    and is never set by any automatic code path in this module.
  • This module never touches the desk review flow: it does not import or
    reimplement the desk's approve/reject helpers and never writes the
    legacy review statuses (pending/blocked/approved/rejected/executed).
  • DB access follows the db_adapter one-statement rule: every query is a
    single statement through an _execute-shaped callable, committed
    immediately; no held transactions.

Full request/response/read-back audit for every submit is persisted into the
queue row's meta.alpaca_json: {request, response, readback, submitted_at} plus
fill/close blocks added by reconcile_fills().

EARNINGS-SPREADS Stage 1b (operator spec Part G) — guarded MULTI-LEG lane:
  submit_spread_paper_order() submits ONE two-leg net-DEBIT vertical as an
  Alpaca order_class='mleg' LIMIT order on the same paper-locked /v2/orders
  endpoint. It is triple-gated (SpreadNotEnabledError otherwise):
    1. the queue row's meta.strategy_json.family starts with
       'earnings_vertical';
    2. the strategy's registry entry (config/options_strategy_registry.yaml,
       read via universe.registry_entry) has alpaca_paper_enabled: true;
    3. that SAME registry entry carries the Part-G opt-in key
       multi_leg_proven: true. This is the multi-leg config flag's single
       home; it is absent from every entry today and absent == FALSE, so no
       spread can be submitted until the operator explicitly adds it.
  Credit families (family starting 'earnings_vertical_credit') are refused
  UNCONDITIONALLY — regardless of flags, even in dry-run — until
  assignment/reconciliation handling is proven.
  Hard shape rules: exactly 2 legs, each ratio_qty exactly 1, top-level qty 1
  (ONE spread max), one buy + one sell leg on the same underlying/expiry/type
  with a genuine debit strike relationship, LIMIT only (net-debit price),
  time_in_force 'day'. Per-leg audit persisted in meta.alpaca_json.legs[] and
  meta.alpaca_json.leg_events[]; the row-level state machine is reused
  unchanged (READY→SUBMITTED→FILLED→CLOSED→OUTCOME_RECORDED).
  reconcile_fills() aggregates multi-leg fills into ONE paper outcome (net
  debit in, net value out) and adds a post-expiry positions poll per leg.
  KNOWN LIMITATION (honest): exercise/assignment detection is inferential —
  the positions endpoint cannot distinguish worthless expiry from fully-ITM
  exercise+assignment that netted flat stock. When legs disappear with no
  closing fill, the row is flagged (meta.alpaca_json.assignment /
  expiry_check with a risk note) and LEFT in ALPACA_PAPER_FILLED for the
  operator; no outcome is invented. Full resolution would need the account
  activities endpoint, which this lane deliberately does not automate yet.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

PAPER_HOST = "paper-api.alpaca.markets"

# Alpaca lifecycle states owned by this module (Part D migration).
STATE_READY = "READY_FOR_ALPACA_PAPER"
STATE_SUBMITTED = "ALPACA_PAPER_SUBMITTED"
STATE_FILLED = "ALPACA_PAPER_FILLED"
STATE_REJECTED = "ALPACA_PAPER_REJECTED"
STATE_CLOSED = "ALPACA_PAPER_CLOSED"
STATE_OUTCOME = "OUTCOME_RECORDED"
STATE_LIVE_REVIEW = "READY_FOR_LIVE_REVIEW"

ALPACA_STATES = (
    STATE_READY, STATE_SUBMITTED, STATE_FILLED, STATE_REJECTED,
    STATE_CLOSED, STATE_OUTCOME, STATE_LIVE_REVIEW,
)

# to_status -> allowed from_statuses. Anything not listed is illegal.
LEGAL_TRANSITIONS: Dict[str, set] = {
    STATE_READY: {"pending", "approved"},          # operator mark only
    STATE_SUBMITTED: {STATE_READY},                # executor --confirm only
    STATE_FILLED: {STATE_SUBMITTED},               # reconcile
    STATE_REJECTED: {STATE_SUBMITTED},             # reconcile
    STATE_CLOSED: {STATE_FILLED},                  # reconcile close-detection
    STATE_OUTCOME: {STATE_CLOSED},                 # reconcile after record_outcome
    STATE_LIVE_REVIEW: {STATE_OUTCOME},            # operator mark only, NEVER automatic
}

# Transitions that require a human: operator_actor must contain 'operator'.
OPERATOR_REQUIRED = {STATE_READY, STATE_LIVE_REVIEW}

SCRATCH_BAND_DOLLARS = 1.0  # |pnl| below this → 'scratch'

# ── Part G (earnings vertical spreads) constants ─────────────────────────────
SPREAD_FAMILY_PREFIX = "earnings_vertical"       # only these families may spread
SPREAD_CREDIT_PREFIX = "earnings_vertical_credit"  # refused unconditionally
# The Part-G multi-leg enablement key. It lives on the strategy's row in
# config/options_strategy_registry.yaml (registry meta — chosen over a new
# executor-side config file so there is exactly ONE per-strategy gating
# surface). Absent everywhere today; absent/false ⇒ spread submits refuse.
MULTI_LEG_PROVEN_KEY = "multi_leg_proven"

Executor = Callable[..., Any]  # (sql, params=None, fetch=None) -> rows | True | None


class PaperEndpointError(RuntimeError):
    """Endpoint/credential environment is not provably paper — refuse to run."""


class OrderPolicyError(ValueError):
    """Order violates the paper-lane policy (limit-only, 1 contract, buy-to-open)."""


class IllegalTransitionError(RuntimeError):
    """Requested queue state change is not in LEGAL_TRANSITIONS."""


class OperatorActionRequiredError(RuntimeError):
    """A human-only transition/submit was attempted without operator authority."""


class SpreadNotEnabledError(RuntimeError):
    """Multi-leg (spread) submission is not enabled for this proposal/strategy."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_executor() -> Executor:
    from db_adapter import _execute
    return _execute


# ── endpoint guard ────────────────────────────────────────────────────────────

def resolve_paper_base_url(env: Optional[Dict[str, str]] = None) -> str:
    """Return the paper base URL or raise PaperEndpointError. No default, ever."""
    e = os.environ if env is None else env
    # Any ALPACA*/APCA* env var whose NAME says LIVE and that holds a value → refuse.
    for name in e:
        up = str(name).upper()
        if (up.startswith("ALPACA") or up.startswith("APCA")) and "LIVE" in up:
            if str(e.get(name) or "").strip():
                raise PaperEndpointError(
                    f"live-indicating env var '{name}' is set — paper-only module refuses to run")
    mode = str(e.get("ALPACA_MODE") or "paper").strip().lower()
    if mode != "paper":
        raise PaperEndpointError(f"ALPACA_MODE={mode!r} — must be 'paper'")
    url = str(e.get("ALPACA_PAPER_BASE_URL") or "").strip()
    if not url:
        raise PaperEndpointError(
            "ALPACA_PAPER_BASE_URL is not set — refusing (paper endpoint must be explicit; "
            "there is deliberately no default)")
    host = (urlparse(url).hostname or "").lower()
    if host != PAPER_HOST or PAPER_HOST not in url:
        raise PaperEndpointError(
            f"ALPACA_PAPER_BASE_URL host {host!r} is not '{PAPER_HOST}' — refusing")
    # Other Alpaca URL envs must not point anywhere non-paper either.
    for name in ("ALPACA_BASE_URL", "APCA_API_BASE_URL"):
        v = str(e.get(name) or "").strip()
        if not v:
            continue
        h = (urlparse(v).hostname or "").lower()
        if h.endswith("alpaca.markets") and h not in (PAPER_HOST, "data.alpaca.markets"):
            raise PaperEndpointError(
                f"env var '{name}' points at non-paper Alpaca host {h!r} — refusing")
    return url.rstrip("/")


# ── OCC symbol construction ──────────────────────────────────────────────────

def build_occ_symbol(underlying: str, expiration: str, strike: float,
                     option_type: str) -> str:
    """OCC/Alpaca contract symbol, e.g. ('RTX','2026-09-18',160.0,'call') → RTX260918C00160000."""
    root = (underlying or "").strip().upper()
    if not root or not root.isalnum() or len(root) > 6:
        raise OrderPolicyError(f"invalid underlying root {underlying!r}")
    try:
        exp = datetime.strptime(str(expiration)[:10], "%Y-%m-%d")
    except ValueError:
        raise OrderPolicyError(f"invalid expiration {expiration!r} (need YYYY-MM-DD)")
    ot = (option_type or "").strip().lower()
    if ot not in ("call", "put", "c", "p"):
        raise OrderPolicyError(f"invalid option_type {option_type!r}")
    cp = "C" if ot.startswith("c") else "P"
    try:
        k = float(strike)
    except (TypeError, ValueError):
        raise OrderPolicyError(f"invalid strike {strike!r}")
    if not (0 < k < 100000):
        raise OrderPolicyError(f"strike {strike} out of range")
    return f"{root}{exp.strftime('%y%m%d')}{cp}{int(round(k * 1000)):08d}"


# ── paper client ─────────────────────────────────────────────────────────────

class AlpacaPaperOptionsClient:
    """Thin HTTP client, constructible ONLY with a verified paper endpoint."""

    def __init__(self, env: Optional[Dict[str, str]] = None, http: Any = None,
                 timeout: int = 15):
        e = os.environ if env is None else env
        self.base_url = resolve_paper_base_url(e)  # raises unless provably paper
        self.api_key = str(e.get("ALPACA_API_KEY") or "").strip()
        self.secret_key = str(e.get("ALPACA_SECRET_KEY") or "").strip()
        if not self.api_key or not self.secret_key:
            raise PaperEndpointError(
                "ALPACA_API_KEY / ALPACA_SECRET_KEY missing — refusing")
        if http is None:
            import requests as http  # lazy so tests never need network deps
        self._http = http
        self._timeout = timeout
        self._headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }

    # -- order policy enforcement happens HERE, at the last gate before HTTP --
    def submit_option_limit_order(self, *, occ_symbol: str, limit_price: float,
                                  qty: int = 1, side: str = "buy",
                                  order_type: str = "limit",
                                  time_in_force: str = "day",
                                  client_order_id: str = "") -> dict:
        payload = build_order_request(
            occ_symbol=occ_symbol, limit_price=limit_price, qty=qty, side=side,
            order_type=order_type, time_in_force=time_in_force,
            client_order_id=client_order_id)
        resp = self._http.post(f"{self.base_url}/v2/orders", headers=self._headers,
                               json=payload, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def get_order(self, order_id: str) -> Optional[dict]:
        resp = self._http.get(f"{self.base_url}/v2/orders/{order_id}",
                              headers=self._headers, timeout=self._timeout)
        if getattr(resp, "status_code", 200) == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_position(self, occ_symbol: str) -> Optional[dict]:
        resp = self._http.get(f"{self.base_url}/v2/positions/{occ_symbol}",
                              headers=self._headers, timeout=self._timeout)
        if getattr(resp, "status_code", 200) == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def list_closed_orders(self, occ_symbol: str, limit: int = 50) -> List[dict]:
        resp = self._http.get(
            f"{self.base_url}/v2/orders",
            headers=self._headers, timeout=self._timeout,
            params={"status": "closed", "symbols": occ_symbol, "limit": limit,
                    "direction": "desc"})
        resp.raise_for_status()
        out = resp.json()
        return out if isinstance(out, list) else []

    def submit_option_spread_limit_order(self, *, legs: List[dict],
                                         net_debit_limit: float,
                                         order_type: str = "limit",
                                         time_in_force: str = "day",
                                         client_order_id: str = "") -> dict:
        """POST one two-leg net-DEBIT vertical (order_class='mleg').

        Policy is re-enforced HERE, at the last gate before HTTP, exactly like
        the single-leg path — same paper-locked base URL, same /v2/orders
        endpoint (Alpaca's documented multi-leg shape: order_class='mleg' with
        legs[] of {symbol, ratio_qty, side, position_intent}).
        """
        payload = build_spread_order_request(
            legs=legs, net_debit_limit=net_debit_limit, order_type=order_type,
            time_in_force=time_in_force, client_order_id=client_order_id)
        resp = self._http.post(f"{self.base_url}/v2/orders", headers=self._headers,
                               json=payload, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()


def build_order_request(*, occ_symbol: str, limit_price: float, qty: int = 1,
                        side: str = "buy", order_type: str = "limit",
                        time_in_force: str = "day",
                        client_order_id: str = "") -> dict:
    """Pure payload builder — enforces limit-only / 1-contract / buy-to-open."""
    if order_type != "limit":
        raise OrderPolicyError(f"order_type {order_type!r} refused — LIMIT orders only")
    try:
        q = int(qty)
    except (TypeError, ValueError):
        raise OrderPolicyError(f"invalid qty {qty!r}")
    if q > 1:
        raise OrderPolicyError(f"qty {q} exceeds the hard 1-contract cap — refused")
    if q < 1:
        raise OrderPolicyError(f"qty {q} invalid — must be exactly 1")
    if (side or "").lower() != "buy":
        raise OrderPolicyError(f"side {side!r} refused — this lane is buy-to-open only")
    try:
        px = float(limit_price)
    except (TypeError, ValueError):
        raise OrderPolicyError(f"invalid limit_price {limit_price!r}")
    if not (0 < px < 10000):
        raise OrderPolicyError(f"limit_price {limit_price} out of sane range")
    if not occ_symbol or len(occ_symbol) < 16:
        raise OrderPolicyError(f"invalid OCC symbol {occ_symbol!r}")
    payload = {
        "symbol": occ_symbol,
        "qty": "1",                      # literal — the cap is structural
        "side": "buy",
        "type": "limit",                 # literal — no other type exists here
        "time_in_force": time_in_force or "day",
        "limit_price": f"{round(px, 2):.2f}",
    }
    if client_order_id:
        payload["client_order_id"] = client_order_id[:48]
    return payload


# ── queue access (one statement per call) ────────────────────────────────────

_ROW_COLS = ("id, proposal_id, symbol, strategy, status, proposal_json, meta, "
             "created_at, updated_at")


def get_queue_row(proposal_id: str, executor: Optional[Executor] = None) -> Optional[dict]:
    ex = executor or _default_executor()
    row = ex(f"""SELECT {_ROW_COLS}
                 FROM options_approval_queue WHERE proposal_id=%s""",
             (proposal_id,), fetch="one")
    return dict(row) if row else None


def list_rows_in_status(status: str, executor: Optional[Executor] = None) -> List[dict]:
    ex = executor or _default_executor()
    rows = ex(f"""SELECT {_ROW_COLS}
                  FROM options_approval_queue WHERE status=%s
                  ORDER BY updated_at""",
              (status,), fetch="all")
    return [dict(r) for r in rows] if rows else []


def status_summary(executor: Optional[Executor] = None) -> List[dict]:
    ex = executor or _default_executor()
    rows = ex("""SELECT status, COUNT(*) AS n FROM options_approval_queue
                 GROUP BY status ORDER BY status""", fetch="all")
    return [dict(r) for r in rows] if rows else []


def transition(proposal_id: str, to_status: str, *,
               operator_actor: Optional[str] = None,
               meta_patch: Optional[dict] = None,
               executor: Optional[Executor] = None) -> dict:
    """Legality-checked, compare-and-swap state change. Raises on anything shady."""
    if to_status not in LEGAL_TRANSITIONS:
        raise IllegalTransitionError(
            f"'{to_status}' is not an Alpaca-lane target state — this module never "
            f"writes legacy review statuses")
    if to_status in OPERATOR_REQUIRED and "operator" not in str(operator_actor or ""):
        raise OperatorActionRequiredError(
            f"transition to {to_status} is an operator-only action — pass "
            f"operator_actor containing 'operator' (got {operator_actor!r}). "
            f"It is NEVER set automatically.")
    ex = executor or _default_executor()
    row = get_queue_row(proposal_id, ex)
    if not row:
        raise IllegalTransitionError(f"proposal {proposal_id!r} not in options_approval_queue")
    from_status = row["status"]
    if from_status not in LEGAL_TRANSITIONS[to_status]:
        raise IllegalTransitionError(
            f"{from_status} → {to_status} is illegal (allowed from: "
            f"{sorted(LEGAL_TRANSITIONS[to_status])})")
    patch = dict(meta_patch or {})
    patch.setdefault("alpaca_state_log", (
        (row.get("meta") or {}).get("alpaca_state_log") or []) + [{
            "from": from_status, "to": to_status, "at": _now_iso(),
            "actor": operator_actor or "executor"}])
    updated = ex(
        """UPDATE options_approval_queue
           SET status=%s,
               meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb,
               updated_at=NOW()
           WHERE proposal_id=%s AND status=%s
           RETURNING id""",
        (to_status, json.dumps(patch, default=str), proposal_id, from_status),
        fetch="one",
    )
    if not updated:
        raise IllegalTransitionError(
            f"compare-and-swap failed for {proposal_id} ({from_status} → {to_status}) — "
            f"row changed underneath us or DB unavailable")
    return {"ok": True, "proposal_id": proposal_id, "from": from_status, "to": to_status}


def mark_ready(proposal_id: str, *, operator_actor: str,
               executor: Optional[Executor] = None) -> dict:
    """Operator mark: pending/approved → READY_FOR_ALPACA_PAPER."""
    return transition(proposal_id, STATE_READY, operator_actor=operator_actor,
                      executor=executor)


def mark_live_review(proposal_id: str, *, operator_actor: str,
                     executor: Optional[Executor] = None) -> dict:
    """Operator mark: OUTCOME_RECORDED → READY_FOR_LIVE_REVIEW. Never automatic."""
    return transition(proposal_id, STATE_LIVE_REVIEW, operator_actor=operator_actor,
                      executor=executor)


# ── proposal → order payload ─────────────────────────────────────────────────

def _proposal_json(row: dict) -> dict:
    pj = row.get("proposal_json")
    if isinstance(pj, str):
        try:
            pj = json.loads(pj)
        except (ValueError, TypeError):
            pj = {}
    return pj or {}


def _client_order_id(proposal_id: str) -> str:
    """Deterministic + short: resubmit attempts dedupe on Alpaca's side."""
    return "aopt_" + hashlib.sha1(proposal_id.encode()).hexdigest()[:20]


def build_order_payload(row: dict) -> dict:
    """Pure: queue row → Alpaca order request dict. No HTTP, no DB writes."""
    pj = _proposal_json(row)
    underlying = pj.get("underlying") or pj.get("symbol") or row.get("symbol") or ""
    expiration = pj.get("expiration") or ((pj.get("meta") or {}).get("dte_bucket") or {}).get("exp")
    strike = pj.get("strike")
    option_type = pj.get("option_type") or "call"
    contracts = pj.get("contracts", 1)
    try:
        n = int(contracts)
    except (TypeError, ValueError):
        raise OrderPolicyError(f"invalid contracts {contracts!r} in proposal")
    if n > 1:
        raise OrderPolicyError(
            f"proposal asks for {n} contracts — hard cap is 1, refusing")
    side = (pj.get("side") or "BUY").upper()
    if side != "BUY":
        raise OrderPolicyError(f"proposal side {side!r} — buy-to-open only")
    limit_price = pj.get("premium")
    if limit_price in (None, ""):
        raise OrderPolicyError("proposal has no premium — cannot price a limit order")
    occ = build_occ_symbol(underlying, expiration, strike, option_type)
    return build_order_request(
        occ_symbol=occ, limit_price=float(limit_price), qty=1, side="buy",
        order_type="limit", time_in_force="day",
        client_order_id=_client_order_id(str(row.get("proposal_id") or "")))


# ── submit (executor CLI only — never called by scanner/generator) ───────────

def submit_ready_proposal(proposal_id: str, *, confirm: bool = False,
                          dry_run: bool = False,
                          executor: Optional[Executor] = None,
                          client: Optional[AlpacaPaperOptionsClient] = None,
                          env: Optional[Dict[str, str]] = None) -> dict:
    """Submit ONE queued proposal as a 1-contract paper LIMIT order.

    dry_run: build + return the exact payload, zero HTTP, zero state change.
    real:    requires confirm=True (operator's --confirm) and the row to be in
             READY_FOR_ALPACA_PAPER; persists {request, response, readback,
             submitted_at} into meta.alpaca_json and moves the row to
             ALPACA_PAPER_SUBMITTED.
    """
    if not proposal_id:
        raise OperatorActionRequiredError("explicit --proposal-id is required")
    ex = executor or _default_executor()
    row = get_queue_row(proposal_id, ex)
    if not row:
        return {"ok": False, "error": f"proposal {proposal_id!r} not in queue"}
    payload = build_order_payload(row)
    if dry_run:
        return {"ok": True, "dry_run": True, "proposal_id": proposal_id,
                "status": row["status"], "would_submit": row["status"] == STATE_READY,
                "payload": payload, "http": "none (dry-run: zero HTTP)"}
    if not confirm:
        raise OperatorActionRequiredError(
            "submit refused — operator must pass --confirm (confirm=True). "
            "There is no automatic submit path.")
    if row["status"] != STATE_READY:
        raise IllegalTransitionError(
            f"proposal {proposal_id} is '{row['status']}' — only "
            f"{STATE_READY} rows may be submitted (use --mark-ready first)")
    cl = client or AlpacaPaperOptionsClient(env)   # paper guard runs here
    submitted_at = _now_iso()
    try:
        response = cl.submit_option_limit_order(
            occ_symbol=payload["symbol"], limit_price=float(payload["limit_price"]),
            qty=1, side="buy", order_type="limit",
            time_in_force=payload["time_in_force"],
            client_order_id=payload.get("client_order_id", ""))
    except Exception as e:  # persist the attempt, leave state at READY
        ex("""UPDATE options_approval_queue
              SET meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb, updated_at=NOW()
              WHERE proposal_id=%s""",
           (json.dumps({"alpaca_submit_error": {
               "request": payload, "error": str(e), "at": submitted_at}}, default=str),
            proposal_id))
        return {"ok": False, "error": f"submit failed: {e}", "request": payload}
    order_id = str(response.get("id") or "")
    readback = None
    if order_id:
        try:
            readback = cl.get_order(order_id)
        except Exception as e:
            readback = {"readback_error": str(e)}
    transition(proposal_id, STATE_SUBMITTED, executor=ex, meta_patch={
        "alpaca_json": {"request": payload, "response": response,
                        "readback": readback, "submitted_at": submitted_at}})
    return {"ok": True, "proposal_id": proposal_id, "order_id": order_id,
            "status": STATE_SUBMITTED, "request": payload,
            "response": response, "readback": readback}


# ── Part G: earnings-vertical DEBIT spreads (multi-leg, guarded) ─────────────

def _strategy_json(row: dict) -> dict:
    """meta.strategy_json (dict) or {} — tolerant of stringified meta."""
    meta = row.get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (ValueError, TypeError):
            meta = {}
    sj = (meta or {}).get("strategy_json")
    return sj if isinstance(sj, dict) else {}


def _spread_client_order_id(proposal_id: str) -> str:
    return "aspr_" + hashlib.sha1(proposal_id.encode()).hexdigest()[:20]


def _norm_option_type(v: Any) -> str:
    ot = str(v or "").strip().lower()
    return "call" if ot.startswith("c") else ("put" if ot.startswith("p") else "")


def build_spread_order_request(*, legs: List[dict], net_debit_limit: float,
                               order_type: str = "limit",
                               time_in_force: str = "day",
                               client_order_id: str = "") -> dict:
    """Pure mleg payload builder — 2-leg net-DEBIT vertical, LIMIT only.

    Input legs: {underlying, expiration, strike, option_type, side} with side
    'buy'|'sell' (ratio_qty, if present, must be 1). Output follows Alpaca's
    documented multi-leg order shape on /v2/orders: order_class='mleg',
    top-level qty, legs[] of {symbol, ratio_qty, side, position_intent}.
    """
    if order_type != "limit":
        raise OrderPolicyError(
            f"order_type {order_type!r} refused — LIMIT orders only (spreads included, "
            f"market orders do not exist in this lane)")
    if (time_in_force or "day") != "day":
        raise OrderPolicyError(
            f"time_in_force {time_in_force!r} refused — spread lane is 'day' only")
    if not isinstance(legs, (list, tuple)) or len(legs) != 2:
        got = len(legs) if isinstance(legs, (list, tuple)) else repr(legs)
        raise OrderPolicyError(f"spread needs exactly 2 legs, got {got}")
    built: List[dict] = []
    sides: List[str] = []
    for leg in legs:
        if not isinstance(leg, dict):
            raise OrderPolicyError("each spread leg must be a mapping")
        try:
            ratio = int(leg.get("ratio_qty", 1))
        except (TypeError, ValueError):
            raise OrderPolicyError(f"invalid leg ratio_qty {leg.get('ratio_qty')!r}")
        if ratio != 1:
            raise OrderPolicyError(
                f"leg ratio_qty {ratio} refused — every leg is exactly 1 (ONE spread max)")
        side = str(leg.get("side") or "").strip().lower()
        if side not in ("buy", "sell"):
            raise OrderPolicyError(f"invalid leg side {leg.get('side')!r}")
        occ = build_occ_symbol(leg.get("underlying"), leg.get("expiration"),
                               leg.get("strike"), leg.get("option_type"))
        built.append({"symbol": occ, "ratio_qty": "1", "side": side,
                      "position_intent": "buy_to_open" if side == "buy" else "sell_to_open"})
        sides.append(side)
    if sorted(sides) != ["buy", "sell"]:
        raise OrderPolicyError(
            "vertical needs exactly one buy leg and one sell leg — refused")
    l0, l1 = legs
    if str(l0.get("underlying") or "").upper() != str(l1.get("underlying") or "").upper():
        raise OrderPolicyError("spread legs must share one underlying — refused")
    if str(l0.get("expiration"))[:10] != str(l1.get("expiration"))[:10]:
        raise OrderPolicyError("vertical legs must share one expiration — refused")
    ot0, ot1 = _norm_option_type(l0.get("option_type")), _norm_option_type(l1.get("option_type"))
    if ot0 != ot1:
        raise OrderPolicyError("vertical legs must share one option type — refused")
    buy_leg = l0 if str(l0.get("side") or "").lower() == "buy" else l1
    sell_leg = l1 if buy_leg is l0 else l0
    bs, ss = float(buy_leg["strike"]), float(sell_leg["strike"])
    if bs == ss:
        raise OrderPolicyError("spread legs must have different strikes — refused")
    if ot0 == "call" and bs > ss:
        raise OrderPolicyError(
            "call vertical with long strike ABOVE short strike is a CREDIT structure — "
            "refused (this lane is net-debit only)")
    if ot0 == "put" and bs < ss:
        raise OrderPolicyError(
            "put vertical with long strike BELOW short strike is a CREDIT structure — "
            "refused (this lane is net-debit only)")
    try:
        px = float(net_debit_limit)
    except (TypeError, ValueError):
        raise OrderPolicyError(f"invalid net debit limit {net_debit_limit!r}")
    if not (0 < px < 10000):
        raise OrderPolicyError(
            f"net debit limit {net_debit_limit!r} out of sane range — a zero/negative "
            f"net price would be a credit structure, refused")
    payload = {
        "order_class": "mleg",
        "qty": "1",                       # literal — ONE spread max, structural
        "type": "limit",                  # literal — no other type exists here
        "time_in_force": "day",
        "limit_price": f"{round(px, 2):.2f}",   # positive = net DEBIT (Alpaca mleg convention)
        "legs": built,
    }
    if client_order_id:
        payload["client_order_id"] = client_order_id[:48]
    return payload


def _spread_specs_from_proposal(row: dict) -> dict:
    """proposal_json → builder kwargs. Strict: missing shape fails honest."""
    pj = _proposal_json(row)
    legs = pj.get("legs")
    if not isinstance(legs, list) or len(legs) != 2:
        raise OrderPolicyError(
            "spread proposal must carry exactly 2 legs in proposal_json.legs — refusing")
    try:
        n = int(pj.get("spreads", pj.get("contracts", 1)))
    except (TypeError, ValueError):
        raise OrderPolicyError(f"invalid spread count {pj.get('spreads')!r} in proposal")
    if n != 1:
        raise OrderPolicyError(
            f"proposal asks for {n} spreads — hard cap is ONE spread, refusing")
    net = pj.get("net_debit", pj.get("limit_price", pj.get("premium")))
    if net in (None, ""):
        raise OrderPolicyError(
            "spread proposal has no net_debit — cannot price a net-debit limit order")
    under = pj.get("underlying") or pj.get("symbol") or row.get("symbol") or ""
    norm = [{"underlying": leg.get("underlying") or under,
             "expiration": leg.get("expiration"),
             "strike": leg.get("strike"),
             "option_type": leg.get("option_type"),
             "side": leg.get("side"),
             "ratio_qty": leg.get("ratio_qty", 1)} for leg in legs]
    return {"legs": norm, "net_debit_limit": float(net),
            "client_order_id": _spread_client_order_id(str(row.get("proposal_id") or ""))}


def build_spread_order_payload(row: dict) -> dict:
    """Pure: queue row → Alpaca mleg order request dict. No HTTP, no DB writes."""
    return build_spread_order_request(**_spread_specs_from_proposal(row))


def assert_spread_allowed(row: dict, *, registry: Optional[dict] = None,
                          enforce_flags: bool = True) -> dict:
    """Part-G triple gate. Raises SpreadNotEnabledError unless ALL hold:
      1. meta.strategy_json.family starts with 'earnings_vertical'
      2. registry entry has alpaca_paper_enabled: true
      3. registry entry has multi_leg_proven: true (Part-G key; absent
         everywhere today, absent == FALSE ⇒ nothing can submit)
    Credit families are refused UNCONDITIONALLY, flags ignored, even dry-run.

    enforce_flags=False (dry-run payload preview) still enforces the family
    rule and the credit block; the two registry flags are only REPORTED in
    the returned guard dict instead of raising, so an operator can inspect
    the exact mleg payload before flipping the flag.
    """
    family = str(_strategy_json(row).get("family") or "")
    if not family.startswith(SPREAD_FAMILY_PREFIX):
        raise SpreadNotEnabledError(
            f"meta.strategy_json.family {family!r} is not an "
            f"'{SPREAD_FAMILY_PREFIX}*' family — spread lane refuses")
    if family.startswith(SPREAD_CREDIT_PREFIX):
        raise SpreadNotEnabledError(
            "credit spreads blocked until assignment/reconciliation proven")
    sid = str(row.get("strategy") or _strategy_json(row).get("strategy_id") or "")
    from lib.options_pipeline.universe import registry_entry as _registry_entry
    entry = _registry_entry(sid, registry=registry) if sid else None
    enabled = (entry or {}).get("alpaca_paper_enabled") is True
    proven = (entry or {}).get(MULTI_LEG_PROVEN_KEY) is True
    guards = {"family": family, "strategy": sid,
              "registry_entry_found": entry is not None,
              "alpaca_paper_enabled": enabled, MULTI_LEG_PROVEN_KEY: proven}
    if enforce_flags:
        if entry is None:
            raise SpreadNotEnabledError(
                f"strategy {sid!r} has no registry entry — spread submit refused")
        if not enabled:
            raise SpreadNotEnabledError(
                f"registry entry {sid!r} has alpaca_paper_enabled false — "
                f"spread submit refused")
        if not proven:
            raise SpreadNotEnabledError(
                f"registry entry {sid!r} does not set {MULTI_LEG_PROVEN_KEY}: true — "
                f"multi-leg is unproven for this strategy, spread submit refused "
                f"(the key defaults to false)")
    return guards


def submit_spread_paper_order(proposal_row, *, confirm: bool = False,
                              dry_run: bool = False,
                              executor: Optional[Executor] = None,
                              client: Optional[AlpacaPaperOptionsClient] = None,
                              env: Optional[Dict[str, str]] = None,
                              registry: Optional[dict] = None) -> dict:
    """Submit ONE two-leg net-DEBIT earnings-vertical as a paper mleg LIMIT order.

    proposal_row may be the queue row dict itself or a proposal_id string.
    The Part-G gates (assert_spread_allowed) run FIRST — before confirm/state
    checks — so a disallowed proposal is refused identically on every path.

    dry_run: builds + returns the exact mleg payload with ZERO HTTP and zero
             writes (family + credit block still enforced; the registry flags
             are reported in 'guards', not enforced).
    real:    requires confirm=True (operator's --confirm), the row in
             READY_FOR_ALPACA_PAPER, and BOTH registry flags true; persists
             {request, response, readback, submitted_at, spread, legs[],
             leg_events[]} into meta.alpaca_json and moves the row to
             ALPACA_PAPER_SUBMITTED.
    """
    ex = executor or _default_executor()
    if isinstance(proposal_row, dict):
        row: Optional[dict] = proposal_row
        pid = str(row.get("proposal_id") or "")
    else:
        pid = str(proposal_row or "")
        row = get_queue_row(pid, ex) if pid else None
    if not pid:
        raise OperatorActionRequiredError("explicit --proposal-id is required")
    if not row:
        return {"ok": False, "error": f"proposal {pid!r} not in queue"}
    guards = assert_spread_allowed(row, registry=registry, enforce_flags=not dry_run)
    payload = build_spread_order_payload(row)
    if dry_run:
        return {"ok": True, "dry_run": True, "proposal_id": pid,
                "status": row.get("status"), "guards": guards,
                "would_submit": (row.get("status") == STATE_READY
                                 and guards["alpaca_paper_enabled"]
                                 and guards[MULTI_LEG_PROVEN_KEY]),
                "payload": payload, "http": "none (dry-run: zero HTTP)"}
    if not confirm:
        raise OperatorActionRequiredError(
            "spread submit refused — operator must pass --confirm (confirm=True). "
            "There is no automatic submit path.")
    if row.get("status") != STATE_READY:
        raise IllegalTransitionError(
            f"proposal {pid} is '{row.get('status')}' — only {STATE_READY} rows "
            f"may be submitted (use --mark-ready first)")
    specs = _spread_specs_from_proposal(row)
    cl = client or AlpacaPaperOptionsClient(env)   # paper endpoint guard runs here
    submitted_at = _now_iso()
    try:
        response = cl.submit_option_spread_limit_order(**specs)
    except Exception as e:  # persist the attempt, leave state at READY
        ex("""UPDATE options_approval_queue
              SET meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb, updated_at=NOW()
              WHERE proposal_id=%s""",
           (json.dumps({"alpaca_submit_error": {
               "request": payload, "error": str(e), "at": submitted_at,
               "spread": True}}, default=str), pid))
        return {"ok": False, "error": f"spread submit failed: {e}", "request": payload}
    order_id = str(response.get("id") or "")
    readback = None
    if order_id:
        try:
            readback = cl.get_order(order_id)
        except Exception as e:
            readback = {"readback_error": str(e)}
    resp_legs = {str(l.get("symbol") or ""): l
                 for l in (response.get("legs") or []) if isinstance(l, dict)}
    legs_detail = []
    for spec, built in zip(specs["legs"], payload["legs"]):
        legs_detail.append({**built,
                            "underlying": spec.get("underlying"),
                            "expiration": spec.get("expiration"),
                            "strike": spec.get("strike"),
                            "option_type": spec.get("option_type"),
                            "response_leg": resp_legs.get(built["symbol"])})
    leg_events = [{"symbol": b["symbol"], "event": "submitted",
                   "from": STATE_READY, "to": STATE_SUBMITTED,
                   "at": submitted_at} for b in payload["legs"]]
    transition(pid, STATE_SUBMITTED, executor=ex, meta_patch={
        "alpaca_json": {"request": payload, "response": response,
                        "readback": readback, "submitted_at": submitted_at,
                        "spread": True, "legs": legs_detail,
                        "leg_events": leg_events}})
    return {"ok": True, "proposal_id": pid, "order_id": order_id,
            "status": STATE_SUBMITTED, "spread": True, "request": payload,
            "response": response, "readback": readback, "legs": legs_detail}


# ── reconcile: fills / rejects / closes / outcomes ───────────────────────────

def _alpaca_meta(row: dict) -> dict:
    meta = row.get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (ValueError, TypeError):
            meta = {}
    return (meta or {}).get("alpaca_json") or {}


def _outcome_from_pnl(pnl: float) -> str:
    if pnl > SCRATCH_BAND_DOLLARS:
        return "win"
    if pnl < -SCRATCH_BAND_DOLLARS:
        return "loss"
    return "scratch"


def reconcile_fills(*, executor: Optional[Executor] = None,
                    client: Optional[AlpacaPaperOptionsClient] = None,
                    env: Optional[Dict[str, str]] = None,
                    dry_run: bool = False,
                    record_outcome_fn: Optional[Callable[..., dict]] = None) -> dict:
    """Poll SUBMITTED rows for fill/reject; FILLED rows for close → outcome.

    dry_run lists what would be polled — zero HTTP, zero writes.
    """
    ex = executor or _default_executor()
    submitted = list_rows_in_status(STATE_SUBMITTED, ex)
    filled = list_rows_in_status(STATE_FILLED, ex)
    closed_pending = list_rows_in_status(STATE_CLOSED, ex)  # outcome-record retries
    report: Dict[str, Any] = {"ok": True, "dry_run": dry_run,
                              "submitted_polled": len(submitted),
                              "filled_polled": len(filled),
                              "closed_retry": len(closed_pending),
                              "transitions": [], "warnings": []}
    if dry_run:
        report["would_poll"] = [
            {"proposal_id": r["proposal_id"], "status": r["status"]}
            for r in submitted + filled + closed_pending]
        return report
    if not submitted and not filled and not closed_pending:
        return report
    cl = None
    if submitted or filled:
        cl = client or AlpacaPaperOptionsClient(env)   # paper guard runs here

    if record_outcome_fn is None:
        from lib.options_pipeline.validation import record_outcome as record_outcome_fn

    for row in submitted:
        pid = row["proposal_id"]
        aj = _alpaca_meta(row)
        order_id = str((aj.get("response") or {}).get("id") or "")
        if not order_id:
            report["warnings"].append(f"{pid}: no order id in meta.alpaca_json — skipped")
            continue
        try:
            order = cl.get_order(order_id)
        except Exception as e:
            report["warnings"].append(f"{pid}: order poll failed: {e}")
            continue
        ostatus = str((order or {}).get("status") or "").lower()
        if ostatus == "filled":
            if _is_spread_meta(aj):
                # multi-leg: aggregate the legs into ONE net-debit entry
                net_entry = _net_signed_from_order(order)
                fill = {"net_debit": net_entry, "qty": order.get("filled_qty"),
                        "filled_at": order.get("filled_at"),
                        "legs": order.get("legs"), "order": order}
                leg_events = (aj.get("leg_events") or []) + [
                    {"symbol": str(lg.get("symbol") or ""), "event": "filled",
                     "price": lg.get("filled_avg_price"), "to": STATE_FILLED,
                     "at": _now_iso()} for lg in (order.get("legs") or [])]
                transition(pid, STATE_FILLED, executor=ex,
                           meta_patch={"alpaca_json": {**aj, "fill": fill,
                                                       "leg_events": leg_events}})
                report["transitions"].append({"proposal_id": pid, "to": STATE_FILLED,
                                              "net_debit": net_entry, "spread": True})
                continue
            fill = {"price": float(order.get("filled_avg_price") or 0.0),
                    "qty": order.get("filled_qty"),
                    "filled_at": order.get("filled_at"),
                    "order": order}
            transition(pid, STATE_FILLED, executor=ex,
                       meta_patch={"alpaca_json": {**aj, "fill": fill}})
            report["transitions"].append({"proposal_id": pid, "to": STATE_FILLED,
                                          "fill_price": fill["price"]})
            _sync_monitored_on_fill(row, fill, ex, report)
        elif ostatus in ("rejected", "canceled", "cancelled", "expired"):
            reason = str(order.get("reject_reason") or ostatus)
            transition(pid, STATE_REJECTED, executor=ex,
                       meta_patch={"alpaca_json": {**aj, "reject": {
                           "reason": reason, "order": order, "at": _now_iso()}}})
            report["transitions"].append({"proposal_id": pid, "to": STATE_REJECTED,
                                          "reason": reason})
        # partially_filled / new / accepted → leave as SUBMITTED

    for row in filled:
        pid = row["proposal_id"]
        aj = _alpaca_meta(row)
        if _is_spread_meta(aj):
            _reconcile_spread_position(row, aj, cl, ex, record_outcome_fn, report)
            continue
        occ = str((aj.get("request") or {}).get("symbol") or "")
        if not occ:
            report["warnings"].append(f"{pid}: no OCC symbol in meta — skipped")
            continue
        try:
            pos = cl.get_position(occ)
        except Exception as e:
            report["warnings"].append(f"{pid}: position poll failed: {e}")
            continue
        if pos is not None:
            continue  # still open on Alpaca paper
        # Position gone → find the closing (sell) fill for exit premium.
        try:
            closed_orders = cl.list_closed_orders(occ)
        except Exception as e:
            report["warnings"].append(f"{pid}: closed-order poll failed: {e}")
            continue
        close_order = next(
            (o for o in closed_orders
             if str(o.get("side") or "").lower() == "sell"
             and str(o.get("status") or "").lower() == "filled"), None)
        if close_order is None:
            report["warnings"].append(
                f"{pid}: position gone but no closing sell fill found — left in "
                f"{STATE_FILLED} for operator investigation (expiry/exercise?)")
            continue
        entry_px = float((aj.get("fill") or {}).get("price") or 0.0)
        exit_px = float(close_order.get("filled_avg_price") or 0.0)
        qty = 1  # structural cap
        entry_debit = round(entry_px * 100.0 * qty, 2)
        exit_value = round(exit_px * 100.0 * qty, 2)
        pnl = round(exit_value - entry_debit, 2)
        close_blob = {"exit_price": exit_px, "closed_at": close_order.get("filled_at"),
                      "close_order": close_order, "pnl": pnl,
                      "entry_debit": entry_debit, "exit_value": exit_value}
        aj = {**aj, "close": close_blob}
        transition(pid, STATE_CLOSED, executor=ex, meta_patch={"alpaca_json": aj})
        report["transitions"].append({"proposal_id": pid, "to": STATE_CLOSED, "pnl": pnl})
        _sync_monitored_on_close(pid, ex, report, pnl=pnl)
        _record_and_finalize(row, aj, ex, record_outcome_fn, report)

    # CLOSED rows whose record_outcome previously failed → retry, no HTTP needed.
    for row in closed_pending:
        _record_and_finalize(row, _alpaca_meta(row), ex, record_outcome_fn, report)
    return report


def _sync_monitored_on_fill(row: dict, fill: dict, ex: Executor,
                            report: Dict[str, Any]) -> None:
    """Hybrid ingest: queue fill → options_monitored_positions (advisory registry)."""
    pid = row.get("proposal_id") or ""
    try:
        from lib.options_pipeline import paper_positions as pp
        updated = dict(row)
        updated["status"] = STATE_FILLED
        meta = dict(row.get("meta") or {})
        meta["alpaca_json"] = {**_alpaca_meta(row), "fill": fill}
        updated["meta"] = meta
        res = pp.upsert_from_queue_fill(updated, fill=fill, executor=ex)
        if not res.get("ok"):
            report["warnings"].append(
                f"{pid}: monitored position upsert failed: {res.get('error')}")
        else:
            report.setdefault("monitored_positions", []).append(res)
            pos = pp.get_position_by_proposal(pid, executor=ex)
            if pos:
                from lib.options_pipeline import paper_position_alerts as ppa
                from lib.options_pipeline.paper_position_monitor import load_config
                alert = ppa.dispatch_lifecycle_alert(
                    pos, alert_type=ppa.LIFECYCLE_FILLED,
                    message=f"Alpaca paper fill @ ${float(fill.get('price') or 0):.2f}",
                    cfg=load_config(), executor=ex,
                    extra={"fill_price": fill.get("price")})
                report.setdefault("alerts", []).append(alert)
    except Exception as e:
        report["warnings"].append(f"{pid}: monitored position upsert error: {e}")


def _sync_monitored_on_close(proposal_id: str, ex: Executor,
                             report: Dict[str, Any],
                             *, pnl: float | None = None) -> None:
    """Broker reconcile close → mark monitored position CLOSED (ledger outcome is separate)."""
    try:
        from lib.options_pipeline import paper_positions as pp
        res = pp.mark_closed(proposal_id, reason="broker_reconcile", executor=ex)
        if not res.get("ok"):
            report["warnings"].append(
                f"{proposal_id}: monitored position close mark failed")
        else:
            report.setdefault("monitored_positions", []).append(res)
            pos = pp.get_position_by_proposal(proposal_id, executor=ex)
            if pos:
                from lib.options_pipeline import paper_position_alerts as ppa
                from lib.options_pipeline.paper_position_monitor import load_config
                alert = ppa.dispatch_lifecycle_alert(
                    pos, alert_type=ppa.LIFECYCLE_CLOSED,
                    message="Broker reconcile detected close — outcome ready",
                    cfg=load_config(), executor=ex, extra={"pnl": pnl})
                report.setdefault("alerts", []).append(alert)
    except Exception as e:
        report["warnings"].append(
            f"{proposal_id}: monitored position close error: {e}")


def _record_and_finalize(row: dict, aj: dict, ex: Executor,
                         record_outcome_fn: Callable[..., dict],
                         report: Dict[str, Any]) -> None:
    """CLOSED → record_outcome → OUTCOME_RECORDED (idempotent: upsert ledger)."""
    pid = row["proposal_id"]
    close = aj.get("close") or {}
    if not close:
        report["warnings"].append(f"{pid}: CLOSED but no close blob in meta — skipped")
        return
    pnl = float(close.get("pnl") or 0.0)
    req = aj.get("request") or {}
    occ = str(req.get("symbol") or "") or ",".join(
        str(l.get("symbol") or "") for l in (req.get("legs") or []))
    rec = record_outcome_fn(
        pid,
        outcome=_outcome_from_pnl(pnl),
        strategy_id=row.get("strategy") or "deep_itm_call",
        symbol=row.get("symbol") or "",
        pnl=pnl,
        entry_debit=close.get("entry_debit"),
        exit_value=close.get("exit_value"),
        opened_at=(aj.get("fill") or {}).get("filled_at"),
        closed_at=close.get("closed_at"),
        exit_reason="manual",
        notes="alpaca paper close detected by reconcile_fills",
        meta={"alpaca_order_id": (aj.get("response") or {}).get("id"),
              "occ_symbol": occ, "lane": "alpaca_paper"},
        executor=ex)
    if not rec.get("ok"):
        report["warnings"].append(
            f"{pid}: record_outcome failed ({rec.get('error')}) — left in "
            f"{STATE_CLOSED}; reconcile will retry")
        return
    transition(pid, STATE_OUTCOME, executor=ex,
               meta_patch={"outcome_recorded_at": _now_iso()})
    report["transitions"].append({"proposal_id": pid, "to": STATE_OUTCOME})


# ── Part G reconcile helpers: multi-leg → ONE outcome, expiry/assignment ─────

def _is_spread_meta(aj: dict) -> bool:
    return str((aj.get("request") or {}).get("order_class") or "") == "mleg"


def _net_signed_from_order(order: dict) -> float:
    """Per-share net across legs, buy legs +, sell legs −.

    Entry of a debit vertical → +net_debit; its closing order → −net_credit.
    Falls back to the parent order's filled_avg_price when no legs are echoed.
    """
    legs = (order or {}).get("legs") or []
    if legs:
        net = 0.0
        for lg in legs:
            px = float(lg.get("filled_avg_price") or 0.0)
            net += px if str(lg.get("side") or "").lower() == "buy" else -px
        return round(net, 4)
    return round(float((order or {}).get("filled_avg_price") or 0.0), 4)


def _occ_expiration_date(occ: str):
    """Expiration date parsed out of an OCC symbol, or None."""
    m = re.match(r"^[A-Z0-9]{1,6}(\d{6})[CP]\d{8}$", str(occ or ""))
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%y%m%d").date()
    except ValueError:
        return None


def _occ_root(occ: str) -> str:
    """Underlying root from an OCC symbol (everything before the 15-char tail)."""
    s = str(occ or "")
    return s[:-15] if len(s) > 15 else ""


def _is_spread_close(order: dict, entry_sides: Dict[str, str]) -> bool:
    """A filled mleg order on the SAME legs with every side OPPOSITE to entry."""
    if str(order.get("status") or "").lower() != "filled":
        return False
    if str(order.get("order_class") or "") != "mleg":
        return False
    legs = order.get("legs") or []
    if len(legs) != len(entry_sides):
        return False
    for lg in legs:
        sym = str(lg.get("symbol") or "")
        if sym not in entry_sides:
            return False
        if str(lg.get("side") or "").lower() == entry_sides[sym]:
            return False  # same direction as entry → adds exposure, not a close
    return True


def _persist_spread_flag(pid: str, aj: dict, ex: Executor) -> None:
    """Meta-only patch (no state change) — write the FULL alpaca_json blob
    because jsonb || merges shallowly."""
    ex("""UPDATE options_approval_queue
          SET meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb, updated_at=NOW()
          WHERE proposal_id=%s""",
       (json.dumps({"alpaca_json": aj}, default=str), pid))


def _flag_spread_assignment(row: dict, aj: dict, cl, ex: Executor,
                            report: Dict[str, Any], *, note: str = "") -> None:
    """Exercise/assignment suspicion → risk note, row LEFT in FILLED (honest)."""
    pid = row["proposal_id"]
    if aj.get("assignment"):
        report["warnings"].append(
            f"{pid}: assignment already flagged — awaiting operator resolution")
        return
    req_legs = (aj.get("request") or {}).get("legs") or []
    root = _occ_root(str((req_legs[0] or {}).get("symbol") or "")) if req_legs else ""
    stock_pos = None
    if root:
        try:
            stock_pos = cl.get_position(root)
        except Exception as e:
            report["warnings"].append(f"{pid}: underlying position poll failed: {e}")
            return
    risk_note = ("exercise/assignment suspected on spread — outcome NOT "
                 "auto-recorded; operator must inspect the paper account, flatten "
                 "any residual stock, and resolve manually. " + note).strip()
    aj2 = {**aj, "assignment": {"detected_at": _now_iso(), "underlying": root,
                                "stock_position": stock_pos,
                                "risk_note": risk_note}}
    _persist_spread_flag(pid, aj2, ex)
    report["warnings"].append(f"{pid}: RISK — {risk_note}")


def _flag_spread_expiry(row: dict, aj: dict, cl, ex: Executor,
                        report: Dict[str, Any]) -> None:
    """Post-expiry poll: stock position ⇒ assignment note; none ⇒ disposition
    UNKNOWN. Either way the row stays FILLED — no outcome is invented.

    LIMITATION (documented): the positions endpoint cannot distinguish a
    worthless expiry (max loss) from fully-ITM exercise+assignment that
    netted flat stock (max profit). Resolving that would need the account
    activities endpoint, which this lane deliberately does not automate.
    """
    pid = row["proposal_id"]
    if aj.get("assignment") or aj.get("expiry_check"):
        report["warnings"].append(
            f"{pid}: expiry/assignment already flagged — awaiting operator resolution")
        return
    req_legs = (aj.get("request") or {}).get("legs") or []
    root = _occ_root(str((req_legs[0] or {}).get("symbol") or "")) if req_legs else ""
    stock_pos = None
    if root:
        try:
            stock_pos = cl.get_position(root)
        except Exception as e:
            report["warnings"].append(f"{pid}: underlying position poll failed: {e}")
            return
    if stock_pos is not None:
        risk_note = ("post-expiry stock position detected on the underlying — "
                     "probable exercise/assignment; outcome NOT auto-recorded, "
                     "operator must resolve")
        aj2 = {**aj, "assignment": {"detected_at": _now_iso(), "underlying": root,
                                    "stock_position": stock_pos,
                                    "risk_note": risk_note}}
        _persist_spread_flag(pid, aj2, ex)
        report["warnings"].append(f"{pid}: RISK — {risk_note}")
        return
    aj2 = {**aj, "expiry_check": {"at": _now_iso(), "disposition": "unknown",
           "note": ("legs expired with no closing fill and no residual stock "
                    "position — positions polling cannot distinguish worthless "
                    "expiry from fully-ITM exercise+assignment that netted flat; "
                    "outcome NOT auto-recorded (see module limitations)")}}
    _persist_spread_flag(pid, aj2, ex)
    report["warnings"].append(
        f"{pid}: spread expired, disposition UNKNOWN — left in {STATE_FILLED} "
        f"for operator resolution")


def _reconcile_spread_position(row: dict, aj: dict, cl, ex: Executor,
                               record_outcome_fn: Callable[..., dict],
                               report: Dict[str, Any]) -> None:
    """FILLED spread → close detection / post-expiry poll → ONE outcome.

    Aggregation contract: both legs always resolve to a SINGLE paper outcome —
    net debit in, net value out, pnl = (net_out − net_in) × 100 × 1 spread.
    """
    pid = row["proposal_id"]
    req = aj.get("request") or {}
    leg_syms = [str(l.get("symbol") or "") for l in (req.get("legs") or [])]
    if len(leg_syms) != 2 or not all(leg_syms):
        report["warnings"].append(f"{pid}: spread meta lacks 2 leg symbols — skipped")
        return
    open_syms: List[str] = []
    for s in leg_syms:                       # positions endpoint, PER LEG
        try:
            pos = cl.get_position(s)
        except Exception as e:
            report["warnings"].append(f"{pid}: leg position poll failed ({s}): {e}")
            return
        if pos is not None:
            open_syms.append(s)
    if len(open_syms) == len(leg_syms):
        return  # both legs still open on Alpaca paper — nothing to do
    if open_syms:
        gone = sorted(set(leg_syms) - set(open_syms))
        _flag_spread_assignment(
            row, aj, cl, ex, report,
            note=f"legs {gone} gone while {open_syms} remain open — probable "
                 f"early exercise/assignment on one leg")
        return
    # both legs gone → look for the closing mleg fill
    try:
        closed_orders = cl.list_closed_orders(leg_syms[0])
    except Exception as e:
        report["warnings"].append(f"{pid}: closed-order poll failed: {e}")
        return
    entry_sides = {str(l.get("symbol") or ""): str(l.get("side") or "").lower()
                   for l in (req.get("legs") or [])}
    close_order = next((o for o in closed_orders
                        if _is_spread_close(o, entry_sides)), None)
    if close_order is not None:
        entry_net = float((aj.get("fill") or {}).get("net_debit") or 0.0)
        exit_net = round(-_net_signed_from_order(close_order), 4)
        entry_debit = round(entry_net * 100.0, 2)   # ONE spread — structural
        exit_value = round(exit_net * 100.0, 2)
        pnl = round(exit_value - entry_debit, 2)
        now = _now_iso()
        close_blob = {"exit_net": exit_net,
                      "closed_at": close_order.get("filled_at"),
                      "close_order": close_order, "pnl": pnl,
                      "entry_debit": entry_debit, "exit_value": exit_value}
        aj2 = {**aj, "close": close_blob,
               "leg_events": (aj.get("leg_events") or []) + [
                   {"symbol": s, "event": "closed", "to": STATE_CLOSED,
                    "at": now} for s in leg_syms]}
        transition(pid, STATE_CLOSED, executor=ex, meta_patch={"alpaca_json": aj2})
        report["transitions"].append({"proposal_id": pid, "to": STATE_CLOSED,
                                      "pnl": pnl, "spread": True})
        _record_and_finalize(row, aj2, ex, record_outcome_fn, report)
        return
    # no closing fill: post-expiry poll, otherwise operator investigation
    exps = [_occ_expiration_date(s) for s in leg_syms]
    if all(exps) and datetime.now(timezone.utc).date() > max(exps):
        _flag_spread_expiry(row, aj, cl, ex, report)
    else:
        report["warnings"].append(
            f"{pid}: spread legs gone but no closing fill found — left in "
            f"{STATE_FILLED} for operator investigation")
