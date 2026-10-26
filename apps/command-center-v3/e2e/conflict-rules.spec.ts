import {test, expect, type Page, type Route} from '@playwright/test'
import {readFileSync, mkdirSync} from 'node:fs'
import path from 'node:path'
test.use({hasTouch: true})

// UI contract fixtures. The rulebook view is generated from scripts/lib/conflicts/rulebook_view.build() on this tree;
// the proposal shape follows the RuleProposal@v1 contract of feat/conflict-rule-proposals-20261025 (fixture only).
// Every API call is intercepted: no live GET reaches :7777 and no decision POST leaves the browser.
const VIEW = JSON.parse(readFileSync(path.resolve('e2e/fixtures/conflict-rulebook-view.json'), 'utf8'))
const SHOTS = process.env.CONFLICT_RULES_SHOTS || path.join(process.env.TMPDIR || path.resolve('test-results'), 'conflict-rules-shots')
mkdirSync(SHOTS, {recursive: true})
const at = '2026-10-25T14:00:00Z'
const proposal = {
  schema: 'RuleProposal@v1', proposal_id: 'rp-fixture-1', status: 'PENDING', revision: 7, signature: 'ups-fixture-a',
  summary: "Advisory desk says 'HEDGE', which no vocabulary rule maps (R8)", plain_rule: 'Treat HEDGE from the advisory desk as the same stance as HOLD.',
  tier: 'T4', never_auto: false, proposed_resolution: [{finding_key: 'security:fixture-guid:UNMATCHED:ups-fixture-a', resolution: 'FIXT: HEDGE counts as HOLD; no flag.'}],
  risks: ['May hide a real reduce signal'], test_cases: [{expected: {kind: 'AGREEMENT'}}, {expected: {kind: 'CONFLICT'}}, {expected: {kind: 'AGREEMENT'}}],
  model: {provider: 'grok', model_id: 'fixture-model', mock: false}, created_at: at, decision: null,
}
const collection = (decisionsEnabled: boolean) => ({schema: 'RuleProposalCollection@v1', proposals: [proposal], total: 1, offset: 0,
  counts: {pending: 1, approved: 0, rejected: 0, unmatched_awaiting_ai: 1}, decisions_enabled: decisionsEnabled,
  rulebook: {schema: 'EffectiveConflictRulebook@v1', base_version: 2, version: '2.1', amendment_count: 1, status: 'PROPOSED'},
  unmatched: [
    {signature: 'ups-fixture-a', summary: proposal.summary, proposal_id: proposal.proposal_id, proposal_status: 'Proposed rule awaiting your approval',
      examples: [{key: 'security:fixture-guid:UNMATCHED:ups-fixture-a', summary: 'Advisory HEDGE vs CIO HOLD', subject: {kind: 'security', id: 'fixture-guid', label: 'FIXT'},
        sides: [{source: 'advisory_desk', source_label: 'Advisory desk', value: 'HEDGE', as_of: at}, {source: 'CIO record', source_label: 'CIO canonical record', value: 'HOLD', as_of: at}]}]},
    {signature: 'ups-fixture-b', summary: 'A sector-posture subject has no profile', proposal_id: null, proposal_status: 'AI proposal pending',
      examples: [{key: 'sector:tech:UNMATCHED:ups-fixture-b', summary: 'Sector posture', subject: {kind: 'sector', id: 'tech', label: 'Technology'}}], last_failure: null},
  ]})

type Options = {view?: unknown; proposals?: 'none' | 'pending' | 'disabled' | 'absent'; posts?: {url: string; body: unknown}[]; decided?: string; refuse?: boolean}

