// Job catalog audit badge (LQ-20261107-506). Synthetic lane ids only.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { jobAuditBadge, N8N_AUDIT_PATH } from './jobCatalogAudit.ts'
import type { N8nCatalogWire } from './n8nCatalog.ts'

const lane = (id: string, verdict: string | null, over: Record<string, unknown> = {}) =>
  ({ lane_id: id, category_key: 'x', mode: 'live', verdict, ...over }) as never
const wire = (lanes: Record<string, unknown>): N8nCatalogWire => ({ lanes } as unknown as N8nCatalogWire)

test('audit not loaded -> no badge (unknown is not "not audited")', () => {
  assert.equal(jobAuditBadge('lane-a', null), null)
  assert.equal(jobAuditBadge('lane-a', {} as N8nCatalogWire), null)
})
test('PASS, PASS_IDLE, FAIL with LQ, UNVERIFIABLE, unaudited', () => {
  const w = wire({
    p: lane('p', 'PASS'), i: lane('i', 'PASS_IDLE'), f: lane('f', 'FAIL_DATA', { work_item: 'LQ-20261107-1', defect: 'stale' }),
    u: lane('u', 'UNVERIFIABLE'),
  })
  assert.equal(jobAuditBadge('p', w)!.label, 'n8n audit: PASS')
  assert.equal(jobAuditBadge('p', w)!.tone, 'success')
  assert.equal(jobAuditBadge('i', w)!.label, 'n8n audit: PASS · weekend idle')
  const f = jobAuditBadge('f', w)!
  assert.equal(f.label, 'n8n audit: FAIL · data'); assert.equal(f.tone, 'danger'); assert.equal(f.lq, 'LQ-20261107-1')
  assert.match(f.tip, /Defect: stale/)
  assert.equal(jobAuditBadge('u', w)!.label, 'n8n audit: UNVERIFIABLE'); assert.equal(jobAuditBadge('u', w)!.tone, 'warning')
  const n = jobAuditBadge('zzz', w)!
  assert.equal(n.state, 'not_audited'); assert.equal(n.label, 'n8n audit: not audited'); assert.equal(n.lq, null); assert.ok(n.tip.length > 20)
})
test('every badge has a tooltip and the audit path is the n8n audit tab', () => {
  assert.equal(N8N_AUDIT_PATH, '/ops/jobs-n8n?tab=catalog')
  const w = wire({ a: lane('a', 'FAIL_RUN'), b: lane('b', 'HALLUCINATION'), c: lane('c', 'WEIRD_NEW') })
  for (const id of ['a', 'b', 'c', 'nope']) assert.ok(jobAuditBadge(id, w)!.tip.length > 0)
})
