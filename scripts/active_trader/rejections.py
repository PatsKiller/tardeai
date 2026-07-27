"""Active Trader Stage 3 — deterministic broker rejection classifier.

Rule pipeline (ordered by specificity, broker-scoped, versioned, fixture-covered):
  1. broker-specific EXACT_CODE rules (raw code/status equality)
  2. broker-specific bounded MESSAGE_PATTERN rules (narrow substrings)
  3. cross-broker STRUCTURAL rules (http status / order-state shape)
  4. FALLBACK → UNKNOWN_BROKER_REJECTION (non-retryable, operator-required)

No raw-message substring alone can trigger an unbounded automatic action: the
classifier only labels; every action decision lives in the fallback evaluator and
notification policy, both of which fail closed on UNKNOWN.

Persistence targets the LAB database only (same guard as the migration runner).
Raw payloads are redacted before they ever reach a dataclass.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from active_trader.contracts import (
    ALLOWED_BROKERS, ContractViolation, Environment, KNOWN_REJECTION_CODES,
)
from active_trader.discovery import mask_identifier

CLASSIFIER_VERSION = "stage3-v1.0"

# ---------------------------------------------------------------- redaction

_REDACT_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(authorization[:=]\s*)\S+"),
    re.compile(r"(?i)(api[-_]?key[:=\s]+)\S+"),
    re.compile(r"(?i)(token[:=]\s*)\S+"),
]
# long digit runs (account-number risk) — free-text messages only, so structured
# broker codes like alpaca 40310000 survive for exact-code rules
_DIGIT_RUN = re.compile(r"\b\d{8,}\b")


def redact(text: Optional[str], limit: int = 300, digit_runs: bool = True) -> str:
    s = str(text or "")[:limit]
    for pat in _REDACT_PATTERNS:
        s = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", s)
    if digit_runs:
        s = _DIGIT_RUN.sub("[REDACTED]", s)
    return s


# ---------------------------------------------------------------- raw event

@dataclass(frozen=True)
class RawBrokerEvent:
    broker: str
    account_label: str
    masked_account_id: str
    symbol: Optional[str]
    order_intent_id: Optional[str]
    raw_status: str
    raw_code: str
    raw_message: str
    http_status: Optional[int]
    order_state: Optional[str]
    filled_quantity: Optional[float]
    remaining_quantity: Optional[float]
    observed_at: str
    adapter_version: str
    provenance: str = "SYNTHETIC"    # CAPTURED_REDACTED | SYNTHETIC | SYNTHETIC_FUTURE_ADAPTER

    def __post_init__(self):
        if self.broker not in ALLOWED_BROKERS:
            raise ContractViolation(f"broker {self.broker!r} outside v1 scope")
        if self.provenance not in ("CAPTURED_REDACTED", "SYNTHETIC", "SYNTHETIC_FUTURE_ADAPTER"):
            raise ContractViolation(f"unknown fixture provenance {self.provenance!r}")
        object.__setattr__(self, "raw_status", redact(self.raw_status, digit_runs=False))
        object.__setattr__(self, "raw_code", redact(self.raw_code, digit_runs=False))
        object.__setattr__(self, "raw_message", redact(self.raw_message, digit_runs=True))
        object.__setattr__(self, "masked_account_id", mask_identifier(self.masked_account_id)
                           if any(c.isdigit() for c in str(self.masked_account_id)[:-4])
                           else self.masked_account_id)

    @property
    def idempotency_key(self) -> str:
        return hashlib.sha256("|".join([
            self.broker, self.account_label, str(self.symbol), str(self.order_intent_id),
            self.raw_status, self.raw_code, self.raw_message]).encode()).hexdigest()


@dataclass(frozen=True)
class Classification:
    normalized_code: str
    retryable: bool
    requires_operator: bool
    requires_broker_call: bool
    affected_capability: Optional[str]
    scope: str                       # symbol | account | account+symbol | session | none
    confidence: str                  # EXACT_CODE | MESSAGE_PATTERN | STRUCTURAL | FALLBACK
    matched_rule_id: str
    classifier_version: str
    reason: str
    retry_backoff_seconds: Optional[int] = None   # only RATE_LIMITED carries bounded backoff

    def __post_init__(self):
        if self.normalized_code not in KNOWN_REJECTION_CODES:
            raise ContractViolation(f"unregistered normalized code {self.normalized_code!r}")
        if self.normalized_code == "RATE_LIMITED" and self.retryable and not self.retry_backoff_seconds:
            raise ContractViolation("RATE_LIMITED may be retryable only with bounded backoff metadata")
        if self.normalized_code == "UNKNOWN_BROKER_REJECTION" and self.retryable:
            raise ContractViolation("UNKNOWN_BROKER_REJECTION can never be retryable")


# ---------------------------------------------------------------- rules

def _c(code, *, retry=False, op=True, call=False, cap=None, scope="account+symbol",
       backoff=None):
    return dict(normalized_code=code, retryable=retry, requires_operator=op,
                requires_broker_call=call, affected_capability=cap, scope=scope,
                retry_backoff_seconds=backoff)


# 1) broker-specific EXACT_CODE rules: (rule_id, broker, raw_code_upper, outcome)
EXACT_RULES = [
    ("AL-EX-001", "alpaca", "40310000", _c("INSUFFICIENT_BUYING_POWER", scope="account")),
    ("AL-EX-002", "alpaca", "ASSET_NOT_TRADABLE", _c("SECURITY_NOT_DAY_TRADE_ELIGIBLE",
                                                     cap="SYMBOL_TRADABILITY", scope="symbol")),
    ("AL-EX-003", "alpaca", "42910000", _c("RATE_LIMITED", retry=True, op=False,
                                           scope="account", backoff=30)),
    ("SW-EX-001", "schwab", "ORDER_VALIDATION_BROKER_ASSIST",
     _c("SECURITY_REQUIRES_BROKER_ASSISTANCE", call=True,
        cap="ELECTRONIC_ENTRY_ELIGIBILITY", scope="account+symbol")),
    ("MM-EX-001", "moomoo", "RET_RATE_LIMIT", _c("RATE_LIMITED", retry=True, op=False,
                                                 scope="account", backoff=30)),
    ("MM-EX-002", "moomoo", "RET_UNLOCK_REQUIRED", _c("ACCOUNT_NOT_AUTHORIZED",
                                                      cap="LIVE_SESSION_UNLOCK", scope="account")),
]

# 2) broker-specific bounded MESSAGE_PATTERN rules: (rule_id, broker, lowercase needle, outcome)
PATTERN_RULES = [
    ("SW-PT-001", "schwab", "broker assistance", _c("SECURITY_REQUIRES_BROKER_ASSISTANCE",
        call=True, cap="ELECTRONIC_ENTRY_ELIGIBILITY")),
    ("SW-PT-002", "schwab", "not permitted for electronic", _c("ELECTRONIC_ENTRY_NOT_ALLOWED",
        cap="ELECTRONIC_ENTRY_ELIGIBILITY")),
    ("SW-PT-003", "schwab", "opening transactions in this security are not permitted",
     _c("ELECTRONIC_ENTRY_NOT_ALLOWED", cap="ELECTRONIC_ENTRY_ELIGIBILITY")),
    ("SW-PT-004", "schwab", "acceptance review", _c("LOW_PRICE_OR_MICROCAP_RESTRICTION",
        cap="ELECTRONIC_ENTRY_ELIGIBILITY")),
    ("SW-PT-005", "schwab", "low-priced security", _c("LOW_PRICE_OR_MICROCAP_RESTRICTION",
        cap="ELECTRONIC_ENTRY_ELIGIBILITY")),
    ("SW-PT-006", "schwab", "not available during extended", _c("SESSION_NOT_SUPPORTED",
        cap="PLACE_LIMIT_EXTENDED", scope="session")),
    ("SW-PT-007", "schwab", "insufficient buying power", _c("INSUFFICIENT_BUYING_POWER",
        scope="account")),
    ("AL-PT-001", "alpaca", "insufficient buying power", _c("INSUFFICIENT_BUYING_POWER",
        scope="account")),
    ("AL-PT-002", "alpaca", "asset is not tradable", _c("SECURITY_NOT_DAY_TRADE_ELIGIBLE",
        cap="SYMBOL_TRADABILITY", scope="symbol")),
    ("AL-PT-003", "alpaca", "order type is not supported", _c("ORDER_TYPE_NOT_SUPPORTED",
        cap="PLACE_LIMIT_RTH", scope="session")),
    ("AL-PT-004", "alpaca", "extended hours", _c("SESSION_NOT_SUPPORTED",
        cap="PLACE_LIMIT_EXTENDED", scope="session")),
    ("AL-PT-005", "alpaca", "sub-penny", _c("PRICE_INCREMENT_INVALID", scope="symbol")),
    ("AL-PT-006", "alpaca", "increment", _c("PRICE_INCREMENT_INVALID", scope="symbol")),
    ("AL-PT-007", "alpaca", "qty must be", _c("QUANTITY_LIMIT_REJECTED", scope="symbol")),
    ("AL-PT-008", "alpaca", "market is closed", _c("MARKET_CLOSED", retry=True, op=False,
        scope="session", backoff=60)),
    ("MM-PT-001", "moomoo", "price invalid", _c("PRICE_INCREMENT_INVALID", scope="symbol")),
    ("MM-PT-002", "moomoo", "session not supported", _c("SESSION_NOT_SUPPORTED", scope="session")),
    ("XB-PT-001", None, "halted", _c("HALTED", scope="symbol")),
    ("XB-PT-002", None, "wash trade", _c("POSITION_OR_ORDER_CONFLICT")),
]

# 3) cross-broker STRUCTURAL rules
def _structural(event: RawBrokerEvent):
    if event.http_status in (401, 403):
        # never retried in the order path; reauth belongs to the managed process
        return "XB-ST-001", _c("AUTHENTICATION_EXPIRED", scope="account")
    if event.http_status == 429:
        return "XB-ST-002", _c("RATE_LIMITED", retry=True, op=False, scope="account", backoff=30)
    if event.order_state == "STALE":
        return "XB-ST-003", _c("STALE_ACCOUNT_STATE", retry=True, op=False,
                               scope="account", backoff=10)
    return None


RULE_INDEX = {rid: ("EXACT_CODE", broker) for rid, broker, _, _ in EXACT_RULES}
RULE_INDEX.update({rid: ("MESSAGE_PATTERN", broker) for rid, broker, _, _ in PATTERN_RULES})


def classify(event: RawBrokerEvent) -> Classification:
    """Deterministic classification. Same input → same output, always."""
    code_u = (event.raw_code or "").strip().upper()
    for rule_id, broker, raw_code, outcome in EXACT_RULES:
        if broker == event.broker and code_u == raw_code:
            return Classification(**outcome, confidence="EXACT_CODE", matched_rule_id=rule_id,
                                  classifier_version=CLASSIFIER_VERSION,
                                  reason=f"exact broker code match ({raw_code})")
    msg_l = re.sub(r"\s+", " ", (event.raw_message or "").lower()).strip()
    for rule_id, broker, needle, outcome in PATTERN_RULES:
        if broker in (None, event.broker) and needle in msg_l:
            return Classification(**outcome, confidence="MESSAGE_PATTERN", matched_rule_id=rule_id,
                                  classifier_version=CLASSIFIER_VERSION,
                                  reason=f"bounded message pattern ({rule_id})")
    st = _structural(event)
    if st:
        rule_id, outcome = st
        return Classification(**outcome, confidence="STRUCTURAL", matched_rule_id=rule_id,
                              classifier_version=CLASSIFIER_VERSION,
                              reason="cross-broker structural signal")
    return Classification(
        normalized_code="UNKNOWN_BROKER_REJECTION", retryable=False, requires_operator=True,
        requires_broker_call=False, affected_capability=None, scope="account+symbol",
        confidence="FALLBACK", matched_rule_id="XB-FB-000",
        classifier_version=CLASSIFIER_VERSION,
        reason="no broker rule matched; failing closed to unknown")


# ---------------------------------------------------------------- capability projection

@dataclass(frozen=True)
class CapabilityEvidenceProposal:
    """A rejection may PROPOSE a capability restriction. It never mutates the
    capability registry directly; persistence writes an auditable evidence row
    and higher-confidence accepted evidence is never silently overwritten."""

    broker: str
    account_label: str
    environment: Environment
    capability: str
    proposed_state: str              # RESTRICTED (rejections restrict; they never grant)
    scope: str                       # account+symbol | account | session
    symbol: Optional[str]
    source_rejection_key: str
    expires_review: str
    idempotency_key: str = field(default="")

    def __post_init__(self):
        if self.proposed_state != "RESTRICTED":
            raise ContractViolation("a rejection can only propose RESTRICTED, never SUPPORTED")
        object.__setattr__(self, "idempotency_key", hashlib.sha256(
            f"{self.broker}|{self.account_label}|{self.capability}|{self.scope}|{self.symbol}|{self.source_rejection_key}".encode()
        ).hexdigest())


def project_capability(event: RawBrokerEvent, cls: Classification,
                       review_days: int = 30) -> Optional[CapabilityEvidenceProposal]:
    if not cls.affected_capability:
        return None
    scope = cls.scope
    symbol = event.symbol if "symbol" in scope else None
    from datetime import timedelta
    review = (datetime.now(timezone.utc) + timedelta(days=review_days)).isoformat()
    return CapabilityEvidenceProposal(
        broker=event.broker, account_label=event.account_label,
        environment=Environment.LIVE if event.broker == "schwab" else Environment.SIMULATION,
        capability=cls.affected_capability, proposed_state="RESTRICTED", scope=scope,
        symbol=symbol, source_rejection_key=event.idempotency_key, expires_review=review)


# ---------------------------------------------------------------- lab persistence

def persist_rejection(dsn: str, event: RawBrokerEvent, cls: Classification,
                      proposal: Optional[CapabilityEvidenceProposal] = None) -> str:
    """Idempotent: replaying the same raw event increments occurrence_count on the
    single existing row. Returns the rejection_event_id."""
    from active_trader.migrate import _resolve_dsn
    import psycopg2, uuid
    conn = psycopg2.connect(_resolve_dsn(dsn))
    try:
        cur = conn.cursor()
        ev_hash = hashlib.sha256(json.dumps(asdict(event), sort_keys=True).encode()).hexdigest()
        rid = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO broker_rejection_events
                   (rejection_event_id, environment, broker, account_label, symbol,
                    order_intent_id, raw_status, raw_code, raw_message, normalized_code,
                    retryable, requires_operator, requires_broker_call, affected_capability,
                    evidence_hash, idempotency_key, classifier_version, matched_rule_id,
                    confidence, capability_evidence_ref)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (idempotency_key) DO UPDATE SET
                    occurrence_count = broker_rejection_events.occurrence_count + 1,
                    last_seen_at = now()
               RETURNING rejection_event_id""",
            (rid, "SIMULATION" if event.provenance != "CAPTURED_REDACTED" else "LIVE",
             event.broker, event.account_label, event.symbol,
             None,  # order_intent_id is synthetic in Stage 3 fixtures; FK-free column stays null
             event.raw_status, event.raw_code, event.raw_message, cls.normalized_code,
             cls.retryable, cls.requires_operator, cls.requires_broker_call,
             cls.affected_capability, ev_hash, event.idempotency_key,
             cls.classifier_version, cls.matched_rule_id, cls.confidence,
             proposal.idempotency_key if proposal else None))
        out = cur.fetchone()[0]
        conn.commit()
        return str(out)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
