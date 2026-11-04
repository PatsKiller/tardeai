// node --experimental-strip-types --import ./src/lib/tsxRegister.mjs src/lib/whatsHappening.render.test.mjs
//
// Row 78 — the operator-approved "What's happening" card, RENDERED. His one condition was that it match the site's
// design colours, so the assertions below read the rendered markup for the TOKEN variables and refuse literals.
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

const { WhatsHappeningCard } = await import('../components/WhatsHappeningCard.tsx')
const { counters, topRows, STATE_TONE, STATE_LABEL, PHONE_COLUMNS, WIDE_COLUMNS } = await import('./whatsHappening.ts')
const { TONES } = await import('./designTokens.ts')
const TONES_ENUM = { in_progress: 'info', verifying: 'ai', in_review: 'warning', waiting_on_you: 'elevated', done: 'success', p0: 'danger' }

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }
const html = (props) => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(WhatsHappeningCard, props)))

const item = (over = {}) => ({ id: 'x', title: 'A plain sentence about the work', state: 'in_progress', owner: 'cc4', eta: '18:00', updated_at: '2026-11-04T14:00:00Z', source: 'board', ...over })
const EIGHT = ['p0','waiting_on_you','in_review','verifying','in_progress','done','in_progress','in_progress','in_progress','in_progress']
  .map((s, i) => item({ id: `i${i}`, state: s, title: `Item ${i}` }))
const ANSWERED = { answered: true, reason: null }

const wide = html({ census: ANSWERED, feed: EIGHT })
const phone = html({ census: ANSWERED, feed: EIGHT, compact: true })

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
check('every state maps to a designTokens tone', Object.values(STATE_TONE).every(t => TONES.includes(t)))
check('the six approved state tones are unchanged', ['in_progress','verifying','in_review','waiting_on_you','done','p0'].every(st => STATE_TONE[st] === TONES_ENUM[st]))
check('an unknown row is neutral, not coloured like work', STATE_TONE.unknown === 'neutral')

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


// ---- the census verdict (F1 of #2592) drives the card: UNKNOWN is rendered, never an empty confident card ----
const unknownCard = html({ census: { answered: false, reason: 'the source says stale' }, feed: [] })
check('an unanswered census renders the reason, not a confident empty', /Cannot tell what is happening/.test(unknownCard) && /stale/.test(unknownCard))
check('an unanswered census renders the unknown marker', unknownCard.includes('data-state="unknown"'))
check('an unanswered census renders no counter strip', !unknownCard.includes('whats-happening-strip'))
check('an unanswered census still offers See everything', /See everything/.test(unknownCard))
const answeredCard = html({ census: { answered: true, reason: null }, feed: [
  { id: 'a', title: 'A row', state: 'pr_open', owner: 'cc4' },
  { id: 'b', title: 'Another', state: 'merged', owner: 'cc6' }] })
check('an answered census renders rows', answeredCard.includes('wh-row-a') && answeredCard.includes('wh-row-b'))
check('served states are mapped to the operator vocabulary', /In review/.test(answeredCard) && /Done/.test(answeredCard))


// ---- F1/F2 (cx-openai-2 at 61042ef9f): no bare-list entry point, and unsupported states are UNKNOWN ------------
const noCensus = html({})
check('F1: NO census renders unknown, never six zeros', noCensus.includes('data-state="unknown"') && !noCensus.includes('whats-happening-strip'))
check('F1: no census explains itself', /Cannot tell what is happening/.test(noCensus))
// F1 in the reviewer's own words: a BARE LIST with no verdict. This is the exact shape that produced six zeros.
const bareList = html({ feed: EIGHT })
check('F1: a bare list with no verdict renders unknown, not six zeros', bareList.includes('data-state="unknown"') && !bareList.includes('whats-happening-strip'), bareList.slice(0, 220))
check('F1: and it does not render a single row from that list', !bareList.includes('wh-row-'))
const nullFeed = html({ census: ANSWERED, feed: null })
check('F1: an answered census with NO row list is unknown, not empty', nullFeed.includes('data-state="unknown"'))
const mixed = html({ census: ANSWERED, feed: [
  { id: 'k', title: 'Known work', state: 'in_review' },
  { id: 'n', title: 'No state recorded', state: null },
  { id: 'i', title: 'Idle', state: 'idle' },
  { id: 's', title: 'Stale', state: 'stale' }] })
check('F2: a null state is NOT counted as in progress', !/Test 0/.test(mixed) || mixed.includes('Not recorded'))
check('F2: unsupported states render as "Not recorded"', (mixed.match(/Not recorded/g) ?? []).length >= 3)
const cellText = (h, st) => {
  const m = h.match(new RegExp(`data-testid="wh-cell-${st}"[^]{0,400}?font-size[^]{0,80}?>([^<]*)<`))
  return m ? m[1].trim() : null
}
check('F2: the in-progress counter is 0 when nothing says in progress', cellText(mixed, 'in_progress') === '0', `in_progress=${cellText(mixed, 'in_progress')}`)
check('F2: the in-review counter still counts the known row', cellText(mixed, 'in_review') === '1', `in_review=${cellText(mixed, 'in_review')}`)
check('F2: the strip keeps the operator-approved six tiles, not a seventh', (mixed.match(/data-testid="wh-cell-/g) ?? []).length === 6)
check('F2: the strip SAYS how many rows it could not count', /3 rows recorded no state/.test(mixed) && mixed.includes('data-testid="wh-unknown-note"'))
const allUnknown = html({ census: ANSWERED, feed: [
  { id: 'a', title: 'One', state: null },
  { id: 'b', title: 'Two', state: 'idle' }] })
check('F1: a list where nothing recorded a state renders unknown, not six zeros', allUnknown.includes('data-state="unknown"') && !allUnknown.includes('whats-happening-strip'), allUnknown.slice(0, 300))
check('F2: known work still renders alongside unknown work', mixed.includes('wh-row-k') && mixed.includes('wh-row-n'))

console.log(`whatsHappening.render: ${pass} passed, ${fail} failed`)
process.exit(fail ? 1 : 0)
