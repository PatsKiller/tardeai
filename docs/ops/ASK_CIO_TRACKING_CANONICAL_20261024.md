# Ask-CIO tracking: canonical My Watchlist readback

**Status:** Source proposal verified with isolated fixtures; publication/application pending.
**Task:** DSN-20261024-ask-tracking-P1-T1.
**Base:** accepted main `d635873e1063efb8a9ff8e8ce542654ed2ef7654` (#2076).

The default Ask tracker wrote `data/portfolios/state/watchlist.json`. My Watchlist reads the operator membership
union in `watch_domains.membership_operator`, so a successful file write could produce a false tracking claim.
The default now delegates the existing `api_v3_watch_commands.post_mine_decision(add)` command and verifies the
same canonical membership reader before it reports success. It never adds another table, store or SQL writer.

The command writes `operator_starred_symbols` and the audited `watch_mine_added` event. Existing operator entries
are not rewritten. The question's thread reference is recorded in the command note; the Ask ledger remains the
thread association/history. The actual reader folds starred, personal/operator list and operator directive
membership and respects a later `watch_mine_removed`. The existing command supplies its normal cache invalidation.
No HTTP/provider, broker, order, stop, credential, schedule or production-state operation was performed by this worker.

## Receipt and identity contract

| Condition | Receipt |
|---|---|
| Matching confirmed EntityRef and registry GUID; accepted command and complete reader presence | `action=added`, `membership_verified=true` |
| Same verified security is already a canonical member | `action=already_present`, verified; no write/event spam |
| Unconfirmed/private entity, mismatched GUID or unavailable identity | skipped/rejected/failed; not verified |
| Command accepted but the reader is unavailable or does not contain the symbol | failed, command accepted, verification false |
| Identity changes before readback | failed; no success claim or automatic repair |
| Legacy explicitly injected file adapter | `membership_verified=false`, `membership_source=legacy_watchlist_file` |

`membership_verified_at` is the readback observation time, not an invented source creation clock. The receipt
names `watch_domains.membership_operator`, current registry-symbol identity binding, actual membership reasons
and the writer path when used. Quote/provider identity is not implied. Partial mutations are not described as
complete; DB errors are sanitized. No rollback, retry loop or source substitution is used to turn a failure green.
An identity refusal also prevents later CIO/directive steps from bypassing it: an operator ticker directive itself
contributes to the membership union. The underlying CIO-record and directive implementation remains independent;
this package does not invent stance, conviction, prospect promotion or PG synchronization acceptance.

The root Ask-quality companion must emit a My Watchlist claim only when `membership_verified is True`, never from
`action=added` or an accepted command alone. Its presentation work also removes raw tracking/provenance dumps from
the answer body. This backend-only package does not claim that companion's UI/mobile tests or live application.

## Untrack and shared ownership

Question untrack does not remove canonical operator membership. A star/directive can be shared by other questions
and operator intent; a thread receipt cannot prove exclusive removal authority. The backend returns `action=kept`
with the explicit operator-removal reason. The operator's existing remove command remains authoritative. Legacy
file compatibility is not promoted into canonical membership; the default product path no longer writes that file.
The existing separate directive/history steps retain their own receipts and behavior.

## Verification

The fixtures call the **real canonical command**, the **real membership reader**, `Tracker.track`, and the real
`watch_curation.my_rows` consumer over injected SQL state. They prove the exact requested TSLA becomes a row in the
same My Watchlist projection without creating a legacy file. Negative controls cover failed initial/postwrite
reads, accepted-without-visible output, partial command failure, unresolved/ambiguous/private identities, wrong
GUID and mid-operation identity drift. Real identity refusals stop later writers. Repeated questions preserve
existing entries; untrack cannot remove another thread/operator membership. No invented UI proof is included.

Required source evidence is in the adjacent packet: affected complete native suites with hidden psycopg2 and
production barriers, canonical gate registration, source lint and host-path/coverage/dark-contract/retention/index
ratchets. Known unrelated full-profile protected-state fixture refusals are not repeated or exempted. Runtime
canonical readback and Ask phone acceptance after release remain separate from these source fixtures.

The actual Ask UI mobile companion is owned by the Ask-quality and mobile workers (task
`DSN-20261024-ask-cio-quality-P1-T1`): 412×915 and 390×844 taps/viewport/focus/Back/URL/44px proof belongs there.
This package changes no page and fabricates no browser screenshot. Coordinator publication/release and operator
re-ask are pending; this worker never pushes, merges, releases or tracks a production symbol.

Measured native result: **114 passed across five complete files**, plus **two strict real-tree completeness cases**.
Host-path, coverage, dark-contract and retention ratchets pass. Exact source hashes and isolated XML receipt paths
are retained in `packets/ask-cio-tracking-20261024/VALIDATION.json`; no full-project green or served acceptance is claimed.
