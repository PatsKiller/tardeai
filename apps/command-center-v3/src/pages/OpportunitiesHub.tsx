import './W9Mobile.css'
/** Watch › Full universe — the CIO curator's ranked list (operator 2026-10-08: "filter 500+ opportunities down to
 *  the top 5 highest-conviction decisions in under 30 seconds"), research, not a to-do list. System Suggests is the top
 *  of this same list.
 *
 *  Operator 2026-10-23: "NAVN is saying add. When I actually sold that yesterday, it should be tracked that formerly
 *  held ... if I made money with it or not. And you need to make it tighter." and "we should be able to filter on
 *  this information." Reads GET /api/v3/data-broker/watch-universe (scripts/lib/data_broker/watch_universe.py): the
 *  curator rank plus, per row, held / formerly held / never held (broker-synced Watch held reader), the last round
 *  trip and the re-entry advice (CIO prospect lifecycle). A sold name shows Type "Re-entry", status "formerly held",
 *  with the curator's own type/stance kept in the row detail. Every filter and sort is a URL parameter applied on the
 *  server. Dense rows: Risk / Reward / R:R share one cell; technical, sector and coverage live in the row detail. */
import './WatchLayout.css'
import { Fragment, useMemo, useState, type CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import ReadableTime from '../components/ReadableTime'
import { BEST_OPPORTUNITIES_API, BEST_OPPORTUNITIES_PATH, OPPORTUNITY_QUERY_KEYS, isHomeBestOpportunities, opportunitiesQuery } from '../lib/bestOpportunities'
import {MobileDetailSheet, useMobilePageDetail} from '../components/MobileDetailSheet'
import { useApi } from '../hooks/useApi'
import { RADIUS, TOKENS, TYPE, numStyle, toneVars } from '../lib/designTokens'
import { tint } from '../components/comms/CommsHubParts'
import { useOpenSymbol } from '../components/opportunity/OpportunityContext'
import { condLabel, convictionColor, money, pct, typeLabel } from '../components/opportunity/format'
import PositionFilterBar from '../components/watch/PositionFilterBar'
import { MINE_TIPS, StarToggle } from '../components/watch/MineControls'
import {
  alertLevelsLabel, heldAccountNames, positionChip, readinessTone, reentryLabel, resultTone, riskRewardCell,
  roundTripLabel, roundTripPath, soldByName, unwrapAny, withQuery, type ListRow,
} from '../lib/watchListsModel'

const MUTED = 'var(--text3)'
const TEXT = 'var(--text0)'
const TEXT2 = 'var(--text2)'
const BORDER = 'var(--border)'

// Render the producer's qualification receipt; no thresholds or verdicts are calculated in the browser.
const topQualified = (row: any) => row?.top_eligibility?.eligible === true
function researchRows(body: any, withheld: any[] = []): any[] {
  const rows = [...(Array.isArray(body?.research_candidates) ? body.research_candidates : []), ...withheld]
  return [...new Map(rows.filter(row => typeof row?.symbol === 'string').map(row => [row.symbol, row])).values()]
}
function ResearchCandidates({ rows, onOpen }: { rows: any[]; onOpen: (symbol: string) => void }) {
  if (!rows.length) return null
  return <section aria-label="Unreviewed research outside the top list" data-unreviewed-research style={{ marginTop: 14 }}>
    <h3 style={{ fontSize: TYPE.md, color: TEXT2, margin: '0 0 6px' }}>Research only — outside the top list</h3>
    {rows.map(row => <article key={row.symbol} data-research-symbol={row.symbol} style={{ borderTop: `1px solid ${BORDER}`, padding: '8px 0', minWidth: 0 }}>
      <strong>{row.symbol}</strong>
      <span style={{ marginLeft: 8, color: MUTED }}>Research score {row.conviction != null ? Math.round(row.conviction) : 'not measured'}</span>
      <p role="note" style={{ margin: '4px 0', color: TOKENS.warning, overflowWrap: 'anywhere' }}>
        {row.top_eligibility?.reason || 'Qualification for the top list has not been verified.'}
      </p>
      {row.cio_review?.reviewed && <div style={{ color: TEXT2, fontSize: TYPE.sm }}>
        CIO stance {String(row.cio_review.stance)} · reviewed <ReadableTime value={row.cio_review.as_of} />
      </div>}
      <button type="button" onClick={() => onOpen(row.symbol)} style={{ minHeight: 44, cursor: 'pointer', color: TEXT, background: 'transparent', border: 0, padding: 0 }}>Read full record →</button>
    </article>)}
    <Link to="/watch?tab=opportunities" style={{ display: 'inline-flex', alignItems: 'center', minHeight: 44, color: TEXT2 }}>Full research list →</Link>
  </section>
}

const PRESETS: [string, string, string][] = [
  ['reentry', 'Re-entry', 'Formerly held names first (most recent sell first), then everything the curator types re-entry.'],
  ['top5', 'Top 5 reviewed opportunities', 'Dated CIO research and technical coverage are required before a name can enter this list.'],
  ['new', 'New positions', 'New position ideas from the curator.'],
  ['add_on', 'Add-on', 'Ideas to add to a currently held name.'],
  ['exit', 'Exit candidates', 'Names the curator marked for exit review.'],
]
const FILTERS: { key: string; label: string; opts: [string, string][] }[] = [
  { key: 'type', label: 'Type', opts: [['', 'Any'], ['new_position', 'New Position'], ['existing', 'Existing Position'], ['re_entry', 'Re-Entry'], ['add_on', 'Add-On'], ['exit_candidate', 'Exit Candidate'], ['watchlist', 'Watchlist']] },
  { key: 'min_conviction', label: 'Conviction', opts: [['', 'Any'], ['90', '90+'], ['80', '80+'], ['70', '70+'], ['60', '60+']] },
  { key: 'min_rr', label: 'R:R', opts: [['', 'Any'], ['1.5', '1.5x+'], ['2', '2.0x+'], ['3', '3.0x+'], ['5', '5.0x+']] },
  { key: 'min_upside', label: 'Upside', opts: [['', 'Any'], ['10', '10%+'], ['20', '20%+'], ['30', '30%+'], ['50', '50%+']] },
  { key: 'technical_condition', label: 'Technical', opts: [['', 'Any'], ['breaking_out', 'Breaking Out'], ['pullback', 'Pullback'], ['oversold', 'Oversold'], ['overbought', 'Overbought'], ['trend_continuation', 'Trend Continuation'], ['range', 'Range-bound']] },
  { key: 'cap_band', label: 'Cap', opts: [['', 'Any'], ['mega', 'Mega'], ['large', 'Large'], ['mid', 'Mid'], ['small', 'Small']] },
]
const SORTS: [string, string][] = [['conviction', 'Conviction'], ['rr', 'Risk/Reward'], ['upside', 'Analyst upside'], ['reward_pct', 'Reward %'], ['risk_pct', 'Lowest risk %'], ['momentum', 'Momentum'], ['rank', 'Rank']]
const KEYS = OPPORTUNITY_QUERY_KEYS

const sel: CSSProperties = { fontSize: TYPE.sm, padding: '2px 4px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, color: TEXT, borderRadius: RADIUS.sm }
const td: CSSProperties = { padding: '2px 6px', whiteSpace: 'nowrap' }
const HEAD: [string, string][] = [
  ['★', `Your watchlist. ${MINE_TIPS.starOff}`],
  ['#', 'Rank in the curator ranking (conviction order).'], ['Symbol', 'Ticker · company · position status.'],
  ['Score', 'Automated factor score, 0–100. A top rank also requires technical coverage and dated CIO research.'], ['Type · stance', 'Opportunity type and stance as Watch shows them (a sold name is Re-entry; the curator value is in the detail).'],
  ['Risk / Reward · R:R', 'Risk % to invalidation / reward % to the primary target · reward-to-risk ratio.'],
  ['Upside', 'Analyst mean target vs price.'], ['Last trade', 'Formerly held: P/L %, P/L $, R and exit cause of the last round trip.'],
  ['Re-entry', 'Formerly held: Re-Entry Desk readiness, distance to the zone, the zone and the reclaim level.'], ['Price', 'Current price.'],
]

export default function OpportunitiesHub() {
  const [sp, setSp] = useSearchParams()
  const open = useOpenSymbol()
  const phone = useMobilePageDetail()
  const [desktopExpanded, setDesktopExpanded] = useState<string | null>(null)
  const expanded = phone.mobile ? phone.id : desktopExpanded
  const setExpanded = (symbol: string | null) => { if (phone.mobile) { if (symbol) phone.open(symbol); else phone.close() } else setDesktopExpanded(symbol) }
  const [note, setNote] = useState('')
  const q = useMemo(() => opportunitiesQuery(sp), [sp])
  const homeBest = isHomeBestOpportunities(sp)
  const { data, loading, error } = useApi<any>(withQuery('/api/v3/data-broker/watch-universe', q), 120_000)
  const body = unwrapAny<any>(data)
  const supplied: ListRow[] = Array.isArray(body?.items) ? body.items : []
  const items = homeBest ? supplied.filter(topQualified) : supplied
  const research = researchRows(body, homeBest ? supplied.filter(row => !topQualified(row)) : [])
  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(sp)
    for (const [k, v] of Object.entries(patch)) { if (v) next.set(k, v); else next.delete(k) }
    if (!('page' in patch)) next.delete('page')
    setSp(next, { replace: true })
  }
  const clear = () => { const next = new URLSearchParams(sp); for (const k of KEYS) next.delete(k); setSp(next, { replace: true }) }
  const sectors = Object.keys(body?.facets?.sector || {}).sort()
  const page = Number(body?.page || 1)
  const pages = body ? Math.max(1, Math.ceil((body.total || 0) / (body.page_size || 100))) : 1

  const recordDetails = (a: ListRow) => <div>                          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                            <span>Technical <b style={{ color: TEXT }}>{condLabel((a as any).technical_condition)}</b></span>
                            <span>Sector <b style={{ color: TEXT }}>{(a as any).sector || '—'}</b></span>
                            <span>Coverage <b style={{ color: TEXT }}>{Math.round(((a as any).coverage || 0) * 100)}%</b></span>
                            <span title="Original automated classification retained for comparison, not a CIO research decision.">Automated assessment: {typeLabel((a as any).curator_type || (a as any).type)} · {String((a as any).automated_stance || (a as any).curator_stance || '—')} · research rank {String((a as any).research_rank ?? '—')}</span>
                            {phone.mobile ? <Link className="mobile-detail-primary" onClick={() => window.scrollTo(0, 0)} to={`/watch/intelligence/${encodeURIComponent(a.symbol)}`}>Open full record →</Link> : <button type="button" onClick={e => { e.stopPropagation(); open(a.symbol) }} style={{ ...sel, cursor: 'pointer' }}>Open full record</button>}
                          </div>
                          {(a as any).ownership_note && <div style={{ color: TOKENS.warning, marginTop: 3 }}>⚠ {(a as any).ownership_note}</div>}
                          {(a as any).stance_rationale && <div style={{ marginTop: 3 }}>{(a as any).stance_rationale}</div>}
                          {a.last_round_trip && (
                            <div style={{ marginTop: 3 }} data-round-trip>
                              Last trade {roundTripPath(a.last_round_trip)} · <b style={{ color: toneVars(resultTone(a.last_round_trip)).color }}>{roundTripLabel(a.last_round_trip)}</b>
                              {a.last_round_trip.stop_raised != null ? ` · stop raised ${a.last_round_trip.stop_raised}× (${money(a.last_round_trip.stop_initial)} → ${money(a.last_round_trip.stop_last)})` : ''}
                              {a.last_round_trip.noise_vs_trend ? ` · exit reads as ${a.last_round_trip.noise_vs_trend.replace('_', ' ')}` : ''}
                              {a.last_round_trip.r_basis ? <span style={{ color: MUTED }}> (R vs the {a.last_round_trip.r_basis})</span> : null}
                            </div>
                          )}
                          {a.reentry && (
                            <div style={{ marginTop: 3 }} data-reentry-advice>
                              Re-entry {a.reentry.state}: {reentryLabel(a.reentry)} · alert levels {alertLevelsLabel(a.reentry)}
                              <div style={{ color: MUTED }}>{a.reentry.conditions.map(c => `${c.met === true ? '✓' : c.met === false ? '✗' : '?'} ${c.text}`).join(' · ')}</div>
                            </div>
                          )}
  </div>
  return (
    <div data-opportunities-hub className="w9-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', margin: '4px 0' }}>
        <div style={{ fontSize: TYPE.base, color: TEXT2 }} title="Research names scored by the CIO curator. Filters apply to this ranking.">
          {homeBest
            ? <><b style={{ color: TEXT }}>{body ? items.length : '—'}</b> shown · Best opportunities · reviewed research</>
            : <><b style={{ color: TEXT }}>{body?.total ?? '—'}</b> of {body?.universe ?? '—'} · Full universe (research)</>}
          {body?.as_of ? <span style={{ color: MUTED }}> · ranking snapshot <ReadableTime value={body.as_of} /></span> : null}
          {body?.held?.source ? <span style={{ color: MUTED }} title="Held / formerly held come from the broker-synced Watch held reader."> · held: {String(body.held.source).split('.')[0]}{body.held.stale ? ' (stale)' : ''}</span> : null}
        </div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {PRESETS.map(([id, label, tip]) => {
            const on = sp.get('preset') === id
            return (
              <button key={id} type="button" data-preset={id} title={tip} onClick={() => set({ preset: on ? '' : id })}
                style={{ fontSize: TYPE.sm, padding: '2px 8px', borderRadius: RADIUS.pill, cursor: 'pointer', fontWeight: 700,
                  border: `1px solid ${on ? TOKENS.success : BORDER}`, background: on ? tint(TOKENS.success) : 'transparent', color: TEXT }}>
                {label}{id === 'reentry' && body?.position_facets?.position?.formerly_held != null ? ` · ${body.position_facets.position.formerly_held}` : ''}
              </button>
            )
          })}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', padding: '4px 6px', border: `1px solid ${BORDER}`, borderRadius: RADIUS.md, background: 'var(--bg1)', marginBottom: 6 }} data-opportunity-filters>
        {FILTERS.map(f => (
          <label key={f.key} style={{ display: 'flex', gap: 3, alignItems: 'center', fontSize: TYPE.xs, color: MUTED }}>
            {f.label}
            <select value={sp.get(f.key) || ''} onChange={e => set({ [f.key]: e.target.value })} style={sel}>
              {f.opts.map(([v, l]) => <option key={v} value={v}>{l}{v && body?.facets?.[f.key]?.[v] != null ? ` (${body.facets[f.key][v]})` : ''}</option>)}
            </select>
          </label>
        ))}
        <label style={{ display: 'flex', gap: 3, alignItems: 'center', fontSize: TYPE.xs, color: MUTED }}>
          Sector
          <select value={sp.get('sector') || ''} onChange={e => set({ sector: e.target.value })} style={sel}>
            <option value="">Any</option>
            {sectors.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', gap: 3, alignItems: 'center', fontSize: TYPE.xs, color: MUTED }}>
          Sort
          <select value={sp.get('sort') || 'conviction'} onChange={e => set({ sort: e.target.value })} style={sel}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <input value={sp.get('q') || ''} onChange={e => set({ q: e.target.value })} placeholder="Symbol, company, sector" style={{ ...sel, minWidth: 150 }} />
        <button type="button" onClick={clear} style={{ ...sel, cursor: 'pointer', color: MUTED }}>Clear</button>
      </div>
      <div style={{ marginBottom: 6 }}>
        <PositionFilterBar specs={body?.position_filters} facets={body?.position_facets} testId="universe-position-filters" />
      </div>

      {note && <div role="status" style={{ color: TEXT2, fontSize: TYPE.base, marginBottom: 4 }}>{note}</div>}
      {loading && !body && <div style={{ color: MUTED, fontSize: TYPE.base }}>Loading {homeBest ? 'Best opportunities' : 'the Full universe'}…</div>}
      {error && !body && <div style={{ color: TOKENS.danger, fontSize: TYPE.base }}>Error: {String(error)}</div>}
      {body && !body.as_of && <div style={{ color: TOKENS.warning, fontSize: TYPE.base, marginBottom: 6 }}>The CIO curator has not run yet — no curated ranking in CIO memory.</div>}
      {body && items.length === 0 && body.as_of && <div style={{ color: TOKENS.warning, fontSize: TYPE.base }}>Nothing matches these filters.</div>}

      {body && <p role="status" data-top-list-notice style={{ color: TOKENS.warning, fontSize: TYPE.base, overflowWrap: 'anywhere' }}>
        {body.top_list?.notice || 'Qualification for the top list is unavailable; these records remain research only.'}
      </p>}
      {items.length > 0 && (
        <div className="watch-universe-panel">
          <table className="watch-universe-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: TYPE.base }} data-opportunity-table>
            <thead>
              <tr style={{ color: MUTED, fontSize: TYPE.xs, textTransform: 'uppercase', letterSpacing: '.04em', textAlign: 'left' }}>
                {HEAD.map(([h, tip]) => <th key={h} title={tip} style={{ ...td, padding: '3px 6px', borderBottom: `1px solid ${BORDER}`, fontWeight: 800 }}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {items.map(a => {
                const rr: any = (a as any).risk_reward || {}
                const chip = positionChip(a)
                const isOpen = expanded === a.symbol
                return (
                  <Fragment key={a.symbol}>
                    <tr onClick={() => setExpanded(isOpen ? null : a.symbol)} className="watch-universe-row" data-opportunity-row={a.symbol} aria-expanded={isOpen} tabIndex={0}
                      onKeyDown={e => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setExpanded(isOpen ? null : a.symbol) } }}
                      style={{ cursor: 'pointer', borderBottom: `1px solid ${BORDER}`, background: isOpen ? 'var(--bg2)' : undefined }}>
                      <td className="watch-universe-star" data-label="Watchlist" style={{ ...td, width: 22 }}><StarToggle symbol={a.symbol} on={!!a.mine} surface="watch.full_universe" size="sm" onChanged={setNote} /></td>
                      <td data-label="Rank" style={{ ...td, ...numStyle, color: TEXT2 }}>{topQualified(a) ? (a as any).rank ?? '—' : 'Unreviewed'}</td>
                      <td className="watch-universe-symbol" data-label="Symbol" style={{ ...td, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis' }} title={(a as any).company || ''}>
                        <b style={{ fontFamily: 'var(--font-mono)' }}>{a.symbol}</b>
                        <span style={{ fontSize: TYPE.xs, color: MUTED }}> {(a as any).company || ''}</span>
                        {chip && <span data-position-chip={a.position_state} title={chip.tip} style={{ marginLeft: 4, fontSize: TYPE.xs, fontWeight: 700, color: toneVars(chip.tone).color }}>· {chip.label}</span>}
                        <span className="watch-universe-mobile-facts">
                          <span><b>Account</b> {heldAccountNames(a).join(', ') || soldByName(a) || 'Unknown'}</span>
                          <span><b>Stage</b> {a.stage?.replace(/_/g, ' ') || 'Not supplied'}</span>
                        </span>
                      </td>
                      <td data-label="Research score" style={{ ...td, ...numStyle, fontWeight: 900, color: convictionColor(a.conviction) }}>{a.conviction != null ? Math.round(a.conviction) : '—'}</td>
                      <td data-label="Type · stance" style={{ ...td, color: TEXT2 }} title={(a as any).ownership_note || (a as any).stance_rationale || ''}>
                        {topQualified(a) ? typeLabel((a as any).type) : 'Research only'} · <b style={{ color: TEXT }}>{(a as any).cio_review?.reviewed ? String((a as any).cio_review.stance) : 'CIO review pending'}</b>
                        <span style={{ display: 'block', whiteSpace: 'normal', maxWidth: 280, overflowWrap: 'anywhere', fontSize: TYPE.sm }}>
                          {(a as any).top_eligibility?.reason || 'Qualification for the top list has not been verified.'}
                        </span>
                        {(a as any).cio_review?.reviewed && <span data-cio-reviewed-as-of style={{ display: 'block', whiteSpace: 'normal', fontSize: TYPE.sm }}>CIO reviewed <ReadableTime value={(a as any).cio_review.as_of} /></span>}
                        {(a as any).ownership_note ? <span style={{ color: TOKENS.warning }}> ⚠</span> : null}
                      </td>
                      <td data-label="Risk / Reward · R:R" style={{ ...td, ...numStyle }} title={rr.rr_flag || ''}>{riskRewardCell(rr)}</td>
                      <td data-label="Upside" style={{ ...td, ...numStyle, color: Number((a as any).upside_pct) >= 0 ? TOKENS.success : TOKENS.danger }} title={(a as any).upside_flag || ''}>{pct((a as any).upside_pct, 0)}{(a as any).upside_flag ? ' ⚠' : ''}</td>
                      <td data-label="Last P/L" style={{ ...td, ...numStyle, color: toneVars(resultTone(a.last_round_trip)).color }} title={a.last_round_trip ? roundTripPath(a.last_round_trip) : ''}>{a.last_round_trip ? roundTripLabel(a.last_round_trip) : '—'}</td>
                      <td data-label="Re-entry · next trigger" style={{ ...td, color: toneVars(readinessTone(a.reentry)).color, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis' }} title={a.reentry ? `${a.reentry.state} — ${a.reentry.reason || ''}` : ''}>{a.reentry ? reentryLabel(a.reentry) : '—'}</td>
                      <td data-label="Price" style={{ ...td, ...numStyle }}>{money(rr.current_price)}</td>
                    </tr>
                    {isOpen && !phone.mobile && (
                      <tr className="watch-universe-detail" data-opportunity-detail={a.symbol}>
                        <td colSpan={HEAD.length} style={{ padding: '4px 10px 8px', background: 'var(--bg2)', fontSize: TYPE.base, color: TEXT2, whiteSpace: 'normal' }}>
                          {recordDetails(a)}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
          {!homeBest && pages > 1 && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', justifyContent: 'flex-end', marginTop: 4, fontSize: TYPE.sm, color: MUTED }}>
              <button type="button" disabled={page <= 1} onClick={() => set({ page: String(page - 1) })} style={{ ...sel, cursor: 'pointer' }}>‹ Prev</button>
              page {page} / {pages}
              <button type="button" disabled={page >= pages} onClick={() => set({ page: String(page + 1) })} style={{ ...sel, cursor: 'pointer' }}>Next ›</button>
            </div>
          )}
        </div>
      )}
      <ResearchCandidates rows={research} onOpen={open} />
      {phone.mobile && expanded && <MobileDetailSheet title={`${expanded} record`} onBack={phone.close}>
        {items.find(a => a.symbol === expanded) ? (() => { const row = items.find(a => a.symbol === expanded)!; return <>
          <h2 tabIndex={-1} data-detail-focus>{row.symbol}</h2>
          <p>{heldAccountNames(row).join(', ') || soldByName(row) || 'Account not supplied'}</p>
          {/* Same record-detail contract as the desktop expanded row. */}
          <div data-opportunity-detail={row.symbol}>{recordDetails(row)}</div>
        </> })() : <p>This record is not in the current page of results.</p>}
      </MobileDetailSheet>}
    </div>
  )
}

/** Home widget: the top 5 high-conviction opportunities from CIO memory. */
export function TopOpportunitiesWidget() {
  const open = useOpenSymbol()
  const { data } = useApi<any>(BEST_OPPORTUNITIES_API, 300_000)
  const body = data?.data && data.data.items ? data.data : data
  const supplied: any[] = Array.isArray(body?.items) ? body.items : []
  const items = supplied.filter(topQualified)
  const research = researchRows(body, supplied.filter(row => !topQualified(row)))
  return (
    <div data-top-opportunities style={{ border: `1px solid ${BORDER}`, borderRadius: RADIUS.lg, padding: 14, background: 'var(--bg1)', marginTop: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: TEXT2, textTransform: 'uppercase', letterSpacing: '.06em' }}>Top opportunities · reviewed data required</div>
        <Link to={BEST_OPPORTUNITIES_PATH} aria-label="View best opportunities" style={{ fontSize: 11, color: MUTED, minHeight: 44, minWidth: 44, display: 'inline-flex', alignItems: 'center' }}>View top 5 →</Link>
      </div>
      {body && <p role="status" style={{ color: TOKENS.warning, overflowWrap: 'anywhere', fontSize: TYPE.sm }}>{body.top_list?.notice || 'Qualification for the top list is unavailable.'}</p>}
      {items.length === 0 && <div style={{ fontSize: 11, color: MUTED }}>{body?.top_list ? 'No reviewed name clears the bar right now.' : body ? 'Top list not verified; research records remain below.' : 'Waiting for the ranking snapshot.'}</div>}
      {items.map((a: any) => (
        <button key={a.symbol} type="button" data-top-opportunity-row={a.symbol} onClick={() => open(a.symbol)} style={{ display: 'flex', flexWrap: 'wrap', width: '100%', background: 'transparent', color: TEXT, textAlign: 'left', border: 0, gap: 8, alignItems: 'center', padding: '5px 0', borderTop: `1px solid ${BORDER}`, cursor: 'pointer', fontSize: TYPE.sm }}>
          <span style={{ ...numStyle, color: MUTED }}>#{a.rank}</span>
          <b style={{ fontFamily: 'var(--font-mono)' }}>{a.symbol}</b>
          <span style={{ color: MUTED, overflowWrap: 'anywhere' }}>{typeLabel(a.type)} · CIO {String(a.cio_review?.stance)}</span>
          <span style={{ ...numStyle, fontWeight: 900, color: convictionColor(a.conviction) }}>{Math.round(a.conviction)}</span>
          <span style={{ ...numStyle }}>{(a.risk_reward || {}).rr != null ? `${Number(a.risk_reward.rr).toFixed(1)}x` : '—'}</span>
          <span style={{ ...numStyle, color: TOKENS.success }}>{pct(a.upside_pct, 0)}</span>
          <span style={{ flexBasis: '100%', color: MUTED }}>CIO reviewed <ReadableTime value={a.cio_review?.as_of} /></span>
        </button>
      ))}
      <ResearchCandidates rows={research} onOpen={open} />
    </div>
  )
}
