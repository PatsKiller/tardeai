# WP-29: Watch closed-session prices and compact level evidence

Design-Task: DSN-20261024-watch-freshness-noise-P1-T1

Worker session: `codex-watch-freshness-20261024`; claim `20261024T144728Z-codex-c5abe281`.
Base: `e5fa288ecc6971d1a55a79f7e3ba5bbbb46c5dd0`. This is a local source delivery; publication and served behavior are not established by these fixture checks. The coordinator/operator owns merge and release.

## Result

My Watchlist now distinguishes a stored observation from the latest closed weekday session from a quote belonging to an older session. It reuses `observationEnvelope.latestSessionDate()` and its ET/DST conversion. Friday observations therefore receive a closed-session label over the weekend, overnight and before Monday's open; once Monday opens they retain their normal stale classification. Original price, source, observation timestamp and backend freshness verdict remain unchanged.

An intraday `LAST` is labeled **Closed session · YYYY-MM-DD**, with **Intraday observation** and its original ET time. An after-hours observation is qualified **After-hours observation**. The more specific **Closed session · YYYY-MM-DD close** is reserved for a source explicitly declaring `as_of_basis: session close`. The current stored-quote projection does not declare that basis, so this change does not manufacture an official closing price. Missing, unknown, future and older-session observations are not promoted. This label describes source evidence; it does not grant trading readiness or alter a shared freshness policy.

The reused helper models weekdays and the 09:30/16:00 ET boundaries; it has no exchange-holiday or early-close calendar. This package adds no competing calendar. The full backend market-session policy remains the authority for those cases.

Support and resistance are inline values with a small selected-source tag. Their full source, original timestamp, timestamp basis, missing reasons and broken-reference source remain available through keyboard-operable **Source details** and the source tag's description. Unknown level time appears once per row. Strategy-card creation time is still qualified as creation time; it is not promoted to observation time.

When the primary stored reference is crossed, the row explicitly shows **broken — nearest valid level**, selecting the nearest existing compatible reference among the existing sources. For price 10, crossed primary resistance 8, strategy resistance 15 and closed-session resistance 11, the fallback is 11 with the closed-session source and original date. If none qualifies, the row says **none below price** or **none above price**. A valid primary retains established source precedence even if another source is nearer. Targets, stops and averages never become support/resistance. No levels are calculated or written.

## Shared-data boundary

Prices continue through the existing CC data-broker projection/canonical quote path. The backend change adds read-view metadata over existing symbol-master, strategy-card and closed-session resistance references. It adds no provider calls, per-process fetch, Watch-specific store, new business-fact writer, recommendation, ranking, broker action or scheduler authority. Security identity, shared CIO facts and all decision/action flows retain their existing owners. The frontend helper is pure presentation and does not mutate source evidence.

Transport retention takes precedence over closed-session/current labels: a failed 503/403 refresh shows **Last snapshot**, while preserving value, source and original time. A 403 still stops automatic polling. Existing missing/source-read, future-time, sub-cent, account-name and MyList-only guards remain covered at the actual App/Watch rendering boundary.

## Verification

| Check | Local result |
| --- | --- |
| Python: new selection tests, existing market facts, data-source authority, gate registry | 96 passed; `PYTHONPATH=/home/johnclaw/.cache/rtc/nopg` |
| Pure presentation fixtures | 35 assertions passed; pinned weekend, overnight, preopen, DST, RTH, old/missing/future/unknown, retained transport and sub-cent cases |
| Actual MyList + useApi fixture, fully intercepted synthetic origin | 6 cases passed: 1440/412 px × normal/503/403; no unexpected/external/mutating requests or page errors; no horizontal overflow; keyboard source-details disclosure verified |
| Existing market-facts browser spec | 18 passed against isolated static preview; empty env, `configFile:false`, proxy disabled; API responses mocked |
| Frontend native profile | `npm run build` passed; existing chunk-size advisory only |
| Host-path and coverage ratchets | Zero new violations / zero new unlisted tests |
| Documentation | Generated INDEX checked; shared append-only backlog and progress log updated |

The Chromium sandbox initially refused process startup with `sandbox_host_linux` EPERM. Normal approval review accepted the exact fixture-only browser command; the successful checks used synthetic intercepted origins and an isolated static preview, with no live 7777, provider or database traffic. Initial fixtures were corrected to use the normalized stored-quote schema and preserve its original `Z` timestamp. A negative test caught an unknown-freshness qualification edge and the helper now rejects it. Production timestamps were not rewritten to satisfy a test. A token-style guard caught a new literal radius; the source tag now uses the existing radius token.

Evidence is in [the packet](packets/watch-freshness-noise-20261024/validation.json). The six PNGs and request/geometry receipts are synthetic proof of the candidate implementation, not live market observations. Their SHA-256 digests, source-file digests and exact test commands are recorded there. CI and runtime acceptance remain separate after publication.

## Coordinator publication

The single `PUSH_NEEDED` progress entry contains the exact branch/worktree and PR body command. Keep the claim until the coordinator handles publication and lifecycle closure. The PR title starts with `WP-29`; the commit and PR body identify the Design-Task above. After integration, rerun the focused fixture workflow on the final head and verify the served release through the coordinator's authorized release path.
