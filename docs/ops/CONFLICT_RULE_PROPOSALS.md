# Conflict rule proposals — unmatched conflicts, AI-proposed rules, operator approval

Operator 2026-10-25 (verbatim): "if no rules on the resolution matches, it should put it out to AI to fix and recommend a
new resolution for my approval right there on that same page."

Code: `scripts/lib/conflicts/proposals.py` (detection, job, decision, notification, read model),
`scripts/lib/conflicts/proposals_api.py` (HTTP), `scripts/conflict_rule_proposals.py` (lane script), hook in
`scripts/conflict_resolver.py` (`rule_proposals.evaluate`, one call per subject). Config:
`config/conflict_rule_proposals.json`. Tests: `tests/test_conflict_rule_proposals.py` (gate
`conflict_rule_proposals_20261025`). AGENTS.md §28.10 applies: the engine still decides what a conflict is; this adds a
route for disagreements no rule classifies. MBI_BEHAVIOR = 0.

## 1. Flow

```
conflict-resolver (shadow)        rule_proposals.evaluate(bundle):
                                    approved amendments (data only) -> unchanged engine -> detect_unmatched -> approved routes
                                  UNMATCHED rows -> data/conflicts/rule_proposals.jsonl  (unmatched_observed, one per pattern)
conflict-rule-proposals (lane)    per pattern signature (not per row), capped: governed bridge -> RuleProposal@v1 (PENDING)
                                  one grouped P2 comms intent for new pending proposals, link to the page
Conflict rules page               "Proposed rules — awaiting your approval": Approve / Edit / Reject
POST .../decision (operator)      approve -> RulebookAmendment@v1 appended (hash chained); next resolver run re-evaluates
```

## 2. What is UNMATCHED

A finding no rule or profile classifies. Never auto-resolved, never dropped. The engine's own finding (usually the U1
`DATA_ERROR`) still flags the card; the UNMATCHED row adds "AI proposal pending".

| gap | when | computed tier |
|---|---|---|
| `unknown_domain` | the subject's profile is not in `PROFILES` (e.g. a sector-posture subject) | T4, never-auto |
| `unknown_role` | an input role outside `rulebook.universal.roles` | role tier, never-auto |
| `vocabulary_unmapped` | a stance label with no mapping after R8 (`posture()` is None; `r8_listed` says if R8 lists it) | T4 |
| `vocabulary_unknown` | a gate / protection / safety / policy / schedule value outside its known list | role tier (T0–T3) |
| `uncovered_input` | a claim / fact / judgment input that produced no finding at all (silently dropped) | role tier |
| `nway_uncovered` | ≥ 3 distinct positions (R6 ordinal) and no R11 finding | T4; never-auto with an owner side |

Pattern signature = `ups-` + sha256(pattern)[:24]; the pattern holds the gap, domain, subject kind, role and the label /
source / ordinal set, never a subject id, so two names with the same unmapped label share one proposal.

Tier and never-auto are **computed** (`pattern_policy`): role tier (safety T0, protection/fact T1, policy T2, gate T3,
claim/judgment T4), numeric/schedule domains T1, and the rulebook `never_auto` categories. The model's tier can only make
it stricter.

## 3. Proposal job and cost caps

Route: caller `n8n_model_job`, task type `conflict_rule_proposal`, process `conflict_rule_proposal`
(`route_profile n8n_oauth_first`: grok OAuth -> chatgpt OAuth -> DeepSeek; DeepSeek on OAuth failure or high reasoning,
one escalation inside the caps). Off-peak deferral (`lib/llm_deferral`) is honoured: a deferred pass makes no call.

Caps (`config/conflict_rule_proposals.json` `caps`): 3 proposals per run, 10 per UTC day, 2 attempts per signature per
day, 20 s between calls, $0.05 per call (refused above), $0.25 per day (stops calling), 48 KB prompt (the matrix is
dropped first), 2,048 output tokens, 5 example findings per pattern, 14-day cooldown after a rejection.

Supplied facts (the only thing the model may cite): F1 pattern, F2 computed tier/never-auto, F3 example findings,
F4 rulebook, F5 allowed machine forms, F6 the binding exceptions matrix — supplied only when its bytes hash to the
rulebook's `matrix_sha256`. Acceptance is deterministic: exact keys, citations ⊆ supplied ids, every number in the prose
present in the facts, resolutions only for supplied finding keys, 1–6 test cases with a known finding kind, and a
machine form from this list (data only, under `/amendments`, never code and never a base key):

| op | fields | effect on the next run | auto? |
|---|---|---|---|
| `vocabulary_alias` | `label`, `maps_to` (a label the rulebook already maps) | claim/judgment value rewritten before the engine (original kept in `metadata.amended_from`) | yes |
| `source_supersede_days` | `source` (one without a limit), `days` 1..14 | supersede limit for that source, scoped to the run | yes |
| `source_label` | `source`, `label` | display name | no |
| `route_to_owner` | `owner` operator\|cio, `kind` NEEDS_OPERATOR\|CONFLICT | the pattern becomes an owner finding (rule = amendment id) in the ledger | no |
| `requires_code` | `reason` | spec only; pattern stays UNMATCHED "Rule A<n> approved; needs an engine change" | no |

