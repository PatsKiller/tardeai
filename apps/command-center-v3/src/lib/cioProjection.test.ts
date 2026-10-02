import { NOT_IN_PAYLOAD, loadLine, projectionFacts, projectionLabels, projectionRows } from './cioProjection.ts'

function eq(actual: unknown, expected: unknown, msg: string) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${msg}: expected ${JSON.stringify(expected)} got ${JSON.stringify(actual)}`)
  }
}

// Labels come from the payload verbatim; nothing is inferred.
const labels = projectionLabels({
  schema: 'MarketContextState@v1', state: 'SHADOW', truth_quality: 'PARTIAL',
  source_as_of: '2026-10-02T10:00:00Z', composition_as_of: '2026-10-02T10:05:00Z', ok: true,
})
eq(labels.schema, 'MarketContextState@v1', 'schema label')
eq(labels.states, [['state', 'SHADOW'], ['truth_quality', 'PARTIAL']], 'state labels verbatim')
eq(labels.clocks, [['source_as_of', '2026-10-02T10:00:00Z'], ['composition_as_of', '2026-10-02T10:05:00Z']], 'clocks verbatim')

// A block without state or clocks is labelled as such, never upgraded to OK/LIVE.
const bare = projectionLabels({ rows: [] })
eq(bare.schema, NOT_IN_PAYLOAD, 'missing schema is NOT_IN_PAYLOAD')
eq(bare.states, [], 'no invented state')
eq(bare.clocks, [], 'no invented clock')
eq(projectionLabels(null).schema, NOT_IN_PAYLOAD, 'null block')

// Error envelopes keep their error text.
eq(projectionLabels({ ok: false, error: 'TimeoutError' }).error, 'TimeoutError', 'error envelope')

// Facts: scalars verbatim, containers summarised, label fields not repeated.
eq(projectionFacts({ schema: 'X@v1', state: 'LIVE', n: 3, rows: [1, 2], cfg: { a: 1 }, none: null }),
  [['n', '3'], ['rows', '2 items'], ['cfg', '1 fields'], ['none', 'null']], 'facts')

eq(projectionRows([{ symbol: 'AAPL', state: 'PROVISIONAL' }, 'x', null]), ['AAPL · PROVISIONAL', 'x', 'null'], 'rows')

// Loading/error never spin forever.
eq(loadLine({ loading: true, error: null, hasData: false }), 'Loading…', 'loading')
eq(loadLine({ loading: false, error: 'HTTP 500', hasData: false }), 'UNAVAILABLE — HTTP 500', 'error')
eq(loadLine({ loading: false, error: null, hasData: false }), 'NO PAYLOAD', 'empty')
eq(loadLine({ loading: true, error: null, hasData: true }), null, 'data shown while refreshing')

console.log('cioProjection.test.ts: ok')
