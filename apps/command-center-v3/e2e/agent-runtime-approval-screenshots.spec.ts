/**
 * Agent Runtime Hub — operator approval screenshots.
 *
 *   cd apps/command-center-v3
 *   npm run build
 *   npm run preview -- --port 4173 --host 127.0.0.1 &
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173/v3 npx playwright test e2e/agent-runtime-approval-screenshots.spec.ts --reporter=line
 *
 * Output: e2e/screenshots/agent-runtime-approval/*.png
 */
import { test, expect } from '@playwright/test'
import path from 'path'
import fs from 'fs'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const OUT = path.join(__dirname, 'screenshots', 'agent-runtime-approval')

const READINESS_FIXTURE = {
  contract: 'agent-runtime-readiness-v1',
  observed_at: '2026-07-31T03:30:00+00:00',
  read_only: true,
  wiring: {
    read_api: { state: 'CONNECTED', gate_enabled: true, dsn_configured: true },
    dispatch: {
      state: 'WIRED',
      operator_auth: true,
      queue_module_configured: true,
      dispatch_dsn_configured: true,
      provider_module_configured: true,
      kill_switch_present: true,
    },
  },
  fleet_summary: {
    wave1_agents: 9,
    wave2_agents: 4,
    catalog_only_agents: 5,
    observability_agents: 13,
    runtime_evidence_agents: 5,
    total_agents: 18,
  },
  agents: [
    {
      agent_id: 'sentinel',
      display_name: 'Sentinel',
      source_class: 'RUNTIME_EVIDENCE',
      next_gate_state: 'INSUFFICIENT_EVIDENCE',
      next_gate_id: 'mvl-sample-size',
      next_step_hint: 'Continue SHADOW runs until sample gate clears.',
      promotion_eligibility: 'INSUFFICIENT_EVIDENCE',
      declared_lifecycle_state: 'SHADOW',
      review_health: 'NOT_RUN',
      sample_size: 122,
      required_sample_size: 200,
    },
  ],
  runbook_refs: ['docs/agent_runtime/DISPATCH_ENV_TEMPLATE.md'],
  manual_run_command_template:
    'AGENT_RUNTIME_OPERATOR_AUTH=1 AGENT_RUNTIME_QUEUE_MODULE=agent_runtime_dispatch_boot '
    + 'AGENT_RUNTIME_PROVIDER_MODULE=agent_runtime.providers.lab_watch_provider '
    + '.venv/bin/python -m scripts.agent_runtime.agents.run_once --agent <agent_id> --once',
}

const MATURITY_FIXTURE = {
  contract: 'agent-maturity-read-api-v1',
  schema_version: 'agent-maturity-observation-v1',
  generated_at: '2026-07-31T03:30:00+00:00',
  freshness: 'live runtime evidence from the read-only agent-runtime DB where present; repository evidence otherwise',
  source_availability: { agent_runtime_db: 'AVAILABLE' },
  unverified_source_warnings: [],
  read_only: true,
  authority: { mutation: false },
  summary: {
    total_agents: 18,
    by_lifecycle_state: { SHADOW: 5, DESIGNED: 13 },
    eligible_for_human_review: 0,
    sample_size_capped_agents: 0,
    unverified_runtime_status: 0,
    frameworks: ['agent-runtime-mvl'],
  },
  data: [
    {
      agent_id: 'sentinel',
      display_name: 'Sentinel',
      subsystem: 'watch_integrity',
      declared_lifecycle_state: 'SHADOW',
      environment: 'SHADOW',
      source_class: 'RUNTIME_EVIDENCE',
      sample_size: 122,
      required_sample_size: 200,
      sample_progress_state: 'MEASURED',
      next_gate_id: 'mvl-sample-size',
      next_gate_state: 'INSUFFICIENT_EVIDENCE',
      next_gate_description: 'Accumulate reviewed artifact evidence before human review.',
      promotion_eligibility: 'INSUFFICIENT_EVIDENCE',
      promotion_authority: 'HUMAN_ONLY',
      automatic_promotion_permitted: false,
      review_health: 'NOT_RUN',
      maturity_framework: 'agent-runtime-mvl',
      operator_checks_required: [],
      evidence_refs: ['config/agent_maturity_catalog.json'],
      warnings: [],
      freshness_state: 'CURRENT_RUNTIME_EVIDENCE',
    },
  ],
  evidence_refs: ['config/agent_maturity_catalog.json'],
}

