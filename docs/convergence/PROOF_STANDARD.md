# Proof Standard

Evidence labels are strict: SOURCE_ONLY, UNIT, INTEGRATION, HISTORICAL_REPLAY,
GOLDEN_SHADOW, SHADOW, DRY_RUN, OPERATOR_REQUESTED_LIVE, CURRENT_SMOKE,
NATURAL_CURRENT, NATURAL_LONGITUDINAL.

Callable code is not live. A live claim requires correct source SHA, process/runtime
proof, natural execution, operator visibility, and persistent evidence. Missing proof is
UNMEASURED, not zero and not inferred from a passing unit test.
