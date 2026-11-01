/** Market risk on Home — the header fact, the Orange/Red banner with Acknowledge, and the compact block for the
 *  "Market in one look" card (design home/v002, DSN-20261031-market-risk-ui P1-T1).
 *  Reads GET /api/v2/market-risk/latest through the caller; Acknowledge POSTs /api/v2/market-risk/ack and shows the
 *  server's answer verbatim (until the episodes store exists the server refuses with the reason). Tokens only. No order,
 *  size or stop control exists here — this is advisory UI (MBI_BEHAVIOR = 0). */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { RADIUS, TOKENS, TYPE, numStyle, toneVars } from '../../lib/designTokens'
import { SHADOW_MARKER, SUMMARY_PHONE_MAX_PX, markerRest, actionableModel, bannerVisible, contributorsLine, episodeLine, factLine, fmtPct, pointsSum, shadowMarker, shortTime, tierTone, type MarketRisk } from '../../lib/marketRisk'
import { ActionableBody, ActionableHead, TopReview } from './MarketRiskActionable'

const tap = { minHeight: 44, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', boxSizing: 'border-box' as const, textDecoration: 'none', fontWeight: 600, fontSize: TYPE.md, borderRadius: RADIUS.md, padding: '0 14px' }

/** The shadow label beside a tier pill: a label only, no new widget (UI change control). Nothing when live. The
 *  explanation is visible text, not a title tooltip — touch has no hover (review of PR 2425). */
export function ShadowTag({ mr, testid }: { mr: MarketRisk | null; testid: string }) {
  if (!shadowMarker(mr)) return null
  return <span data-testid={testid}
    style={{ fontSize: TYPE.sm, color: TOKENS.text[1], border: `1px dashed ${toneVars('warning').border}`, borderRadius: RADIUS.pill, padding: '2px 8px' }}>
    <b style={{ fontWeight: 800, letterSpacing: '0.04em', color: toneVars('warning').color }}>{shadowMarker(mr).split(' ')[0]}</b> · {markerRest(mr)} — {shadowMarker(mr) === SHADOW_MARKER ? 'no alert was sent for this tier' : (mr?.alerts?.sends ?? 0) > 0 ? 'the tier rests on data from before the market closed' : 'the tier rests on data from before the market closed; no alert sent'}
  </span>
}

/** Header fact (replaces the "Market" fact; the old regime/VIX text moved to the Market-in-one-look card). */
export function MarketRiskFact({ mr, loading }: { mr: MarketRisk | null; loading?: boolean }) {
  const f = factLine(mr)
  const tv = toneVars(f.tone)
  return (
    <Link to="/risk?tab=market-risk" data-testid="home-market-risk" title="Market Risk Engine tier and score (GET /api/v2/market-risk/latest). Tap for the categories, your budget, probabilities and the alert log."
      style={{ display: 'flex', flexDirection: 'column', gap: 2, minHeight: 44, textDecoration: 'none', cursor: 'pointer' }}>
      <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2], textTransform: 'uppercase', letterSpacing: '0.04em' }}>Market risk</span>
      <span data-testid="home-market-risk-value" style={{ ...numStyle, fontSize: TYPE.lg, fontWeight: 700, color: f.tone === 'neutral' ? TOKENS.text[0] : tv.color }}>{loading && !mr ? '…' : f.value}</span>
      <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{loading && !mr ? '' : shadowMarker(mr)
        ? <><b data-testid="home-market-risk-shadow" style={{ fontWeight: 800, letterSpacing: '0.04em', color: toneVars('warning').color }}>{shadowMarker(mr).split(' ')[0]}</b> · {markerRest(mr)}{f.sub.slice(shadowMarker(mr).length)}</>
        : f.sub}</span>
    </Link>
  )
}

