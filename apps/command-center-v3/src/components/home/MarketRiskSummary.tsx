/** The YELLOW market-risk summary card on Home (design home/v005 when the projection carries the v005 data — verdict
 *  with dollars, top review item, sectors, re-entry, positions, review, budgets, "Why the score is N" — else home/v004, builds on home/v002; DSN-20261031-market-risk-ui).
 *  Sits in the v002 banner slot, above the header, never sticky, and only for an evaluated YELLOW (live or shadow, fresh
 *  or stale). Calm warning tone: the ordinary card surface with a warning left rule and a soft pill, not the ORANGE/RED
 *  alarm fill. Collapsible: collapsed by default on phone (≤820 px), open on desktop; the viewer's choice is remembered
 *  in browser storage as a convenience only. No Acknowledge: YELLOW never pages and has no episode. Tokens only. No
 *  order, size or stop control exists here — this is advisory UI (MBI_BEHAVIOR = 0). */
import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { RADIUS, TOKENS, TYPE, chipStyle, numStyle, toneVars } from '../../lib/designTokens'
import { SUMMARY_OPEN_KEY, SUMMARY_PHONE_MAX_PX, actionableModel, summaryDefaultOpen, summaryModel, type MarketRisk } from '../../lib/marketRisk'
import { ActionableBody, ActionableHead, TopReview } from './MarketRiskActionable'
import { ActionsTop, Explain } from './MarketRiskActions'
import { ShadowTag } from './MarketRiskBanner'

function readStored(): boolean | null {
  try {
    const v = window.localStorage.getItem(SUMMARY_OPEN_KEY)
    return v === '1' ? true : v === '0' ? false : null
  } catch { return null }
}

function writeStored(open: boolean) {
  try { window.localStorage.setItem(SUMMARY_OPEN_KEY, open ? '1' : '0') } catch { /* storage blocked: the default applies */ }
}

function isPhone(): boolean {
  try { return window.matchMedia(`(max-width: ${SUMMARY_PHONE_MAX_PX}px)`).matches } catch { return false }
}

const linkStyle = {
  minHeight: 44, minWidth: 44, display: 'inline-flex', alignItems: 'center', boxSizing: 'border-box' as const, padding: '0 2px',
  color: TOKENS.info, fontWeight: 700, fontSize: TYPE.md, textDecoration: 'none',
}

