"""Hermes Discovery Inbox package (Stage 1) — advisory-only candidate intake.

Never imports broker/execution modules (brokers/, schwab_adapter, alpaca) —
enforced by tests/test_hermes_discovery_inbox.py's source grep.
"""
from .dedupe import NEAR_DUP_JACCARD, find_near_duplicate, jaccard, normalize_key, tokenize
from .feedback import (FEEDBACK_DELTAS, MAX_ABS_DELTA, WEIGHTS_PATH,
                       apply_weight_delta, load_weight_adjustments, record_feedback)
from .inbox import (ALLOWED_TRANSITIONS, CANDIDATE_TYPES, DECISIONS, SAFE_ACTION_LEVELS,
                    STATUSES, CandidateNotFoundError, DBUnavailableError,
                    DiscoveryInboxError, IllegalTransitionError, decide_candidate,
                    get_candidate, inbox_stats, list_candidates,
                    transition_candidate, upsert_candidate)
from .scoring import PENALTIES, SCORING_VERSION, WEIGHTS, discovery_score
from .symbol_validation import (DENYLIST, VERDICT_INVALID, VERDICT_NEEDS_VALIDATION,
                                VERDICT_VALID, validate_ticker)

__all__ = [
    "ALLOWED_TRANSITIONS", "CANDIDATE_TYPES", "DECISIONS", "DENYLIST",
    "FEEDBACK_DELTAS", "MAX_ABS_DELTA", "NEAR_DUP_JACCARD", "PENALTIES",
    "SAFE_ACTION_LEVELS", "SCORING_VERSION", "STATUSES", "VERDICT_INVALID",
    "VERDICT_NEEDS_VALIDATION", "VERDICT_VALID", "WEIGHTS", "WEIGHTS_PATH",
    "CandidateNotFoundError", "DBUnavailableError", "DiscoveryInboxError",
    "IllegalTransitionError", "apply_weight_delta", "decide_candidate",
    "discovery_score", "find_near_duplicate", "get_candidate", "inbox_stats",
    "jaccard", "list_candidates", "load_weight_adjustments", "normalize_key",
    "record_feedback", "tokenize", "transition_candidate", "upsert_candidate",
    "validate_ticker",
]