Never-auto: a T0–T2 pattern, any rulebook `never_auto` category (safety, protection, policy, money_mismatch,
schedule_state, nway_recorded_split …), an unknown domain or role can be **proposed**, but approving an auto op is refused
`409 NEVER_AUTO_REFUSED`; edit it to `route_to_owner` or `requires_code`, or reject.

## 4. HTTP

Identity: same mechanism as `POST /api/v3/conflicts/{key}/decision` — the operator's tailnet identity through the serve
proxy plus same-origin CSRF (`scripts/lib/cio_ask_api._operator`, `ctx.csrf`). Agents, n8n and service tokens get
`403 AGENT_CALLER_REFUSED` before any validation or write. api_v2 wraps responses as `{ok: true, data: …}` /
`{ok: false, error, reason?}`. Decision writes answer `503 PROPOSAL_DECISIONS_NOT_ACTIVATED` until
`decision_writes_enabled` is flipped in the config (operator activation, with the proposed store row).

### GET /api/v3/conflicts/proposals?status=PENDING|APPROVED|REJECTED|ALL&limit=50&offset=0

```json
{"ok": true, "data": {
  "schema": "RuleProposalCollection@v1",
  "proposals": [RuleProposal],             // pending first, newest first; paged
  "total": 3, "offset": 0,
  "counts": {"pending": 1, "approved": 1, "rejected": 1, "unmatched_awaiting_ai": 2},
  "unmatched": [{
    "signature": "ups-…", "summary": "desk says 'FOO_BAR', which no vocabulary rule maps (R8)",
    "pattern": {"gap": "vocabulary_unmapped", "domain": "security_stance", "subject_kind": "security", "role": "claim",
                "label": "FOO_BAR", "r8_listed": false},
    "policy": {"tier": "T4", "tier_rank": 4, "categories": [], "never_auto": false},
    "examples": [{"key": "security:<guid>:UNMATCHED:ups-…", "summary": "…", "sides": [{"source": "desk", "value": "FOO BAR",
                  "as_of": "…", "account": null, "source_label": "desk"}], "subject": {"kind": "security", "id": "<guid>", "label": "AAA"}}],
    "first_seen": "…", "last_seen": "…",
    "proposal_status": "AI proposal pending" | "Proposed rule awaiting your approval" | "Rule approved" | "Proposal rejected",
    "proposal_id": "rp-…" | null,
    "last_failure": {"at": "…", "reason": "ungrounded_number", "detail": "…", "cost_estimate_usd": 0.0} | null}],
  "decisions_enabled": false,
  "rulebook": {"schema": "EffectiveConflictRulebook@v1", "base_version": 2, "version": "2.1", "amendment_count": 1,
               "status": "PROPOSED", "matrix_sha256": "e40e…", "base_rulebook_sha256": "…", "amendments_head_sha256": "…",
               "amendments": [{"amendment_id": "A1", "sha256": "…", "proposal_id": "rp-…", "approved_by": "tailnet:…",
                               "approved_at": "…", "plain_rule": "…", "tier": "T4", "op": "vocabulary_alias",
                               "auto_resolvable": true, "version_after": "2.1"}]},
  "as_of": "…"}}
```

`RuleProposal` (also `GET /api/v3/conflicts/proposals/{proposal_id}`):

```json
{"schema": "RuleProposal@v1", "proposal_id": "rp-…", "status": "PENDING" | "APPROVED" | "REJECTED", "revision": 7,
 "signature": "ups-…", "pattern": {…}, "pattern_policy": {"tier": "T4", "tier_rank": 4, "categories": [], "never_auto": false},
 "example_findings": ["security:<guid>:UNMATCHED:ups-…"], "summary": "…",
 "plain_rule": "Treat FOO BAR from the desk as the same stance as WATCH.",
 "tier": "T4", "model_tier": "T4",
 "proposed_resolution": [{"finding_key": "…", "resolution": "…"}],
 "machine_form": {"op": "vocabulary_alias", "label": "FOO_BAR", "maps_to": "WATCH"},
 "patch": [{"op": "add", "path": "/amendments/vocabulary_aliases/FOO_BAR", "value": "WATCH"}],
 "auto_resolvable": true, "never_auto": false, "never_auto_implications": "…",
 "test_cases": [{"inputs": {…}, "expected": {"kind": "AGREEMENT"}}], "risks": ["…"], "citations": ["F1", "F4"],
 "confidence": 0.8,
 "model": {"model_id": "…", "provider": "grok", "mock": false, "reservation_id": "…", "bridge_request_id": "…"},
 "route": {… n8n_model_job.route_summary: tier, lane served, lanes tried, escalation …},
 "cost": {"cost_estimate_usd": 0.0}, "rulebook_matrix_sha256": "e40e…", "created_at": "…",
 "decision": null | {"decision": "approve" | "edit-and-approve" | "reject", "actor_kind": "operator", "actor": "tailnet:…",
                     "reason": "…", "at": "…", "edited": false, "amendment_id": "A1", "amendment_sha256": "…",
                     "current_case": {…}},
 "history": [{"event": "proposal_created", "at": "…", "sequence": 5}, …]}
```

