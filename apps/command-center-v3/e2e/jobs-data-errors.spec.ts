import { test, expect } from '@playwright/test'
import path from 'node:path'
import { readFileSync } from 'node:fs'
test.use({ hasTouch: true })

// UI contract fixtures only. These inputs do not classify conflicts or prove the policy golden.
const at = '2026-10-24T22:00:00Z'
const key = 'fixture:data-error/source-path'
const secondKey = 'fixture:aaa-data-error/other-path'
const finding = {
  schema: 'ConflictFinding@v1', engine: 'fixture canonical engine', kind: 'DATA_ERROR', rule: 'fixture data error', key,
  summary: 'Canonical producer input needs repair', clears_when: 'The authoritative producer supplies a valid dated input',
  action: 'repair_source', severity: 'P2', owner: 'Fixture producer owner', next_run: 'After the authoritative producer next runs',
  sides: [{ source: 'Producer input', source_label: 'Producer input', value: 'Invalid dated input', as_of: at },
    { source: 'Canonical check', source_label: 'Canonical check', value: 'Valid dated input required', as_of: at }],
}
const second = {...finding, key: secondKey, summary: 'Second canonical data error'}
const section = { findings: [finding], headline: 'Canonical data error needs attention', gap: null, source: 'fixture', as_of: at, stale: false }
const record = { ...finding, schema: 'ConflictRecord@v1', subject: {kind: 'data', id: 'fixture-input'}, state: 'DECIDED',
  opened_at: at, updated_at: at, revision: 3, decision: {schema: 'ConflictDecision@v1', actor_kind: 'operator', actor: 'Fixture operator',
    chosen_side: 'producer', reason: 'Fixture decision retained pending engine check', evidence_refs: ['fixture-receipt'], at, expires_at: at},
  history: [{schema: 'ConflictEvent@v1', key, event: 'opened', at}, {schema: 'ConflictEvent@v1', key, event: 'decided', at}],
}
const jobs = {schema: 'JobsHealth@v1', as_of: at, rows: [], total: 0, offset: 0, limit: 50, has_more: false,
  summary: {due_today: 0, succeeded: 0, failed: 0, missed: 0, paused: 0, retired: 0},
  monitor: {observed_at: at, status: 'OK', cause: null}, coverage_gaps: [], incident_count: 0}

for (const width of [1440, 412, 390]) for (const state of ['canonical', 'null-headline', 'gap', 'unavailable', 'stale', 'detail-unavailable', 'multi'] as const) {
  test(`Jobs DATA_ERROR ${state} fixture ${width}`, async ({page}) => {
    const height = width === 412 ? 915 : width === 390 ? 844 : 1000
    await page.setViewportSize({width, height})
    const selectedRequests: string[] = []
    const methods: string[] = []
    await page.route('**/api/**', route => {
      const request = route.request()
      const url = new URL(request.url())
      methods.push(request.method())
      if (url.port === '7777') throw new Error('Live API traffic is forbidden')
      if (url.pathname === '/api/v2/jobs-health') {
        const supplied = state === 'multi' ? {...section, findings: [finding, second]}
          : state === 'null-headline' ? {...section, headline: null}
          : state === 'gap' ? {...section, findings: [], headline: null, gap: {reason: 'Canonical ledger not yet produced'}}
          : state === 'stale' ? {...section, stale: true} : section
        return route.fulfill({status: 200, json: {...jobs, data_errors: state === 'unavailable'
          ? {section: null, unavailable_reason: 'Conflict data is unavailable: the canonical reader is not installed'}
          : {section: supplied, unavailable_reason: null}}})
      }
      if ([key, secondKey].some(selected => url.pathname === `/api/v3/conflicts/${encodeURIComponent(selected)}`)) {
        selectedRequests.push(url.pathname)
        const body = url.pathname.endsWith(encodeURIComponent(secondKey)) ? {...record, ...second, schema: 'ConflictRecord@v1',
          history: record.history.map(event => ({...event, key: secondKey}))} : record
        return route.fulfill(state === 'detail-unavailable' ? {status: 404, json: {error: 'Fixture selected record missing'}}
          : {status: 200, json: body})
      }
      throw new Error(`Unexpected API path ${url.pathname}`)
    })
    await page.goto(process.env.W4_JOBS_FIXTURE_PATH || '/v3/ops/jobs')
    const root = page.getByTestId('jobs-health')
    await expect(root).toContainText('0 jobs in this filter')
    const line = root.getByTestId('conflict-line')
    expect(selectedRequests).toHaveLength(0)
    if (state === 'null-headline') await expect(line).toHaveCount(0)
    else if (state === 'gap') {
      await expect(line).toHaveCount(0)
      await expect(root.getByTestId('conflict-gap')).toHaveText('Conflict check unavailable: Canonical ledger not yet produced')
    } else if (state === 'unavailable') {
      await expect(line).toHaveCount(0)
      await expect(root.getByTestId('jobs-conflict-unavailable')).toContainText('canonical reader is not installed')
    } else {
      await expect(line).toHaveText(/Canonical data error needs attention/)
      expect((await line.boundingBox())?.height).toBeGreaterThanOrEqual(44)
      if (state === 'stale') await expect(root).toContainText('The data error comparison is out of date')
      if (width < 820) await line.tap(); else await line.click()
      const sheet = page.getByRole('dialog', {name: 'Job data error'})
      await expect(sheet).toBeInViewport()
      await expect(sheet.getByRole('heading', {name: 'What disagrees'})).toBeInViewport()
      await expect(sheet).toContainText(finding.summary)
      await expect(sheet).toContainText(finding.clears_when)
      await expect(sheet).toContainText('Fixture producer owner')
      await expect(sheet).toContainText('After the authoritative producer next runs')
      if (state === 'detail-unavailable') await expect(sheet.getByTestId('conflict-record-gap')).toContainText('review state is unknown')
      else {
        await expect(sheet.getByTestId('conflict-record-state')).toHaveText('Decision recorded · awaiting engine re-evaluation')
        await expect(sheet).toContainText('Fixture decision retained pending engine check')
        await expect(sheet).toContainText('Finding opened')
      }
      expect(selectedRequests).toHaveLength(1)
      if (width < 820) {
        const box = await sheet.boundingBox()
        expect(box?.x).toBe(0); expect(box?.y).toBe(0); expect(box?.width).toBe(width); expect(box?.height).toBe(height)
      }
      const back = sheet.getByRole('button', {name: '← Back', exact: true})
      expect((await back.boundingBox())?.height).toBeGreaterThanOrEqual(44)
      if (process.env.W4_SCREENSHOT_DIR) await page.screenshot({path: path.join(process.env.W4_SCREENSHOT_DIR, `impl-16-dataerror-detail-${state}-${width}.png`), fullPage: true})
      if (state === 'multi') {
        const choices = sheet.getByRole('navigation', {name: 'Other recorded findings'}).getByRole('button')
        await expect(choices).toHaveText([finding.summary, second.summary])
        expect((await choices.nth(1).boundingBox())?.height).toBeGreaterThanOrEqual(44)
        if (width < 820) await choices.nth(1).tap(); else await choices.nth(1).click()
        await expect(sheet.getByTestId('conflict-record-state')).toBeVisible()
        await expect(sheet.getByTestId('conflict-facts')).toContainText(second.summary)
        expect(selectedRequests).toHaveLength(2)
        expect(selectedRequests[1]).toBe(`/api/v3/conflicts/${encodeURIComponent(secondKey)}`)
        await page.goBack()
        await expect(sheet.getByTestId('conflict-facts')).toContainText(finding.summary)
      }
      await page.goBack()
      await expect(sheet).toHaveCount(0)
      await expect(line).toBeInViewport()
      if (width < 820) await line.tap(); else await line.click()
      await expect(sheet).toBeVisible()
      await expect(sheet.getByTestId(state === 'detail-unavailable' ? 'conflict-record-gap' : 'conflict-record-state')).toBeVisible()
      if (width < 820) await back.tap(); else await back.click()
      await expect(sheet).toHaveCount(0)
      await expect(line).toBeInViewport()
    }
    expect(methods.every(method => method === 'GET')).toBeTruthy()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    if (process.env.W4_SCREENSHOT_DIR) await page.screenshot({path: path.join(process.env.W4_SCREENSHOT_DIR, `impl-16-dataerror-${state}-${width}.png`), fullPage: true})
  })
}

