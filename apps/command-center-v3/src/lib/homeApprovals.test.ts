// node --experimental-strip-types src/lib/homeApprovals.test.ts
// Home v008 "Needs you": the client model and the request shape the HTTP edge (scripts/lib/home_approvals_api.py)
// requires. Synthetic fixtures only (the repo is public). No node:* imports: CI's tsc has no @types/node; the parity
// check against the server's ACTION_TYPES literal lives in needsYouCard.render.test.mjs.
import {
  CLOSED_ACTIONS, HOME_APPROVALS, URGENT_SECONDS, askedBy, blockedText, boundFacts, fetchForConfirm, isClosedAction, needsYouList,
  outcomeFrom, postDecision, titledWithCount, CHANGED_TEXT, EXPIRED_TEXT, type NeedsYouItem,
} from './homeApprovals.ts'
declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

// ── Forbidden actions are never buttons (parity with the server literal: needsYouCard.render.test.mjs) ─────────
check('the closed list has the eight reviewed types', CLOSED_ACTIONS.length === 8 && new Set(CLOSED_ACTIONS).size === 8)
for (const forbidden of ['place_order', 'broker_order', 'set_stop', 'size', 'credential', 'live_flag', 'force_push', 'delete_repo', 'shell', 'command']) {
  check(`forbidden action "${forbidden}" is not a button`, !isClosedAction(forbidden))
}

// ── Ordering: only real decisions; urgent first, then newest ───────────────────────────────────────────────────────
const base = (over: Partial<NeedsYouItem>): NeedsYouItem => ({
  id: 'r', type: 'merge_pr', title: 'Synthetic', state: 'open', can_act: true, created_at: '2026-01-02T12:00:00Z',
  expires_in_seconds: 20 * 3600, facts: { pr: 1, head_sha: 'a'.repeat(40) }, requester: { session: 's-1', actor: 'the lead' }, ...over,
})
const q = {
  count: 6, total: 6, items: [
    base({ id: 'old', created_at: '2026-01-02T10:00:00Z' }),
    base({ id: 'new', created_at: '2026-01-02T12:30:00Z' }),
    base({ id: 'urgent-old', created_at: '2026-01-02T08:00:00Z', expires_in_seconds: URGENT_SECONDS - 60 }),
    base({ id: 'unknown', type: 'run_shell' }),
    base({ id: 'done', state: 'executed' }),
    base({ id: 'exp', state: 'expired', created_at: '2026-01-02T09:00:00Z' }),
  ],
}
const listed = needsYouList(q)
check('urgent item is first even though oldest', listed.items[0]?.id === 'urgent-old')
check('then newest first', listed.items.map(i => i.id).join(',') === 'urgent-old,new,old,exp')
check('a type off the closed list is never listed', !listed.items.some(i => i.id === 'unknown') && listed.hiddenUnknown === 1)
check('a decided (executed) request is not listed', !listed.items.some(i => i.id === 'done'))
check('empty/absent queue → no items', needsYouList(null).items.length === 0 && needsYouList({ count: 0, total: 0, items: [] }).items.length === 0)

// ── Labels ─────────────────────────────────────────────────────────────────────────────────────────────────────────
check('asked by uses the actor', askedBy({ session: 's-1', actor: 'the lead' }) === 'asked by the lead')
check('asked by falls back honestly', askedBy(null) === 'asker not recorded')
check('bound facts shorten a full sha', boundFacts({ pr: 7, head_sha: 'b'.repeat(40) }) === `bound to pr 7 · head sha bbbbbbb`)
check('no facts → no line', boundFacts(null) === '' && boundFacts({}) === '')
check('expired item says re-ask', blockedText(base({ state: 'expired' })) === EXPIRED_TEXT)
check('moved fact shows the server sentence', blockedText(base({ blocked_reason: 'The head moved.' })) === 'The head moved.')
check('can_act false without reason → changed text', blockedText(base({ can_act: false })) === CHANGED_TEXT)
check('actionable item has no block', blockedText(base({})) === null)
check('title count added', titledWithCount('Command Center v3', 3) === '(3) Command Center v3')
check('title count replaced, not stacked', titledWithCount('(3) Command Center v3', 1) === '(1) Command Center v3')
check('title count removed at zero', titledWithCount('(2) Command Center v3', 0) === 'Command Center v3')

