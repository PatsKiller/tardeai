"""Advisory layer — deterministic desk + opinion engine + L4 memory (S1–S3 / Phase 3)."""

from lib.advisory.advisory_opinion_engine import (
    generate_row_opinion,
    generate_desk_synthesis,
    validate_opinion_output,
)
from lib.advisory.advisory_memory import (
    REASON_CODES,
    append_run_history,
    apply_thrash_penalty,
    build_memory_for_row,
    format_memory_block,
    load_calibration,
    load_prior_for_row,
    record_feedback,
    score_pending_outcomes,
)

# Phase 5 shadow (optional import — heavy paths stay lazy in runners)
