// node --experimental-strip-types src/lib/needsYouCard.render.test.mjs
// Home v008 "Needs you" (design home/v008, operator-approved 2026-11-03). RENDERS the real card and confirm sheet and
// asserts what the operator sees: list / empty / unavailable states, buttons only for closed-list types, the in-page
// confirm (never window.confirm), the blocked state, and each click's receipt or refusal. Synthetic fixtures only.
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

globalThis.window = { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, location: { pathname: '/', search: '', href: 'http://synthetic.invalid/' } }

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
  source = source.replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.split('\n').map(line => {
    if (!/^\s*(import|export)\b/.test(line)) return line
    return line.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
      if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
      let target = resolve(dirname(path), spec)
      const isFile = (p) => existsSync(p) && statSync(p).isFile()
      if (!isFile(target)) target = ['.ts', '.tsx', '.js', '/index.ts', '/index.tsx'].map(s => target + s).find(isFile)
      if (!target) throw new Error(`Missing fixture dependency ${spec}`)
      return `from ${JSON.stringify(compile(target))}`
    })
  }).join('\n')
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const cardPath = join(app, 'src/components/home/NeedsYouCard.tsx')
const { NeedsYouView, ConfirmSheet } = await import(compile(cardPath))

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }
const count = (html, needle) => html.split(needle).length - 1
const h = (el) => renderToStaticMarkup(el)
const noop = () => {}

const item = (over) => ({
  id: 'req-a', type: 'merge_pr', title: 'Merge the synthetic holdings rebuild', why: 'Market hours: agents do not merge.',
  rule: 'Release window', what_happens: 'Merged now and live in about 15 min.', risk: 'Low; one revert undoes it.', undo: 'Revert the merge.',
  facts: { pr: 42, head_sha: '0123456789abcdef0123456789abcdef01234567' }, requester: { session: 'sess-synthetic', actor: 'the lead' },
  created_at: '2026-01-05T17:44:00Z', expires_at: '2026-01-06T17:44:00Z', state: 'open', can_act: true, blocked_reason: null,
  expires_in_seconds: 20 * 3600, ...over,
})
const queue = (items) => ({ schema: 'HomeApprovalsQueue@v1', as_of: '2026-01-05T17:58:00Z', count: items.length, total: items.length, has_more: false,
  empty_text: 'Nothing needs you', items })

// 1. List: three real requests, urgent first, three buttons each, count shown.
const list = h(React.createElement(NeedsYouView, { queue: queue([
  item({ id: 'req-a', created_at: '2026-01-05T17:44:00Z' }),
  item({ id: 'req-b', type: 'install_schedule', title: 'Put the synthetic fixer on its schedule', created_at: '2026-01-05T17:20:00Z' }),
  item({ id: 'req-c', type: 'rerun_ci', title: 'Re-run the failed synthetic test', created_at: '2026-01-05T16:00:00Z', expires_in_seconds: 3600 }),
]), onAct: noop }))
check(/data-state="list"/.test(list), 'list state missing')
check(/>Needs you</.test(list), 'card title "Needs you" missing')
check(/data-testid="needs-you-count"[^>]*>3</.test(list), 'count 3 missing')
check(count(list, 'data-testid="needs-you-request"') === 3, 'expected three requests')
check(list.indexOf('data-id="req-c"') < list.indexOf('data-id="req-a"'), 'urgent request is not first')
check(list.indexOf('data-id="req-a"') < list.indexOf('data-id="req-b"'), 'newest-first order broken after urgent')
check(/>URGENT</.test(list) && />MERGE</.test(list) && />SCHEDULE</.test(list), 'tags missing')
check(count(list, '>Approve<') === 3 && count(list, '>Decline<') === 3 && count(list, '>Ask<') === 3, 'Approve/Decline/Ask must be on every actionable request')
for (const label of ['Why you', 'On approve', 'Risk', 'Undo']) check(list.includes(`>${label}<`), `row "${label}" missing`)
check(list.includes('asked by the lead'), 'who asked missing')
check(list.includes('bound to pr 42 · head sha 0123456'), 'bound facts missing')
check(/min-height:46px/.test(list), 'buttons must be at least 44 px tall')
check(!/Nothing needs you/.test(list), 'list must not say Nothing needs you')

// 2. Empty: small, green, exact words.
const empty = h(React.createElement(NeedsYouView, { queue: queue([]), onAct: noop }))
check(/data-state="empty"/.test(empty) && /data-testid="needs-you-empty"[^>]*>Nothing needs you</.test(empty), 'empty state text missing')
check(/success-color/.test(empty), 'empty state must be green')
check(!/<button/.test(empty) && !/needs-you-request/.test(empty), 'empty state must stay small (no buttons/requests)')

// 3. Unavailable: an unreadable store is NEVER "Nothing needs you".
const down = h(React.createElement(NeedsYouView, { queue: null, error: 'approvals service unavailable', onAct: noop }))
check(/data-state="unavailable"/.test(down) && !/Nothing needs you/.test(down), 'an error must not read as empty')
check(h(React.createElement(NeedsYouView, { queue: null, loading: true, onAct: noop })) === '', 'loading renders nothing (no flash of empty)')

