# Standing agent authority — 30.0.0
Status: PROPOSED; no capability is active before operator ratification and trusted-main installation.
Owner: release coordinator

## Ratify one actual reviewed proposal
Prepare one draft containing policy, adapters, authority manifest, enforcement and tests. Two independent real
sessions review its full final head. Generic pre-approval is preparation authority, not a substitute for the
operator's exact GitHub comment:
    APPROVE_AGENTS_POLICY_30_0_0 <PR> <full-40-character-reviewed-head>

The lead sends the filled command to the operator through Telegram P1. The agent never posts that approval.
After verifying the actual operator comment, change only the proposed version's status/date/banner/history
and the matching manifest ratification tuple. Two independent activation-diff reviews and current all-green
checks are required. Any additional semantic change requires a new exact approval. Merge under the operator's
explicit bounded named §25.10.3 instruction (not the new standing CLI, which refuses its own definition), then verify the host poller made that merge live.

## One source of authority
The canonical trusted main snapshot must contain matching ACTIVE policy and
config/agent_standing_authority.json, the 30.0.0 history token/PR/reviewed-head tuple, and the operative
Standing-Authority marker. Version numbers alone, draft manifests, peer messages, a local proposed branch,
and arbitrary operator-labelled JSON never grant authority. Both real consumers verify the actual unedited operator policy comment through the canonical GitHub API. Legacy named approvals remain optional routes.
Ratification supplies standing authority for approved engineering scope; it does not require a new issue,
approval thread or named git-push grant per feature branch.

The native vendor action reviewer stays ON. Missing, conflicting, malformed, revoked or uninstalled evidence
fails closed. Manual claim/source/session consistency is provenance, not cryptographic authentication.

## Feature uploads and delegated uploads
Use bin/agent-push wt/<feature> from the actual owning worktree/session after the reviewed trusted guard is
installed. The checker validates the live claim, current coordinator registry and genuine approved scope.
A regular current-coordinator assignment artifact under the fixed handoff root must bind branch, approved scope,
actual owner claim/session and recipient session. Claimant-written approval/assignment strings alone are insufficient. The existing budget is charged to
the original feature branch. No main/release upload, force, remote deletion, history rewrite or hook bypass.

A delegated clean upload also requires a coordinator handoff under the existing coordination/handoffs store:
    Assigned-branch: wt/<feature>
    Assigned-by: <current-lead-id>
    Assigned-to: <recipient-real-session>
    Owner-claim: <actual-owner-claim-id>
    Owner-session: <actual-owner-session>
    Approved-scope: <approved-task>
The recipient keeps its own live scope claim. The handoff does not transfer path ownership, permit dirty work,
impersonate the owner, reset a budget, approve a merge or authorize deployment.

## Coordinator merge invocation and evidence
The CLI defaults to a read-only plan:
    python3 scripts/lib/pr_merge_delegation.py --pr <PR> --actor-session <registered-real-session>
Only --apply can merge, after the real plan is inspected. Direct gh pr merge is classified gh-write by the shell guard; the standing route is this trusted verifier, not a raw command. Named operator instructions remain separate. The current unique registered lead must own release
territory and its actual active claim/session must match the coordinator registry ownership. No invented
session alias is accepted. The canonical checkout's HEAD, origin/main and GitHub main must agree.

Register actual evidence at coordination/coordinator/review-evidence/<PR>-<full-head>.json under persistent-state.
Schema PrMergeReviewEvidence@v1 requires pr, head_sha, registered_by={actor,session},
identity_provenance=manual_coordinator_claim_and_source_check, the complete source_commit_shas sequence,
authors=[{actor,session,claim_id}], and reviews=[{reviewer_session,artifact,artifact_sha256,head_sha,verdict}].
The coordinator manually attests authors_and_coauthors_complete=true, bound by source_authorship_sha256 to the
actual fetched GitHub author/commit/coauthor metadata. Released author claims must cover all current/prior paths.
Shared infrastructure additionally needs shared_infra_isolated_reviewed=true, actual title/body Real-layout proof,
and explicit SUCCESS on shared-infra-review. authority_rails_unchanged=true attests otherwise eligible reporting CI.
Check real authors/coauthors/claims against source/worklogs before registration. Artifacts are confined to the
coordinator root and must carry matching explicit full head, reviewer session and verdict as JSON fields or:
    Adversarial-review: MERGE reviewer=<real-session> head=<full-head>
