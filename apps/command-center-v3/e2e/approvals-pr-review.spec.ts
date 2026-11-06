import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'
test.use({ hasTouch: true })

// Approvals → Merges + the PR review sheet (Design approvals-pr-review/v001). Synthetic PRs only (numbers 91xx,
// invented titles/paths/SHAs); every /api request is intercepted and live :7777 traffic fails the test.
// Phone (412/390): the Merges list, row → full-screen sheet with a 56 px header (the only fixed chrome), decision card
// last, no sideways page scroll, tap targets ≥ 44 px; desktop (1440): modal over the list with index + sticky decision.
const now = Date.now()
const iso = (minAgo: number) => new Date(now - minAgo * 60000).toISOString()
const H1 = '7c41e2a90f' + '1'.repeat(30), H2 = 'e02d5f1aa' + '2'.repeat(31), H3 = 'a51c9e3bb' + '3'.repeat(31), H3_OLD = '9f00aa11' + '4'.repeat(32)
const checks = { 'cio-hardening': 'SUCCESS', 'agent-governance': 'SUCCESS', 'release-readiness': 'SUCCESS', 'ci-gate': 'SUCCESS' }
const hunk = (id: string, file: string, start: number, note: string | null) => ({ id, file, header: `@@ -${start},3 +${start},6 @@ def fixture():`, start_line: start, end_line: start + 5,
  added: 4, removed: 1, truncated: false, note, lines: ['     count = record.attempts', '-    retry()', '+    if count >= cap:', '+        alert_once(record)  # a deliberately long fixture line that must scroll sideways inside its own card and never the page', '+        return', '+    retry()'] })
const review = (pr: number, head: string, over: Record<string, unknown> = {}) => ({
  schema: 'PrReview@v1', pr, title: `Fixture PR ${pr}`, url: `https://example.test/pr/${pr}`, base_sha: '5ef2' + '0'.repeat(36), head_sha: head, diff_sha256: 'd'.repeat(64),
  files: [{ path: 'scripts/fixture_supervisor.py', additions: 48, deletions: 9, status: 'modified' }, { path: 'tests/test_fixture_supervisor.py', additions: 72, deletions: 0, status: 'added' }],
  author: { vendor: 'Claude Code', agent: null, session: 'cl-fx02', model: 'Claude Opus 5.5', ids: ['https://example.test/s/cl-fx02'] },
  reviewer: { process_id: 'pr_independent_review', provider: 'anthropic', model: 'Claude Sonnet 5.5', run_id: 'rv-1027-0912', id: 'host:pr_independent_review:rv-1027-0912', started_at: iso(41), finished_at: iso(40), duration_s: 41, cost_usd: 0.09, calls: 1 },
  second_read: null, independent: { ok: true, rule: 'AGENTS.md §28.15 item 10', compared: [], reviewer: 'host:pr_independent_review:rv-1027-0912' },
  summary: 'Stops the fixture supervisor from retrying the same fix forever. After three failed attempts it sends one alert instead. Nothing here touches trading, the broker, secrets or the merge tooling.',
  risk: { level: 'MEDIUM', why: 'it changes a host job that runs every 10 minutes.', floor: 'MEDIUM' },
  classes: { held: [], held_paths: {}, shared_infra: true, labels: ['shared-infra'] },
  areas: [{ name: 'Operations job', additions: 48, deletions: 9, files: [{ path: 'scripts/fixture_supervisor.py', additions: 48, deletions: 9, status: 'modified', hunks: [hunk('h_1', 'scripts/fixture_supervisor.py', 138, 'Reads the attempt count before calling the model; at the cap it alerts once.'), hunk('h_2', 'scripts/fixture_supervisor.py', 210, null)] }] },
    { name: 'Tests', additions: 72, deletions: 0, files: [{ path: 'tests/test_fixture_supervisor.py', additions: 72, deletions: 0, status: 'added', hunks: [hunk('h_3', 'tests/test_fixture_supervisor.py', 1, 'Six tests: cap reached, below cap, missing count.')] }] }],
  evidence: { checks, tests_changed: 0, tests_added: 1, dry_run_quoted: true, real_layout_proof: true, adversarial_receipts: [] },
  findings: [{ id: 'F1', severity: 'MAJOR', title: 'A reopened record starts again at 0 attempts', file: 'scripts/fixture_supervisor.py', line: 141, detail: 'The counter lives on the open record; reopening starts a fresh count.', suggestion: 'Carry the count across.' }],
  dropped_findings: 0, unexplained_hunks: 1, hunk_count: 3, verdict: 'MERGE_WITH_NOTES', verdict_reason: 'follow-up findings', created_at: iso(40), document_sha: `doc-${pr}-${head.slice(0, 6)}`, ...over })
