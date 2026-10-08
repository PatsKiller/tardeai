/** Watch → Opportunities — the ranking engine (operator 2026-10-08): "filter 500+ opportunities down to the top 5
 *  highest-conviction decisions in under 30 seconds". Curated ranking from CIO memory via /api/v3/opportunities;
 *  presets + global filters + sort; click a row → the opportunity modal. */
import { useMemo, type CSSProperties } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { RADIUS, TOKENS, numStyle } from '../lib/designTokens'
import { tint } from '../components/comms/CommsHubParts'
import { useOpenSymbol } from '../components/opportunity/OpportunityContext'
import { condLabel, convictionColor, money, pct, typeLabel } from '../components/opportunity/format'

const MUTED = 'var(--text3)'
const TEXT = 'var(--text0)'
const TEXT2 = 'var(--text2)'
const BORDER = 'var(--border)'

const PRESETS: [string, string][] = [['top5', 'Top 5 high-conviction'], ['new', 'New positions'], ['re_entry', 'Re-entry'], ['add_on', 'Add-on'], ['exit', 'Exit candidates']]
const FILTERS: { key: string; label: string; opts: [string, string][] }[] = [
  { key: 'type', label: 'Opportunity type', opts: [['', 'Any'], ['new_position', 'New Position'], ['existing', 'Existing Position'], ['re_entry', 'Re-Entry'], ['add_on', 'Add-On'], ['exit_candidate', 'Exit Candidate'], ['watchlist', 'Watchlist']] },
  { key: 'min_conviction', label: 'Conviction', opts: [['', 'Any'], ['90', '90+'], ['80', '80+'], ['70', '70+'], ['60', '60+']] },
  { key: 'min_rr', label: 'Risk/Reward', opts: [['', 'Any'], ['1.5', '1.5x+'], ['2', '2.0x+'], ['3', '3.0x+'], ['5', '5.0x+']] },
  { key: 'min_upside', label: 'Analyst upside', opts: [['', 'Any'], ['10', '10%+'], ['20', '20%+'], ['30', '30%+'], ['50', '50%+']] },
  { key: 'technical_condition', label: 'Technical', opts: [['', 'Any'], ['breaking_out', 'Breaking Out'], ['pullback', 'Pullback'], ['oversold', 'Oversold'], ['overbought', 'Overbought'], ['trend_continuation', 'Trend Continuation'], ['range', 'Range-bound']] },
  { key: 'cap_band', label: 'Market cap', opts: [['', 'Any'], ['mega', 'Mega'], ['large', 'Large'], ['mid', 'Mid'], ['small', 'Small']] },
  { key: 'position_status', label: 'Position', opts: [['', 'Any'], ['owned', 'Owned'], ['not_owned', 'Not Owned'], ['recently_sold', 'Recently Sold'], ['watchlist', 'Watchlist']] },
]
const SORTS: [string, string][] = [['conviction', 'Conviction'], ['rr', 'Risk/Reward'], ['upside', 'Analyst upside'], ['reward_pct', 'Reward %'], ['risk_pct', 'Lowest risk %'], ['momentum', 'Momentum'], ['rank', 'Rank']]
const KEYS = ['preset', 'sort', 'sector', 'q', 'limit', ...FILTERS.map(f => f.key)]

