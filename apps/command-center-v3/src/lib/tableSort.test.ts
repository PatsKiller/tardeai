// PR2 (2026-09-27): pure sort helpers (plain node, runs in npm build).
import { compareValues, sortRows, nextSort } from './tableSort.ts'
import { fillGuide } from './metricGuide.ts'

function fail(msg: string): never { throw new Error(msg) }
const eq = (a: unknown, b: unknown, m = '') => { if (JSON.stringify(a) !== JSON.stringify(b)) fail(`${m} ${JSON.stringify(a)} != ${JSON.stringify(b)}`) }

const rows = [{ s: 'B', v: 2 }, { s: 'a', v: 10 }, { s: 'C', v: null }, { s: 'c2', v: 2 }]
eq(sortRows(rows, { key: 'v', dir: 'desc' }).map(r => r.s), ['a', 'B', 'c2', 'C'], 'numeric desc, empties last, stable')
eq(sortRows(rows, { key: 'v', dir: 'asc' }).map(r => r.s), ['B', 'c2', 'a', 'C'], 'numeric asc keeps empties last')
eq(sortRows(rows, { key: 's', dir: 'asc' }).map(r => r.s), ['a', 'B', 'C', 'c2'], 'text sort is case-insensitive and numeric-aware')
eq(sortRows(rows, null), rows, 'no sort = original order')
console.log('✓ sortRows numeric/text/empties/stable')

eq(nextSort(null, 'v'), { key: 'v', dir: 'desc' }); eq(nextSort({ key: 'v', dir: 'desc' }, 'v'), { key: 'v', dir: 'asc' })
eq(nextSort({ key: 'v', dir: 'asc' }, 'v'), null); eq(nextSort({ key: 'v', dir: 'asc' }, 's', 'asc'), { key: 's', dir: 'asc' })
console.log('✓ nextSort cycles and switches keys')

if (compareValues('10', '9') <= 0) fail('numeric strings compare as numbers')
if (compareValues(undefined, 1) <= 0) fail('empty sorts after a value')
console.log('✓ compareValues')

eq(fillGuide('POP {pop}% vs floor {floor}%', { pop: 58.7, floor: 52 }), 'POP 58.7% vs floor 52%')
eq(fillGuide('keeps {unknown}', { pop: 1 }), 'keeps {unknown}')
eq(fillGuide(undefined), '')
console.log('✓ fillGuide substitutes payload values only')