async function mock(page: Page, opts: Options = {}) {
  const posts = opts.posts ?? []
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.port === '7777') throw new Error('Live API traffic is forbidden')
    if (request.method() === 'POST') {
      posts.push({url: url.pathname, body: request.postDataJSON()})
      if (url.pathname !== `/api/v3/conflicts/proposals/${proposal.proposal_id}/decision`) throw new Error(`Unexpected POST ${url.pathname}`)
      if (opts.refuse) return route.fulfill({status: 409, json: {ok: false, error: 'NEVER_AUTO_REFUSED', reason: 'Fixture: protection rules always go to you; edit it to route to an owner.'}})
      return route.fulfill({status: 200, json: {ok: true, proposal: {...proposal, status: opts.decided ?? 'APPROVED', revision: 8},
        amendment: opts.decided === 'REJECTED' ? null : {amendment_id: 'A2'}, current_case: {requested: true, applied: true}}})
    }
    if (url.pathname === '/api/v2/desk-sources') return route.fulfill({status: 200, json: {ok: true, data: {observed_at: at, writers: []}}})
    if (url.pathname === '/api/v3/conflicts/rulebook') return route.fulfill({status: 200, json: {ok: true, data: opts.view ?? VIEW}})
    if (url.pathname === '/api/v3/conflicts/proposals') {
      if (opts.proposals === 'absent') return route.fulfill({status: 404, json: {ok: false, error: 'NOT_FOUND'}})
      if (opts.proposals === 'none' || !opts.proposals) return route.fulfill({status: 200, json: {ok: true, data: {schema: 'RuleProposalCollection@v1', proposals: [], unmatched: [], decisions_enabled: false}}})
      return route.fulfill({status: 200, json: {ok: true, data: collection(opts.proposals !== 'disabled')}})
    }
    // Shell chrome reads (header, nav badges) are not under test; answer 404 rather than reach a server.
    return route.fulfill({status: 404, json: {ok: false, error: 'fixture: not mocked'}})
  })
  return posts
}

async function noOverflow(page: Page) {
  const {scroll, inner} = await page.evaluate(() => ({scroll: document.documentElement.scrollWidth, inner: window.innerWidth}))
  expect(scroll).toBeLessThanOrEqual(inner)
}

async function tapTargets(page: Page, scope: string) {
  const small = await page.locator(`${scope} button:visible, ${scope} a:visible, ${scope} summary:visible`).evaluateAll(nodes => nodes
    .map(node => ({text: (node.textContent || '').trim().slice(0, 40), h: node.getBoundingClientRect().height}))
    .filter(row => row.h > 0 && row.h < 44))
  expect(small).toEqual([])
}

