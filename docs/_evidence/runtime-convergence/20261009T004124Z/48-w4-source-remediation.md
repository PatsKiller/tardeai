# Host routing and streaming source remediation

Status: SOURCE_ONLY fixes with TEST_ONLY acceptance; not yet deployed.
Owner: platform / governed model bridge.
as_of: 2026-10-09T03:04:00Z.
Base: merged W4 main d444fe9eb970f9e9640c149794f95f334deee320.

Independent review found three P1 defects in merged W4: alternate selection ignored the process registry's fallback_allowed=false; stale/global-only health could qualify another provider; and streaming resolved again and generated a second, unaccounted response. The duplicate streaming generation predated W4, while W4 enabled mutable provider selection on that second path. The model, role, auth, sender and broker authorities remain unchanged by the correction.

The selector now honors explicit fallback permission, including the canonical missing-field default False. Alternate health requires an aware/current checked_at within the llm-provider-health lane's existing hourly cadence and an attributable producer recovery finding with valid counts. Global OK is insufficient. window_hours remains the DB lookback, not a freshness TTL. Existing negative balance/auth/billing evidence remains conservative; unknown primary health retains the existing primary-selection behavior. No global SLO or automatic policy ratification was introduced.

Streaming emits chat.completion.chunk deltas and final usage/provenance/[DONE] from the first settled governed result. It does not resolve policy or call a provider again. Error results become typed JSON before a successful HTTP status. Text, reasoning, tool-call indexes, finish reason, usage and host receipt lineage are retained. The canary bridge's transport remains DeepSeek-only; unsupported OAuth/Grok requests refuse rather than silently using DeepSeek. OAuth-first routing is not claimed globally and no provider keys move into n8n.

Registered existing routing tests produced 20 prior failures initially and then 30 failures/one positive pass after expanded canonical-default/attribution/nonfinite-clock cases. Final routing: 47 passed. Nine affected bridge/provider/model/n8n families: 158 passed, repeated after focused line-ending cleanup. Independent bridge/routing/provider-alarm verification: 94 passed. [Initial negatives](48-w4-negative-prior.log), [expanded negatives](48-w4-negative-expanded-prior.log), [routing pass](48-w4-routing-final.log), [affected regression pass](48-w4-regression-final.log) and the reviewer tool receipts substantiate this TEST_ONLY result. Sandbox fixture-socket failures and an obsolete duplicate-resolve test expectation are preserved as separate failed attempts, not relabelled acceptance.

The inherited bridge file mixed 1800 CRLF and 174 LF separators. New/changed lines only were normalized to LF to satisfy the unchanged raw whitespace gate: final 1762 CRLF/251 LF; every untouched byte was asserted identical. Native line-ending churn audit, raw diff check, compilation, Ruff lint and edited-test formatting passed. Whole-file source formatter debt already existed and no formatter/config/gate was weakened.

Full attempt46 started before these defects were fixed and caught 20 new W4 negatives; it is a failed experiment, not final acceptance. Final combined canonical attempt49 must pass on the completed source candidate before remote sync. Natural provider/runtime proof remains separate; all provider calls in these tests are mocked.

Rollback: deploy the captured prior approved immutable release with canonical CURRENT rebind and verify build/API/process roots. Preserve durable state/receipts and independent recovery services. Do not replay paid jobs, change model identities, disable cost gates or reactivate retired Ollama as a rollback shortcut.
