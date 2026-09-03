# RUNTIME_NEGATIVE_CONTROLS

Each control must be detected for the expected reason.

## inconsistent_position_count — PASS
- expected: overview.position_count != risk.position_count
- detected: True

## split_root_stale_date — PASS
- expected: STALE from data_as_of; never fresh via as_of/last_repriced
- detected: True

## literal_fresh_stale_file — PASS
- expected: pipeline_status=fresh while chrome data clock is STALE
- detected: True

## missing_envelope_fields — PASS
- expected: missing data_as_of → STALE · data UNDATED; asOf null
- detected: True

## wrong_build_sha — PASS
- expected: build identity mismatch vs expected SHA
- detected: True

## unaccounted_route — PASS
- expected: discovered page missing from route ledger
- detected: True

## attempted_live_write — PASS
- expected: POST refused to live/preview; harness detects attempt
- detected: True
