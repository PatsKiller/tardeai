import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'
import { W7Gap, W7Metric, W7Panel, grid, line, linkStyle, mono, pct, text, when } from './W7PagePanels'
import W7DetailSheet, { useW7Detail } from './W7DetailSheet'

const DO_NOW_SHEET = 'do-now-all'

const localHref = (v: unknown) => typeof v === 'string' ? v.replace(/^\/v3(?=\/|$)/, '') || '/' : null

/** Same link as the stop desks: a single protection item opens that position on Risk. A rolled-up row does not. */
function protectionHref(item: { id?: string; href?: string; action?: { where?: string } }): string | null {
  const id = typeof item?.id === 'string' ? item.id : ''
  const match = /^protection:([^:]+):(.+)$/.exec(id)
  if (!match) return null
  const href = typeof item?.href === 'string' ? item.href : typeof item?.action?.where === 'string' ? item.action.where : ''
  if (!/^(\/v3)?\/risk(\?|$)/.test(href)) return null
  const q = new URLSearchParams({ tab: 'exposure', detail: `position:${match[1]}:${match[2]}` })
  return `/risk?${q.toString()}`
}

const itemHref = (item: { id?: string; href?: string; action?: { where?: string } }) => protectionHref(item) || localHref(item.href || item.action?.where)

const KIND_TONE: Record<string, Tone> = { STOP: 'danger', REVIEW: 'warning', ENTRY: 'success', INFO: 'info' }

function KindChip({ kind }: { kind?: string }) {
  if (!kind || !(kind in KIND_TONE)) return null
  const tone = toneVars(KIND_TONE[kind])
  const style: CSSProperties = {
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', minWidth: 64, minHeight: 28,
    padding: '2px 8px', borderRadius: RADIUS.sm, background: tone.bg, color: tone.color, border: `1px solid ${tone.border}`,
    fontSize: TYPE.sm, fontWeight: 600, letterSpacing: '0.04em',
  }
  return <span data-testid="home-do-now-kind" style={style}>{kind}</span>
}

function gapText(gap: unknown) {
  if (!gap) return null
  return typeof gap === 'string' ? gap : (gap as { reason?: string }).reason
}

const moreStyle: CSSProperties = {
  ...linkStyle, width: '100%', minHeight: 44, justifyContent: 'center', marginTop: 8, cursor: 'pointer',
  background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, font: 'inherit',
}

function DoNowRow({ item, testId }: { item: any; testId: string }) {
  const href = itemHref(item)
  return <div data-testid={testId} style={{ ...line, alignItems: 'center' }}>
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: '1 1 220px', minWidth: 0 }}>
      <KindChip kind={item.kind} />
      <b>{item.symbol && <span style={mono}>{item.symbol} </span>}{item.title || item.text}</b>
      {item.account_label && <div style={{ color: TOKENS.text[2], fontSize: TYPE.base }}>{item.account_label}</div>}
      <div style={{ color: TOKENS.text[2] }}>{item.reason || item.why || item.detail}</div>
      {item.stance && <span>CIO {item.stance} · conviction {text(item.conviction)}</span>}
    </div>
    {href && <Link style={{ ...linkStyle, width: '100%', justifyContent: 'center', background: TOKENS.bg[2] }} to={href}>{item.cta || item.action?.label || 'Review'} →</Link>}
  </div>
}

