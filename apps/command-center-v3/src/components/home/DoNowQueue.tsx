import { useState } from 'react'
import { Link } from 'react-router-dom'
import { RADIUS, TOKENS, TYPE, numStyle, toneVars } from '../../lib/designTokens'
import { TABS, TOP_N, ageLabel, money, severityTone, visibleItems, type DoNowItem, type DoNowModel, type Tab } from '../../lib/homeDoNow'

// Home "Do now" (operator-approved Home redesign, 2026-10-22). ONE queue over GET /api/v2/home/do-now (data-broker
// projection home_do_now) replacing Needs action, Requires attention, Operator inbox, Top risks and Platform.
// Tabs Protect money / Decide / Fix system, top 7 + Show all, one action button per item, sorted by the server:
// money at risk first, then severity. "Nothing to do" only when every source answered (lib/homeDoNow.ts).

function itemTip(it: DoNowItem): string {
  return [
    it.why,
    it.money != null ? `Money at risk: ${money(it.money)} (${it.moneyBasis ?? 'basis not stated'})` : 'No money at risk on this item',
    `Sources: ${it.sources.join(', ') || 'unknown'}`,
    it.since ? `Since ${it.since}` : null,
  ].filter(Boolean).join('\n')
}

function sourcesTip(m: DoNowModel): string {
  return m.sources.map(s => `${s.name}: ${s.status}${s.stale ? ' · STALE' : ''} · ${s.basis ?? 'no clock'} ${s.asOf ?? ''}${s.ageS != null ? ` (${ageLabel(s.ageS)} old)` : ''}${s.error ? ` · ${s.error}` : ''}`).join('\n')
}

