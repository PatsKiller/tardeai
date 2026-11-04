// node --experimental-strip-types --import ./src/testharness/tsxRegister.mjs src/lib/healthFindingCard.render.test.mjs
//
// FQ-038: a health finding must open with what a person needs, and keep the implementation detail behind a toggle.
// The audit's phone screenshot was a wall of expanded cards: paths, unit names, raw codes and repair commands.
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'

const { HealthFindingCard, findingDetail } = await import('../components/HealthFindingCard.tsx')

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

const F = { message: 'The disk hygiene job did not run', why: 'unit tradeai-disk-hygiene.service exited 1 (/home/johnclaw/scripts/x.py:44)',
  recommended_action: 'systemctl --user restart tradeai-disk-hygiene.service', severity: 'warning', category: 'jobs',
  detected_by: 'health_agent', detected_at: '2026-11-04T10:00:00Z',
  remediation: { status: 'unresolved', detail: 'rc=1 stderr=/var/log/tradeai/x.log' } }

const closed = renderToStaticMarkup(React.createElement(HealthFindingCard, { finding: F }))
const compact = renderToStaticMarkup(React.createElement(HealthFindingCard, { finding: F, compact: true }))

check('the plain sentence is visible', closed.includes('The disk hygiene job did not run'))
check('the severity and status are visible', /warning/i.test(closed) && /unresolved/.test(closed))
check('the toggle exists and starts CLOSED', closed.includes('data-testid="health-finding-toggle"') && closed.includes('aria-expanded="false"'))
check('the implementation detail is NOT in the closed card', !closed.includes('systemctl --user restart'))
check('nor the file path', !closed.includes('/home/johnclaw/scripts/x.py'))
check('nor the rc/errno detail', !closed.includes('rc=1'))
check('the card says what the toggle will show', /Why, and what to do/.test(closed))
check('on a phone the card drops the "seen by" line', !compact.includes('Seen by') && closed.includes('Seen by'))
check('the phone still shows the sentence', compact.includes('The disk hygiene job did not run'))
check('a finding with no detail renders no toggle', !renderToStaticMarkup(React.createElement(HealthFindingCard, { finding: { message: 'x' } })).includes('health-finding-toggle'))
check('detail extraction keeps every field', (() => { const d = findingDetail(F); return d.why && d.action && d.detail })())
check('the card carries a machine severity marker', closed.includes('data-severity="warning"'))
check('no hex literal is rendered', !/#[0-9a-fA-F]{3,8}\b/.test(closed))


// ---- the mount contract: the /health hub owns the drill-down and the action buttons, the card must keep both ----
const mountable = renderToStaticMarkup(React.createElement(HealthFindingCard, { finding: F, onOpen: () => {} },
  React.createElement('button', { 'data-testid': 'page-fix-now' }, 'Fix now')))
check('a card with a drill handler is marked openable', mountable.includes('data-openable="true"'))
check('the page\'s own action button is rendered, not re-implemented', mountable.includes('page-fix-now'))
const readOnly = renderToStaticMarkup(React.createElement(HealthFindingCard, { finding: F }))
check('a read-only card says so, and has no empty action row', readOnly.includes('data-openable="false"') && !readOnly.includes('health-finding-actions'))

console.log(`healthFindingCard.render: ${pass} passed, ${fail} failed`)
process.exit(fail ? 1 : 0)