// Actual native reader output over a frozen engine and disposable ledger; no policy golden claim.
for (const width of [1440, 412, 390]) {
  test(`Jobs native canonical DATA_ERROR fixture ${width}`, async ({page}) => {
    const native = JSON.parse(readFileSync(path.resolve('e2e/fixtures/w4-native-conflict.fixture.json'), 'utf8'))
    const height = width === 412 ? 915 : width === 390 ? 844 : 1000
    await page.setViewportSize({width, height})
    const reads: string[] = []
    await page.route('**/api/**', route => {
      const request = route.request(), url = new URL(request.url())
      expect(request.method()).toBe('GET')
      if (url.port === '7777') throw new Error('Live API traffic is forbidden')
      if (url.pathname === '/api/v2/jobs-health') return route.fulfill({status: 200,
        json: {...jobs, data_errors: {section: native.section, unavailable_reason: null}}})
      if (url.pathname === `/api/v3/conflicts/${encodeURIComponent(native.record.key)}`) {
        reads.push(url.pathname)
        return route.fulfill({status: 200, json: native.record})
      }
      throw new Error(`Unexpected API path ${url.pathname}`)
    })
    await page.goto(process.env.W4_JOBS_FIXTURE_PATH || '/v3/ops/jobs')
    const line = page.getByTestId('conflict-line')
    await expect(line).toContainText(native.section.headline)
    expect(reads).toHaveLength(0)
    if (width < 820) await line.tap(); else await line.click()
    const sheet = page.getByRole('dialog', {name: 'Job data error'})
    await expect(sheet).toBeInViewport()
    await expect(sheet.getByTestId('conflict-record-state')).toHaveAttribute('data-state', 'OPEN')
    await expect(sheet).toContainText(native.record.summary)
    await expect(sheet).toContainText(native.record.clears_when)
    await expect(sheet).toContainText(native.record.owner)
    await expect(sheet).toContainText(native.record.next_run)
    await expect(sheet).toContainText('Finding opened')
    await expect(sheet.getByRole('button', {name: /resolve|choose|apply/i})).toHaveCount(0)
    expect(reads).toHaveLength(1)
    if (width < 820) {
      const box = await sheet.boundingBox()
      expect(box?.x).toBe(0); expect(box?.y).toBe(0); expect(box?.width).toBe(width); expect(box?.height).toBe(height)
    }
    if (process.env.W4_SCREENSHOT_DIR) await page.screenshot({path: path.join(process.env.W4_SCREENSHOT_DIR, `impl-16-native-dataerror-detail-${width}.png`), fullPage: true})
    await page.goBack()
    await expect(sheet).toHaveCount(0)
    if (width < 820) await line.tap(); else await line.click()
    const back = sheet.getByRole('button', {name: '← Back', exact: true})
    expect((await back.boundingBox())?.height).toBeGreaterThanOrEqual(44)
    if (width < 820) await back.tap(); else await back.click()
    await expect(sheet).toHaveCount(0)
    await expect(line).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  })
}
