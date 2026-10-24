# WP-15: AGENTS 20.2.0 package delivery

Status: DRAFT — locally verified operator package; policy ratification and runtime enablement pending
as_of: 2026-10-24T02:30:31Z
Measured at: base `4acb33ada3eed278c5f7652fcdcd6cbda15e68e5`, AGENTS 20.1.0 ACTIVE; session `codex-wp15-20261023`

The worker completed the inert 20.2.0 operator package. No repository policy, adapter, runtime feature flag, service, broker code, credential or live endpoint was changed. Publishing this delivery PR does not apply or ratify the package. The coordinator owns merge/release and the operator owns policy application and ratification.

## Reviewable deliverable

- Repository copy: [`packets/agents-20-2-20261023/README.md`](packets/agents-20-2-20261023/README.md).
- Durable operator copy: `/home/johnclaw/trade-ai-releases/persistent-state/data/coordination/handoffs/agents-20-2/`.
- The pre-existing `NOTE_WP19_cio_prospect_7A_row.md` is preserved. Its generated-table pin correction is already in this base. The new 20.2.0 whole-document comparison also masks only the renderer-owned §7A table.
- Frozen base: `4acb33ada3eed278c5f7652fcdcd6cbda15e68e5`. Later observed main `fe826d2ec` contains only WP-03 documentation changes; all bound policy/support/config bytes match, as the final operator preview confirmed.

The repository and durable copies have identical bytes for all 18 package files. The pre-existing WP-19 note is outside this manifest and remains unchanged.

| Artifact | SHA-256 |
|---|---|
| `SHA256SUMS` | `e98988359c9e39375a48bd90832c7237a5f856882476ffe25af95c1bde8c876f` |
| `agents-20.2.0-proposed.patch` | `51d7977cf056cae15608a916322f6c09b974aca6df9dcfcf55db6fa0cb4197b0` |
| `tests-20.2.0.patch` | `46732507e1941770f3d71db16799f4dc3c487454183e4fcfda5cd67bb439dceb` |
| `package.json` | `c58d9e795a0e4765c0609d11091a257364c18e089bdbe66706799663449f52fb` |
| `tier2-flags-after-ratification.patch` | `1daf6abfcc7e304153cfd29a556ce9f3fd0dee74b384c6eefcc313809d144a84` |

The package contains proposed-policy and support-test patches, a canonical new CI gate in the patch, an exact-base digest map, operator apply/ratify entry points, and a three-stage verifier. Each verification uses a unique export under the worker's own cache directory; no scratch tree is removed. Source policy remains 20.1.0 ACTIVE.

## What the proposal changes

1. §27.2 recognizes the named Work pipeline Tier 2 acts as the operator's own acts, requiring a fresh passkey assertion and typed phrase through the existing host applier. Required merge checks must be exactly success on the shown head; release grants and exact-main gates remain binding. Agents still cannot call Controls endpoints.
2. Grant-binding package approval stays outside the clause. `approve_item_enabled` remains false. The older proposal's Telegram wording was not copied: current §27.3 says Telegram is notification only.
3. §28.3 records shared-additive claim semantics, with exclusive behavior on a missing or invalid configuration.
4. §28.3a permits evidence-only closure of already-shipped **free** tasks, never taken tasks or ownership overrides.
5. §28.3b includes WP-41's five sections and evidence requirement. A PR-open label is not proof of a served change.
6. Adapter headings and their parity test say **eleven**. Their §0 bodies are byte-identical. Older pinning tests retain their existing digests by undoing only the exact 20.2.0 additions before comparison.
7. §28.8 already uses `TRADEAI_LIVE_SMOKE_AFTER_CLOSE=1`, so the package verifies and preserves that name rather than adding a redundant edit.

`merge_pr_enabled`, `release_now_enabled` and `approve_item_enabled` stay false. An inert `tier2-flags-after-ratification.patch` is provided only for review of a future separate task/PR. Neither apply nor ratify scripts apply it. The follow-up enabling PR remains blocked until the operator actually ratifies and merges 20.2.0.

## Verification

The governing fixture approval is explicitly synthetic. It records no operator decision and enables nothing live.

| Isolated stage | Governance tests | Policy state | Other checks |
|---|---:|---|---|
| none | 736 passed, 5 skipped | 20.1.0 ACTIVE | docs index and whitespace passed |
| proposed | 744 passed, 5 skipped | 20.2.0 PROPOSED | docs index and whitespace passed |
| ratified fixture | 744 passed, 5 skipped | 20.2.0 ACTIVE | docs index and whitespace passed |

The eight new policy tests verify exact insertion reversal, unrelated-authority mutation detection, generated-table tolerance, adapter parity, operator-only controls, default flag preservation, coordination obligations and canonical gate registration. Seven additional local safety checks confirmed intact digests, tampered-patch refusal, drifted-base refusal, non-TTY refusal, invalid approval metadata refusal and deterministic fixture ratification. Package Python passed Ruff check/format; shell entry points passed `bash -n`.

Evidence:

- `/home/johnclaw/.cache/rtc/codex-wp15-20261023/verification-ecblw2pp/receipt.json`
- The adjacent `none.log`, `proposed.log` and `ratified.log` retain exact test output.
- `/home/johnclaw/.cache/rtc/codex-wp15-20261023/safety-checks.txt`
- `/home/johnclaw/.cache/rtc/codex-wp15-20261023/final-preview.log`
- `/home/johnclaw/.cache/rtc/codex-wp15-20261023/final-patch-parity.json`

Two local preparation defects were corrected before verification: `operator.py` was renamed to `package_operator.py` to avoid shadowing Python's standard-library module; the builder now freezes its reviewed base so another worker's fetch cannot silently change it during generation. The final verified payload includes those fixes.

Final patch serialization omits the marker space on empty context lines so the tracked patch files pass repository whitespace checks. Both final patches apply cleanly; all eleven generated target files are byte-identical to the proposed tree used by the three-stage test run.

## Operator next step

The exact preview, apply and ratify sequence is in the package README. Begin with:

```bash
cd /home/johnclaw/trade-ai-releases/persistent-state/data/coordination/handoffs/agents-20-2
sha256sum SHA256SUMS
sha256sum -c SHA256SUMS
bash apply202-operator.sh
bash apply202-operator.sh --apply
```

Default mode is a preview. Apply requires the operator's TTY phrase, creates an isolated operator worktree and publishes the proposed PR. Ratify requires the exact open head and a token comment authored by `PatsKiller`; its default is also preview. The README derives the real PR number/head via `gh pr view` after creation, without a placeholder or fabricated PR number. Nothing merges automatically.

Paste back the proposed PR URL/head, ratification preview's comment ID/time and exact-head required-check results. Never paste keys or credential values.
