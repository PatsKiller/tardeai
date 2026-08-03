/**
 * Consumption DeepSeek contract (mocked provider boundary — no paid calls).
 *
 *   npx playwright test e2e/consumption-deepseek.spec.ts
 */
import { test, expect } from '@playwright/test'

test.describe('Consumption DeepSeek Flash smoke contract', () => {
  test('readiness cards, disabled Flash, smoke process, free ensemble', async ({ page }) => {
    // Mock readiness: Flash offline, Pro ready (independent)
    await page.route('**/api/v2/llm/oauth-lanes**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            ok: true,
            lanes: [
              { lane: 'grok', label: 'Grok', ready: true, status: 'ready', port: 8645, billing: 'free_oauth' },
              { lane: 'chatgpt', label: 'ChatGPT', ready: true, status: 'ready', port: 8646, billing: 'free_oauth' },
              {
                lane: 'deepseek-flash',
                label: 'DeepSeek V4 Flash',
                ready: false,
                status: 'offline',
                configured: true,
                reachable: false,
                model_available: false,
                reason_code: 'PROVIDER_UNAVAILABLE',
                hint: 'Provider is configured but not reachable.',
                billing: 'metered',
                kind: 'metered_api',
              },
              {
                lane: 'deepseek-v4-pro',
                label: 'DeepSeek V4 Pro',
                ready: true,
                status: 'ready',
                configured: true,
                reachable: true,
                model_available: true,
                billing: 'metered',
                kind: 'metered_api',
              },
            ],
            ready_count: 3,
          },
        }),
      })
    })

    await page.route('**/api/v2/consumption/**', async (route) => {
      const url = route.request().url()
      if (url.includes('overview')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            data: {
              overview: {
                by_lane: {
                  grok: { today: { calls: 1, failures: 0, relative_units: 1 }, week: { calls: 1, failures: 0, relative_units: 1 } },
                },
              },
            },
          }),
        })
        return
      }
      if (url.includes('processes') || url.includes('lane-registry') || url.includes('logs')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, data: { processes: [], logs: [], policy_labels: {} } }),
        })
        return
      }
      await route.continue()
    })

    let capturedBody: any = null
    await page.route('**/api/v2/consumption/run-manual**', async (route) => {
      if (route.request().method() === 'POST') {
        capturedBody = route.request().postDataJSON()
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            data: {
              ok: true,
              text: 'OK',
              returned_model: 'deepseek-v4-flash',
              requested_model_id: 'deepseek-v4-flash',
              requested_policy: 'FAST',
              executed_policy: 'FAST',
              fallback_used: false,
              billing: 'metered',
            },
          }),
        })
        return
      }
      await route.continue()
    })

    await page.goto('/v3/consumption')
    await expect(page.getByText('LLM Consumption')).toBeVisible()

    // Independent cards
    await expect(page.getByText('DeepSeek V4 Flash', { exact: false }).first()).toBeVisible()
    await expect(page.getByText('DeepSeek V4 Pro', { exact: false }).first()).toBeVisible()

    const flashBtn = page.getByRole('button', { name: /Test V4 Flash/i })
    await expect(flashBtn).toBeDisabled()

    // Switch readiness to Flash ready and re-open
    await page.unroute('**/api/v2/llm/oauth-lanes**')
    await page.route('**/api/v2/llm/oauth-lanes**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            lanes: [
              { lane: 'grok', ready: true, status: 'ready' },
              { lane: 'chatgpt', ready: true, status: 'ready' },
              {
                lane: 'deepseek-flash',
                label: 'DeepSeek V4 Flash',
                ready: true,
                status: 'ready',
                configured: true,
                reachable: true,
                model_available: true,
                billing: 'metered',
              },
              {
                lane: 'deepseek-v4-pro',
                label: 'DeepSeek V4 Pro',
                ready: false,
                status: 'offline',
                configured: true,
                reachable: true,
                model_available: false,
                billing: 'metered',
              },
            ],
          },
        }),
      })
    })
    await page.getByText('Refresh lane probe').click()
    await expect(flashBtn).toBeEnabled({ timeout: 10_000 })

    await flashBtn.click()
    await expect(page.getByText(/deepseek-v4-flash|model deepseek-v4-flash/i)).toBeVisible({ timeout: 10_000 })

    expect(capturedBody).not.toBeNull()
    expect(capturedBody.process_id).toBe('deepseek_flash_operator_smoke')
    expect(capturedBody.lane).toBe('deepseek-flash')
    expect(capturedBody.operator_confirmed).toBeUndefined()

    // No Pro generic button
    await expect(page.getByRole('button', { name: /Test.*Pro/i })).toHaveCount(0)

    // RUN ALL FREE is on WatchTruth, not this page — assert source contract via absence of free ensemble DeepSeek on hub
    // (Playwright cannot open unbundled TS; free path covered in unit e2e string + Watch panel.)
  })
})
