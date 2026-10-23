// Ask the CIO fixture — the shapes /api/v2/cio/asks and /api/v2/cio/asks/<thread_id> return
// (scripts/lib/cio_ask_store.py thread projection; scripts/lib/cio_ask_core.py list_threads).
// Shared by src/lib/askCioModel.test.ts and e2e/ask-cio.spec.ts.
import type { Thread, ThreadSummary } from '../lib/askCioModel.ts'

const ANSWER_V1 =
  'TSLA closed at $250.00 on 2026-10-22. The house thesis is neutral.\n\n' +
  'Sizing context — the quantities you named (exposure and risk, not a recommendation):\n' +
  '- 100 TSLA: ≈ $25,000 · 2.5% of portfolio · within the 12% limit\n' +
  '- 1,000 TSLA: ≈ $250,000 · 25.0% of portfolio · over the 12% single-position limit\n\n' +
  'Tracking: TSLA → My Watchlist, catalyst watch, CIO record\n\n' +
  'Thread thr_0123456789abcdef · reply here or open My questions in the Command Center to follow up.\n' +
  'Sources: daily_bars\nREAD_ONLY_ADVISORY'

export const THREAD: Thread = {
  thread_id: 'thr_0123456789abcdef',
  title: '100 or 1,000 TSLA given the SpaceX merger talk?',
  created_at: '2026-10-23T13:00:00Z',
  updated_at: '2026-10-23T15:10:00Z',
  status: 'reanswer',
  channels: ['cc', 'telegram'],
  reanswers: 1,
  entities: [
    { key: '11111111-2222-4333-8444-555555555555', name: 'Tesla', symbol: 'TSLA', kind: 'security',
      tracking: { state: 'tracked', at: '2026-10-23T13:00:01Z' } },
    { key: 'ent_5c1d0f3e-0000-5000-8000-000000000001', name: 'SpaceX', symbol: null, kind: 'private_entity',
      tracking: { state: 'tracked', at: '2026-10-23T13:00:01Z' } },
  ],
  turns: [
    {
      ask_id: 'ask_0123456789abcdef', question: '100 or 1,000 TSLA given the SpaceX merger talk?', channel: 'cc',
      asked_at: '2026-10-23T13:00:00Z', turn_kind: 'ask',
      answers: [
        { version: 1, status: 'quick', depth: 'quick', summary: ANSWER_V1, produced_at: '2026-10-23T13:00:02Z',
          sources: [{ title: 'daily_bars', kind: 'house_store', as_of: '2026-10-23T13:00:02Z' }],
          sizing_context: [
            { symbol: 'TSLA', operator_amount: 100, operator_unit: 'shares', exposure_usd: 25000, pct_of_portfolio: 2.5,
              concentration_limit_pct: 12, over_concentration_limit: false, reference_stop_price: 230,
              reference_stop_basis: 'reference 8% below price (illustrative)', loss_at_reference_usd: 2000 },
            { symbol: 'TSLA', operator_amount: 1000, operator_unit: 'shares', exposure_usd: 250000, pct_of_portfolio: 25,
              concentration_limit_pct: 12, over_concentration_limit: true, reference_stop_price: 230,
              reference_stop_basis: 'reference 8% below price (illustrative)', loss_at_reference_usd: 20000 },
          ],
          confidence: { level: 'medium' }, mbi_guard: { stripped: 0 } },
        { version: 2, status: 'capped', depth: 'deep', produced_at: '2026-10-23T13:00:03Z',
          summary: 'Deep research not run — the research spend cap ($5/day proposed) awaits your approval. The quick answer stands.' },
      ],
    },
    {
      ask_id: 'ask_fedcba9876543210', question: 'what about the downside?', channel: 'telegram',
      asked_at: '2026-10-23T14:00:00Z', turn_kind: 'follow_up',
      answers: [{ version: 1, status: 'quick', depth: 'quick', produced_at: '2026-10-23T14:00:02Z',
        summary: 'Downside: the 52-week low is $180.\nREAD_ONLY_ADVISORY' }],
    },
    {
      ask_id: 'ask_aaaaaaaaaaaaaaaa', question: '100 or 1,000 TSLA given the SpaceX merger talk?', channel: 'event',
      asked_at: '2026-10-23T15:10:00Z', turn_kind: 'reanswer',
      answers: [{ version: 1, status: 'reanswer', depth: 'quick', produced_at: '2026-10-23T15:10:02Z',
        what_changed: 'TSLA filed 8-K (merger agreement) (2026-10-23 15:00 UTC, sec_filing_events)',
        summary: 'What changed: TSLA filed 8-K (merger agreement).\n\nTSLA closed at $262.00.\nREAD_ONLY_ADVISORY' }],
    },
  ],
}

export const LIST: { ok: true; data: { threads: ThreadSummary[]; as_of: string } } = {
  ok: true,
  data: {
    as_of: '2026-10-23T15:11:00Z',
    threads: [
      { thread_id: 'thr_1111111111111111', title: 'Invest in Skydance after Musk’s $1B?', updated_at: '2026-10-23T12:00:00Z',
        status: 'quick', channels: ['telegram'], turns: 1, reanswers: 0,
        entities: [{ key: 'ent_x', name: 'Skydance', symbol: null, kind: 'private_entity', tracking: 'tracked' }],
        last_answer_excerpt: 'Skydance is private; no listed security.' },
      { thread_id: THREAD.thread_id, title: THREAD.title, updated_at: THREAD.updated_at, status: 'reanswer',
        channels: ['cc', 'telegram'], turns: 3, reanswers: 1,
        entities: [{ key: '11111111-2222-4333-8444-555555555555', name: 'Tesla', symbol: 'TSLA', kind: 'security', tracking: 'tracked' }],
        last_answer_excerpt: 'What changed: TSLA filed 8-K (merger agreement).' },
    ],
  },
}

export const ASK_RESPONSE = {
  ok: true,
  data: { ok: true, ask_id: 'ask_0123456789abcdef', thread_id: THREAD.thread_id, answer_text: ANSWER_V1, thread: THREAD },
}