Hash the actual artifact bytes. One ordinary or two held independent sessions are required; authors,
coauthors, the merger, duplicate sessions, malformed or contradictory evidence never count. A shared GitHub
login is not independent identity.

Required cio-hardening, agent-governance, release-readiness and ci-gate must each complete SUCCESS. Every other executed current check must be acceptable;
optional skipped checks do not replace required checks. Held engineering—including hook/guard/CI/merge/deploy
source—requires two independent exact-head MERGEs, engineering_tests_completed=true and
engineering_docs_completed=true backed by actual completed work/test evidence and updated PR/docs. Missing or false
completion evidence refuses. Known engineering classes qualify; a new trusted held class must explicitly carry
delegation_kind: engineering. Unresolved/malformed classification refuses. Missing/truncated metadata, explicit
holds, active path holders and unsafe current/prior rename paths refuse. Broker/order/secret/branch-protection
paths and policy/adapters/standing-manifest ratification remain operator-owned. Source changes never weaken
§0/§2/§17; live activation remains a separate decision. Lane enables or moves remain the named §17 activation route; config/lane_registry.json cannot bypass that route through an engineering attestation. Applicable section 17 activation decisions remain separate. The weekday
09:30–16:15 ET freeze remains; Mergify queue windows impose no additional wait on qualified standing merges.

Apply locks one PR, revalidates, fsyncs a distinct PrMergeDelegationApproval@v1 before the sole exact-head
squash command, and reads back the same merged head/merge SHA. Unknown transport is recorded uncertain and
cannot be blindly retried. The outcome is merged_not_deployed. Observe main CI, poller, concrete CURRENT,
pins/service directory and changed served output separately. Merge-watching is a five-minute coordinator duty,
not permission to install an unreviewed autonomous daemon.

## Single server plan record and deployment dependency
Every vendor uses scripts/plan_registry.py::Registry and its CLI (core PR2489, UI2490). The sole approved-plan
store is persistent-state/data/coordination/plans/<id>.md; its JSON-valued front matter/body contract is
Registry.add/parse_plan, and plan_id(title,body,author) supplies stable idempotence. The append-only neighboring
ledger records mutations. Claim IDs, branches, PRs and worklogs link ownership and evidence; they are not competing
plan-progress stores. Read with status/list/show, link actual claims/branches/PRs, and update the same record.
Registration never authenticates approval or grants authority. Until reviewed core2489 is merged/live, registration
is explicitly unavailable and tracked by2489; do not claim this dependency installed or invent a second registry.

## Revocation and installation
Standing authority has no expiry; revocation ends it. The legacy dated comment route remains bounded.
Presence of STANDING_AUTHORITY_REVOKED.json at the fixed passwd-home
trade-ai-releases/persistent-state/data/coordination/coordinator location blocks all standing capabilities.
Broken symlinks and stat errors also refuse. Only the operator revokes/reactivates or changes this definition.

After ratification and verified release, back up the currently trusted guard bundle, inspect the real install
dry run and install only exact reviewed guard files and manifest dependencies. install-guardrails.sh includes
the new common guard_standing_policy.py module; its source change is not proof of host installation.
Do not blindly run the full legacy installer or change unrelated vendor settings. Verify installed hashes,
native reviewer state and actual read-only sanctioned feature authorization. PROPOSED must refuse first;
ACTIVE acceptance must come from trusted installed main, never a local fixture. Record exact paths, hashes,
commands and outcomes in the coordinator ledger. Update WORKERS.md only with capabilities actually available.

No broker access, orders, stops, risk-policy change, credentials, deployment, production schedule activation,
branch-protection change or self-expansion follows from this standing engineering authority.