const rows = [
  { pr: 9107, head: H1, title: 'Fixture supervisor: stop retrying after 3 failed fixes', pill: { state: 'notes', label: 'Merge · 1 follow-up', tone: 'warning' }, rec: review(9107, H1), held: false, refusal: null },
  { pr: 9110, head: H2, title: 'Fixture merge window: add a Saturday slot', pill: { state: 'held', label: 'Held · your own merge', tone: 'danger' },
    rec: review(9110, H2, { classes: { held: ['merge_deploy_control'], held_paths: { merge_deploy_control: ['.mergify.yml'] }, shared_infra: false, labels: [] }, risk: { level: 'HIGH', why: 'merge tooling', floor: 'HIGH' }, findings: [],
      reviewer: { process_id: 'pr_independent_review_deep', provider: 'anthropic', model: 'Claude Opus 5.5', run_id: 'rv-1027-0915', id: 'host:pr_independent_review:rv-1027-0915', started_at: iso(30), finished_at: iso(29), duration_s: 60, cost_usd: 0.31, calls: 1 },
      second_read: { process_id: 'pr_independent_review_oauth', provider: 'chatgpt', run_id: 'rv-1027-0915-2', id: 'host:pr_independent_review:rv-1027-0915-2', cost_usd: 0, verdict: 'MERGE', summary: 'ok', findings: [], error: null }, verdict: 'MERGE' }), held: true, refusal: null },
  { pr: 9112, head: H3, title: 'Fixture report: rename a heading', pill: { state: 'stale', label: 'New push · re-reviewing', tone: 'neutral' }, rec: review(9112, H3_OLD), held: false, refusal: 'REVIEW_STALE' },
]
const item = (r: typeof rows[number], storeOk: boolean) => ({
  id: `pr:${r.pr}`, kind: 'MERGE', title: r.title, pr: r.pr, created_at: iso(40), proposed_by: 'Claude Code · cl-fx02', source: 'pr_reviews', governed_href: null, decision_mode: 'RECORD',
  pill: r.pill, summary: r.refusal ? null : r.rec.summary, head_sha: r.head, checks_green: true, checks, classes: r.rec.classes,
  merge: { head_sha: r.head, held: r.held, reviewed: !r.refusal, stale: !!r.refusal, state: r.pill.state, refusal: r.refusal },
  document_sha: r.refusal ? `stale-${r.pr}` : r.rec.document_sha,
  document: { document_sha: r.refusal ? `stale-${r.pr}` : r.rec.document_sha, source_sha: r.head, changes: r.refusal ? [] : r.rec.findings.map(f => ({ id: `finding_${f.id}`, section: f.severity, after: f.title })),
    review: { pr: r.pr, title: r.title, url: `https://example.test/pr/${r.pr}`, current_head: r.head, labels: [], checks, checks_green: true, pill: r.pill, stale: !!r.refusal,
      queue: r.refusal ? { state: 'SETTLING', reason: 'settle', next_try_at: iso(-6), head_sha: r.head } : null, approve_all: { eligible: !r.refusal, reason: 'x' }, review: r.rec } },
  thread: { questions: r.pr === 9107 ? [{ at: iso(20), question: 'Does this change anything on the trading side?', head_sha: r.head, answer: 'No. The files are a fixture job and its tests.', answered_at: iso(19), cost_usd: 0.02 }] : [],
    decisions: r.refusal ? [{ at: iso(90), decision: 'APPROVE', effect: 'OPERATOR_MERGE_LABEL', head_sha: H3_OLD, source_sha: H3_OLD, actor: 'tailnet:op', comment: '' }] : [] },
  decisions_store_approved: storeOk })
