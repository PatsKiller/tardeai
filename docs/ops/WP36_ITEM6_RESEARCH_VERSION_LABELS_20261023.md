# WP-36 item 6: truthful research thesis-version labels

Status: DRAFT — local source fix verified; publication, deployment and new generated-brief acceptance pending
as_of: 2026-10-24T02:49:00Z
Measured at: main `fe826d2ecdb59a19bd7c510c8923c7b743f06eee`
Design-Task: DSN-20261023-handoff-v3-P7-T366

The site-validation report recorded an LLM brief saying `(INSUFFICIENT_DATA, v.null)`. The canonical producer, `build_research_prompt_context`, exposed `standing_thesis.version: null` and the insufficient-data state without telling narrative consumers how to describe the absent version. Adding a `v` prefix to that nullable value produced a false version label. No deterministic version renderer existed in this prompt contract.

The fix adds three presentation fields inside `standing_thesis`, keeping the existing nullable `version`, thesis ID, state and authority intact:

| Input version | Version status | Exact narrative display |
|---|---|---|
| `null`, blank or a missing-value sentinel | `UNAVAILABLE` | `thesis version unavailable` |
| `7` | `AVAILABLE` | `thesis version 7` |
| `symbol_fixture@v7` | `AVAILABLE` | `thesis version symbol_fixture@v7` |

`version_rendering_rule` tells consumers to copy `version_display` verbatim, never prepend `v` to the raw identity, and never infer a version from state, dates or prior research. Known pins retain their existing prefix exactly once. These are additive `ResearchPromptContext@v1` fields; the original raw fields and classifications keep their meaning. The context hash includes the presentation semantics, so a changed display rule cannot reuse the same prompt-context identity.

The contract already reaches external research through `canonical_prompt_context` and the stateful bridge; no provider entrypoint, model selection, credential, broker code, scheduler, prompt authority or runtime state is changed. The new fixtures exercise the canonical producer without importing or invoking a provider.

## Verification

- Before the source change, the missing-version regression failed with `KeyError: version_status`, proving the old producer lacked the presentation contract. Receipt: `/home/johnclaw/.cache/rtc/codex-wp36i6-20261023/before.xml`.
- After the change, 67 tests pass across the new version-label cases, existing context/thesis-delta behavior, write-path/fanout, stateful bridge, delta-index, data hygiene and canonical CI-gate registry. Receipt: `/home/johnclaw/.cache/rtc/codex-wp36i6-20261023/after.xml`.
- New fixtures pin the clock, replace thesis lookup, database queries and operator-watch lookup, and inject empty memory/evidence/feedback/lesson/receipt inputs. Missing and canonical/numeric versions preserve their raw value, state and authority. Serialized context carries the rule, and changing its display semantics changes the context hash.
- The new test file is registered through `scripts.lib.ci_gates.render` in `config/ci_gates/research_prompt_version_labels_20261023.json`. Python lint, Git whitespace and docs-index checks pass.

The existing compatibility tests attempted eleven live-DSN connections; the hermetic test guard refused all eleven before libpq. No live database connection succeeded. Those older fixtures still need independent isolation work; this delivery does not remove the guard or widen their access. The new version-label fixture suite uses mocked sources.

## Acceptance still pending

Historical stored LLM text and cached briefs are unchanged. The local tests establish the deterministic prompt contract, not a model's compliance with every instruction. After operator publication and exact-head CI, the coordinator owns merge and release. An authorized future research run should produce a new brief that describes a missing version as unavailable and preserves a known thesis pin without adding another prefix; capture the source context hash and generated research ID for acceptance. No paid generation or live rewrite was performed for this fix.

This delivery covers WP-36 item 6 only. It makes no portfolio valuation, rotation safety, broker, stop/order, scheduler or promotion change.