for (const width of [412, 390]) {
  const height = width === 412 ? 915 : 844
  test.describe(`conflict rules ${width}`, () => {
    test.beforeEach(async ({page}) => { await page.setViewportSize({width, height}) })

    test(`matrix page renders, rule card → full-screen sheet → Back (${width})`, async ({page}) => {
      await mock(page, {proposals: 'none'})
      await page.goto('/v3/conflicts/rules')
      const root = page.getByTestId('conflict-rules')
      await expect(root.getByTestId('cr-status')).toContainText('Rulebook proposed — not yet approved by you')
      await expect(root.getByTestId('cr-status')).toContainText('Not live')
      await expect(root.getByTestId('cr-status')).toContainText(VIEW.rulebook.matrix_sha256.slice(0, 12))
      await expect(root.getByTestId('cr-approval')).toHaveText('Approval: none recorded')
      await expect(root.getByTestId('cr-approval')).not.toContainText('{')
      await expect(root.getByTestId('cr-proposals')).toHaveCount(0)
      await expect(root.getByTestId('cr-tiers').locator('li')).toHaveCount(5)
      await expect(root.getByTestId('cr-rule-card')).toHaveCount(VIEW.rules.length)
      await expect(root.getByTestId('cr-never').locator('li')).toHaveCount(VIEW.never_auto.length)
      await expect(root.getByTestId('cr-live-gap')).toContainText('conflict ledger not yet produced')
      await expect(root.getByTestId('cr-lifecycle').locator('li')).toHaveCount(6)
      await expect(root.getByTestId('cr-scale-held').locator('ol > li')).toHaveCount(4)
      await noOverflow(page)
      await tapTargets(page, '[data-testid="conflict-rules"] main, [data-testid="conflict-rules"] .cr-stack')
      await page.screenshot({path: path.join(SHOTS, `conflict-rules-page-${width}.png`), fullPage: false, animations: 'disabled'})
      for (const part of ['cr-status', 'cr-tiers', 'cr-rules', 'cr-never', 'cr-scale', 'cr-conc', 'cr-life']) {
        const target = part === 'cr-status' ? root.getByTestId(part) : root.locator(`section[aria-labelledby="${part}"]`)
        await target.scrollIntoViewIfNeeded()
        await target.screenshot({path: path.join(SHOTS, `conflict-rules-${part}-${width}.png`), animations: 'disabled'})
      }

      const card = root.locator('[data-rule="R13"]')
      await card.scrollIntoViewIfNeeded()
      expect((await card.boundingBox())!.height).toBeGreaterThanOrEqual(44)
      await card.tap()
      const sheet = page.getByRole('dialog', {name: 'R13 · Concentration headroom'})
      await expect(sheet).toBeInViewport()
      const box = (await sheet.boundingBox())!
      expect(box.width).toBeGreaterThanOrEqual(width - 1)
      await expect(sheet.getByTestId('cr-rule-status')).toHaveText('Implemented')
      await expect(sheet).toContainText('R13 ADD gated by IPS headroom')
      await expect(sheet).toContainText('tests/test_conflict_rulebook.py')
      await expect(page).toHaveURL(/rule=R13/)
      await noOverflow(page)
      await page.screenshot({path: path.join(SHOTS, `conflict-rules-r13-sheet-${width}.png`), fullPage: false, animations: 'disabled'})
      await sheet.getByRole('button', {name: '← Back'}).tap()
      await expect(sheet).toHaveCount(0)
      await expect(page).not.toHaveURL(/rule=/)
      await expect(card).toBeVisible()
    })

    test(`concentration limits come from the API, never the page (${width})`, async ({page}) => {
      const view = JSON.parse(JSON.stringify(VIEW))
      view.concentration.rows[0].limit_pct = 31.5
      view.live = {by_kind: {GATE: 2, NEEDS_OPERATOR: 1}, by_state: {OPEN: 3}, open_total: 3, gap: null, as_of: at}
      await mock(page, {view, proposals: 'absent'})
      await page.goto('/v3/conflicts/rules')
      await expect(page.getByTestId('cr-concentration')).toContainText('31.5%')
      await expect(page.getByTestId('cr-live-counts')).toContainText('Waiting on you')
      await expect(page.getByTestId('cr-proposals-gap')).toContainText('AI rule proposals: not available yet')
      await noOverflow(page)
    })

    for (const flow of ['approve', 'reject'] as const) test(`AI-proposed rule ${flow} flow with confirm (${width})`, async ({page}) => {
      const posts = await mock(page, {proposals: 'pending', decided: flow === 'approve' ? 'APPROVED' : 'REJECTED'})
      await page.goto('/v3/conflicts/rules')
      const section = page.getByTestId('cr-proposals')
      await expect(section).toContainText('Proposed rules — awaiting your approval')
      await expect(section.getByTestId('cr-unmatched')).toContainText('Technology')
      await expect(section.getByTestId('cr-unmatched')).toContainText('AI proposal pending')
      await expect(page.getByTestId('cr-amendments')).toContainText('Effective version 2.1')
      const card = section.getByTestId('cr-proposal-card')
      await expect(card).toContainText('3 test cases')
      await expect(card).toContainText('grok · fixture-model')
      await expect(card).toContainText('Treat HEDGE from the advisory desk')
      await expect(card).toContainText('FIXT: HEDGE counts as HOLD')
      await noOverflow(page)
      if (flow === 'approve') await page.screenshot({path: path.join(SHOTS, `conflict-rules-proposals-${width}.png`), fullPage: false, animations: 'disabled'})
      await card.tap()
      const sheet = page.getByRole('dialog', {name: 'Proposed rule'})
      await expect(sheet).toBeInViewport()
      await expect(sheet).toContainText('FIXT: HEDGE counts as HOLD; no flag.')
      await expect(sheet).toContainText('Advisory desk: HEDGE')
      await expect(sheet).toContainText('May hide a real reduce signal')
      await sheet.getByRole('radio', {name: flow === 'approve' ? 'Approve' : 'Reject', exact: true}).tap()
      await sheet.getByRole('button', {name: `${flow === 'approve' ? 'Approve' : 'Reject'}…`}).tap()
      await expect(sheet.getByRole('alert')).toContainText('Write a short reason')
      expect(posts).toHaveLength(0)
      await sheet.getByLabel('Decision reason').fill(flow === 'approve' ? 'Matches how I read hedges' : 'Too broad')
      await sheet.getByRole('button', {name: `${flow === 'approve' ? 'Approve' : 'Reject'}…`}).tap()
      await expect(sheet.getByTestId('cr-confirm')).toBeVisible()
      expect(posts).toHaveLength(0)
      await noOverflow(page)
      await tapTargets(page, '[role="dialog"]')
      if (flow === 'approve') await page.screenshot({path: path.join(SHOTS, `conflict-rules-proposal-confirm-${width}.png`), fullPage: false, animations: 'disabled'})
      await sheet.getByRole('button', {name: flow === 'approve' ? 'Confirm approve' : 'Confirm reject'}).tap()
      await expect(sheet.getByTestId('cr-decision-result')).toContainText(flow === 'approve' ? 'You approved this rule. Recorded state: APPROVED · rulebook amendment A2' : 'You rejected this rule. Recorded state: REJECTED')
      expect(posts).toEqual([{url: `/api/v3/conflicts/proposals/${proposal.proposal_id}/decision`,
        body: flow === 'approve' ? {decision: 'approve', reason: 'Matches how I read hedges', expected_revision: 7, apply_current_case: true}
          : {decision: 'reject', reason: 'Too broad', expected_revision: 7}}])
      if (flow === 'reject') await page.screenshot({path: path.join(SHOTS, `conflict-rules-proposal-rejected-${width}.png`), fullPage: false, animations: 'disabled'})
      await sheet.getByRole('button', {name: '← Back'}).tap()
      await expect(sheet).toHaveCount(0)
    })

    test(`edit then approve sends the edited text (${width})`, async ({page}) => {
      const posts = await mock(page, {proposals: 'pending'})
      await page.goto('/v3/conflicts/rules?proposal=rp-fixture-1')
      const sheet = page.getByRole('dialog', {name: 'Proposed rule'})
      await sheet.getByRole('radio', {name: 'Edit then approve'}).tap()
      await sheet.getByLabel('Edited rule text').fill('Treat HEDGE as HOLD only when the CIO record is HOLD.')
      await sheet.getByLabel('Decision reason').fill('Narrower')
      await noOverflow(page)
      await sheet.getByRole('button', {name: 'Edit then approve…'}).tap()
      await sheet.getByRole('button', {name: 'Confirm edit and approve'}).tap()
      await expect(sheet.getByTestId('cr-decision-result')).toContainText('approved with your edit')
      expect(posts[0].body).toEqual({decision: 'edit-and-approve', reason: 'Narrower', expected_revision: 7,
        edited: {plain_rule: 'Treat HEDGE as HOLD only when the CIO record is HOLD.'}, apply_current_case: true})
    })

    test(`a refused decision shows the server's reason verbatim (${width})`, async ({page}) => {
      const posts = await mock(page, {proposals: 'pending', refuse: true})
      await page.goto('/v3/conflicts/rules?proposal=rp-fixture-1')
      const sheet = page.getByRole('dialog', {name: 'Proposed rule'})
      await sheet.getByLabel('Decision reason').fill('ok')
      await sheet.getByRole('button', {name: 'Approve…'}).tap()
      await sheet.getByRole('button', {name: 'Confirm approve'}).tap()
      await expect(sheet.getByTestId('cr-decision-result')).toContainText('Fixture: protection rules always go to you; edit it to route to an owner.')
      expect(posts).toHaveLength(1)
    })

    test(`"Decisions for you" opens the proposal sheet directly (${width})`, async ({page}) => {
      await mock(page, {proposals: 'pending'})
      await page.goto('/v3/conflicts/rules')
      const link = page.getByRole('region', {name: 'Decisions for you'}).getByRole('link', {name: /Proposed rule:/})
      expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44)
      await link.tap()
      const sheet = page.getByRole('dialog', {name: 'Proposed rule'})
      await expect(sheet).toBeInViewport()
      await sheet.getByRole('button', {name: '← Back'}).tap()
      await expect(sheet).toHaveCount(0)
    })

    test(`decisions not activated: proposal readable, buttons disabled (${width})`, async ({page}) => {
      const posts = await mock(page, {proposals: 'disabled'})
      await page.goto('/v3/conflicts/rules')
      await expect(page.getByTestId('cr-activation-pending')).toBeVisible()
      await page.getByTestId('cr-proposal-card').tap()
      const sheet = page.getByRole('dialog', {name: 'Proposed rule'})
      await expect(sheet.getByTestId('cr-decisions-disabled')).toContainText('Approval activation pending')
      await expect(sheet.getByRole('button', {name: 'Approve…'})).toBeDisabled()
      await expect(sheet.getByRole('radio', {name: 'Reject'})).toBeDisabled()
      expect(posts).toHaveLength(0)
    })
  })
}