const summary = (storeOk: boolean) => ({ store_approved: true, decisions_store_approved: storeOk, label_applier_live: true, snapshot_as_of: iso(2),
  counts: { ready: 1, held: 1, rereviewing: 1, waiting_credit: 0, cannot: 0, hold: 0 }, digest: { last_sent_at: iso(60), next_at: 'Tue 2031-03-04 16:30 ET' },
  spend: { usd_today: 1.84, cap_usd: 2, reviews_today: 7, max_reviews_per_day: 20, questions_today: 2 }, models: { normal: 'Claude Sonnet 5.5', deep: 'Claude Opus 5.5' } })

async function rig(page: Page, storeOk: boolean) {
  const posts: { path: string; body: Record<string, unknown> }[] = []
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.port === '7777') throw new Error('Live API traffic is forbidden')
    if (!url.pathname.startsWith('/api/')) return route.continue()
    const p = decodeURIComponent(url.pathname)
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON()
      posts.push({ path: p, body })
      if (p.endsWith('/open')) return route.fulfill({ json: { ok: true, data: { review_id: 'review_fixture' } } })
      if (p.endsWith('/decide')) return route.fulfill({ json: { ok: true, data: { decision: body.decision, effect: p.includes('9110') ? 'REVIEW_APPROVED_NO_LABEL' : 'OPERATOR_MERGE_LABEL' } } })
      return route.fulfill({ json: { ok: true, data: { event: 'READ_MARKER' } } })
    }
    if (p === '/api/v2/governance/pr-reviews/summary') return route.fulfill({ json: { ok: true, data: summary(storeOk) } })
    const m = /^\/api\/v2\/governance\/approvals\/(pr:\d+)$/.exec(p)
    if (m) { const r = rows.find(x => `pr:${x.pr}` === m[1]); return route.fulfill({ json: { ok: true, data: item(r!, storeOk) } }) }
    if (p === '/api/v2/governance/approvals') {
      const items = rows.map(r => { const { document: _d, ...rest } = item(r, storeOk); return rest })
      return route.fulfill({ json: { ok: true, data: { items, pending_count: 3, known_pending_count: 3, complete: true, gaps: [], as_of: iso(1), recent: [], filtered_count: 3, offset: 0, resolved: [] } } })
    }
    return route.fulfill({ json: { ok: true, data: {} } })
  })
  return posts
}

const shots = process.env.PR_REVIEW_SCREENSHOT_DIR
async function noSideways(page: Page) { expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy() }
async function tapTargets(page: Page, scope: string) {
  const small = await page.evaluate(sel => [...document.querySelectorAll(`${sel} button, ${sel} a[href], ${sel} summary`)]
    .filter(el => (el as HTMLElement).offsetParent !== null).map(el => el.getBoundingClientRect()).filter(r => r.width > 0 && (r.height < 44 || r.width < 44)).length, scope)
  expect(small).toBe(0)
}