// 4. Types off the closed list never get a button and are not listed.
const odd = h(React.createElement(NeedsYouView, { queue: queue([item({ id: 'req-x', type: 'place_order', title: 'Synthetic forbidden' })]), onAct: noop }))
check(!/Synthetic forbidden/.test(odd) && !/>Approve</.test(odd), 'a non-closed-list type was rendered with buttons')
check(/not on the reviewed action list/.test(odd), 'hidden unknown types must be acknowledged')

// 5. Moved facts / expired: buttons disabled-out with the plain sentence.
const moved = h(React.createElement(NeedsYouView, { queue: queue([item({ can_act: false, blocked_reason: 'The head moved since review.' })]), onAct: noop }))
check(/data-testid="needs-you-blocked"[^>]*>The head moved since review.</.test(moved) && !/>Approve</.test(moved), 'moved facts must replace the buttons')
const exp = h(React.createElement(NeedsYouView, { queue: queue([item({ state: 'expired', can_act: false })]), onAct: noop }))
check(/expired/.test(exp) && !/>Approve</.test(exp), 'expired request must not offer Approve')

// 6. After a click: receipt shown, buttons gone, count drops; refusal keeps the buttons and shows the reason.
const done = h(React.createElement(NeedsYouView, { queue: queue([item({})]), onAct: noop,
  outcomes: { 'req-a': { kind: 'done', text: 'Done ✓ Merged.', receipt: 'abcdef0123456789' } } }))
check(/data-kind="done"/.test(done) && /Done ✓ Merged\./.test(done), 'result text missing')
check(/data-testid="needs-you-receipt"[^>]*>Receipt saved to the coordination log · abcdef012345</.test(done), 'receipt missing')
check(!/>Approve</.test(done) && !/needs-you-count/.test(done), 'a decided request must lose its buttons and its count')
const refused = h(React.createElement(NeedsYouView, { queue: queue([item({})]), onAct: noop,
  outcomes: { 'req-a': { kind: 'refused', code: 'CSRF_REFUSED', text: 'The request did not come from the Command Center page.', receipt: null } } }))
check(/did not come from the Command Center page/.test(refused) && />Approve</.test(refused), 'a retryable refusal must show its reason and keep the buttons')
const changedAfter = h(React.createElement(NeedsYouView, { queue: queue([item({})]), onAct: noop,
  outcomes: { 'req-a': { kind: 'refused', code: 'CHANGED', text: 'This card changed.', receipt: null, blocked: 'This card changed.' } },
  blocked: { 'req-a': 'This card changed.' } }))
check(!/>Approve</.test(changedAfter) && /needs-you-blocked/.test(changedAfter), 'CHANGED must disable the buttons')

// 7. Confirm sheet: built into the page, no window.confirm; blocked; question.
const sheet = (over) => h(React.createElement(ConfirmSheet, { sheet: { item: item({}), verb: 'approve', phase: 'confirm', binding: 'bind-1', reason: null, note: '', ...over },
  onCancel: noop, onConfirm: noop, onNote: noop }))
const ap = sheet({})
check(/role="dialog"/.test(ap) && /aria-modal="true"/.test(ap), 'sheet must be a modal dialog')
check(/Approve: Merge the synthetic holdings rebuild\?/.test(ap), 'sheet title missing')
check(/>Yes, approve</.test(ap) && />Cancel</.test(ap), 'sheet buttons missing')
check(/Agents can ask, but they can never approve/.test(ap), 'operator-only sentence missing')
const checking = sheet({ phase: 'checking' })
check(/Checking that nothing changed/.test(checking) && !/Yes, approve/.test(checking), 'no confirm button until revalidated')
const blk = sheet({ phase: 'blocked', reason: 'This changed. The lead will re-ask.' })
check(/needs-you-sheet-blocked[^>]*>This changed\. The lead will re-ask\.</.test(blk) && !/Yes, approve/.test(blk) && />Close</.test(blk), 'blocked sheet wrong')
const dc = sheet({ verb: 'decline' })
check(/Decline: /.test(dc) && />Yes, decline</.test(dc), 'decline sheet wrong')
const ask = sheet({ verb: 'question' })
check(/<textarea/.test(ask) && />Send to the lead</.test(ask) && /disabled=""[^>]*>Send to the lead</.test(ask), 'question sheet must need words before sending')
// 8. The client's closed list equals the server's ACTION_TYPES literal (scripts/lib/home_approvals.py): none invented.
const { CLOSED_ACTIONS } = await import(compile(join(app, 'src/lib/homeApprovals.ts')))
const py = readFileSync(resolve(app, '../../scripts/lib/home_approvals.py'), 'utf8')
const at = py.indexOf('ACTION_TYPES: dict[str, str] = {')
const serverTypes = [...py.slice(at, py.indexOf('}', at)).matchAll(/^\s*"([a-z_0-9]+)":/gm)].map(m => m[1]).sort()
check(at >= 0 && serverTypes.length >= 7, 'server ACTION_TYPES literal not found')
check(JSON.stringify([...CLOSED_ACTIONS].sort()) === JSON.stringify(serverTypes), `client closed list ${[...CLOSED_ACTIONS].sort()} != server ${serverTypes}`)
const src = readFileSync(cardPath, 'utf8')
check(!/window\.confirm|\bconfirm\(/.test(src) && !/\balert\(/.test(src), 'no window.confirm/alert')

if (failed) { console.error(`needsYouCard.render: ${failed} failure(s)`); process.exit(1) }
console.log('needsYouCard.render: ok')
