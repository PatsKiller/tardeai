import { Link } from 'react-router-dom'
import W7DetailSheet, { useW7Detail } from '../W7DetailSheet'
import { RADIUS, TOKENS, TYPE, chipStyle, numStyle, toneVars } from '../../lib/designTokens'
import { useMarketEvent } from '../../hooks/useMarketEvent'
import {
  candidateSubline, candidateTone, fmtNum, fmtPctSigned, fmtPrice, fmtUsd, gateTone, trancheStatusLabel,
  type Candidate, type Gate, type MarketEvent,
} from '../../lib/marketEvent'

const card = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, padding: 12, display: 'flex', flexDirection: 'column' as const, gap: 8, minWidth: 0 }
const muted = { color: TOKENS.text[2], fontSize: TYPE.base }

const Chip = ({ tone, children }: { tone: Parameters<typeof chipStyle>[0]; children: React.ReactNode }) => <span style={chipStyle(tone)}>{children}</span>
const GateChips = ({ gates }: { gates: Gate[] }) => gates.length === 0 ? null : (
  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{gates.map(g => <Chip key={g.id} tone={gateTone(g.state)}>{g.label}</Chip>)}</div>
)
const Row = ({ k, v, tone }: { k: string; v: React.ReactNode; tone?: string }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, borderTop: `1px solid ${TOKENS.borderSubtle}`, padding: '8px 0', fontSize: TYPE.base }}>
    <span style={{ color: TOKENS.text[2] }}>{k}</span><span style={{ ...numStyle, textAlign: 'right', color: tone ?? TOKENS.text[0] }}>{v}</span>
  </div>
)

function Detail({ c, ev }: { c: Candidate; ev: MarketEvent }) {
  const stateLabel = c.state === 'READY' ? 'READY · tranche 1 of 3' : c.state
  return (
    <div data-testid="market-event-detail" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div><Chip tone={candidateTone(c.state)}>{stateLabel}</Chip>{c.fell_for_reason && <> <Chip tone="danger">FELL FOR A REASON</Chip></>}</div>
      <GateChips gates={c.gates} />
      <div style={card}>
        <Row k={`Drawdown from baseline${ev.episode?.baseline_date ? ` (${ev.episode.baseline_date})` : ''}`} v={fmtPctSigned(c.drawdown_pct)} tone={c.drawdown_pct != null && c.drawdown_pct < 0 ? TOKENS.danger : undefined} />
        <Row k="Beta-expected drawdown" v={fmtPctSigned(c.beta_expected_drawdown_pct)} />
        <Row k="Last · baseline price" v={`${fmtPrice(c.last_price)} · ${fmtPrice(c.baseline_price)}`} />
        <Row k="Discount score" v={fmtNum(c.discount_score, 0)} />
        <Row k="Quality score" v={fmtNum(c.quality_score, 0)} />
        <Row k="Forward P/E · sector median" v={`${fmtNum(c.fwd_pe)} · ${fmtNum(c.sector_median_pe)}`} />
        <Row k="PEG · ROIC" v={`${fmtNum(c.peg)} · ${c.roic_pct == null ? 'not on file' : `${c.roic_pct.toFixed(0)}%`}`} />
        <Row k="Orders / backlog" v={c.orders_backlog ?? 'not on file'} />
        <Row k="Why it fell" v={c.reason_evidence ?? 'not on file'} />
      </div>
      <div style={card} data-testid="market-event-plan">
        <b style={{ fontSize: TYPE.base }}>Tranche plan · 30 / 30 / 40</b>
        {!c.plan || c.plan.tranches.length === 0 ? <span style={muted}>No plan yet: {c.state === 'READY' ? 'not on file' : 'the name is not READY'}.</span> : <>
          {c.plan.tranches.map((t, i) => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: 8, borderTop: `1px solid ${TOKENS.borderSubtle}`, padding: '8px 0', fontSize: TYPE.base }}>
              <Chip tone={t.status === 'now' ? 'success' : 'neutral'}>T{t.n}</Chip>
              <span>{t.account_label}{t.shares != null ? ` · ${t.shares} sh` : ''}{t.usd != null ? ` · ${fmtUsd(t.usd)}` : ''}
                <span style={{ display: 'block', ...muted }}>{t.entry_low != null && t.entry_high != null ? `entry zone ${fmtPrice(t.entry_low)}–${fmtPrice(t.entry_high)}` : t.condition ?? `${t.pct ?? '—'}%`}</span></span>
              <span style={{ ...numStyle, ...muted }}>{trancheStatusLabel(t)}</span>
            </div>))}
          <Row k="Invalidation (new low below)" v={fmtPrice(c.plan.invalidation)} tone={TOKENS.danger} />
          <Row k="Risk if invalidated (T1)" v={c.plan.risk_usd == null ? 'not on file' : `${fmtUsd(c.plan.risk_usd)} of ${fmtUsd(c.plan.risk_budget_usd)} budget`} />
          {c.plan.notes.map((n, i) => <div key={i} style={muted}>{n}</div>)}
        </>}
      </div>
      <div style={{ ...muted, border: `1px dashed ${TOKENS.border}`, borderRadius: RADIUS.lg, padding: '8px 10px' }}>
        Source: {c.source.length ? c.source.join(', ') : 'market-event read model'} · computed {ev.computed_at ?? 'unknown'}. Advisory plan text, not an order.
      </div>
    </div>
  )
}

