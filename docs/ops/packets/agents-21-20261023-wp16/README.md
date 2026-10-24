# WP-16: proposed AGENTS 21.0.0 operator package

Status: DRAFT — proposal artifacts only; operator application and ratification required
as_of: 2026-10-24T02:20:00Z
Measured at: base `4acb33ada3eed278c5f7652fcdcd6cbda15e68e5`, policy 20.1.0 ACTIVE

This rebuild replaces the stale 20.0.0-based package without changing the repository's actual policy, adapters, sizing authority or runtime code. The proposed stdlib-only module remains absent from the repository until the operator applies its patch and returns no suggestion until policy 21.0.0 is ACTIVE with §29 present. Ask-CIO wiring is held until actual ratification and #2011's contract are available.

The package retains the operator's option-B design, the three explicitly quoted ratifying clauses, the deterministic formula, visible input/constraint provenance, model-field stripping and the unconditional existing behavior rail. It fixes an inconsistency in the earlier proposal: existing position exposure is required, rather than silently assumed zero; only the risk budget has a specified default. The importer test examines actual imports, so documentation and generators mentioning the module do not count as production importers.

## Contents and bounds

- `BASE_SHA` and `BASE_MANIFEST.json` pin the actual 20.1.0 policy, adapters, behavior-rail module and every touched test/gate source. Apply refuses drift, including a later WP-15 20.2.0 policy. Rebuild after that lands; never weaken the pins.
- `agents-21.0.0-proposed.patch`: operator-applied header/banner/§29/history proposal. The existing §0/§17/§26 clauses and adapters remain unchanged until ratification.
- `code-tests-21.0.0.patch`: the inert proposed library, regression tests, older-test normalizers and **canonical CI gate** for the new policy test. Baseline policy digests are retained; the 20.1.0 whole-document comparison removes only this new amendment before checking its old hash.
- `build_ratify21.py`: exactly the three ratifying clause edits and the header/banner/history transitions. The four adapters receive only the specified advisory exception sentence.
- `rebuild21.sh`: deterministic generation from a git archive, in a unique `$HOME/.cache/rtc/codex-wp16-20261023/` directory. It does not use `/tmp` or remove existing directories.
- `verify21.sh`: tests **none**, **proposed** and **ratified** isolated exports. Ratified-stage token/PR values are synthetic fixtures, never real authorization.
- `SHA256SUMS`: package content digests, checked before apply/ratification/testing.
- `apply21-operator.sh` and `ratify21-operator.sh`: default preview; `--apply` is operator-only. They never push, merge, release, change a live flag or wire an importer. They print review/commit/publication commands after successful checks.

## Worker verification

```bash
cd /home/johnclaw/wt-codex-wp16-20261023
bash docs/ops/packets/agents-21-20261023-wp16/rebuild21.sh --source /home/johnclaw/wt-codex-wp16-20261023 --base 4acb33ada3eed278c5f7652fcdcd6cbda15e68e5
bash docs/ops/packets/agents-21-20261023-wp16/verify21.sh all --source /home/johnclaw/wt-codex-wp16-20261023
```

The verifier retains each export and its `tests.log`; it emits a machine-readable acceptance receipt under the unique scratch root. It never applies the proposal to the worker or canonical checkout. No broker, provider, production DB or live-server calls are needed.

## Operator steps, preview first

These commands are for the operator after reviewing this package. If a relevant source or policy changed, the preview refuses and this package must be rebuilt.

```bash
cd /home/johnclaw/wt-codex-wp16-20261023
git fetch origin
bash docs/ops/packets/agents-21-20261023-wp16/apply21-operator.sh --preview
bash docs/ops/packets/agents-21-20261023-wp16/apply21-operator.sh --apply
```

Apply creates `/home/johnclaw/wt-agents-21-0-0-wp16-apply` on `ops/agents-21-0-0-wp16-20261023`, claims the operator's changed paths, applies the proposal and runs the policy suite. Review and execute its printed commit/push/PR commands. No proposal approval is implied by creating that PR.

Once that real proposal PR exists, this preview resolves its actual PR number and current full SHA and prints the exact approval-comment command; it never posts the comment:

```bash
cd /home/johnclaw/wt-codex-wp16-20261023
bash docs/ops/packets/agents-21-20261023-wp16/ratify21-operator.sh --preview
```

After the operator has posted that exact token, apply verifies the operator account, complete token, PR number, current head, branch and clean worktree before making any ratifying edit:

```bash
bash /home/johnclaw/wt-codex-wp16-20261023/docs/ops/packets/agents-21-20261023-wp16/ratify21-operator.sh --apply
```

Paste back the preview/apply summaries and policy-test results, the proposal PR URL/head, then the actual token-comment reference and ratification results. Never paste a secret. The operator/coordinator merges only after the four required checks pass; the coordinator handles release. Wiring `size_suggestion` into the real Ask-CIO contract is a later, separately claimed implementation after ratification.
