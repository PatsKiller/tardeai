# Coverage map — every test in the retired `test_overview_projection_20261109.py`

Retired 2026-11-14 (R7 blocker, LEAD 2026-11-14T18:46Z) because ACC-CACHE r4 changed the reader
contract on purpose: `overview_projection.read()` no longer answers `(None, {"source": "inline",
"reason": ...})` so that the route can compute inline; it answers a labelled LAST-KNOWN-GOOD
(`stale: true` + `aged` / `invalidated` / `code_mismatch` / `write_tracking_off`) or a named
UNKNOWN (`(None, {"source": "none", "reason": missing|corrupt|not_ok|clock_skew|expired})`), and
`serve()` never calls its compute argument (S2 item 2, operator 2026-11-14;
`config/ci_gates/S2_READ_MODEL_20261114.json`).

Measured on R7 head `6e4c41770` (the bytes in this directory): the retired file is **10 failed /
39 passed** together with `test_overview_projection_started_at_precision_20261110.py` and
`test_s2_overview_never_inline_20261114.py` — 10 failed / 29 passed on the retired file alone.
Every one of the 10 failures is the contract change; none is a defect the retirement hides.

Legend — **ported**: byte-identical function moved to `tests/test_overview_projection_20261114.py`
(gate `overview_projection_20261114`); **S2**: covered by `tests/test_s2_overview_never_inline_20261114.py`
(gate `S2_READ_MODEL_20261114`); **new**: a restated test in the successor file, because the old
assertion described a shape that no longer exists. No row is "dropped".

