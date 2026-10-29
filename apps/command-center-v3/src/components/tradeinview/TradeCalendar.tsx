/** Shared calendar: server statistics only, explicit month; also replaces the classic journal calendar. */
import { useState, type CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, chipStyle, numStyle, toneVars } from '../../lib/designTokens'
import { calendarPayload, coverageReason, etMonth, monthLabel, monthShift, responseReason, serverMoney, serverNumber, tradeLink, type CalendarEvent } from '../../lib/tradeInViewModel'
import './TradeInViewLayout.css'
import ReadableTime from '../ReadableTime'
import { readableTimesInText } from '../../lib/readableTime'

const modes = [['realized', 'Realized P/L'], ['earnings', 'Earnings'], ['catalyst', 'Catalysts'], ['ex_dividend', 'Ex-dividend']] as const
export default function TradeCalendar({ embedded = false }: { embedded?: boolean }) {
  const [params] = useSearchParams()
  const identity = new URLSearchParams({ month: params.get('month') || etMonth(new Date()), account: params.get('account') || '', names: params.get('names') === 'held' ? 'held' : 'held_watch' }).toString()
  // A last-good body belongs to this query only, including terminal/error state in useApi.
  return <CalendarView key={identity} embedded={embedded} />
}
function CalendarView({ embedded }: { embedded: boolean }) {
  const [params, setParams] = useSearchParams()
  const month = params.get('month') || etMonth(new Date())
  const query = new URLSearchParams({ month, account: params.get('account') || '', names: params.get('names') === 'held' ? 'held' : 'held_watch' })
  const api = useApi<any>(`/api/v3/data-broker/trade-calendar?${query}`, 60_000)
  const data = calendarPayload(api.data, { month, account: query.get('account')!, names: query.get('names')! })
  const [shown, setShown] = useState<string[]>(['realized', 'earnings', 'catalyst'])
  const [day, setDay] = useState<string | null>(params.get('day'))
  const update = (key: string, value: string) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); next.delete('day'); setDay(null); setParams(next, { replace: true }) }
  const selectDay = (date: string) => { setDay(date); const next = new URLSearchParams(params); next.set('day', date); setParams(next, { replace: true }) }
  const eventVisible = (event: CalendarEvent) => shown.includes(event.type === 'earnings' || event.type === 'ex_dividend' ? event.type : 'catalyst')
  const eventLabel = (e: CalendarEvent) => ({ earnings: 'Earnings', catalyst: 'Catalyst', ex_dividend: 'Ex-dividend', wash_sale: 'Wash-sale window', macro: 'Macro', other: 'Other' }[e.type] || 'Other') + (e.type === 'other' && e.source_event_type ? ` (${e.source_event_type})` : '')
  const events = data?.events.filter(eventVisible) || []
  const selected = data?.days.find(d => d.date === day)
  return <section className="tradeinview" data-testid="trade-calendar" style={{ fontSize: TYPE.base, color: TOKENS.text[0], '--tradeinview-font-sm': `${TYPE.sm}px` } as CSSProperties}>
    {embedded && <h2 style={{ fontSize: TYPE.lg, margin: 0 }}>Calendar P/L</h2>}
    <div className="tradeinview-controls">
      <button type="button" aria-label="Previous month" style={button} onClick={() => update('month', monthShift(month, -1))}>‹</button>
      <b style={{ fontSize: TYPE.lg, minWidth: 160, textAlign: 'center' }}>{monthLabel(month)}</b>
      <button type="button" aria-label="Next month" style={button} onClick={() => update('month', monthShift(month, 1))}>›</button>
      {modes.map(([key, label]) => <button type="button" key={key} aria-pressed={shown.includes(key)} onClick={() => setShown(old => old.includes(key) ? old.filter(x => x !== key) : [...old, key])} style={{ ...chipStyle(shown.includes(key) ? 'warning' : 'neutral', shown.includes(key) ? 'soft' : 'outline', 'md'), cursor: 'pointer' }}>{label}</button>)}
      <label>Account <select aria-label="Calendar account" value={query.get('account') || ''} onChange={e => update('account', e.target.value)} style={select}><option value="">All accounts</option>{data?.account_options.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}</select></label>
      <label title="Names selects event coverage; realized P/L uses the selected month and account.">Names <select aria-label="Calendar names" value={query.get('names')!} onChange={e => update('names', e.target.value)} style={select}><option value="held_watch">Held + My Watchlist</option><option value="held">Held only</option></select></label>
    </div>
    {api.stale && <div role="status" style={{ color: TOKENS.warning }}>Refresh unavailable — last successful snapshot. Collection <ReadableTime value={data?.as_of} />.</div>}
    {!data ? <div role="status" className="tradeinview-gap">{api.loading ? 'Loading calendar…' : `Calendar unavailable — ${api.error || responseReason(api.data) || 'server response did not contain the calendar schema'}`}</div> : <>
      {data.summary.trade_count === 0 && <div data-testid="calendar-empty" className="tradeinview-gap">No closed trips recorded for this month and account.</div>}
      <div className="tradeinview-calendar-layout">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div className="tradeinview-calendar-week" style={{ fontSize: TYPE.sm, color: TOKENS.text[2], textTransform: 'uppercase' }}>{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Week'].map(d => <span key={d}>{d}</span>)}</div>
          {data.weeks.map(week => <div key={week.start_date} className="tradeinview-calendar-week" data-testid="calendar-week">
            {week.days.map((date, index) => {
              const d = data.days.find(item => item.date === date), outside = !!date && !date.startsWith(data.month)
              const value = d?.realized_pl, tone = value == null || value === 0 ? 'neutral' : value > 0 ? 'success' : 'danger'
              const intensity = d?.heat_intensity
              return date ? <button type="button" key={date} data-testid="calendar-day" data-date={date} aria-pressed={day === date} onClick={() => selectDay(date)} className="tradeinview-calendar-day" style={{ background: outside || intensity == null ? TOKENS.bg[1] : `color-mix(in srgb, ${toneVars(tone).bg} ${Math.max(0, Math.min(1, intensity)) * 100}%, ${TOKENS.bg[1]})`, border: `1px solid ${day === date ? TOKENS.info : TOKENS.borderSubtle}`, borderRadius: RADIUS.md, color: TOKENS.text[0] }}>
                <span style={{ color: TOKENS.text[2], fontSize: TYPE.sm }}>{date.slice(8)}{outside ? ` · ${date.slice(5, 7)}` : ''}</span>
                {d && <>{d.trade_count !== 0 && <span style={{ color: TOKENS.text[2], fontSize: TYPE.sm }}>{serverNumber(d.trade_count)} trades</span>}{d.trade_count !== 0 && shown.includes('realized') && <b style={{ ...numStyle, color: toneVars(tone).color }}>{serverMoney(value)}</b>}<span style={{ fontSize: TYPE.sm }}>{d.symbols.map(s => `${s.symbol} ${serverMoney(s.realized_pl)}`).join(' · ')}</span>{d.events.filter(eventVisible).map(e => <span key={e.id} style={{ color: TOKENS.warning, fontSize: TYPE.sm }}>{e.symbol ? `${e.symbol} · ` : ''}{eventLabel(e)} · {e.title}</span>)}{d.coverage.status.toUpperCase() !== 'COMPLETE' && <span style={{ fontSize: TYPE.sm }} title={coverageReason(d.coverage)}>Coverage gap</span>}</>}
                {!d && !outside && <span className="tradeinview-gap">Day evidence unavailable</span>}
              </button> : <div key={`blank-${index}`} />
            })}
            <div title={coverageReason(week.coverage)} style={{ ...numStyle, padding: '10px 2px', textAlign: 'right', color: week.realized_pl == null || week.realized_pl === 0 ? TOKENS.text[2] : week.realized_pl < 0 ? TOKENS.danger : TOKENS.success }} data-testid="calendar-week-total">{shown.includes('realized') ? serverMoney(week.realized_pl) : '—'}</div>
          </div>)}
          {data.non_grid_days?.length ? <section aria-label="Activity outside weekday grid" className="tradeinview-panel" style={{ padding: 10 }}><b>Recorded activity outside the weekday grid</b>{data.non_grid_days.map(d => <button key={d.date} type="button" onClick={() => selectDay(d.date)} style={{ ...button, display: 'block', marginTop: 6 }}>{d.date} · {serverMoney(d.realized_pl)} · {serverNumber(d.trade_count)} trades</button>)}</section> : null}
          <p className="tradeinview-gap" style={{ margin: '4px 0' }}>Realized P/L uses the same closed round trips as Journeys. Tap a day for its trades and Replay links. Names scope applies to events. Collection <ReadableTime value={data.as_of} />.</p>
        </div>
        <aside className="tradeinview-panel" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 8 }}>
            <div style={tile}><span>{monthLabel(data.month)} realized</span><b data-testid="calendar-month-total" style={{ ...metric, color: data.summary.realized_pl == null || data.summary.realized_pl === 0 ? TOKENS.text[0] : data.summary.realized_pl < 0 ? TOKENS.danger : TOKENS.success }}>{serverMoney(data.summary.realized_pl)}</b>{data.summary.realized_pl == null && <span>{coverageReason(data.summary.coverage)}</span>}</div>
            <div style={tile}><span>Green days</span><b data-testid="calendar-green-days" title="Days with at least one recorded closed trade; this is not a count of exchange trading days." style={metric}>{serverNumber(data.summary.green_days)}{data.summary.active_days != null ? ` of ${serverNumber(data.summary.active_days)}` : ''}</b><span style={{ fontSize: TYPE.sm }}>days with closed trades</span></div>
          </div>
          <b style={{ fontSize: TYPE.sm, letterSpacing: '.06em', color: TOKENS.text[2] }}>EVENTS · SELECTED MONTH · {data.names === 'held' ? 'HELD NAMES' : 'HELD + MY WATCHLIST'}</b>
          {events.length ? events.map(e => <div key={e.id} data-testid="calendar-event" style={{ display: 'grid', gridTemplateColumns: '70px minmax(0, 1fr)', gap: 8, borderBottom: `1px solid ${TOKENS.borderSubtle}`, paddingBottom: 8 }}><span style={{ fontFamily: FONT.mono }}>{e.date}</span><div>{e.symbol && <b>{e.symbol} · </b>}{eventLabel(e)} · {e.title}<div className="tradeinview-gap" style={{ fontSize: TYPE.sm }}>{e.source || e.missing_reason || 'Event source unavailable'} · {e.as_of ? <ReadableTime value={e.as_of} /> : 'Observation time unavailable'}{e.date_basis && e.date_basis !== 'stored event date' ? ` · ${e.date_basis}` : ''}</div></div></div>) : <div className="tradeinview-gap">No events in the selected view. Source coverage and gaps are listed below.</div>}
        </aside>
      </div>
      {selected && <section className="tradeinview-panel" data-testid="calendar-day-drawer" aria-label={`Trades on ${selected.date}`} style={{ padding: 16 }}><div className="tradeinview-heading"><h2 style={{ fontSize: TYPE.lg, margin: 0 }}>{selected.date} · {serverMoney(selected.realized_pl)}</h2><button type="button" style={button} onClick={() => { setDay(null); const n = new URLSearchParams(params); n.delete('day'); setParams(n, { replace: true }) }}>Close day</button></div>
        {selected.trades.length ? selected.trades.map(t => <div key={t.trade_id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', padding: '10px 0', borderBottom: `1px solid ${TOKENS.borderSubtle}` }}><span><b>{t.symbol}</b> · {t.account_label || 'Unlabelled account'} · {serverMoney(t.realized_pl)}{t.basis_unknown ? ` · ${t.basis_reason || 'Basis unknown'}` : ''}</span><Link to={tradeLink('replay', { trade_id: t.trade_id })} style={{ color: TOKENS.info }}>Replay</Link></div>) : <p className="tradeinview-gap">No closed trips supplied for this day. {coverageReason(selected.coverage)}</p>}
        {selected.events.filter(eventVisible).map(e => <p key={e.id}>{e.symbol ? `${e.symbol} · ` : ''}{eventLabel(e)} · {e.title} · {e.source || e.missing_reason || 'Source unavailable'}{e.date_basis ? ` · ${e.date_basis}` : ''}</p>)}
      </section>}
      {data.gaps.map((g, i) => <div role="note" className="tradeinview-gap" key={`${g.source}-${i}`}>{g.source}: {readableTimesInText(g.reason)}</div>)}
    </>}
  </section>
}
const button = { background: TOKENS.bg[1], color: TOKENS.text[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, minWidth: 44, padding: '6px 10px', cursor: 'pointer' } as const
const select = { background: TOKENS.bg[1], color: TOKENS.text[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, fontSize: TYPE.base, padding: 6 } as const
const tile = { padding: 10, background: TOKENS.bg[2], borderRadius: RADIUS.md, display: 'flex', flexDirection: 'column', gap: 6, color: TOKENS.text[2] } as const
const metric = { ...numStyle, fontSize: TYPE.lg, color: TOKENS.text[0] }
