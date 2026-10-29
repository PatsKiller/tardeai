import { test, expect } from '@playwright/test'
import { spawnSync } from 'node:child_process'
import path from 'node:path'

/** Fully intercepted fixtures; no live server, credentials or provider calls. */
test('System Suggests facts and CIO tap flow at 1440, 412 and 390', async ({}, info) => {
  test.setTimeout(120_000)
  const output = process.env.WATCH_SUGGESTS_PROOF_DIR || info.outputPath('synthetic-proof')
  const result = spawnSync(process.execPath, [path.resolve('e2e/watch-system-suggests.fixture.mjs'), output], {
    encoding: 'utf8', timeout: 110_000,
  })
  expect(result.status, result.stderr || result.error?.message).toBe(0)
  const rows = JSON.parse(result.stdout.trim())
  expect(rows.map((r: { width: number }) => r.width)).toEqual([1440, 412, 390])
  expect(rows.every((r: { status: string }) => r.status === 'PASS')).toBe(true)
})
