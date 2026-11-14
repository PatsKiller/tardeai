// OPS-C6b finding 1, review -3 F1: the host-file chip must never claim a relation the server did not compute.
// Before this test's fix, `only_in_host_file: null` rendered "host file 104 · all effective" — a comparison nobody
// made. Runs in the CC-v3 build: node --experimental-strip-types src/lib/releasesSchedules.liveChips.test.ts
import { effectiveLiveChip, hostFileChip, type Timeline } from './releasesSchedules.ts'
// No node:assert: CI's tsc has no @types/node (same local-assert pattern as opsControlsN8n.test.ts).
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
const has = (hay: string, needle: string, m: string) => { if (!hay.includes(needle)) fail(`${m}: "${hay}" lacks "${needle}"`) }
const lacks = (hay: string, needle: string, m: string) => { if (hay.includes(needle)) fail(`${m}: "${hay}" claims "${needle}"`) }

function tl(over: Partial<Timeline> = {}): Timeline {
  return {
    horizon_hours: 3, from: '2026-11-14T20:45:00+00:00', to: '2026-11-14T23:45:00+00:00', rows: [], recurring: [],
    rows_total: 0, recurring_total: 0, truncated: false,
    crontab: { source: 'crontab', error: null, active_lines: 286, paused_lines: 5 },
    live_lanes: { status: 'ok', count: 104,
                  role: "host env file (fallback input + paused override), not the relay's live list" },
    effective_live: { status: 'OK', source: 'registry_render', detail: 'ok', count: 134,
                      as_of: '2026-11-14T16:39:57+00:00', render_path: '/rel/N8N_RELAY_LIVE_LANES.json',
                      paused_by_override: [], only_in_host_file: ['maturity-remeasure'], only_effective: ['lane-b'] },
    notes: [], ...over,
  }
}

// 1. The relation computed and non-empty: named, with the lanes in the title.
const uneven = hostFileChip(tl())
eq(uneven.tone, 'warning', 'uneven relation is a warning')
has(uneven.text, 'lists 1 more that the relay ignores', 'uneven relation is named')
has(uneven.title, 'maturity-remeasure', 'the ignored lane is named')

// 2. The relation computed and empty: the only state allowed to say "all effective".
const even = hostFileChip(tl({ effective_live: { ...tl().effective_live!, only_in_host_file: [], count: 104 } }))
eq(even.tone, 'neutral', 'agreement is neutral')
has(even.text, 'host file 104 · all effective', 'computed agreement says so')
has(even.title, "not the relay's live list", 'the host file keeps its role even when it agrees')

// 3. THE FIX: relation NOT computed (the relay list is unknown) -> "not compared", never "all effective".
const unknownRelay = tl({ effective_live: { status: 'UNAVAILABLE', source: null, detail: 'the state root was not named, so the ops pause overrides were not read',
                                            count: null, as_of: null, render_path: '/rel/N8N_RELAY_LIVE_LANES.json',
                                            paused_by_override: null, only_in_host_file: null, only_effective: null } })
const notCompared = hostFileChip(unknownRelay)
has(notCompared.text, 'not compared', 'an uncomputed relation says so')
lacks(notCompared.text, 'all effective', 'an uncomputed relation never claims agreement')
has(notCompared.title, 'could not be compared', 'the title names why')

// 4. Same rule when the relay list IS known but the relation field is absent (older payload).
const missingField = hostFileChip(tl({ effective_live: { ...tl().effective_live!, only_in_host_file: null } }))
has(missingField.text, 'not compared', 'a missing relation is not agreement')
lacks(missingField.text, 'all effective', 'a missing relation never claims agreement')

// 5. The host file itself unreadable: unknown, not agreement, and not a zero.
const noHost = hostFileChip(tl({ live_lanes: { status: 'unavailable', count: null } }))
eq(noHost.tone, 'warning', 'an unreadable host file is a warning')
has(noHost.text, 'UNAVAILABLE', 'an unreadable host file says so')
lacks(noHost.text, 'all effective', 'an unreadable host file never claims agreement')

// 6. Chip 1 is the backend's decision: a number with its source, or UNKNOWN — never a page-side inference.
const eff = effectiveLiveChip(tl())
has(eff.text, 'relay live 134 lanes · release registry render', 'the effective count and source are named')
has(eff.title, 'N8N_RELAY_LIVE_LANES.json', 'the render path is in the title')
has(eff.title, 'rendered', 'the render age is in the title')
const effUnknown = effectiveLiveChip(unknownRelay)
eq(effUnknown.tone, 'warning', 'an unknown relay list is a warning')
has(effUnknown.text, 'relay live UNKNOWN', 'an unknown relay list says UNKNOWN, not 0')
lacks(effUnknown.text, '0 lanes', 'an unknown relay list never reads as zero')

console.log('  [PASS] host-file chip: computed / not-compared / unreadable are three distinct states')
console.log('  [PASS] relay chip: a number with its source, or UNKNOWN')
