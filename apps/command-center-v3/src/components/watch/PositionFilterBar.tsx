/** Position filters for Watch (operator 2026-10-23: "we should be able to filter on this information").
 *  Held / formerly held / never held, last trade result and P/L range, exit cause, exit date, re-entry readiness,
 *  distance to the re-entry trigger, R multiple — plus position sorts. Every value lives in the URL (bookmarkable)
 *  and is sent to the server as-is; the server filters. Each chip's tooltip is the server's own rule
 *  (``position_filters[key].server``) and its count comes from the server facets. */
import { useState, type CSSProperties } from 'react'
import { useSearchParams } from 'react-router-dom'
import { RADIUS, TOKENS, TYPE, chipStyle } from '../../lib/designTokens'
import {
  OPTION_LABEL, POSITION_FILTER_KEYS, POSITION_SORTS, activeCount, chipsFor, toggleOption,
  type Facets, type FilterSpec,
} from '../../lib/watchListsModel'

const RANGES: { key: string; min: string; max: string; unit: string }[] = [
  { key: 'pnl_usd', min: 'pnl_usd_min', max: 'pnl_usd_max', unit: '$' },
  { key: 'pnl_pct', min: 'pnl_pct_min', max: 'pnl_pct_max', unit: '%' },
  { key: 'reentry_dist', min: 'reentry_dist_min', max: 'reentry_dist_max', unit: '%' },
  { key: 'r', min: 'r_min', max: 'r_max', unit: 'R' },
]
const RANGE_LABEL: Record<string, string> = { pnl_usd: 'P/L $', pnl_pct: 'P/L %', reentry_dist: 'To re-entry %', r: 'R' }
const input: CSSProperties = {
  width: 64, fontSize: TYPE.sm, padding: '2px 4px', background: TOKENS.bg[2], color: TOKENS.text[0],
  border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm,
}

export default function PositionFilterBar({ specs, facets, sortable = true, testId = 'position-filters' }: {
  specs?: Record<string, FilterSpec> | null; facets?: Facets | null; sortable?: boolean; testId?: string
}) {
  const [sp, setSp] = useSearchParams()
  const [open, setOpen] = useState(() => activeCount(sp) > 0)
  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(sp)
    for (const [k, v] of Object.entries(patch)) { if (v) next.set(k, v); else next.delete(k) }
    setSp(next, { replace: true })
  }
  const clear = () => {
    const next = new URLSearchParams(sp)
    for (const k of POSITION_FILTER_KEYS) next.delete(k)
    next.delete('psort')
    setSp(next, { replace: true })
  }
  const n = activeCount(sp)
  const multi = (key: string) => {
    const spec = specs?.[key]
    if (!spec) return null
    const cur = sp.get(key) || ''
    const on = new Set(cur.split(',').filter(Boolean))
    const single = spec.kind === 'single'
    return (
      <div key={key} style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }} title={spec.server}>
        <span style={{ fontSize: TYPE.xs, color: TOKENS.text[2], minWidth: 92 }}>{spec.label}</span>
        {chipsFor(key, spec, facets || undefined).map(c => {
          const active = on.has(c.opt)
          return (
            <button key={c.opt} type="button" aria-pressed={active} data-filter={key} data-opt={c.opt}
              title={`${spec.server}. ${c.count} row(s) carry “${c.label}”.`}
              onClick={() => set({ [key]: single ? (active ? '' : c.opt) : toggleOption(cur, c.opt) })}
              style={{ ...chipStyle(active ? 'info' : 'neutral', active ? 'soft' : 'outline', 'sm'), cursor: 'pointer' }}>
              {c.label} <b>{c.count}</b>
            </button>
          )
        })}
      </div>
    )
  }
  return (
    <div data-testid={testId} style={{ border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, background: TOKENS.bg[1], padding: '6px 8px' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
          title="Filter by what happened to your position: held or not, how the last trade went, why it ended, and how close a re-entry is. Filters are applied on the server and kept in the URL."
          style={{ ...chipStyle(n ? 'info' : 'neutral', 'outline', 'sm'), cursor: 'pointer', fontWeight: 700 }}>
          Position filters{n ? ` · ${n} on` : ''} {open ? '▴' : '▾'}
        </button>
        {multi('position')}
        {sortable && (
          <label style={{ fontSize: TYPE.xs, color: TOKENS.text[2], display: 'flex', gap: 4, alignItems: 'center' }}
            title="Position sorts (server side): formerly held first = most recent sell first, then conviction; exit date = most recent sell first; P/L % / P/L $ / R = last round trip, high to low; closest to re-entry = smallest absolute distance to the zone.">
            Sort
            <select value={sp.get('psort') || ''} onChange={e => set({ psort: e.target.value })} style={{ ...input, width: 'auto' }}>
              <option value="">Default</option>
              {POSITION_SORTS.map(s => <option key={s} value={s}>{OPTION_LABEL[s]}</option>)}
            </select>
          </label>
        )}
        {n > 0 && <button type="button" onClick={clear} style={{ ...chipStyle('neutral', 'outline', 'sm'), cursor: 'pointer' }}>Clear position filters</button>}
      </div>
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 }}>
          {['result', 'exit_cause', 'exited_within', 'reentry'].map(multi)}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {RANGES.map(r => (
              <span key={r.key} style={{ display: 'flex', gap: 3, alignItems: 'center', fontSize: TYPE.xs, color: TOKENS.text[2] }}
                title={`${specs?.[r.min]?.server || ''} · ${specs?.[r.max]?.server || ''}`}>
                {RANGE_LABEL[r.key]}
                <input aria-label={`${RANGE_LABEL[r.key]} minimum`} inputMode="decimal" placeholder="min" defaultValue={sp.get(r.min) || ''}
                  onBlur={e => set({ [r.min]: e.target.value.trim() })} style={input} />
                –
                <input aria-label={`${RANGE_LABEL[r.key]} maximum`} inputMode="decimal" placeholder="max" defaultValue={sp.get(r.max) || ''}
                  onBlur={e => set({ [r.max]: e.target.value.trim() })} style={input} />
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
