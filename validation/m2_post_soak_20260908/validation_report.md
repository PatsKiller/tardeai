# Independent post-soak falsification report

As of: 2026-09-08 America/New_York (validator workspace time)

Verdict: FAIL. The candidate is locally coherent at contract/test level, but the
required atomic handoffs and reproducible served-runtime evidence are absent or
contradictory. No production, broker, schedule, Drive, or financial state was
mutated.

## Identity and integrity

| Item | Result |
|---|---|
| Campaign | `[DOC-CLAIM]` `m2-canary-20260907` inferred from `scripts/lib/campaign_interfaces.py:3-4` and `scripts/settle_agent_commitments.py:23-33`; no owner handoff supplied |
| Baseline | `[DOC-CLAIM]` `87333fee5` inferred from the local canary branch history; not supplied by owner |
| Integrated candidate | `[VERIFIED]` `2c650b9686ad2f93acc68b624a38c68020dcc920` (`git rev-parse HEAD`) |
| Merge SHA | `[VERIFIED]` `ad1b32a715b79b599ed78cee87f7ff49eecaccfd` is `origin/main` and the served `SOURCE_COMMIT`/`BUILD_SHA`; its history contains the merge of `2c650b968` |
| PR URL/checks | `[UNRUNNABLE]` GitHub API returned `error connecting to api.github.com`; PR #919 is only inferred from the local merge subject |
| Served release | `[VERIFIED]` `CURRENT -> /home/johnclaw/trade-ai-releases/portfolio-server/ad1b32a71-main-exact-phase2-20260907-235227`; `SOURCE_COMMIT` and `BUILD_SHA` both equal `ad1b32a715b79b599ed78cee87f7ff49eecaccfd` |
| Served metadata | `[VERIFIED]` `apps/command-center-v3/build-meta.json` has `git_sha`, `source_sha`, and `source_commit` equal to `ad1b32a715b79b599ed78cee87f7ff49eecaccfd` |
| Candidate manifest | `[VERIFIED]` candidate `data/audit/manifest_candidate/RELEASE_MANIFEST.json` names candidate `2c650b968`, but `deployed_release_path` is stale `bcc9cd6eb…` and `backend_release_sha` is `bcc9cd6eb…` |
| Served manifest | `[VERIFIED]` served `docs/investment-office/RELEASE_MANIFEST.json` says production SHA `aa037b738…`, branch `chore/cio-pin-aa037b73`, while the served release is `ad1b32a…` |
| Remote refresh | `[FAIL]` `git fetch origin` was denied because the external worktree gitdir could not open `FETCH_HEAD` (`Read-only file system`); no alternate remote method was used |
| Secrets | `[VERIFIED]` private-key marker scan over tracked non-evidence files returned no matches; no secret values were printed |

The integrity gate fails on missing atomic handoffs, blocked remote refresh, and
the two release-manifest identity contradictions. `archive/ARCHIVE_MANIFEST.json`
is the generic G4 mechanism with `items: []`; it is not the requested campaign
evidence archive.

## Required-input disposition

No owner-supplied artifact was found for: campaign ID/baseline packet; integrated
candidate and merge packet; PR URL and required checks; release/served-SHA packet;
integration handoff; soak archive and SHA-256; lane A, B, C, or D handoffs and
hashes; frozen interfaces and leases; rollback target; or claimed domain maturity
levels. The validation therefore fails each corresponding integrity gate rather
than substituting commit messages, tests, or stale documents.

## Three critical traces

The source contracts are present, and disposable fixture tests cover identifier
joins. Runtime/organic proof is absent. The first broken edge in each trace is
the unattended served producer-to-observed-receipt edge.

### Research

`organic research -> identity/provenance -> dossier -> scheduled wake -> exact
receipt -> changed later output`

`[CODE]` The code provides deterministic research identity, dossiers, wake IDs,
memory-first loading, and consumption receipts. `persistent_agent_wake.py:323-359`
loads memory and prior history before the decision; `tests/test_integrated_traces.py:39-45`
checks cross-lane IDs. `[VERIFIED]` the integrated trace tests passed in isolated
state. `[VERIFIED]` no `run_persistent_wake` or `persistent_agent_wake` entry was
present in the active crontab, no matching systemd unit appeared, and no matching
process was running. `[CODE]` the wake module explicitly says it does not install
or activate a production schedule (`persistent_agent_wake.py:4-5,648-662`).

Hop status: organic research UNKNOWN; immutable identity/provenance M1 fixture;
dossier M1 fixture; unattended scheduled wake M0; exact consumption receipt M1
fixture; changed later output M0. First broken edge: dossier/identity to an
unattended served wake. Domain maturity: M1 (implemented/tested), not M2.

### Communications

`producer -> event GUID -> subject history -> curation provenance -> channel
formatting -> gateway delivery -> provider settlement -> inbound/outbound link ->
agent receipt`

