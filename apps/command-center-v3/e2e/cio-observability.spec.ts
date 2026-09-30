import { test, expect } from '@playwright/test'

const observability = {
  ok: true,
  schema: 'CIODeskObservability@v1',
  as_of: '2026-09-30T12:00:00Z',
  overall: { status: 'DEGRADED', working: 4, degraded: 1, blocked: 1, finding_count: 2 },
  scorecards: [
    { id: 'hermes_/_research', name: 'Hermes / Research', status: 'DEGRADED', value: 8, source: '/api/v3/cio/agent-research-ops', last_success: '2026-09-30T12:00:00Z', blocker: 'AGENT_FLASH_CIRCUIT_OPEN', downstream_impact: 'Research-backed thesis latency', metrics: { failed: 2 } },
  ],
  workflows: [
    { id: 'research', label: 'Research / Hermes', status: 'DEGRADED', throughput: 8 },
    { id: 'policy', label: 'Policy Review', status: 'BLOCKED', throughput: 1 },
  ],
  recommendation_funnel: [
    { id: 'created', label: 'Research Created', count: 10 },
    { id: 'influence', label: 'Memory Influence', count: 0 },
  ],
  findings: [{ issue_id: 'CIO-LEARNING-001', severity: 'HIGH', title: 'Outcomes due but none matured', root_cause: 'Maturation has not occurred', status: 'ACCEPTED_LIMITATION', component: 'learning' }],
  policy: { status: 'POLICY_REQUIRED', missing_count: 2, blocked: true },
}

test.describe('CIO Desk observability', () => {
  test('shows overall health, workflow, funnel, and remediation evidence', async ({ page }) => {
    await page.route('**/api/v3/cio/observability*', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(observability) }))
    await page.route('**/api/v3/cio/home*', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, as_of: observability.as_of, cio_now: { decisions: [], decision_count: 0, open_actions_count: 0, open_plans_count: 0 }, evidence: {} }) }))
    await page.route('**/api/v3/cio/dispositions*', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, dispositions: {} }) }))
    await page.route('**/api/v3/cio/brain*', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) }))
    await page.goto('/v3/cio?tab=cio-now')
    await expect(page.getByTestId('cio-observability')).toBeVisible()
    await expect(page.getByText('DEGRADED').first()).toBeVisible()
    await expect(page.getByTestId('cio-workflow-graph')).toContainText('Research / Hermes')
    await expect(page.getByTestId('cio-recommendation-funnel')).toContainText('Memory Influence')
    await expect(page.getByTestId('cio-findings')).toContainText('CIO-LEARNING-001')
    await expect(page.getByText('Policy: POLICY_REQUIRED')).toBeVisible()
  })
})