export default function DoNowQueue({ model }: { model: DoNowModel }) {
  const [tab, setTab] = useState<Tab>('all')
  const [showAll, setShowAll] = useState(false)
  const { shown, total } = visibleItems(model, tab, showAll)
  const m = model
  const danger = toneVars('danger')
  return (
    <section data-testid="do-now" aria-label="Do now"
      style={{ flex: '999 1 560px', minWidth: 0, background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 10, padding: '12px 14px', borderBottom: `1px solid ${TOKENS.border}` }}>
        <h2 style={{ margin: 0, fontSize: TYPE.lg, fontWeight: 700, color: TOKENS.text[0] }}>Do now</h2>
        <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>sorted by money at risk, then urgency</span>
        <span style={{ flex: 1 }} />
        <span data-testid="do-now-sources" title={sourcesTip(m)} style={{ fontSize: TYPE.xs, cursor: 'help',
          color: m.unavailableSources.length || m.staleSources.length || m.state === 'STALE' ? TOKENS.warning : TOKENS.text[3] }}>
          {m.state === 'LOADING' ? 'checking sources…'
            : `${m.sources.length - m.unavailableSources.length}/${m.sources.length} sources answered`
              + (m.staleSources.length ? ` · ${m.staleSources.length} stale` : '')
              + (m.state === 'STALE' ? ' · queue STALE' : '')}
        </span>
      </div>
      <div role="group" aria-label="Queue filter" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '8px 14px', borderBottom: `1px solid ${TOKENS.borderSubtle}` }}>
        {TABS.map(t => {
          const on = tab === t.key
          return (
            <button key={t.key} type="button" aria-pressed={on} data-testid={`do-now-tab-${t.key}`}
              onClick={() => { setTab(t.key); setShowAll(false) }}
              style={{ borderRadius: RADIUS.pill, padding: '5px 12px', fontSize: TYPE.sm, fontWeight: 600, cursor: 'pointer', minHeight: 32, fontFamily: 'inherit',
                background: on ? TOKENS.bg[3] : 'transparent', border: `1px solid ${on ? TOKENS.info : TOKENS.border}`, color: on ? TOKENS.text[0] : TOKENS.text[2] }}>
              {t.label} <span style={{ ...numStyle, opacity: 0.85 }}>{m.state === 'LOADING' ? '…' : m.counts[t.key]}</span>
            </button>
          )
        })}
      </div>
      {m.state === 'LOADING' && <div style={{ padding: 14, fontSize: TYPE.base, color: TOKENS.text[3] }}>Checking every source…</div>}
      {m.state === 'UNAVAILABLE' && (
        <div role="alert" data-testid="do-now-unavailable" style={{ padding: 14, fontSize: TYPE.base, color: TOKENS.warning }}>
          Do-now UNAVAILABLE{m.reason ? ` · ${m.reason}` : ''} — this is not an all-clear.
        </div>
      )}
      {m.state === 'CLEAR' && (
        <div data-testid="do-now-clear" style={{ padding: 14, fontSize: TYPE.base, color: TOKENS.success }}>Nothing to do — every source answered.</div>
      )}
      {m.state === 'STALE' && (
        <div data-testid="do-now-stale" style={{ padding: '8px 14px 0', fontSize: TYPE.sm, color: TOKENS.warning }}>STALE{m.reason ? ` (${m.reason})` : ''} — the queue below may be out of date.</div>
      )}
      {shown.length === 0 && (m.state === 'ITEMS' || m.state === 'STALE') && (
        <div style={{ padding: 14, fontSize: TYPE.base, color: TOKENS.text[3] }}>Nothing in this tab.</div>
      )}
      <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {shown.map(it => {
          const tone = toneVars(severityTone(it.severity))
          const protect = it.category === 'protect'
          return (
            <li key={it.id} data-testid="do-now-item" data-category={it.category}
              style={{ display: 'grid', gridTemplateColumns: '34px minmax(0, 1fr) auto', gap: 12, alignItems: 'center', padding: '10px 14px', borderBottom: `1px solid ${TOKENS.borderSubtle}` }}>
              <span title={`${it.severity}: ${it.severity === 'P0' ? 'act now' : it.severity === 'P1' ? 'today' : it.severity === 'P2' ? 'this week' : 'when convenient'}`}
                style={{ fontSize: TYPE.sm, fontWeight: 700, textAlign: 'center', padding: '2px 0', borderRadius: RADIUS.sm, color: tone.color, background: tone.bg, border: `1px solid ${tone.border}` }}>
                {it.severity}
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }} title={itemTip(it)}>
                <span style={{ fontSize: TYPE.md, fontWeight: 600, lineHeight: 1.35, color: TOKENS.text[0] }}>
                  {it.title}
                  {it.money != null && <span style={{ ...numStyle, fontSize: TYPE.sm, color: TOKENS.text[2], fontWeight: 500 }}> · {money(it.money)} at risk</span>}
                </span>
                <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2], lineHeight: 1.4, overflowWrap: 'anywhere' }}>{it.why}</span>
              </div>
              <Link to={it.where} data-testid="do-now-action"
                style={{ whiteSpace: 'nowrap', fontSize: TYPE.sm, fontWeight: 600, padding: '8px 12px', borderRadius: RADIUS.md, minHeight: 36, boxSizing: 'border-box', display: 'inline-flex', alignItems: 'center', textDecoration: 'none',
                  background: protect ? danger.bg : TOKENS.bg[2], border: `1px solid ${protect ? danger.border : TOKENS.border}`, color: protect ? danger.color : TOKENS.text[0] }}>
                {it.actionLabel}
              </Link>
            </li>
          )
        })}
      </ol>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, padding: '8px 14px', flexWrap: 'wrap' }}>
        <span data-testid="do-now-footer" style={{ fontSize: TYPE.sm, color: TOKENS.text[3] }}
          title="Items from several sources about the same thing (one symbol's stop, the pending proposals) are merged into one row that lists every source.">
          {shown.length} of {total} shown
          {m.rolledUp.raw != null && m.rolledUp.afterDedupe != null && m.rolledUp.raw > m.rolledUp.afterDedupe ? ` · ${m.rolledUp.raw} source items merged into ${m.rolledUp.afterDedupe}` : ''}
          {m.rolledUp.inboxTotal != null ? ` · ${m.rolledUp.inboxTotal} inbox items rolled up` : ''}
        </span>
        {total > TOP_N && (
          <button type="button" data-testid="do-now-show-all" onClick={() => setShowAll(s => !s)}
            style={{ background: 'none', border: 'none', color: TOKENS.info, cursor: 'pointer', fontSize: TYPE.base, padding: '8px 4px', minHeight: 36, fontFamily: 'inherit' }}>
            {showAll ? `Show top ${TOP_N}` : `Show all ${total}`}
          </button>
        )}
      </div>
    </section>
  )
}