for (const width of [1440, 412, 390]) {
  const height = width === 412 ? 915 : width === 390 ? 844 : 900
  test(`merges list and review sheet ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const errors: string[] = []
    page.on('pageerror', e => errors.push(String(e)))
    const posts = await rig(page, true)
    await page.goto('/v3/approvals?tab=MERGE')
    await expect(page.getByTestId('merges-tab')).toBeVisible()
    await expect(page.getByTestId('merges-strip')).toContainText('1 held')
    await expect(page.getByTestId('merges-spend')).toContainText('$1.84')
    await expect(page.getByTestId('merge-row-9107')).toContainText('Merge · 1 follow-up')
    await expect(page.getByTestId('merge-row-9110')).toContainText('Held · your own merge')
    await expect(page.getByTestId('merge-row-9112')).toContainText('New push · re-reviewing')
    await expect(page.getByRole('button', { name: /Waiting on you/ })).toBeVisible()  // nothing removed
    await noSideways(page)
    if (shots) await page.screenshot({ path: path.join(shots, `list-${width}.png`), fullPage: true })
    await page.getByTestId('merge-row-9107').tap()
    const sheet = page.getByTestId('pr-review-sheet')
    await expect(sheet).toBeVisible()
    await expect(page).toHaveURL(/\/approvals\/pr:9107/)
    const header = await page.getByTestId('prr-header').boundingBox()
    expect(header!.height).toBeLessThanOrEqual(56)
    expect(header!.height / height).toBeLessThanOrEqual(0.15)
    await expect(page.getByTestId('prr-verdict')).toContainText('Medium risk')
    await expect(page.getByTestId('prr-who')).toContainText('Yes — reviewer is not the author')
    await expect(page.getByTestId('prr-approve')).toBeDisabled()
    await expect(page.getByTestId('prr-block')).toContainText('Read 1 more finding')
    // Read the one finding: fully on screen for 3 s (the ledger's read rule).
    await page.getByTestId('prr-finding-F1').scrollIntoViewIfNeeded()
    await expect(page.getByTestId('prr-read-F1')).toHaveText('✓ read', { timeout: 8000 })
    await expect(page.getByTestId('prr-read-count')).toContainText('1 of 1')
    // Go to the change → opens the hunk; its code scrolls inside its own card only.
    await page.getByTestId('prr-finding-F1').getByRole('button', { name: 'Go to the change →' }).tap()
    await expect(page.getByTestId('prr-hunk-h_1').getByTestId('prr-code')).toBeVisible()
    await expect(page.getByTestId('prr-hunk-h_2')).toContainText('Not explained by the reviewer')
    await noSideways(page)
    await tapTargets(page, '[data-testid="pr-review-sheet"]')
    if (width < 821) {
      // Phone: one column, the decision card is the last card.
      const decide = await page.getByTestId('prr-decide').boundingBox(), ask = await page.locator('#prr-ask').boundingBox()
      expect(decide!.y).toBeGreaterThan(ask!.y)
    }
    if (shots) await page.screenshot({ path: path.join(shots, `review-${width}.png`), fullPage: false })
    const approve = page.getByTestId('prr-approve')
    await expect(approve).toBeEnabled()
    await expect(approve).toHaveText('Approve merge')
    await approve.tap()
    await expect(page.getByTestId('prr-saved')).toContainText('operator-merge')
    const decided = posts.find(p => p.path.endsWith('/decide'))!
    expect(decided.path).toBe('/api/v2/governance/approvals/pr:9107/decide')
    expect(decided.body).toMatchObject({ decision: 'APPROVE', document_sha: rows[0].rec.document_sha, review_id: 'review_fixture' })
    expect(posts.some(p => p.path.endsWith('/open'))).toBeTruthy()
    await page.getByTestId('prr-back').tap()
    await expect(page.getByTestId('pr-review-sheet')).toHaveCount(0)
    await expect(page.getByTestId('merges-tab')).toBeVisible()
    expect(errors).toEqual([])
  })

  test(`held, stale and store-pending states ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    await rig(page, true)
    await page.goto('/v3/approvals/pr:9110?head=e02d5f1aa')
    await expect(page.getByTestId('prr-verdict')).toContainText('Held · needs your own merge')
    await expect(page.getByTestId('prr-held-note')).toContainText('.mergify.yml')
    await expect(page.getByTestId('prr-who')).toContainText('chatgpt')
    await expect(page.getByTestId('prr-approve')).toHaveText('Approve review')
    await expect(page.getByTestId('prr-approve')).toBeEnabled()
    await expect(page.getByTestId('prr-decide')).toContainText('adds no label')
    if (shots) await page.screenshot({ path: path.join(shots, `held-${width}.png`), fullPage: false })
    await page.goto('/v3/approvals/pr:9112')
    await expect(page.getByTestId('prr-state-banner')).toContainText('this review is out of date')
    await expect(page.getByTestId('prr-state-banner')).toContainText('earlier approval')
    await expect(page.getByTestId('prr-approve')).toBeDisabled()
    await expect(page.getByTestId('prr-block')).toContainText('re-reviewed')
    await noSideways(page)
    if (shots) await page.screenshot({ path: path.join(shots, `stale-${width}.png`), fullPage: false })
  })

  test(`decision store not approved disables decisions ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const posts = await rig(page, false)
    await page.goto('/v3/approvals/pr:9107')
    await expect(page.getByTestId('prr-block')).toHaveText('Decision store not yet approved')
    await expect(page.getByTestId('prr-approve')).toBeDisabled()
    await expect(page.getByTestId('prr-hold')).toBeDisabled()
    await expect(page.getByTestId('prr-ask-reviewer')).toBeDisabled()
    expect(posts.length).toBe(0)
    await page.goto('/v3/approvals?tab=MERGE')
    await expect(page.getByTestId('merges-decisions-pending')).toBeVisible()
  })
}