### POST /api/v3/conflicts/proposals/{proposal_id}/decision

Body (no other field is accepted; never an actor field):

```json
{"decision": "approve" | "edit-and-approve" | "reject",
 "reason": "required, 1..4000 chars",
 "expected_revision": 7,
 "edited": {"plain_rule": "…", "machine_form": {…}, "tier": "T1"},   // only with edit-and-approve; any subset
 "apply_current_case": true}                                           // optional: record the proposed resolution for the example cases
```

200:

```json
{"ok": true, "proposal": RuleProposal, "amendment": RulebookAmendment | null,
 "current_case": {"requested": true, "applied": true, "recorded_in": "rule_proposals.jsonl", "resolutions": […],
                  "takes_effect": "next conflict-resolver run re-evaluates these findings under A1"},
 "rulebook": EffectiveConflictRulebook (without overlay)}
```

Errors: `400 DECISION_INVALID | REASON_REQUIRED | EXPECTED_REVISION_REQUIRED | EDIT_INVALID | MACHINE_FORM_REFUSED |
UNKNOWN_OR_ACTOR_FIELD | INVALID_ID`, `403 AGENT_CALLER_REFUSED | CSRF_REFUSED`, `404 NOT_FOUND`,
`409 PROPOSAL_NOT_PENDING | PROPOSAL_CHANGED (reason = current revision) | NEVER_AUTO_REFUSED (reason = plain text to show)`,
`503 PROPOSAL_DECISIONS_NOT_ACTIVATED | PROPOSAL_STORE_UNAVAILABLE | AUTH_CONFIG_UNAVAILABLE`.

`RulebookAmendment@v1`: `{amendment_id "A<n>", sequence, prev_sha256, sha256, proposal_id, signature, rule {plain_rule,
tier, machine_form, patch, test_cases, never_auto_implications, never_auto, auto_resolvable}, base {rulebook_version,
matrix_sha256, rulebook_sha256}, version_after "2.<n>", provenance {proposal_id, approved_by, approved_at, reason,
decision, edited, model, route, facts_sha256}}`. `config/conflict_rulebook.json` (and its `matrix_sha256` binding) is
never rewritten; the effective version is `<base>.<amendment count>`.

## 5. Page contract (for the Conflict rules page)

Section "Proposed rules — awaiting your approval": one card per `proposals[]` with `status == PENDING` — `plain_rule`,
`summary`, tier chip, `never_auto` badge with `never_auto_implications`, `proposed_resolution`, `risks`, `test_cases`
(collapsed), `model.provider` + `created_at`. Buttons: **Approve**, **Edit** (plain_rule / machine_form / tier, then
`edit-and-approve`), **Reject** (reason required for all three). Send `expected_revision = proposal.revision`. Show
`409 NEVER_AUTO_REFUSED`'s `reason` verbatim. When `decisions_enabled` is false, show the buttons disabled with
"Approval activation pending". Below it, "Unmatched — AI proposal pending": `unmatched[]` rows whose `proposal_id` is
null, with `last_failure.reason` when present. Mobile: list → full-screen sheet at ≤ 820 px.

## 6. Notification

One grouped intent per pass for pending proposals not yet announced (`notified` events), through
`scripts/lib/host_comms_intents.queue_intent` (producer `conflict_rule_proposals`, domain `conflicts`, kind
`rule_proposals_pending`, DIGEST → P2 needs-action). Never one per row, never a send from the lane. Until the route row
exists the attempt is recorded `notify_failed intent_unrouted` and retried next pass.

## 7. Stores

`data/conflicts/rule_proposals.jsonl` — `RuleProposalEvent@v1` (`unmatched_observed`, `proposal_created`,
`proposal_failed`, `decided`, `notified`, `notify_failed`), and `data/conflicts/rulebook_amendments.jsonl` —
`RulebookAmendment@v1`. Both append-only, `sequence` + `prev_sha256` + `sha256` chained; a broken chain fails closed (the
API answers 503; the resolver applies no amendment and reports `amendments_gap`). Proposed rows:
`config/data_source_authority.json` `proposed_domains[conflict_rule_proposals]`,
`config/proposals/conflict_rule_proposals/`. Retention 400 days, archive only.

## 8. Not in this PR (separate `[shared-infra]` PR)

`config/lane_registry.json` + `config/n8n_run_allowlist.json` lane `conflict-rule-proposals`,
`config/host_comms_intent_routes.json` route (`conflicts`, `rule_proposals_pending`), and the governed process
registration (`config/llm_process_registry.json`, `config/llm_routing_policy.json`,
`scripts/lib/governed_process_routes.py` `CALLER_TASK_PROCESS_MAP["n8n_model_job"]["conflict_rule_proposal"]`). The first
three files are sha-pinned by `docs/ops/packets/disk-standing-apply-20261024/activation-input-sha256.json`
(`tests/test_disk_standing_apply_20261024.py`). Until that PR lands, the bridge refuses the process (`governance_refused`,
recorded as `proposal_failed`) and the intent is `intent_unrouted` — nothing is called or sent.
