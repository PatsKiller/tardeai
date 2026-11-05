import { describe, expect, it } from 'vitest'
import {
  FAIL_RATE_BANNER_PCT, STALE_AFTER_MS, displayCount, fmtEt, matchesFilter, projectAutomations, rowFailure,
  searchRows, topCause, type AutomationsPayload, type WorkflowRow,
} from './automationsProjection'

const NOW = Date.parse('2026-11-05T12:00:00Z')
const at = (offsetMs: number) => new Date(NOW - offsetMs).toISOString()
const row = (over: Partial<WorkflowRow> = {}): WorkflowRow => ({
  name: 'tradeai-fabric-run-lane', state: 'live', runs: 42, ok: 42, fail: 0, folder: 'fabric', steps: 6, ...over,
})
const payload = (over: Partial<AutomationsPayload> = {}): AutomationsPayload => ({
  schema: 'Automations@v1', as_of: at(30_000), window_days: 7,
  kpi: { runs: 100, ok: 85, failed: 15, running: 0, fail_rate_pct: 15, avg_run_s: 4.2, cron_left: 368, cron_left_has_draft: 140, deltas: null, deltas_unavailable_reason: 'no prior 7-day snapshot' },
  workflows: [row(), row({ name: 'tradeai-event-router', fail: 15, ok: 0, runs: 15, last_error: 'ETIMEDOUT calling relay', state: 'off' })],
  counts: { workflows: 2, live: 1, shadow: 0, off: 1, failing: 1 },
  ...over,
})

describe('projectAutomations', () => {
  it('raises the banner above 10% and names the top cause', () => {
    const v = projectAutomations(payload(), { nowMs: NOW })
    expect(v.status).toBe('OK')
    expect(v.banner.show).toBe(true)
    expect(v.banner.cause?.name).toBe('tradeai-event-router')
    expect(v.banner.cause?.reason).toBe('ETIMEDOUT calling relay')
  })

  it('does not raise the banner at exactly the threshold, and never when the rate is unread', () => {
    const atLimit = payload({ kpi: { ...payload().kpi, fail_rate_pct: FAIL_RATE_BANNER_PCT } })
    expect(projectAutomations(atLimit, { nowMs: NOW }).banner.show).toBe(false)
    const unread = payload({ kpi: { ...payload().kpi, fail_rate_pct: null } })
    expect(projectAutomations(unread, { nowMs: NOW }).banner.show).toBe(false)
  })

  it('goes STALE past three missed refreshes and UNAVAILABLE on an unknown schema', () => {
    expect(projectAutomations(payload({ as_of: at(STALE_AFTER_MS + 1) }), { nowMs: NOW }).status).toBe('STALE')
    expect(projectAutomations(payload({ schema: 'Something@v2' }), { nowMs: NOW }).status).toBe('UNAVAILABLE')
    expect(projectAutomations(null, { nowMs: NOW }).status).toBe('UNAVAILABLE')
  })

  it('keeps an absent delta as unknown with its reason, not as zero', () => {
    const v = projectAutomations(payload(), { nowMs: NOW })
    expect(v.kpi.deltas).toBeNull()
    expect(v.kpi.deltasUnavailable).toBe('no prior 7-day snapshot')
    expect(displayCount(null)).toBe('—')
  })

  it('renders no rows for an unavailable payload, rather than an empty-and-healthy table', () => {
    expect(projectAutomations(null, { nowMs: NOW }).rows).toEqual([])
  })
})

describe('filters and search', () => {
  const rows = [
    row(),
    row({ name: 'tradeai-event-router', fail: 3, state: 'off', last_error: 'relay refused', folder: 'routing' }),
    row({ name: 'shadow-lane', state: 'shadow', folder: 'research' }),
  ]

  it('filters by failing, live and off', () => {
    expect(rows.filter(r => matchesFilter(r, 'failing')).map(r => r.name)).toEqual(['tradeai-event-router'])
    expect(rows.filter(r => matchesFilter(r, 'live')).map(r => r.name)).toEqual(['tradeai-fabric-run-lane'])
    expect(rows.filter(r => matchesFilter(r, 'off')).map(r => r.name)).toEqual(['tradeai-event-router'])
    expect(rows.filter(r => matchesFilter(r, 'all'))).toHaveLength(3)
  })

  it('searches name, folder and error text case-insensitively', () => {
    expect(searchRows(rows, 'ROUTER').map(r => r.name)).toEqual(['tradeai-event-router'])
    expect(searchRows(rows, 'fabric').map(r => r.name)).toEqual(['tradeai-fabric-run-lane'])
    expect(searchRows(rows, 'relay refused').map(r => r.name)).toEqual(['tradeai-event-router'])
    expect(searchRows(rows, '   ')).toHaveLength(3)
  })
})

describe('row failure text', () => {
  it('never invents a cause', () => {
    expect(rowFailure(row())).toEqual({ failing: false, reason: null })
    expect(rowFailure(row({ fail: 1, last_error: null })).reason).toBe('no error text recorded for the last failure')
  })

  it('picks the failing row with the most failures as the top cause', () => {
    const cause = topCause([row({ name: 'a', fail: 2, last_error: 'x' }), row({ name: 'b', fail: 9, last_error: 'y' })])
    expect(cause).toEqual({ name: 'b', reason: 'y', fail: 9 })
    expect(topCause([row()])).toBeNull()
  })
})

describe('fmtEt', () => {
  it('renders an ET stamp and returns null for junk', () => {
    expect(fmtEt('2026-11-05T16:30:00Z')).toContain('ET')
    expect(fmtEt('not-a-date')).toBeNull()
    expect(fmtEt(null)).toBeNull()
  })
})