const PROMOTION_GATES_FIXTURE = {
  contract: 'agent-maturity-promotion-gates-v1',
  agent_id: 'sentinel',
  maturity_target: 'SHADOW',
  promotable: false,
  blockers: ['Sample size below threshold (122/200).'],
  gates: [
    { gate_id: 'mvl-sample-size', description: 'Minimum reviewed sample size', status: 'OPEN', measured_value: 122, threshold: 200, comparator: '>=' },
    { gate_id: 'healthy-review-evidence', description: 'Independent review health', status: 'NOT_RUN', measured_value: null, threshold: 1, comparator: '>=' },
  ],
}

async function mockReadApis(page: import('@playwright/test').Page, backendOrigin = 'http://127.0.0.1:7777') {
  await page.route('**/api/**', async route => {
    const url = route.request().url()
    if (url.includes('/agent-runtime/readiness')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(READINESS_FIXTURE) })
      return
    }
    if (url.includes('/agent-maturity/sentinel/promotion-gates')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PROMOTION_GATES_FIXTURE) })
      return
    }
    if (url.endsWith('/agent-maturity') || url.includes('/agent-maturity?')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MATURITY_FIXTURE) })
      return
    }
    if (url.includes('/agent-runtime/runs')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract: 'agent-runtime-command-center-read-api-v1',
          read_only: true,
          connected: true,
          kind: 'runs',
          data: [{ agent_id: 'sentinel', status: 'COMPLETED', run_id: 'run_25e7ac15ac1244b0b4c4a7b971833081' }],
        }),
      })
      return
    }
    const backendUrl = url.replace(/^https?:\/\/[^/]+/, backendOrigin)
    const response = await route.fetch({ url: backendUrl })
    await route.fulfill({ response })
  })
}

test.describe('Agent Runtime Hub — approval screenshots', () => {
  test.setTimeout(120_000)

  test('runtime hub overview, wiring, maturity expanded', async ({ page }) => {
    fs.mkdirSync(OUT, { recursive: true })
    page.setViewportSize({ width: 1920, height: 1080 })

    await mockReadApis(page)

    await page.goto('/v3/agents', { waitUntil: 'domcontentloaded', timeout: 90_000 })
    await page.waitForTimeout(8000)

    await page.screenshot({
      path: path.join(OUT, '01-runtime-hub-overview.png'),
      fullPage: true,
    })

    const wiring = page.getByText('Operator wiring').first()
    await wiring.scrollIntoViewIfNeeded()
      await page.waitForTimeout(400)
    await page.screenshot({
      path: path.join(OUT, '02-operator-wiring-panel.png'),
      fullPage: false,
    })

    const maturity = page.getByText('Maturity scoreboard').first()
    await maturity.scrollIntoViewIfNeeded()
      await page.waitForTimeout(400)
    await page.screenshot({
      path: path.join(OUT, '03-maturity-scoreboard.png'),
      fullPage: false,
    })

    const sentinelRow = page.locator('table tbody tr').filter({ hasText: /sentinel/i }).first()
    if (await sentinelRow.count()) {
      await sentinelRow.click()
      await page.waitForTimeout(800)
      await page.screenshot({
        path: path.join(OUT, '04-sentinel-row-expanded.png'),
        fullPage: false,
      })

      const copyBtn = page.getByRole('button', { name: /Copy LAB run command/i })
      if (await copyBtn.count()) {
        await copyBtn.scrollIntoViewIfNeeded()
        await page.waitForTimeout(300)
        await page.screenshot({
          path: path.join(OUT, '05-copy-lab-run-command.png'),
          fullPage: false,
        })
      }
    }

    const files = fs.readdirSync(OUT).filter(f => f.endsWith('.png'))
    console.log('approval screenshots:', files.join(', '))
    expect(files.length).toBeGreaterThanOrEqual(1)
  })
})