| # | retired test | behaviour | now carried by | assertion that carries it |
|---|---|---|---|---|
| 1 | `test_overview_route_reads_the_projection_before_computing_inline` | `/api/v2/overview` is bound to the projection reader, not to the inline compute | **new** `test_the_overview_route_is_bound_to_the_projection_reader` (+ S2 `test_the_overview_route_never_computes`) | route lambda resolves to a function calling `.serve(`; exactly one `_overview_with_today_move` occurrence, inside the `_overview_projection is None` import-failure guard (mutant M1: route re-pointed to the inline compute → red) |
| 2 | `test_api_v2_registers_the_overview_write_invalidation` | api_v2 registers the write invalidation at import | **ported** (same name) | `"register_write_invalidation(" in api_v2.py` |
| 3 | `test_fresh_projection_is_served_with_its_age` | a fresh, same-release, not-invalidated body is served as current, with its age | **S2** `test_a_current_projection_carries_fresh_and_no_reason` | body value served; `_projection == {source: projection, built_at, stale: False, reason: None}`; `meta.stale is False and meta.age_s == 10.0` |
| 4a | `test_aged_or_future_projection_falls_back[aged]` | a body past `MAX_AGE_S` is still served, labelled stale with its age — **contract flip**: the retired test asserted `body is None` and an inline compute | **S2** `test_an_aged_projection_is_served_stale_with_its_age` | `body is not None`; `meta.stale is True`, `reason == "aged"`, `age_s == MAX_AGE_S + 100` |
| 4b | `test_aged_or_future_projection_falls_back[clock_skew]` | a body stamped in the future is named and **not served** | **new** `test_read_refuses_a_missing_file_and_a_future_stamp_with_a_named_reason` (+ S2 `test_a_future_stamp_is_a_clock_problem`) | `body is None and meta["source"] == "none" and meta["reason"] == "clock_skew"` (mutant M3: reader returns `{}` instead of `None` → red) |
| 5 | `test_projection_from_another_release_falls_back` | a body from another release is last-known-good, named `code_mismatch` — **contract flip**: was `body is None` | **S2** `test_a_body_from_another_release_is_last_good_and_says_so` | `body is not None and meta["stale"] is True and meta["reason"] == "code_mismatch"` |
| 6a | `test_a_write_after_the_build_started_falls_back` (write at T0+1) | a write after the build STARTED downgrades the body to stale, never recomputes — **contract flip**: was `body is None`, reason `invalidated` | **S2** `test_a_write_after_the_build_is_served_stale_not_recomputed` | `body is not None and meta["stale"] is True and meta["reason"] == "invalidated"` |
| 6b | `test_a_write_after_the_build_started_falls_back` (write at T0−1) | a write OLDER than the build does not downgrade it | **new** `test_a_write_older_than_the_build_does_not_downgrade_it` | `body is not None and meta["stale"] is False and meta["reason"] is None` (mutant M5: any recorded write downgrades → red) |
| 7 | `test_corrupt_projection_falls_back_with_the_reason` (4 params) | not-JSON, foreign schema, non-dict body and `status: failed` each yield no body and the named reason (`corrupt` ×3, `not_ok`) | **ported** (same name, 4 params) | `body is None and meta["reason"] == reason` |
| 8 | `test_missing_projection_falls_back` | a missing file yields no body and names `missing` | **new** `test_read_refuses_a_missing_file_and_a_future_stamp_with_a_named_reason` (+ S2 `test_serve_answers_the_named_unknown_instead_of_computing`) | `body is None and meta == {"source": "none", "reason": "missing"}` (whole-meta equality; mutants M3 red) |
| 9 | `test_serve_never_blank_inline_body_names_the_reason` | `serve()` never blanks and never computes: it answers the named UNKNOWN | **S2** `test_serve_answers_the_named_unknown_instead_of_computing` | compute callable called 0 times; `status == "UNKNOWN"`, `unavailable is True`, every number `None`, `gap.reason == "missing"`, `gap.owner`/`gap.next_action` name the lane; `_projection == {source: unknown, reason: missing, age_s: None, built_at: None}` |
| 10 | `test_serve_prefers_a_fresh_projection_and_does_not_compute` | `serve()` serves a fresh body without calling the compute argument | **ported** (same name) | compute callable is `pytest.fail`; `_projection.source == "projection"` and the body value |
| 11 | `test_unreadable_invalidation_record_is_inline_never_a_pre_write_body` | an unreadable invalidation record never yields a body labelled current | **S2** `test_an_unreadable_invalidation_record_never_shows_a_current_body` | `body["_projection"]["stale"] is True` (serve maps the unreadable record to `cut = inf`; the reason it then carries is the ordinary `invalidated`, asserted in row 6a) |
| 12 | `test_served_projection_is_a_fresh_top_level_dict_each_read` | a caller cannot poison the next read by mutating what it was served | **new** `test_a_served_projection_is_a_fresh_top_level_dict_each_read` | after mutating the served body and `_projection`, a second read returns the body value and `_projection == {source: projection, built_at, stale: False, reason: None}` (mutant M2: return the cached `doc["body"]` → red) |
| 13 | `test_served_body_is_byte_identical_across_reads_so_etags_hold` | the served bytes do not change with age, so ETags hold | **ported** (same name) | `json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)`; `(ma["age_s"], mb["age_s"]) == (1.0, 100.0)` |
| 14 | `test_build_writes_the_envelope_atomically_0600` | the build writes the envelope atomically at 0600, records inputs and leaves no `.tmp` | **ported** (same name) | envelope fields + `stat.S_IMODE == 0o600` + no `*.tmp` left |
| 15 | `test_a_failed_build_keeps_the_previous_projection` | a failed build leaves the previous file byte-identical | **ported** (same name) | `s["status"] == "failed"`, error text, `p.read_bytes() == before` |
| 16 | `test_an_overlapping_build_is_refused_not_queued` | an overlapping build is refused, not queued | **ported** (same name) | `s == {"status": "refused", "reason": "build_in_flight"}`; no file written |
| 17 | `test_parity_the_projection_body_is_the_inline_body_on_the_wire` | the served bytes equal the inline body serialization (`default=str`, NaN/inf → null) | **ported** (same name) | `served == op.to_wire(inline)` with the literal wire dict |
| 18 | `test_a_body_that_is_not_a_dict_is_a_failed_build` | a non-dict body fails the build and writes nothing | **ported** (same name) | `s["status"] == "failed" and not p.exists()` |
| 19 | `test_code_identity_reads_the_release_build_sha` | identity is `sha:<BUILD_SHA>`, else `path:<resolved>` | **ported** (same name) | both branches asserted |
| 20 | `test_projection_path_honours_the_override` | the path override wins; the default is `data/runtime/overview_projection.json` | **ported** (same name) | both branches asserted |
| 21 | `test_operator_writes_invalidate_the_overview` | every operator write that can change the overview invalidates it; an unrelated write does not; registration is idempotent | **ported** (same name) | five POST routes included, watchlist add excluded, `register_write_invalidation` called twice |
| 22 | `test_write_tracking_off_means_inline` | with `TRADEAI_SWR=0` the reader says `WRITE_TRACKING_OFF` and a body is never current | **new** `test_write_tracking_off_is_the_sentinel_and_serves_last_good` (+ S2 `test_write_tracking_off_serves_last_good_labelled`) | `reader() is op.WRITE_TRACKING_OFF`; body served but `meta.stale is True and meta["reason"] == "write_tracking_off"` (mutant M4: sentinel no longer downgrades → red) |
| 23 | `test_builder_dry_run_writes_only_where_told` | a dry run writes only `--out` and no receipt | **ported** (same name) | `rc 0`; body at `--out`; runtime path absent; `_write_receipt` is `pytest.fail` |
| 24 | `test_builder_apply_failure_exits_nonzero_and_writes_a_failed_receipt` | an apply failure exits 1 with a failed receipt | **ported** (same name) | `rc 1`; receipt `status == "failed"` and carries the error |
| 25 | `test_builder_apply_refused_is_a_typed_empty_not_a_failure` | a refused apply is rc 0 with a typed receipt | **ported** (same name) | `rc 0`; receipt `{status: refused, reason: build_in_flight}` |
| 26 | `test_builder_forces_a_read_only_db_session` | the builder's DB session is read-only (and keeps existing PGOPTIONS) | **ported** (same name) | `default_transaction_read_only=on` appended, existing options preserved |

## Counts

* 26 retired test functions (30 nodeids: the corrupt matrix is 4 params, the aged/future matrix 2).
* **16 ported byte-identical** (rows 2, 7, 10, 13–21, 23–26), verified function by function with
  `ast` against the archived bytes — 0 altered.
* **5 new tests** in the successor file, carrying rows 1 (route binding), 4b and 8 (the two no-body
  cases: a future stamp, a missing file), 6b (a write older than the build), 12 (per-read dict
  isolation) and 22 (the write-tracking-off sentinel) — five tests across six rows, because one test
  carries both no-body cases. Each is proven to have teeth by a mutant of
  `scripts/lib/overview_projection.py` / `scripts/api_v2.py` that turns exactly that test red
  (M1–M5, quoted in the READY delivered to `inbox/claude-lead/`).
* **5 retired functions are covered only by the S2 gate**: rows 3, 4a, 5, 9, 11 — every one is a case
  whose OLD assertion asserted the very behaviour the operator's S2 item 2 removed (inline compute /
  `source: inline`).

## Restore

See `TRIPWIRE.md` here and the two `ARCHIVE_MANIFEST.json` entries for this batch. Restoring the test
without restoring the pre-S2 reader puts 10 known failures back on the line.
