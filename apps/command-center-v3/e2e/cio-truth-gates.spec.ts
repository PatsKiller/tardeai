import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const enabled = process.env.CIO_TRUTH_BROWSER === '1'
const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '../../..')
const out = path.join(root, 'docs/_evidence/autonomous_advisory_loop/cio_truth_gates')

const decision = {
  kind: 'position', decision_id: 'dec_conflicted_schd_1', symbol: 'SCHD',
  account: 'schwab_rollover_ira', stance: 'Trim', action: 'TRIM',
  action_label: 'DATA_CONFLICT', action_label_display: 'DATA CONFLICT', act_now: false,
  recommended_delta_usd: null, delta_usd: null, value_usd: 230000,
  current_weight_pct: 17.9, target_weight_pct: null,
  trim_to_clear_fire_usd: null, trim_to_policy_usd: null, scenario_trim_usd: null,
  sizing_method: null, sizing_objective: null, sizing_suppressed: true,
  sizing_suppression_reason: 'DATA_CONFLICT',
  why_now: 'Standing trim view; current action is suppressed pending reconciled truth.',
  freshness: { state: 'STALE', financial_truth_quality: 'CONFLICTED' },
  symbol_thesis_id: 'symbol_schd', symbol_thesis_version: 'symbol_schd@v4',
}

test.describe('CIO financial truth and feedback gates', () => {
  test.skip(!enabled, 'set CIO_TRUTH_BROWSER=1 for isolated acceptance')

  test('conflicted cards withhold sizing and expose governed feedback', async ({ page }) => {
    fs.mkdirSync(out, { recursive: true })
    await page.route('**/api/v3/cio/dispositions*', route => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, dispositions: {} }),
    }))
    await page.route('**/api/v3/cio/home*', route => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({
        ok: true, authority: 'READ_ONLY_ADVISORY', as_of: '2026-08-23T13:03:00Z',
        cio_now: {
          decisions: [decision], decision_count: 1, open_actions_count: 0, open_plans_count: 0,
          material_today_count: 1,
          attention: { investment_decisions: 1, workflow_actions: 0, open_plans: 0, material_today: 1 },
        },
        operator_trust: {},
      }),
    }))

    await page.goto('/v3/cio')
    const card = page.getByTestId('cio-decision-card')
    await expect(card).toBeVisible()
    await expect(card.getByTestId('cio-sizing-suppressed')).toContainText('DATA CONFLICT')
    await expect(card).not.toContainText('Trim to clear fire')
    await expect(card).not.toContainText('Trim to policy')
    await expect(card).not.toContainText('Scenario trim')
    await expect(card).not.toContainText('Sizing method')
    await expect(card.getByRole('button', { name: /^Agree / })).toBeVisible()
    await expect(card.getByRole('button', { name: /^Disagree / })).toBeVisible()
    await expect(card.getByRole('button', { name: /^Defer / })).toBeVisible()
    await expect(card.getByRole('button', { name: /^Request data / })).toBeVisible()
    await expect(card.getByRole('button', { name: /^No longer relevant / })).toBeVisible()
    await expect(card.getByRole('button', { name: /^Acknowledge / })).toHaveCount(0)
    await page.screenshot({ path: path.join(out, 'conflicted-sizing-withheld.png'), fullPage: true })
  })
})