export function MarketRiskSummary({ mr }: { mr: MarketRisk | null }) {
  const m = summaryModel(mr)
  // design home/v005: the actionable card when the projection carries the v005 data; the v004 card otherwise
  const a = m && !m.stale ? actionableModel(mr) : null
  const bodyId = useId()
  // The viewer's tap this session; until then the default (phone/desktop, stale, remembered choice) decides. Computed
  // per render so a projection that arrives after first paint (or turns stale) still gets its own default.
  const [choice, setChoice] = useState<boolean | null>(null)
  if (!m || !mr) return null
  const open = choice ?? summaryDefaultOpen({ phone: isPhone(), stale: m.stale, stored: m.stale ? null : readStored() })
  const warn = toneVars('warning')
  const toggle = () => { const next = !open; setChoice(next); if (!m.stale) writeStored(next) }
  const links = (
    <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
      {m.links.map(l => <Link key={l.to} to={l.to} data-testid={l.testid} style={linkStyle}>{l.label}</Link>)}
    </div>
  )
  return (
    <section data-testid="home-market-risk-summary" data-open={open ? 'true' : 'false'} data-stale={m.stale ? 'true' : 'false'}
      aria-label="Market risk summary"
      style={{ display: 'flex', flexDirection: 'column', gap: 0, borderRadius: RADIUS.lg, background: TOKENS.bg[1],
        border: `1px solid ${TOKENS.border}`, borderLeft: `4px solid ${warn.color}`, padding: '4px 14px 4px 14px' }}>
      {/* Phone (≤820): "N of 9" sits in the evaluated line; wider: in the summary row (SPEC v004, expanded item 1). */}
      <style>{`@media(max-width:${SUMMARY_PHONE_MAX_PX}px){[data-testid="home-market-risk-summary"] .mr-summary-wide{display:none}}@media(min-width:${SUMMARY_PHONE_MAX_PX + 1}px){[data-testid="home-market-risk-summary"] .mr-summary-narrow{display:none}}`}</style>
      <button type="button" data-testid="home-market-risk-summary-toggle" aria-expanded={open} aria-controls={bodyId} onClick={toggle}
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'stretch', gap: 6, minHeight: 44, width: '100%', boxSizing: 'border-box',
          padding: '8px 0', background: 'transparent', border: 0, color: 'inherit', font: 'inherit', textAlign: 'left', cursor: 'pointer' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: '6px 10px', flexWrap: 'wrap', width: '100%' }}>
          <span data-testid="home-market-risk-summary-tier" style={chipStyle('warning', 'soft', 'md')}>YELLOW</span>
          <span style={{ fontSize: TYPE.md, fontWeight: 700, color: TOKENS.text[0] }}>
            Market risk{m.score != null && <> <span style={{ ...numStyle }}>{m.score}</span><span style={{ ...numStyle, fontWeight: 400, color: TOKENS.text[2] }}>/100</span></>}
          </span>
          <ShadowTag mr={mr} testid="home-market-risk-summary-shadow" />
          {open && !m.stale && m.confirm && <span className="mr-summary-wide" data-testid="home-market-risk-summary-confirm-wide" style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{m.confirm}</span>}
          <span aria-hidden="true" style={{ marginLeft: 'auto', fontSize: TYPE.base, fontWeight: 700, color: TOKENS.text[1], whiteSpace: 'nowrap' }}>{open ? 'Less ▴' : 'Details ▾'}</span>
        </span>
        {a ? <ActionableHead m={a} /> : (!open || m.stale) && (
          <span data-testid="home-market-risk-summary-line" style={{ fontSize: TYPE.base, lineHeight: 1.5, color: m.stale ? warn.color : TOKENS.text[1] }}>{m.line}</span>
        )}
      </button>
      {a && (a.protect || a.hedge || a.rotate ? <ActionsTop m={a} open={open} /> : <TopReview m={a} />)}
      <div id={bodyId} data-testid="home-market-risk-summary-body" hidden={!open} style={{ paddingBottom: 10 }}>
        {a ? (
          <ActionableBody m={a} why={(
            <div data-testid="mr-why" style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
              <h3 style={{ margin: 0, fontSize: TYPE.base, color: TOKENS.text[2], textTransform: 'uppercase', letterSpacing: '.05em', fontWeight: 700 }}>Why the score is {m.score ?? '—'}</h3>
              <div style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{m.evaluated}{m.confirm ? ` · ${m.confirm}` : ''}</div>
              {m.contributors.map((c, i) => (
                <div key={i} data-testid="home-market-risk-summary-contributor" style={{ display: 'flex', alignItems: 'baseline', gap: 10, fontSize: TYPE.md, lineHeight: 1.4 }}>
                  <span style={{ flex: '1 1 0%', minWidth: 0, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>{c.name}{c.detail ? <span style={{ color: TOKENS.text[2] }}> · {c.detail}</span> : null}{/P\/C OI/.test(c.detail ?? '') && <> <Explain term="pc_oi" /></>}</span>
                  <span style={{ ...numStyle, flex: '0 0 auto', fontWeight: 700, color: TOKENS.text[1], textAlign: 'right' }}>{c.points}</span>
                </div>
              ))}
              {mr.book?.vulnerability != null && <div data-testid="mr-why-vulnerability" style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>Portfolio vulnerability <Explain term="vulnerability" /> <span style={numStyle}>{mr.book.vulnerability}</span>/100</div>}
              {m.uplift && <div style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{m.uplift}</div>}
              {m.notMeasured && <div data-testid="home-market-risk-summary-not-measured" style={{ fontSize: TYPE.sm, color: TOKENS.text[3], lineHeight: 1.5 }}>{m.notMeasured}</div>}
              {m.deescalates && <div data-testid="home-market-risk-summary-deescalates" style={{ fontSize: TYPE.base, color: TOKENS.text[2], lineHeight: 1.5 }}><b style={{ color: TOKENS.text[0] }}>De-escalates if</b> {m.deescalates}</div>}
              <div data-testid="home-market-risk-summary-footer" style={{ fontSize: TYPE.sm, color: TOKENS.text[3], lineHeight: 1.5 }}>{m.footer}{mr.carried_only ? <> <Explain term="carried" /></> : mr.mode === 'shadow' ? <> <Explain term="shadow" /></> : null}</div>
              {links}
            </div>
          )} />
        ) : m.stale ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ fontSize: TYPE.base, color: TOKENS.text[2], lineHeight: 1.5 }}>{m.footer}</div>
            {links}
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 340px), 1fr))', gap: '10px 20px', alignItems: 'start' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
              <div style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{m.evaluated}{m.confirm ? <span className="mr-summary-narrow"> · {m.confirm}</span> : null}</div>
              {m.contributors.map((c, i) => (
                <div key={i} data-testid="home-market-risk-summary-contributor" style={{ display: 'flex', alignItems: 'baseline', gap: 10, fontSize: TYPE.md, lineHeight: 1.4 }}>
                  <span style={{ flex: '1 1 0%', minWidth: 0, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>{c.name}{c.detail ? <span style={{ color: TOKENS.text[2] }}> · {c.detail}</span> : null}</span>
                  <span style={{ ...numStyle, flex: '0 0 auto', fontWeight: 700, color: TOKENS.text[1], textAlign: 'right' }}>{c.points}</span>
                </div>
              ))}
              {m.uplift && <div style={{ fontSize: TYPE.base, color: TOKENS.text[2], borderTop: `1px solid ${TOKENS.borderSubtle}`, paddingTop: 6 }}>{m.uplift}</div>}
              {m.notMeasured && <div data-testid="home-market-risk-summary-not-measured" style={{ fontSize: TYPE.sm, color: TOKENS.text[3], lineHeight: 1.5 }}>{m.notMeasured}</div>}
              {m.deescalates && <div data-testid="home-market-risk-summary-deescalates" style={{ fontSize: TYPE.base, color: TOKENS.text[2], lineHeight: 1.5 }}><b style={{ color: TOKENS.text[0] }}>De-escalates if</b> {m.deescalates}</div>}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
              {m.book && (
                <div data-testid="home-market-risk-summary-book" style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: TYPE.base, lineHeight: 1.5, color: TOKENS.text[1], padding: 12, borderRadius: RADIUS.md, background: TOKENS.bg[0], border: `1px solid ${TOKENS.borderSubtle}` }}>
                  <b style={{ color: TOKENS.text[0], fontSize: TYPE.md }}>Your book</b>
                  {m.book.vulnerability && <span>Vulnerability <b style={{ ...numStyle, color: TOKENS.text[0] }}>{m.book.vulnerability}</b></span>}
                  {m.book.breaches.length > 0 && <span>{m.book.breaches.length} budget breach{m.book.breaches.length === 1 ? '' : 'es'}: {m.book.breaches.join(' · ')}</span>}
                  {(m.book.nearStop.length > 0 || m.book.otherDrivers) && (
                    <span>{m.book.nearStop.length > 0 && <>Near a stop: {m.book.nearStop.join(' · ')}</>}{m.book.nearStop.length > 0 && m.book.otherDrivers ? ' · ' : ''}{m.book.otherDrivers && <>Driving vulnerability: {m.book.otherDrivers}</>}</span>
                  )}
                  <span style={{ color: TOKENS.text[3] }}>{m.book.note}</span>
                </div>
              )}
              <div data-testid="home-market-risk-summary-footer" style={{ fontSize: TYPE.sm, color: TOKENS.text[3], lineHeight: 1.5 }}>{m.footer}</div>
              {links}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
