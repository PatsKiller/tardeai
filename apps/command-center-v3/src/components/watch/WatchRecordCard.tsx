import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { FONT, RADIUS, TOKENS, TYPE } from '../../lib/designTokens'
import { rowRail, type RailState } from '../../lib/watchTokens'
import './WatchRecordCard.css'
import { useSearchParams } from 'react-router-dom'
import { cycleHeaderSort } from '../../lib/watchRecordCardModel'

export function WatchCardHeader() {
  const [sp, setSp] = useSearchParams()
  const current = sp.get('psort')
  const sort = (field: 'conviction' | 'setup') => {
    const next = new URLSearchParams(sp), value = cycleHeaderSort(current, field)
    if (value) next.set('psort', value); else next.delete('psort')
    setSp(next, { replace: true })
  }
  const sortable = (field: 'conviction' | 'setup', name: string) => {
    const active = field === 'setup' ? current === 'setup' : current?.startsWith('conviction_')
    const asc = current === 'conviction_asc' || field === 'setup'
    return <div role="columnheader" aria-sort={active ? asc ? 'ascending' : 'descending' : 'none'}>
      <button className="watch-card-sort" type="button" onClick={() => sort(field)} data-testid={`watch-sort-${field}`}>
        {name}{active ? asc ? ' ▲' : ' ▼' : ''}</button>
    </div>
  }
  return <div role="table" aria-label="Watch row sort controls"><div className="watch-card-header" role="row"
    style={{ fontSize: TYPE.sm, textTransform: 'uppercase', letterSpacing: '.06em', color: TOKENS.text[2] }}>
    <div role="columnheader">Company</div>{sortable('setup', 'Setup · why')}<div role="columnheader">Price vs levels</div>
    {sortable('conviction', 'Conviction')}<div role="columnheader">Next step</div>
  </div></div>
}

/** Responsive shell only. The existing Watch parent owns every action and source record. */
export default function WatchRecordCard({ symbol, company, setup, market, conviction, primary, secondary, rail, selected, lane }: {
  symbol: string; company: ReactNode; setup: ReactNode; market: ReactNode; conviction: ReactNode
  primary: ReactNode; secondary: ReactNode; rail: RailState; selected: boolean; lane: string
}) {
  const [more, setMore] = useState(false)
  const toggle = useRef<HTMLButtonElement>(null)
  const panelId = `watch-more-${symbol.replace(/[^a-zA-Z0-9_-]/g, '-')}`
  useEffect(() => {
    if (!more) return
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') { setMore(false); toggle.current?.focus() } }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [more])
  const style = { ...rowRail(rail), borderRadius: RADIUS.md, background: TOKENS.bg[1],
    borderTop: `1px solid ${TOKENS.borderSubtle}`, borderRight: `1px solid ${TOKENS.borderSubtle}`, borderBottom: `1px solid ${TOKENS.borderSubtle}`,
    fontFamily: FONT.sans, fontSize: TYPE.base, color: TOKENS.text[0],
    '--watch-card-font-sm': `${TYPE.sm}px`, '--watch-card-font-base': `${TYPE.base}px`,
    '--watch-card-font-md': `${TYPE.md}px`, '--watch-card-font-lg': `${TYPE.lg}px`, '--watch-card-font-xl': `${TYPE.xl}px`,
  } as CSSProperties
  return <article className="watch-record-card" data-testid="watch-row" data-symbol={symbol} data-lane={lane} data-selected={selected ? '1' : '0'} style={style}>
    <div className="watch-card-company">{company}</div>
    <div className="watch-card-setup">{setup}</div>
    <div className="watch-card-market">{market}</div>
    <div className="watch-card-conviction">{conviction}</div>
    <div className="watch-card-actions">
      {primary}
      <button ref={toggle} type="button" className="watch-card-more" aria-label="More actions" aria-expanded={more} aria-controls={panelId}
        onClick={() => setMore(v => !v)}><span className="watch-card-more-desktop">Set alert · Remove</span><span className="watch-card-more-phone" aria-hidden="true">⋯</span></button>
      <div id={panelId} className="watch-card-secondary" role="group" aria-label={`${symbol} secondary actions`} hidden={!more}>{secondary}</div>
    </div>
  </article>
}
