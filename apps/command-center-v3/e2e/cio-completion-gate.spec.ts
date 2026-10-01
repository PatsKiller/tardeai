import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const stages = [
  'wake_event', 'security_identity', 'office_truth', 'institutional_cognition',
  'canon_frameworks', 'research_retrieved', 'research_used', 'research_rejected',
  'research_gap', 'specialist_delegation', 'specialist_disagreement', 'model_route',
  'judgment', 'counter_thesis', 'confidence', 'falsifier', 'notification',
  'operator_disposition', 'checkpoint', 'outcome', 'belief_calibration_lesson',
]

const decision = {
  decision_id: 'dec_browser_exact', symbol: 'SCHD', stance: 'HOLD', action: 'HOLD',
  action_label: 'ADVISORY_ONLY', act_now: false, freshness: { state: 'PARTIAL' },
}

const home = {
  ok: true, as_of: '2026-10-01T18:00:00Z', authority: 'READ_ONLY_ADVISORY',
  cio_now: { decisions: [decision], decision_count: 1, open_actions_count: 0, open_plans_count: 0, material_today_count: 1, attention: { investment_decisions: 1, workflow_actions: 0, open_plans: 0, material_today: 1 } },
  operator_trust: {}, opportunities: { watch: [], reentry: [], rotation: [], research_gaps: [], watch_total: 0, reentry_total: 0 },
  evidence: { source_refs: [], validator_states: [], run_ids: [] },
  capital_plan: { cash_band: {}, sources: [], uses: [], deploy_request_notes: [] },
  report: {}, coverage: {}, posture: {}, funding: {},
}

const operatorEvidence = {
  ok: true, schema: 'CIOOperatorEvidence@v1', authority: 'READ_ONLY_ADVISORY',
  source_as_of: '2026-10-01T17:00:00Z', composition_as_of: '2026-10-01T18:00:00Z', freshness: 'OBSERVED', producer: 'fixture-projection',
  blocks: {
    research: { schema: 'CIOResearchProvenance@v1', artifacts: [{ artifact_id: 'res-1', status: 'RETRIEVED', related_securities: ['SCHD'] }], retrieved: [{ artifact_id: 'res-1', status: 'RETRIEVED' }], used_in_judgment: [], rejected: [], unknown: [], counts: { retrieved: 1, used_in_judgment: 0, rejected: 0, unknown: 0 }, source_as_of: '2026-10-01T17:00:00Z', composition_as_of: '2026-10-01T18:00:00Z', freshness: 'OBSERVED', producer: 'fixture-projection' },
    institutional_cognition: { items: [{ id: 'ctx-1', kind: 'memory_retrieval', state: 'RETRIEVED', influence: 'NOT_PROVEN' }], office_truth_boundary: ['price', 'holdings', 'cash', 'orders', 'broker_state', 'risk_limits'], source_as_of: '2026-10-01T17:00:00Z', composition_as_of: '2026-10-01T18:00:00Z', freshness: 'OBSERVED', producer: 'fixture-projection' },
    learning: { settled_outcomes: [], pending_outcomes: [{ outcome_id: 'out-1', decision_id: 'dec_browser_exact', status: 'PENDING' }], beliefs: [], lessons: [], research_derived_lessons: [], outcome_derived_lessons: [], hypotheses: [], experiments: [], sample_size: 0, successful_count: 0, success_rate: null, maturity_state: 'INSUFFICIENT_EVIDENCE', source_as_of: '2026-10-01T17:00:00Z', composition_as_of: '2026-10-01T18:00:00Z', freshness: 'OBSERVED', producer: 'fixture-projection' },
    capability_coverage: { rows: [{ capability: 'Hermes research', state: 'PARTIAL', current_status: 'PARTIAL', contract: 'fixture', producer: 'fixture', consumer: 'fixture', durable_artifact: 'fixture', last_produced_at: null, last_consumed_at: null, artifact_age: null, reason: 'runtime proof is partial' }], counts: { LIVE: 0, PARTIAL: 1, UNWIRED: 0, DARK: 0, UNKNOWN: 0 }, source_as_of: null, composition_as_of: '2026-10-01T18:00:00Z', freshness: 'UNKNOWN', producer: 'fixture-projection' },
  },
}