`[CODE]` CampaignInterfaces@v1 defines event, thread, receipt, gateway-mode,
delivery-owner, curation-kind, and settlement-state identifiers at
`scripts/lib/campaign_interfaces.py:57-74,119-140`. `[VERIFIED]` isolated gateway,
retry, curation, inbound, receipt, router, and negative-control tests passed.
The tests use fake providers/memory stores and explicitly describe isolated state;
they do not prove a live provider settlement or gateway-owned production delivery.
`[VERIFIED]` no matching gateway process or backend listener was visible; a local
read-only `curl` was blocked by `Operation not permitted`, so endpoint truth is
UNKNOWN. `[VERIFIED]` the active crontab contained no campaign-specific consumer.

Hop status: producer/event/thread/curation/formatting M1 fixture; gateway-owned
delivery M0 runtime; provider settlement ID M0; inbound/outbound linkage M1
fixture; agent receipt M1 fixture. First broken edge: fixture event to served
gateway/provider settlement. Domain maturity: M1, not M2.

### Persistent learning

`unattended wake -> memory load -> organic commitment -> observation -> outcome ->
shadow belief proposal -> changed later unattended behavior`

`[CODE]` the wake implementation loads memory before deciding and creates a
commitment only from a genuine decision (`persistent_agent_wake.py:323-359,427-475`).
`[CODE]` the settlement module is deliberately shadow-only, has no database,
network, scheduler, or model dependency, and says its proposals await operator
review (`settle_agent_commitments.py:1-5,22-35`). `[VERIFIED]` disposable lifecycle,
duplicate, mismatch, and non-organic fixture tests passed. `[VERIFIED]` no
unattended wake schedule or process was found. No natural commitment, later
observation, outcome, proposal, or changed unattended behavior was supplied.

Hop status: unattended wake M0; memory load M1 fixture; organic commitment M1
fixture only; later observation M1 fixture only; outcome settlement M1 fixture;
shadow proposal M1 fixture; changed later behavior M0. First broken edge: no
unattended served wake. Domain maturity: M1, not M2/M4.

## Adversarial checks

| Check | Disposition |
|---|---|
| Brave callers use governed router | PASS at isolated source/test level; live served usage UNKNOWN |
| quota/cache/settlement atomic and one clock | PARTIAL; contracts/tests pass, live store/clock proof absent |
| gateway mode is CANARY | UNKNOWN; no running gateway/process/env attestation; historical docs conflict across timestamps |
| gateway owns selected deliveries | PASS only with fake provider; live ownership UNKNOWN |
| settlement IDs complete | FAIL for maturity proof: no live settlement archive/rows |
| retries do not duplicate | PASS in disposable negative control; live settlement unknown |
| inbound triggers intended path | PASS in fixture; live path unknown |
| real event IDs receive receipts | FAIL for organic proof; fixture IDs only |
| same-subject history affects curation | PASS in fixture; no organic receipt |
| LLM messages carry provenance | PASS source/test scope where exercised; no live model receipts |
| deterministic messages not mislabeled | PASS in fixture |
| scheduled wakes execute producer | FAIL: no active schedule/process observed |
| research changes later behavior | FAIL: no organic later behavior evidence |
| commitments organic, not backfilled | UNKNOWN; no natural population archive |
| outcomes attach to correct population/horizon | PASS fixture validation; no live population |
| belief proposals do not mutate behavior | PASS by source design and tests; no production mutation performed |
| Command Center matches backend truth | FAIL/UNKNOWN: no listener; served manifest stale |
| Drive and GitHub current docs agree | FAIL/UNKNOWN: Drive search found current-looking index/AGENTS objects but no M2 handoff; GitHub API unavailable |

## Maturity arithmetic

The exact assessed denominator is four surfaces: research, communications,
persistent-agent, and Command Center truth. Validated levels are `[1, 1, 1, 0]`.
Arithmetic mean = `3 / 4 = 0.75`; weakest link = `M0`; critical-path floor =
`M0` because served runtime/Command Center reconciliation is not established.
Unknown-as-M0 sensitivity is also `M0.75` (all unknown runtime edges are already
zeroed). The three core domains alone average `M1.00`, but the overall result may
not exceed the critical-path floor. No claimed maturity levels were supplied.

## Decisions

- Evidence integrity: FAIL.
- GitHub/Drive/runtime reconciliation: FAIL/UNKNOWN.
- Research maturity: M1, fixture/implementation only.
- Communications maturity: M1, fixture/implementation only.
- Persistent-agent maturity: M1, fixture/implementation only.
- Command Center truth: M0 / UNKNOWN; served metadata is stale relative to the served SHA and no listener was observed.
- Broader multi-agent acceleration: NO-GO.

Further implementation may parallelize only inside the existing lane leases after
an owner supplies a complete handoff. Keep CampaignInterfaces, release identity,
runtime pin/current, schedule registration, evidence manifest, and shared control
surface files single-owner. Do not use this report to authorize deployment,
schedule changes, provider calls, Drive writes, or broker actions.

