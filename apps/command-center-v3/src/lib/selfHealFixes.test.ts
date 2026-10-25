const assert = {
  equal(actual: unknown, expected: unknown, message = 'expected equality') { if (actual !== expected) throw new Error(`${message}: ${String(actual)} !== ${String(expected)}`) },
  match(value: string, pattern: RegExp) { if (!pattern.test(value)) throw new Error(`expected ${value} to match ${pattern}`) },
}
import { costText, monitorLine, outcomeLabel, remediationLabel, shortSha, sourceLabel, type SelfHealFixesWire } from './selfHealFixes.ts'

assert.equal(outcomeLabel('fixed-released').tone, 'success')
assert.equal(outcomeLabel('gave-up').tone, 'danger')
assert.equal(outcomeLabel('shadow-proposed').label, 'Proposed (shadow)')
assert.match(outcomeLabel('new-thing').label, /Unknown \(new-thing\)/)
assert.equal(outcomeLabel(null).tone, 'warning')
assert.equal(sourceLabel('ci'), 'Main CI')
assert.equal(remediationLabel('deterministic:ci_infra_flake_rerun'), 'Deterministic: ci infra flake rerun')
assert.equal(remediationLabel('refused:broker_active_trader'), 'Refused scope: broker active trader')
assert.equal(remediationLabel('claude_code'), 'Claude Code fix PR')
assert.equal(costText(null), 'no model cost')
assert.equal(costText(3.256), '$3.26')
assert.equal(shortSha('abcdef0123456789'), 'abcdef012')

const base: SelfHealFixesWire = {
  schema: 'SelfHealFixes@v1', as_of: '2026-10-25T20:00:00Z', status: 'OK', reason: null, source: 'data/self_heal/fix_log.jsonl',
  monitor: { mode: 'shadow', ok_at: '2026-10-25T19:58:00Z', stale: false, policy_why: 'AGENTS.md 20.2.0 < 20.4.0', ci: 'GREEN' },
  summary: { total: 0, open: 0, fixed: 0, escalated: 0, proposed: 0, model_cost_usd: 0 },
  rows: [], total: 0, offset: 0, limit: 50, has_more: false, history: null,
}
assert.match(monitorLine(base).text, /SHADOW/)
assert.equal(monitorLine({ ...base, monitor: { ...base.monitor, stale: true } }).tone, 'warning')
assert.equal(monitorLine({ ...base, monitor: { ...base.monitor, ok_at: null } }).text, 'Monitor has not run (no heartbeat)')
assert.equal(monitorLine({ ...base, monitor: { ...base.monitor, mode: 'live' } }).tone, 'success')
assert.equal(monitorLine(null).tone, 'warning')
console.log('selfHealFixes.test.ts ok')