function lineage() {
  return { ok: true, authority: 'READ_ONLY_ADVISORY', lineage: { schema: 'CIODecisionLineage@v1', decision_id: decision.decision_id, lineage_id: 'lineage-browser', source_as_of: '2026-10-01T17:00:00Z', composition_as_of: '2026-10-01T18:00:00Z', authority: 'READ_ONLY_ADVISORY', stages: Object.fromEntries(stages.map(stage => [stage, { state: 'UNKNOWN', producer: null, consumer: null, source_ref: null, source_as_of: null, composition_as_of: '2026-10-01T18:00:00Z', evidence_class: 'FIXTURE', run_id: null, trace_id: null }])), institutional_cognition: { items: [] }, learning: { settled_outcomes: [], pending_outcomes: [{ outcome_id: 'out-1', decision_id: decision.decision_id, status: 'PENDING' }], maturity_state: 'INSUFFICIENT_EVIDENCE' }, research_provenance: { schema: 'CIOResearchProvenance@v1', counts: { retrieved: 1, used_in_judgment: 0, rejected: 0, unknown: 0 }, artifacts: [] } } }
}

test('CIO completion gate renders tabs, labels partial/unknown evidence, and preserves basename routing', async ({ page }, testInfo) => {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()) })
  page.on('pageerror', error => pageErrors.push(String(error)))
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    let body: unknown = { ok: true, authority: 'READ_ONLY_ADVISORY' }
    if (url.pathname.endsWith('/cio/home')) body = home
    else if (url.pathname.endsWith('/cio/scorecard')) body = { ok: true, schema: 'CIOScorecard@v1', tiles: [] }
    else if (url.pathname.endsWith('/cio/dispositions')) body = { ok: true, dispositions: {} }
    else if (url.pathname.endsWith('/cio/operator-evidence')) body = operatorEvidence
    else if (url.pathname.endsWith('/cio/research-provenance')) body = { ...operatorEvidence.blocks.research, ok: true, schema: 'CIOResearchProvenance@v1', authority: 'READ_ONLY_ADVISORY' }
    else if (url.pathname.includes('/cio/decision/') && url.pathname.endsWith('/lineage')) body = lineage()
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })

  const paths = [
    '/v3/cio?tab=overview', '/v3/cio?tab=decisions', '/v3/cio?tab=research',
    '/v3/cio?tab=capital-policy', '/v3/cio?tab=evidence-comms&sub=capability-coverage',
    '/v3/advisory', '/v3/agents', '/v3/hermes', '/v3/research-intelligence',
  ]
  const evidenceDir = path.resolve(process.cwd(), '../../docs/_evidence/cio_completion/browser')
  fs.mkdirSync(evidenceDir, { recursive: true })
  for (const [index, target] of paths.entries()) {
    await page.setViewportSize({ width: index % 2 ? 390 : 1440, height: 900 })
    await page.goto(target)
    await expect(page.locator('#root')).toBeVisible()
    await page.waitForTimeout(400)
    await page.screenshot({ path: path.join(evidenceDir, `${index}-${target.replace(/[^a-z0-9]+/gi, '_')}.png`), fullPage: true })
    const observation = await page.evaluate(() => ({
      textLength: document.body.innerText.length,
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      loadingText: /Loading office home|Loading operator evidence|Loading decision lineage/.test(document.body.innerText),
    }))
    expect(observation.textLength).toBeGreaterThan(80)
    expect(observation.horizontalOverflow).toBe(false)
    expect(observation.loadingText).toBe(false)
    expect(page.url()).not.toContain('/v3/v3/')
  }

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/v3/cio?tab=decisions')
  await expect(page.getByTestId('cio-decision-lineage-link')).toBeVisible()
  await page.getByTestId('cio-decision-lineage-link').click()
  await expect(page).toHaveURL(/\/v3\/cio\?tab=evidence-comms&sub=decision-lineage&decision=dec_browser_exact/)
  await expect(page.getByTestId('cio-decision-lineage')).toContainText('CIODecisionLineage@v1')
  await expect(page.getByTestId('cio-decision-lineage')).toContainText('UNKNOWN')
  expect(page.url()).not.toContain('/v3/v3/')
  expect(consoleErrors).toEqual([])
  expect(pageErrors).toEqual([])
  await testInfo.attach('browser-observations.json', { body: JSON.stringify({ paths, consoleErrors, pageErrors }, null, 2), contentType: 'application/json' })
})