/** Board 14 Home body. Facts come from the CIO page payload. Nothing here calls a broker. */
export default function HomeBoard14({ data }: { data: any }) {
  const todo = data.do_now || {}
  const stops = data.stops || {}
  const regime = data.regime || {}
  const approvals = data.approvals || {}
  const questions = data.questions || {}
  const releases = data.releases || {}
  const items: any[] = todo.items || []
  const allItems: any[] = Array.isArray(todo.all_items) && todo.all_items.length >= items.length ? todo.all_items : items
  const limit = typeof todo.limit === 'number' ? todo.limit : 7
  // Rows the panel does not show. Never silent: the button below names the count and opens the full list.
  const hidden = Math.max(0, typeof todo.hidden_count === 'number' ? todo.hidden_count
    : (typeof todo.total === 'number' ? todo.total : allItems.length) - items.length)
  const detail = useW7Detail()
  const nearest = stops.nearest
  const awaiting: any[] = stops.awaiting_fill || []
  const filledAwaitingSync: any[] = stops.filled_awaiting_sync || []
  const stopsGap = gapText(stops.gap)
    || (stops.stale ? `Stop data is out of date — counts are from the last broker stop read${stops.last_broker_read_label ? ` on ${stops.last_broker_read_label}` : ''}.` : null)
  const favoured = data.sectors?.favoured
  const since = regime.since_label || regime.since_gap || 'Regime start is not in the fetched history'
  const vix = regime.vix == null ? 'Not available' : text(regime.vix)
  const questionCount = questions.count == null ? 'Not available' : `${questions.count} new`
  const releaseCount = releases.count == null ? 'Not available' : String(releases.count)
  return <div style={{ ...grid, gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,360px),1fr))' }}>
    <W7Panel title="Do now" testId="home-do-now">
      <p style={{ color: TOKENS.text[2], marginTop: 0 }}>Ranked by the CIO · {hidden > 0 ? `top ${items.length} of ${items.length + hidden}` : `up to ${limit}`}</p>
      {todo.gap && <W7Gap>{gapText(todo.gap)}</W7Gap>}
      {!items.length && !todo.gap && <p>No actions published by the CIO.</p>}
      {items.map((item, i) => <DoNowRow key={item.id || i} item={item} testId="home-do-now-row" />)}
      {hidden > 0 && <button type="button" data-testid="home-do-now-more" onClick={() => detail.open(DO_NOW_SHEET)} style={moreStyle}>
        +{hidden} more · see all {allItems.length}
      </button>}
    </W7Panel>
    {detail.selected === DO_NOW_SHEET && <W7DetailSheet title={`Do now · all ${allItems.length}`} onClose={detail.close}>
      <p style={{ color: TOKENS.text[2], marginTop: 0 }}>Every action the CIO ranked, in the same order. Home shows the top {limit}.</p>
      <div data-testid="home-do-now-all">
        {allItems.map((item, i) => <DoNowRow key={item.id || i} item={item} testId="home-do-now-all-row" />)}
      </div>
    </W7DetailSheet>}
    <div style={{ display: 'grid', gap: 12 }}>
      <W7Panel title="Protection">
        <div style={grid}>
          <W7Metric label="With an active broker stop" value={stops.active_count != null && stops.position_count != null ? `${stops.active_count} of ${stops.position_count}` : text(stops.active_count)} detail={stops.pending_count == null ? undefined : `${stops.pending_count} pending activation`} />
          <W7Metric label="Awaiting fill" value={awaiting.length || filledAwaitingSync.length
            ? [...new Set([...awaiting, ...filledAwaitingSync].map(p => p.symbol))].join(', ') : text(stops.awaiting_fill_count)}
            detail={filledAwaitingSync.length ? <span data-testid="home-filled-awaiting-sync">{filledAwaitingSync.map(p => `${p.symbol}${p.account_label ? ` (${p.account_label})` : ''}: ${p.reason || 'stop filled · awaiting holdings sync'}`).join('; ')}</span> : undefined} />
          <W7Metric label="Nearest active stop" value={nearest ? `${nearest.symbol} ${pct(nearest.distance_pct)}` : 'Not available'} />
        </div>
        {stops.last_broker_read_label && <p data-testid="home-stops-as-of" style={{ color: TOKENS.text[2], margin: '8px 0 0' }}>As of last broker read {stops.last_broker_read_label}</p>}
        {stopsGap && <W7Gap>{stopsGap}</W7Gap>}
        <p><Link to="/risk" style={linkStyle}>All positions and stops → Risk</Link></p>
      </W7Panel>
      <W7Panel title="CIO view of the market">
        <p data-testid="home-regime">Regime <b>{text(regime.label, 'Not classified')}</b> since <b>{since}</b> · VIX <b>{vix}</b></p>
        <p style={{ color: TOKENS.text[2] }}>{when(regime.as_of)}{regime.stale ? ' · Last published view; refresh overdue' : ''}</p>
        {regime.vix_gap && <W7Gap>{gapText(regime.vix_gap)}</W7Gap>}
        {regime.gap && <W7Gap>{gapText(regime.gap)}</W7Gap>}
        <p>Favoured sectors: {Array.isArray(favoured) ? favoured.length ? favoured.join(', ') : 'None favoured' : 'Not published'}</p>
        {!Array.isArray(favoured) && data.sectors?.favoured_gap && <W7Gap>{gapText(data.sectors.favoured_gap)}</W7Gap>}
        <Link to="/watch?tab=sectors" style={linkStyle}>Sector trends and leaders →</Link>
      </W7Panel>
      <W7Panel title="Waiting on you">
        <div style={line}><Link to="/trading?tab=Proposals" style={linkStyle}>Approvals</Link><b data-testid="home-approvals-count" style={mono}>{text(approvals.total)}</b></div>
        {approvals.gap && <W7Gap>{gapText(approvals.gap)}</W7Gap>}
        <div style={line}><Link to="/cio/questions" style={linkStyle}>Questions answered</Link><b data-testid="home-questions-count" style={mono}>{questionCount}</b></div>
        {questions.gap && <W7Gap>{gapText(questions.gap)}</W7Gap>}
        <div style={line}><Link to="/system/releases" style={linkStyle}>Releases to merge</Link><b data-testid="home-releases-count" style={mono}>{releaseCount}</b></div>
        {releases.gap && <W7Gap>{gapText(releases.gap)}</W7Gap>}
      </W7Panel>
    </div>
  </div>
}