const sel: CSSProperties = { fontSize: 11, padding: '4px 6px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, color: TEXT, borderRadius: RADIUS.sm }

export default function OpportunitiesHub() {
  const [sp, setSp] = useSearchParams()
  const open = useOpenSymbol()
  const q = useMemo(() => Object.fromEntries(KEYS.map(k => [k, sp.get(k) || '']).filter(([, v]) => v)), [sp])
  const qs = new URLSearchParams({ limit: '50', ...q }).toString()
  const { data, loading, error } = useApi<any>(`/api/v3/opportunities?${qs}`, 120_000)
  const body = data?.data && data.data.items ? data.data : data
  const items: any[] = body?.items || []
  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(sp)
    for (const [k, v] of Object.entries(patch)) { if (v) next.set(k, v); else next.delete(k) }
    setSp(next, { replace: true })
  }
  const clear = () => { const next = new URLSearchParams(sp); for (const k of KEYS) next.delete(k); setSp(next, { replace: true }) }
  const sectors = Object.keys(body?.facets?.sector || {}).sort()

  return (
    <div data-opportunities-hub>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', margin: '8px 0' }}>
        <div style={{ fontSize: 12, color: TEXT2 }}>
          <b style={{ color: TEXT }}>{body?.total ?? '—'}</b> of {body?.universe ?? '—'} opportunities
          {body?.as_of ? <span style={{ color: MUTED }}> · curated by the CIO {new Date(body.as_of).toLocaleString()}</span> : null}
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {PRESETS.map(([id, label]) => {
            const on = sp.get('preset') === id
            return (
              <button key={id} type="button" data-preset={id} onClick={() => set({ preset: on ? '' : id })}
                style={{ fontSize: 11, padding: '4px 10px', borderRadius: RADIUS.pill, cursor: 'pointer', fontWeight: 700,
                  border: `1px solid ${on ? TOKENS.success : BORDER}`, background: on ? tint(TOKENS.success) : 'transparent', color: TEXT }}>
                {label}
              </button>
            )
          })}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end', padding: 10, border: `1px solid ${BORDER}`, borderRadius: RADIUS.md, background: 'var(--bg1)', marginBottom: 10 }} data-opportunity-filters>
        {FILTERS.map(f => (
          <label key={f.key} style={{ display: 'grid', gap: 2, fontSize: 10, color: MUTED }}>
            {f.label}
            <select value={sp.get(f.key) || ''} onChange={e => set({ [f.key]: e.target.value })} style={sel}>
              {f.opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        ))}
        <label style={{ display: 'grid', gap: 2, fontSize: 10, color: MUTED }}>
          Sector
          <select value={sp.get('sector') || ''} onChange={e => set({ sector: e.target.value })} style={sel}>
            <option value="">Any</option>
            {sectors.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label style={{ display: 'grid', gap: 2, fontSize: 10, color: MUTED }}>
          Sort by
          <select value={sp.get('sort') || 'conviction'} onChange={e => set({ sort: e.target.value })} style={sel}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <input value={sp.get('q') || ''} onChange={e => set({ q: e.target.value })} placeholder="Symbol, company, sector" style={{ ...sel, minWidth: 170 }} />
        <button type="button" onClick={clear} style={{ ...sel, cursor: 'pointer', color: MUTED }}>Clear</button>
      </div>

      {loading && !body && <div style={{ color: MUTED, fontSize: 12 }}>Loading opportunities…</div>}
      {error && !body && <div style={{ color: TOKENS.danger, fontSize: 12 }}>Error: {String(error)}</div>}
      {body && !body.as_of && <div style={{ color: TOKENS.warning, fontSize: 12, marginBottom: 8 }}>The CIO curator has not run yet — no curated ranking in CIO memory.</div>}
      {body && items.length === 0 && body.as_of && <div style={{ color: TOKENS.warning, fontSize: 12 }}>Nothing matches these filters.</div>}

      {items.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }} data-opportunity-table>
          <thead>
            <tr style={{ color: MUTED, fontSize: 10, textTransform: 'uppercase', letterSpacing: '.04em', textAlign: 'left' }}>
              {['Rank', 'Symbol', 'Conviction', 'Upside', 'R:R', 'Risk', 'Reward', 'Type', 'Stance', 'Technical', 'Sector', 'Price'].map(h => (
                <th key={h} style={{ padding: '6px 8px', borderBottom: `1px solid ${BORDER}`, fontWeight: 800 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((a: any) => {
              const rr = a.risk_reward || {}
              return (
                <tr key={a.symbol} onClick={() => open(a.symbol)} data-opportunity-row={a.symbol} style={{ cursor: 'pointer', borderBottom: `1px solid ${BORDER}` }}>
                  <td style={{ ...numStyle, padding: '6px 8px', color: TEXT2 }}>{a.rank ?? '—'}</td>
                  <td style={{ padding: '6px 8px' }}>
                    <b style={{ fontFamily: 'var(--font-mono)' }}>{a.symbol}</b>
                    <div style={{ fontSize: 10, color: MUTED, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.company || ''}</div>
                  </td>
                  <td style={{ padding: '6px 8px' }}>
                    <span style={{ ...numStyle, fontWeight: 900, color: convictionColor(a.conviction) }}>{a.conviction != null ? Math.round(a.conviction) : '—'}</span>
                    <span style={{ fontSize: 10, color: MUTED }}> · {Math.round((a.coverage || 0) * 100)}% cov</span>
                  </td>
                  <td style={{ ...numStyle, padding: '6px 8px', color: Number(a.upside_pct) >= 0 ? TOKENS.success : TOKENS.danger }} title={a.upside_flag || ''}>{pct(a.upside_pct, 0)}{a.upside_flag ? ' ⚠' : ''}</td>
                  <td style={{ ...numStyle, padding: '6px 8px', fontWeight: 800 }} title={rr.rr_flag || ''}>{rr.rr != null ? `${Number(rr.rr).toFixed(1)}x` : '—'}</td>
                  <td style={{ ...numStyle, padding: '6px 8px', color: TOKENS.danger }}>{rr.risk_pct != null ? `-${Number(rr.risk_pct).toFixed(1)}%` : '—'}</td>
                  <td style={{ ...numStyle, padding: '6px 8px', color: TOKENS.success }}>{pct(rr.reward_pct, 1)}</td>
                  <td style={{ padding: '6px 8px', color: TEXT2 }}>{typeLabel(a.type)}</td>
                  <td style={{ padding: '6px 8px', fontWeight: 800 }}>{String(a.stance || '—').replace('_', '-')}</td>
                  <td style={{ padding: '6px 8px', color: TEXT2 }}>{condLabel(a.technical_condition)}</td>
                  <td style={{ padding: '6px 8px', color: MUTED, fontSize: 11 }}>{a.sector || '—'}</td>
                  <td style={{ ...numStyle, padding: '6px 8px' }}>{money(rr.current_price)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

/** Home widget: the top 5 high-conviction opportunities from CIO memory. */
export function TopOpportunitiesWidget() {
  const open = useOpenSymbol()
  const { data } = useApi<any>('/api/v3/opportunities?preset=top5', 300_000)
  const body = data?.data && data.data.items ? data.data : data
  const items: any[] = body?.items || []
  return (
    <div data-top-opportunities style={{ border: `1px solid ${BORDER}`, borderRadius: RADIUS.lg, padding: 14, background: 'var(--bg1)', marginTop: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: TEXT2, textTransform: 'uppercase', letterSpacing: '.06em' }}>Top opportunities · conviction ≥80 · R:R ≥2</div>
        <a href="/v3/watch?tab=opportunities&preset=top5" style={{ fontSize: 11, color: MUTED }}>All {body?.total ?? ''} →</a>
      </div>
      {items.length === 0 && <div style={{ fontSize: 11, color: MUTED }}>{body?.as_of ? 'Nothing clears the bar right now.' : 'Waiting for the first CIO curation run.'}</div>}
      {items.map((a: any) => (
        <div key={a.symbol} onClick={() => open(a.symbol)} style={{ display: 'grid', gridTemplateColumns: '28px 70px 1fr 60px 60px 70px', gap: 8, alignItems: 'center', padding: '5px 0', borderTop: `1px solid ${BORDER}`, cursor: 'pointer', fontSize: 12 }}>
          <span style={{ ...numStyle, color: MUTED }}>#{a.rank}</span>
          <b style={{ fontFamily: 'var(--font-mono)' }}>{a.symbol}</b>
          <span style={{ color: MUTED, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{typeLabel(a.type)} · {condLabel(a.technical_condition)}</span>
          <span style={{ ...numStyle, fontWeight: 900, color: convictionColor(a.conviction) }}>{Math.round(a.conviction)}</span>
          <span style={{ ...numStyle }}>{(a.risk_reward || {}).rr != null ? `${Number(a.risk_reward.rr).toFixed(1)}x` : '—'}</span>
          <span style={{ ...numStyle, color: TOKENS.success }}>{pct(a.upside_pct, 0)}</span>
        </div>
      ))}
    </div>
  )
}