/** Compact block for the "Market in one look" card: tier pill + score + the five contributors. */
export function MarketRiskCompact({ mr }: { mr: MarketRisk | null }) {
  if (!mr) return <div data-testid="home-market-risk-compact" style={{ fontSize: TYPE.base, color: TOKENS.text[3] }}>Market risk unavailable.</div>
  const tv = toneVars(tierTone(mr.tier))
  if (mr.state === 'not_evaluated') {
    const flow = mr.sources?.options_flow
    return (
      <div data-testid="home-market-risk-compact" style={{ fontSize: TYPE.base, lineHeight: 1.5, color: TOKENS.text[1] }}>
        <b style={{ color: TOKENS.text[0] }}>Market risk: not yet evaluated.</b> {mr.reason}
        {flow?.findings?.length ? <> Options flow: {flow.findings.map(x => `${x.symbol} ${x.state.toLowerCase()}`).join(', ')} ({flow.as_of ? shortTime(flow.as_of) : 'time unavailable'}).</> : null}
      </div>
    )
  }
  return (
    <div data-testid="home-market-risk-compact" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: TYPE.sm, fontWeight: 800, letterSpacing: '0.04em', color: TOKENS.bg[0], background: tv.color, borderRadius: RADIUS.pill, padding: '3px 8px' }}>{mr.tier}</span>
        <ShadowTag mr={mr} testid="home-market-risk-compact-shadow" />
        <span style={{ ...numStyle, fontSize: TYPE.md, fontWeight: 700, color: TOKENS.text[0] }}>{mr.score != null ? `${Math.round(mr.score)}/100` : '—'}</span>
        {mr.confirming && <span style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>· {mr.confirming.n} of {mr.confirming.of} categories confirm</span>}
        {mr.state === 'stale' && <span style={{ fontSize: TYPE.base, color: toneVars('warning').color }}>· stale, last evaluation {shortTime(mr.as_of)}</span>}
      </div>
      {contributorsLine(mr) && <div style={{ fontSize: TYPE.base, color: TOKENS.text[1], lineHeight: 1.5 }}>{contributorsLine(mr)}</div>}
    </div>
  )
}