// ── Responses, exactly as home_approvals_api._decision_response / _store_error shape them ─────────────────────────
const executed = outcomeFrom('approve', 200, { ok: true, data: { state: 'executed', outcome: 'executed', receipt: 'c'.repeat(64), result: { ok: true, plain: 'Merged.' } } })
check('200 executed → done with the server words and receipt', executed.kind === 'done' && executed.text.includes('Merged.') && executed.receipt === 'c'.repeat(64))
const pending = outcomeFrom('approve', 202, { ok: true, data: { state: 'executing', outcome: 'uncertain', receipt: 'd'.repeat(64) } })
check('202 uncertain → pending, never "done"', pending.kind === 'pending' && !pending.text.includes('Done'))
const declined = outcomeFrom('decline', 200, { ok: true, data: { state: 'declined', outcome: 'declined', receipt: 'e'.repeat(64) } })
check('decline → declined with receipt', declined.kind === 'declined' && declined.receipt === 'e'.repeat(64))
const failed = outcomeFrom('approve', 502, { ok: false, code: 'ACTION_FAILED', reason: 'The merge was refused: head moved.', data: { receipt: 'f'.repeat(64) } })
check('502 ACTION_FAILED → failed with the reason verbatim', failed.kind === 'failed' && failed.text === 'The merge was refused: head moved.')
const changed = outcomeFrom('approve', 409, { ok: false, code: 'CHANGED', reason: 'This card changed.', blocked_reason: 'This card changed.', state: 'open' })
check('409 CHANGED → refused and blocks the buttons', changed.kind === 'refused' && changed.blocked === 'This card changed.')
const expired = outcomeFrom('approve', 410, { ok: false, code: 'EXPIRED', reason: 'This request expired.', state: 'expired', reask_requested: true })
check('410 EXPIRED → refused, marked expired', expired.kind === 'refused' && expired.expired === true)
const self = outcomeFrom('approve', 403, { ok: false, code: 'SELF_APPROVAL_REFUSED', reason: 'The session that asked cannot also decide.' })
check('403 self-approval → refusal shown verbatim', self.kind === 'refused' && self.code === 'SELF_APPROVAL_REFUSED' && self.text.startsWith('The session that asked'))
const net = outcomeFrom('approve', 0, null)
check('no answer → plain "nothing was decided"', net.kind === 'refused' && /nothing was decided/.test(net.text))
check('question delivered', outcomeFrom('question', 200, { ok: true, data: { delivered: true } }).text === 'Note sent to the lead ✓')
check('question saved but not delivered says so', /could not be put in the lead/.test(outcomeFrom('question', 200, { ok: true, data: { delivered: false } }).text))

// ── Request shape: same-origin JSON POST with the binding (what cc_auth.command_csrf_check requires) ───────────────
type Call = { url: string; init?: RequestInit }
function fakeFetch(status: number, body: unknown, calls: Call[]) {
  return async (url: string, init?: RequestInit) => { calls.push({ url, init }); return { status, json: async () => body } }
}
const calls: Call[] = []
await postDecision('req-1', 'approve', { binding: 'b1' }, fakeFetch(200, { ok: true, data: { outcome: 'executed', receipt: 'r' } }, calls))
const c0 = calls[0]
check('approve posts to /<id>/approve', c0.url === `${HOME_APPROVALS}/req-1/approve`)
check('approve is a POST', c0.init?.method === 'POST')
check('credentials same-origin', c0.init?.credentials === 'same-origin')
check('Content-Type application/json', (c0.init?.headers as Record<string, string>)['Content-Type'] === 'application/json')
check('body carries the binding and nothing else', c0.init?.body === JSON.stringify({ binding: 'b1' }))
await postDecision('req-1', 'question', { note: 'Why now?' }, fakeFetch(200, { ok: true, data: { delivered: true } }, calls))
check('question posts the note to /<id>/question', calls[1].url === `${HOME_APPROVALS}/req-1/question` && calls[1].init?.body === JSON.stringify({ note: 'Why now?' }))
const bad = await postDecision('../evil', 'approve', { binding: 'b' }, fakeFetch(200, {}, calls))
check('an unsafe id is never sent', bad.kind === 'refused' && calls.length === 2)
const thrown = await postDecision('req-2', 'approve', { binding: 'b' }, async () => { throw new Error('offline') })
check('a network failure resolves to a refusal, never throws', thrown.kind === 'refused')

const confirmCalls: Call[] = []
const conf = await fetchForConfirm('req-1', fakeFetch(200, { ok: true, data: { id: 'req-1', binding: 'b1', can_act: true } }, confirmCalls))
check('confirm sheet reads one request with revalidate=1', confirmCalls[0].url === `${HOME_APPROVALS}/req-1?revalidate=1` && conf.item?.binding === 'b1')
check('confirm read is a GET (no method)', confirmCalls[0].init?.method === undefined)
const confErr = await fetchForConfirm('req-1', fakeFetch(404, { ok: false, code: 'NOT_FOUND', reason: 'That request does not exist.' }, []))
check('confirm read error surfaces the server reason', confErr.item === null && confErr.error === 'That request does not exist.')

console.log(`homeApprovals: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
