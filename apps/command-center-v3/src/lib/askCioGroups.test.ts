import { countsText, groupBy, groupedPath, groupedPayload, memoryText, regroupPath, relatedFor, type QuestionGroup } from './askCioGroups.ts'

const eq = (name: string, a: unknown, b: unknown) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${name}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`); console.log(`  [PASS] ${name}`) }

eq('default grouping is Security (approved mockup)', groupBy(new URLSearchParams()), 'security')
eq('unknown grouping falls back to Security', groupBy(new URLSearchParams('group=planet')), 'security')
eq('date grouping from URL', groupBy(new URLSearchParams('group=date')), 'date')
eq('path carries group_by, q and channel', groupedPath('sector', ' tsla ', 'telegram'), '/api/v2/cio/asks?group_by=sector&q=tsla&channel=telegram')
eq('path omits empty q/channel', groupedPath('none', '', ''), '/api/v2/cio/asks?group_by=none')
eq('regroup path', regroupPath('thr_a'), '/api/v2/cio/asks/thr_a/regroup')

const grouped = { group_by: 'security', q: '', channel: null, groups: [], counts: { groups: 0, questions: 0, threads: 0 }, group_bys: [] }
eq('payload accepted for its own request', !!groupedPayload({ ok: true, data: { grouped } }, { group_by: 'security', q: '', channel: '' }), true)
eq('payload for another grouping refused', groupedPayload({ data: { grouped } }, { group_by: 'sector', q: '', channel: '' }), null)
eq('payload for another search refused', groupedPayload({ data: { grouped } }, { group_by: 'security', q: 'x', channel: '' }), null)
eq('server without grouping → null (never invented groups)', groupedPayload({ data: { threads: [] } }, { group_by: 'security', q: '', channel: '' }), null)
eq('related map read from thread response', relatedFor({ data: { related_from_memory: { ask_1: [] } } }), { ask_1: [] })
eq('related read from an already-unwrapped body', relatedFor({ related_from_memory: { ask_2: [] } }), { ask_2: [] })
eq('related absent → empty', relatedFor({ data: {} }), {})

const g = { key: 'k', label: 'TSLA', sub: null, symbol: 'TSLA', security_guid: 'g', questions: [], thread_ids: [], symbols: ['TSLA'],
  counts: { questions: 3, threads: 2, names: 1 }, memory: { last_answer_at: '2026-10-21T02:30:30+00:00', stance: 'HOLD', conviction: 61.4 } } as QuestionGroup
eq('counts text', countsText(g, 'security'), '3 questions · 2 threads')
eq('sector counts names', countsText({ ...g, counts: { questions: 1, threads: 1, names: 3 } }, 'sector'), '1 question · 1 thread · 3 names')
eq('memory text from fields', memoryText(g.memory, () => 'yesterday'), 'Question memory: answer recorded yesterday · Current stance: HOLD · conviction 61')
eq('memory gaps are stated, never invented', memoryText({ last_answer_at: null, stance: null, conviction: null, stance_missing_reason: 'CIO prospect store not live (absent)' }, () => 'x'),
  'Question memory: not measured · Current stance: unavailable — CIO prospect store not live (absent)')
eq('non-security group omits the per-security stance', memoryText({ last_answer_at: null, stance: null, conviction: null }, () => 'x', false), 'Question memory: not measured')

eq('shadow stance never means that saved question memory is missing', memoryText({ last_answer_at: '2031-03-10T12:00:00Z', stance: 'HOLD', conviction: 50, stance_source: 'prospect shadow' }, () => 'yesterday'),
  'Question memory: answer recorded yesterday · Current stance: unavailable (shadow record)')
eq('legacy missing memory is safe', memoryText(undefined as never, () => 'x'), 'Question memory: not measured · Current stance: unavailable')
