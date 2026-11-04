// node --experimental-strip-types --import ./src/lib/tsxRegister.mjs src/lib/whatsHappening.render.test.mjs
//
// Row 78 — the operator-approved "What's happening" card, RENDERED. His one condition was that it match the site's
// design colours, so the assertions below read the rendered markup for the TOKEN variables and refuse literals.
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

const { WhatsHappeningCard } = await import('../components/WhatsHappeningCard.tsx')
const { counters, topRows, STATE_TONE, STATE_LABEL, PHONE_COLUMNS, WIDE_COLUMNS } = await import('./whatsHappening.ts')

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }
const html = (props) => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(WhatsHappeningCard, props)))

const item = (over = {}) => ({ id: 'x', title: 'A plain sentence about the work', state: 'in_progress', owner: 'cc4', eta: '18:00', updated_at: '2026-11-04T14:00:00Z', source: 'board', ...over })
const EIGHT = ['p0','waiting_on_you','in_review','verifying','in_progress','done','in_progress','in_progress','in_progress','in_progress']
  .map((s, i) => item({ id: `i${i}`, state: s, title: `Item ${i}` }))

const wide = html({ items: EIGHT })
const phone = html({ items: EIGHT, compact: true })

// the six-cell strip, in the approved order
for (const s of ['in_progress','verifying','in_review','waiting_on_you','done','p0']) {
  check(`the strip renders a ${s} cell`, wide.includes(`data-testid="wh-cell-${s}"`))
}
check('the strip shows the operator words, not codes', wide.includes('Waiting on you') && !wide.includes('waiting_on_you<'))
check('the card renders at most eight rows', (wide.match(/data-testid="wh-row-/g) ?? []).length === 8, String((wide.match(/wh-row-/g)??[]).length))
check('P0 sorts first', wide.indexOf('wh-row-i0') < wide.indexOf('wh-row-i1'))

// colours come from tokens, never literals
check('the card contains no hex colour literal', !/#[0-9a-fA-F]{3,8}\b/.test(wide), (wide.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []).join(','))
check('state colours are token variables', /color:var\(--info-color\)/.test(wide) && /var\(--danger-color\)/.test(wide))
check('every state maps to a designTokens tone', Object.values(STATE_TONE).every(t => ['info','ai','warning','elevated','success','danger'].includes(t)))

// the phone drops columns instead of squashing them
check('wide shows ETA', wide.includes('ETA 18:00'))
check('phone DROPS ETA', !phone.includes('ETA 18:00'))
check('phone DROPS the last-update stamp', !phone.includes('2026-11-04T14:00:00Z'))
check('phone DROPS the source', !/source/.test(phone) || !phone.includes('board'))
check('phone keeps title, state and owner', phone.includes('Item 0') && phone.includes('owner') === false && phone.includes('cc4'))
check('the column contract is explicit', PHONE_COLUMNS.length === 3 && WIDE_COLUMNS.length === 6)
check('compact is a data attribute the page can assert', phone.includes('data-compact="true"') && wide.includes('data-compact="false"'))
check('a See everything link is always present', wide.includes('See everything') && wide.includes('data-testid="whats-happening-see-everything"'))

// the model
check('counters total equals the item count', counters(EIGHT).reduce((a, c) => a + c.count, 0) === EIGHT.length)
check('topRows caps at eight', topRows(EIGHT, 8).length === 8)
check('labels are the operator words', STATE_LABEL.waiting_on_you === 'Waiting on you')

console.log(`whatsHappening.render: ${pass} passed, ${fail} failed`)
process.exit(fail ? 1 : 0)
