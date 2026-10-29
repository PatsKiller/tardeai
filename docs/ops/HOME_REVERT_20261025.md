# Home: restore the pre-Board-14 Do now page

Operator order: 2026-10-25. Historical source: `90c071052`; former served release: `3ed0573d3`.

The operator rejected Board 14 on 2026-10-25. Home again defaults to `HomeDoNow`, with the summary strip, ranked/filterable Do-now queue, Accounts, book movers and three small numbers, opportunities/market/pulse cards, and four collapsed sections. `?view=classic` remains available. The existing App footer still identifies the loaded bundle.

## Correctness retained

- Protection uses the categorized CIO positions supplied by `/api/v2/cio/pages`, the same presentation record and `stopCategory` helper as Risk. Legacy risk-snapshot below-stop/no-stop assertions cannot overwrite that record. Active resting stops do not produce false alerts; pending activation, filled awaiting sync, planned levels and unknown states remain distinct. Filled awaiting-sync rows do not claim money at risk.
- The unprotected count, broker-read clock and stale gap use the categorized CIO record. Missing current categories produce a source gap and an unknown count, never an all-clear or fabricated zero.
- Retained responses after failed refreshes keep their observed stop categories and approval count, with stale source receipts and a visible queue warning. A stale contributing source cannot become a fresh all-clear.
- The approval row uses `overview.pending_approvals ?? overview.approvals_count`, exactly the header's precedence; its action opens Approvals Center.
- Home release navigation opens `/system/releases` (Releases & Schedules); the retained STOP releases control is unchanged.
- Times use the existing ET display helpers. Account chips use the existing names-only sanitizer.
- The existing shared phone-shell scroll fix is untouched. Home links have 44 px phone targets, with the phone rule taking precedence over inline row sizing. Phone queue details and all four collapsed sections open the existing full-screen detail sheet with browser Back and focus restoration.
- Shared W7 panels, Risk/CIO/Portfolio pages and all backend/data sources are unchanged. Historic Classic colors/fonts are expressed through existing tokens/the minimum font size rather than adding design debt.

## Tests retained, replaced and archived

`e2e/home-board14.spec.ts` is archived as `e2e/archive/home-board14.spec.ts.disabled`, preserving the rejected layout's assertions without collecting them. The Home-only assertions forbidding HomeDoNow/repeated summary metrics in `test_decision_cards_20261008.py` and `test_w7_pages_20261024.py` now describe the operator-restored layout. Other page assertions remain.

`home-do-now.spec.ts` again covers the old page's layout, filters, Show all, Classic view and missing-source behavior, with invented symbols, names and amounts. Its fixtures live separately in `e2e/fixtures/homeDoNow.fixture.ts`. `home-protection-stops.spec.ts` preserves broker-read/stale/stop-category coverage inside this layout. The Python `home_board14` measurement suite and its CI gate remain active: they test backend clocks, missing receipts and count correctness, not the rejected visual layout.

Model checks cover current-vs-legacy category disagreement, pending/filled/active/planned/unknown states, exact Risk position links, approval precedence and zero, missing/failed current reads, stale reads, retained HTTP 503 answers, and account names.

## Verification and remaining proof

- 72 Home model checks pass after the independent audit patch.
- 76 Python tests pass with psycopg2 hidden (Home queue, Home measurement helpers, W7 projection and decision-card coverage).
- Both host-path and test-coverage ratchets report zero new violations.
- TypeScript typecheck passes; the UI build passes, including token/UI standards/contrast checks and the existing model suites.
- All twelve replacement Home fixture tests passed in an actual, narrowly approved browser run, including retained HTTP 503 source failures, every queue row/filter/Show all, all four phone drawers and Classic view. The dedicated Home UI workflow also passed at `f52ed0f5c`. Browser access used static built assets on an ephemeral loopback port, synthetic API fixtures and an external-origin barrier; no production traffic occurred.

Private reference images remain outside this public repository. No private reference image, holding, amount or account name was copied into fixtures or PR text. Actual screenshots are saved privately under `handoffs/home-revert-20261025/proof/` as `impl-home-1440.png`, `impl-home-412.png`, and `impl-home-390.png`, with row-detail and drawer proofs. They were compared against the operator's private references; the existing shared shell remains unchanged.

The broader CC surface-agreement CI run at that head passed 31 cases and exposed two remaining Home-only Board-14 assertions in `account-labels.spec.ts`: the retired card identifier and the assertion that book movers must be absent. This follow-up updates the Home fixture/assertions for the restored queue and grouped movers while retaining names-only account checks. The Risk and Journal assertions stay unchanged. Full exact-head CI remains required; these local/individual results do not imply that the PR is ready to release.

The corrected fixture then passed all **45 actual browser cases** locally: the complete 33-case CC surface-agreement selection plus the 12 restored Home cases. Home account-name proof uses invented two-account data and checks both queue chips and expanded mover rows, with zero Home writes. Private screenshots include those account-name rows. Application source is unchanged from `f52ed0f5c`; this follow-up changes only the Home portions of the account-label test and this report. Both ratchets and the regenerated-in-memory documentation index check pass.

Fixture proof commands (two terminals; use the worktree, never the live server). The existing static fixture server rejects API requests and has no proxy. Desktop uses a tall 1440 px viewport so the fixed shell cannot crop the lower Home sections; phone screenshots use full document scrolling. The 412 px test additionally saves each opened row and drawer when the proof directory is set:

```bash
# Terminal 1
cd /home/johnclaw/wt-codex-home-revert-20261025/apps/command-center-v3
export TMPDIR=/home/johnclaw/.cache/agent-tmp/home-revert
npm run build
python3 e2e/support/account_label_static_server.py --dist dist --port 4186 \
  --port-file "$TMPDIR/home-revert-fixture.port"

# Terminal 2
cd /home/johnclaw/wt-codex-home-revert-20261025/apps/command-center-v3
export TMPDIR=/home/johnclaw/.cache/agent-tmp/home-revert
export HOME_REVERT_PROOF_DIR="$HOME/trade-ai-releases/persistent-state/data/coordination/handoffs/home-revert-20261025/proof"
mkdir -p "$HOME_REVERT_PROOF_DIR"
HOME_REVERT_PROOF_DIR="$HOME_REVERT_PROOF_DIR" \
PLAYWRIGHT_BASE_URL=http://127.0.0.1:4186 \
node node_modules/@playwright/test/cli.js test e2e/home-do-now.spec.ts e2e/home-protection-stops.spec.ts --workers=1
```

Publication requires the operator: automatic approval review rejected the session's remote push and stated that remote pushes must remain user-controlled despite the explicit authorization. No push workaround, merge or release was attempted. Keep the PR draft until the coordinator can compare the private proof screenshots and inspect the phone taps.

## Home UI workflow correction

The existing `home-board14-ui` workflow silently selected only three protection tests after the old layout spec was archived. It now selects the active Do-now and protection files (12 tests), includes the restored page/model/fixture trigger paths, checks both files exist and uploads the three synthetic viewport screenshots from a temporary artifact directory. Workflow and job names stay stable. Draft runs still skip the full browser job; quick checks are not a full CI acceptance receipt.