/** Full-width banner, visible only for an evaluated ORANGE or RED (design home/v002 §2). Never sticky. */
export function MarketRiskBanner({ mr }: { mr: MarketRisk | null }) {
  const [ack, setAck] = useState<{ busy: boolean; note: string | null }>({ busy: false, note: null })
  const [detailsOpen, setDetailsOpen] = useState<boolean | null>(null)
  if (!bannerVisible(mr) || !mr) return null
  // design home/v005: the banner is extended with the same verdict, exposure, top review item and sections
  const a = actionableModel(mr)
  let phone = false
  try { phone = window.matchMedia(`(max-width: ${SUMMARY_PHONE_MAX_PX}px)`).matches } catch { /* no matchMedia: desktop */ }
  const open = detailsOpen ?? !phone
  const tv = toneVars(tierTone(mr.tier))
  const sum = pointsSum(mr)
  const acked = !!mr.episode?.acknowledged_at
  const shadow = !!shadowMarker(mr)  // a shadow tier sent nothing and has no episode: nothing to acknowledge
  const acknowledge = async () => {
    setAck({ busy: true, note: null })
    try {
      const r = await fetch('/api/v2/market-risk/ack', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ episode_id: mr.episode?.id ?? null, episode_tier: mr.episode?.tier ?? null, tier: mr.tier, score: mr.score }) })
      const j: any = await r.json().catch(() => ({}))
      setAck({ busy: false, note: r.ok ? `Acknowledged ${shortTime(new Date().toISOString())}` : `Not recorded: ${j?.error ?? `HTTP ${r.status}`}${j?.detail ? ` — ${j.detail}` : ''}` })
    } catch (e) {
      setAck({ busy: false, note: `Not recorded: ${String(e)}` })
    }
  }
  return (
    <section data-testid="home-market-risk-banner" aria-label="Market risk banner" aria-live="polite"
      style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: 14, borderRadius: RADIUS.lg, background: tv.bg, border: `1px solid ${tv.border}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span data-testid="home-market-risk-tier" style={{ fontSize: TYPE.base, fontWeight: 800, letterSpacing: '0.04em', color: TOKENS.bg[0], background: tv.color, borderRadius: RADIUS.pill, padding: '4px 10px' }}>{mr.tier}</span>
        <ShadowTag mr={mr} testid="home-market-risk-banner-shadow" />
        <span style={{ ...numStyle, fontSize: TYPE.xl, fontWeight: 700, color: TOKENS.text[0] }}>MARKET RISK {mr.score != null ? Math.round(mr.score) : '—'}<span style={{ fontSize: TYPE.md, color: TOKENS.text[2] }}>/100</span></span>
      </div>
      <div style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>
        {episodeLine(mr) || `evaluated ${shortTime(mr.as_of)}`}{mr.confirming ? ` · ${mr.confirming.n} of ${mr.confirming.of} categories confirm` : ''} · evaluated {shortTime(mr.as_of)}
      </div>
      {a && <ActionableHead m={a} />}
      {a && <TopReview m={a} />}
      {a && (
        <button type="button" data-testid="home-market-risk-banner-details" aria-expanded={open} onClick={() => setDetailsOpen(!open)}
          style={{ ...tap, alignSelf: 'flex-start', border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1], color: TOKENS.text[0], padding: '0 14px', cursor: 'pointer' }}>
          {open ? 'Less ▴' : 'Details ▾'}
        </button>
      )}
      {a && open && <ActionableBody m={a} why={null} />}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: TYPE.md, lineHeight: 1.35 }}>
        {mr.contributors.slice(0, 5).map((c, i) => (
          <div key={i} data-testid="home-market-risk-contributor" style={{ display: 'grid', gridTemplateColumns: '1fr 48px', gap: 8 }}>
            <span style={{ color: TOKENS.text[0] }}>{c.name}{c.detail ? <span style={{ color: TOKENS.text[2] }}> · {c.detail}{c.as_of ? ` · ${shortTime(c.as_of)}` : ''}</span> : null}</span>
            <span style={{ ...numStyle, textAlign: 'right', color: tv.color }}>{c.points >= 0 ? '+' : ''}{Math.round(c.points)}</span>
          </div>
        ))}
        {mr.uplift && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 48px', gap: 8, borderTop: `1px solid ${tv.border}`, paddingTop: 6, color: TOKENS.text[2] }}>
            <span>{mr.uplift.note ?? `Market ${mr.uplift.market_score ?? '—'} → ${mr.tier} after portfolio vulnerability ${mr.uplift.vulnerability ?? '—'}`}</span>
            <span style={{ ...numStyle, textAlign: 'right', color: TOKENS.text[0] }}>= {mr.score != null ? Math.round(mr.score) : '—'}</span>
          </div>
        )}
        {sum != null && mr.score != null && Math.round(sum) !== Math.round(mr.score) && !mr.uplift && (
          <div style={{ fontSize: TYPE.sm, color: toneVars('warning').color }}>Contributors sum to {Math.round(sum)}, score is {Math.round(mr.score)} — the engine owes an explanation line.</div>
        )}
      </div>
      {mr.book && !a && (
        <div data-testid="home-market-risk-book" style={{ fontSize: TYPE.base, lineHeight: 1.45, color: TOKENS.text[1], padding: 10, borderRadius: RADIUS.md, background: TOKENS.bg[0] }}>
          <b style={{ color: TOKENS.text[0] }}>Your book:</b>{' '}
          {(mr.book.budgets ?? []).filter(b => b.breached).map(b => `${b.budget} ${b.actual}${b.unit ?? '%'} vs ${b.limit}${b.unit ?? '%'} budget`).join(' · ')}
          {(mr.book.positions ?? []).length ? ` · ${(mr.book.positions ?? []).map(p => `${p.symbol}${p.stop_distance_pct != null ? ` stop ${fmtPct(p.stop_distance_pct / 100)} below` : ''}${p.note ? ` (${p.note})` : ''}`).join(' · ')}` : ''}
          {mr.book.note ? ` ${mr.book.note}` : ''}
        </div>
      )}
      {mr.deescalates_if && <div style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}><b style={{ color: TOKENS.text[0] }}>De-escalates if</b> {mr.deescalates_if}</div>}
      <div style={{ fontSize: TYPE.sm, color: TOKENS.text[3] }}>Advisory. No order, size or stop level is implied.</div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" data-testid="home-market-risk-ack" onClick={acknowledge} disabled={ack.busy || acked || shadow}
          style={{ ...tap, flex: '1 1 140px', border: 0, background: tv.color, color: TOKENS.bg[0], fontWeight: 800, cursor: ack.busy || acked || shadow ? 'default' : 'pointer', opacity: acked || shadow ? 0.7 : 1 }}>
          {shadow ? `${shadowMarker(mr) === SHADOW_MARKER ? 'Shadow' : 'Carried'}: nothing to acknowledge` : acked ? `Acknowledged ${shortTime(mr.episode?.acknowledged_at)}` : ack.busy ? 'Recording…' : 'Acknowledge'}
        </button>
        <Link to="/risk?tab=market-risk" style={{ ...tap, flex: '1 1 110px', border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1], color: TOKENS.text[0] }}>Open Risk</Link>
        <Link to="/risk?tab=exposure" style={{ ...tap, flex: '1 1 110px', border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1], color: TOKENS.text[0] }}>Review stops</Link>
      </div>
      {ack.note && <div role="status" data-testid="home-market-risk-ack-note" style={{ fontSize: TYPE.base, color: ack.note.startsWith('Not recorded') ? toneVars('warning').color : toneVars('success').color }}>{ack.note}</div>}
    </section>
  )
}