test('desktop 1440: rule detail opens as a side panel with Back', async ({page}) => {
  await page.setViewportSize({width: 1440, height: 1000})
  await mock(page, {proposals: 'none'})
  await page.goto('/v3/conflicts/rules')
  await page.locator('[data-rule="R1"]').click()
  const panel = page.getByRole('dialog', {name: 'R1 · Freshness'})
  await expect(panel).toBeVisible()
  await panel.getByRole('button', {name: '← Back'}).click()
  await expect(panel).toHaveCount(0)
})

for (const width of [412, 390]) test(`ConflictSheet links to the matrix: "How conflicts are decided →" (${width})`, async ({page}) => {
  await page.setViewportSize({width, height: width === 412 ? 915 : 844})
  const key = 'fixture:data-error/source-path'
  const finding = {schema: 'ConflictFinding@v1', engine: 'fixture', kind: 'DATA_ERROR', rule: 'R8', key, summary: 'Unmapped stance from a fixture source',
    clears_when: 'The source uses the shared vocabulary', action: 'notify_operator', severity: 'warn', owner: 'Source owner', next_run: 'Next engine run',
    sides: [{source: 'desk', source_label: 'Desk', value: 'ADD_ON_PULLBACK', as_of: at}]}
  const section = {findings: [finding], headline: 'Unmapped stance needs attention', gap: null, source: 'fixture', as_of: at, stale: false}
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url())
    if (url.port === '7777' || route.request().method() !== 'GET') throw new Error('Live API traffic or writes are forbidden')
    if (url.pathname === '/api/v2/desk-sources') return route.fulfill({status: 200, json: {ok: true, data: {observed_at: at, writers: []}}})
    if (url.pathname === '/api/v2/jobs-health') return route.fulfill({status: 200, json: {schema: 'JobsHealth@v1', as_of: at, rows: [], total: 0, offset: 0, limit: 50,
      has_more: false, summary: {due_today: 0, succeeded: 0, failed: 0, missed: 0, paused: 0, retired: 0}, monitor: {observed_at: at, status: 'OK', cause: null},
      coverage_gaps: [], incident_count: 0, data_errors: {section, unavailable_reason: null}}})
    if (url.pathname === '/api/v3/conflicts/rulebook') return route.fulfill({status: 200, json: {ok: true, data: VIEW}})
    if (url.pathname === '/api/v3/conflicts/proposals') return route.fulfill({status: 200, json: {ok: true, data: {proposals: []}}})
    if (url.pathname === '/api/v3/conflicts') return route.fulfill({status: 200, json: {ok: true, data: {records: [], total: 0, offset: 0}}})
    return route.fulfill({status: 404, json: {ok: false, error: 'fixture: not mocked'}})
  })
  await page.goto('/v3/ops/jobs')
  await page.getByTestId('jobs-health').getByTestId('conflict-line').tap()
  const link = page.getByRole('dialog').getByTestId('conflict-rules-link')
  await expect(link).toHaveText('How conflicts are decided →')
  expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  await link.tap()
  await expect(page).toHaveURL(/\/v3\/conflicts\/rules\?rule=R8/)
  const sheet = page.getByRole('dialog', {name: 'R8 · One shared vocabulary'})
  await expect(sheet).toBeInViewport()
  await sheet.getByRole('button', {name: '← Back'}).tap()
  await expect(sheet).toHaveCount(0)
  await expect(page.getByTestId('cr-status')).toBeVisible()
})