/** The Event section of the Re-Entry desk (spec §4.6): episode card, per-account cash, ranked candidate list, full-screen detail sheet. */
export default function MarketEventSection() {
  const { event, banner, loading, error } = useMarketEvent()
  const detail = useW7Detail()
  if (!event) {
    return <div data-testid="market-event-section" style={card}>{loading && !error ? <span style={muted}>Loading the market event…</span>
      : banner.kind === 'hidden' ? <span style={muted}>The market-event feed is not live yet (route not found). Nothing to report.</span>
      : <span style={{ color: TOKENS.danger, fontSize: TYPE.base }}>Market event status unavailable{error ? `: ${error}` : ''}. This is not an all-clear.</span>}</div>
  }
  if (!event.episode || event.episode.state === 'CLOSED') {
    return <div data-testid="market-event-section" style={card}><span style={muted}>No market event is open.</span></div>
  }
  const ep = event.episode
  const tone = banner.kind === 'event' ? banner.tone : 'warning'
  const selected = detail.selected ? event.candidates.find(c => c.symbol === detail.selected) : undefined
  return (
    <div data-testid="market-event-section" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}><b>{ep.title}</b><Chip tone={tone}>{ep.state === 'OPEN' ? ep.tier ?? 'OPEN' : ep.state}</Chip></div>
        <div style={muted}>{ep.summary ?? ''}{ep.baseline_date ? ` Baseline close ${ep.baseline_date}.` : ''} {event.candidates.length} candidates{event.stale ? ` · STALE, as of ${event.computed_at ?? 'unknown'}` : ''}</div>
        <GateChips gates={event.market_gate.chips} />
      </div>
      <div style={card} data-testid="market-event-cash">
        <b style={{ fontSize: TYPE.base }}>Cash to deploy (reserve kept per account)</b>
        {event.accounts.length === 0 ? <span style={muted}>Account cash not on file.</span> : event.accounts.map(a => <Row key={a.account_label} k={a.account_label} v={`${fmtUsd(a.deployable_usd)} deployable`} />)}
      </div>
      <div style={card} data-testid="market-event-candidates">
        <div style={{ display: 'flex', justifyContent: 'space-between' }}><b style={{ fontSize: TYPE.base }}>Candidates · by rank</b><span style={muted}>top {event.candidates.length}</span></div>
        {event.candidates.length === 0 && <span style={muted}>No candidates on file.</span>}
        {event.candidates.map(c => (
          <button key={c.symbol} type="button" data-testid="market-event-candidate" data-symbol={c.symbol} onClick={() => detail.open(c.symbol)}
            style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '2px 10px', minHeight: 56, padding: '10px 0', border: 0, borderTop: `1px solid ${TOKENS.borderSubtle}`, background: 'transparent', color: TOKENS.text[0], textAlign: 'left', font: 'inherit', cursor: 'pointer' }}>
            <span><b>{c.symbol}</b> <Chip tone={candidateTone(c.state)}>{c.state}</Chip>{c.fell_for_reason && <> <Chip tone="danger">FELL FOR A REASON</Chip></>}</span>
            <span style={{ ...numStyle, textAlign: 'right', color: c.drawdown_pct != null && c.drawdown_pct < 0 ? toneVars('danger').color : TOKENS.text[1] }}>{fmtPctSigned(c.drawdown_pct)}</span>
            <span style={muted}>{candidateSubline(c)}</span><span style={{ ...muted, textAlign: 'right' }}>tap →</span>
          </button>))}
      </div>
      <div style={{ ...muted, border: `1px dashed ${TOKENS.border}`, borderRadius: RADIUS.lg, padding: '8px 10px' }}>Advisory only. The CIO owns each account's verdict. Nothing here places or sizes an order.</div>
      {detail.selected && (selected
        ? <W7DetailSheet title={selected.symbol} onClose={detail.close}><Detail c={selected} ev={event} /></W7DetailSheet>
        : <W7DetailSheet title={detail.selected} onClose={detail.close}><div style={muted}>{detail.selected} is not in the current candidate list.</div></W7DetailSheet>)}
      <Link to="/portfolio/re-entry" style={{ color: TOKENS.info, minHeight: 44, display: 'flex', alignItems: 'center', fontSize: TYPE.base }}>← Back to the Re-Entry desk</Link>
    </div>
  )
}
