import { useState } from 'react'
import { BB, numStyle, terminalButton } from '../lib/watchlistTerminalTokens'
import {
  buildOperatorPresentation,
  operatorStateColor,
  type OperatorPresentation,
  type OperatorState,
} from '../lib/operatorDecisionCard'

/*
 * Calm operator presentation for the Watch Decision Desk.
 * Color is intentionally scarce: one state rail, one state word, and genuine
 * validation failures. Everything else is neutral hierarchy and whitespace.
 * Advisory only. No orders, approvals, broker writes, or 2FA.
 */

type Props = {
  packet: any
  generatedAt?: string
  actionPolicy?: any
  held?: boolean
  onRefresh?: (e: React.MouseEvent) => void
  onRefreshStrategy?: (e: React.MouseEvent) => void
  refreshing?: boolean
  onPrimary?: (pres: OperatorPresentation, e: React.MouseEvent) => void
  onAlert?: (pres: OperatorPresentation, e: React.MouseEvent) => void
}

const FAMILY_ORDER = [
  ['long_term', 'Long term'],
  ['swing', 'Swing'],
  ['bearish', 'Bearish'],
  ['options', 'Options'],
  ['no_trade', 'No trade'],
] as const

function asDate(value?: string | null): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? date : null
}
function clock(value?: string | null): string {
  const date = asDate(value)
  if (!date) return '—'
  return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York', timeZoneName: 'short' })
}
function age(value?: string | null): string {
  const date = asDate(value)
  if (!date) return '—'
  const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60_000))
  if (minutes < 1) return 'now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  return hours < 48 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`
}
function money(value: any): string {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(String(value).replace(/[$,]/g, ''))
  return Number.isFinite(parsed) ? `$${parsed.toFixed(2)}` : String(value)
}
function familyWord(key: string, family: any, overrides?: any): string {
  const override = overrides?.[key]
  if (override) return override[0]
  if (key === 'no_trade') return family?.preferred || family?.dominant ? 'PREFERRED' : family?.available ? 'ALTERNATIVE' : '—'
  const action = String(family?.action_state || '').toUpperCase()
  const decision = String(family?.decision_state || family?.state || '').toUpperCase()
  if (action === 'READY') return 'READY'
  if (action.startsWith('WAIT') || decision.startsWith('WAIT') || decision === 'CONDITIONAL') return 'WAIT'
  if (decision.includes('REJECT') || action.includes('REJECT')) return 'REJECTED'
  if (key === 'options' && (decision.includes('STALE') || action.includes('STALE'))) return 'CHAIN STALE'
  if (decision.includes('UNAVAILABLE') || action.includes('UNAVAILABLE') || decision.includes('DATA_UNAVAILABLE')) return 'UNAVAILABLE'
  if (decision.includes('ELIGIBLE') || decision.includes('VALID') || decision.includes('CONSTRUCT')) return 'AVAILABLE'
  return '—'
}
function familyReason(key: string, family: any): string {
  if (key === 'options') {
    const structures: any[] = family?.structures || []
    const reasons = [...(family?.rejection_reasons || []), ...structures.flatMap((structure: any) => structure?.rejection_reasons || [])].join(' · ')
    if (/chain|provider|schwab|quote/i.test(reasons) || String(family?.state || '').includes('UNAVAILABLE')) return 'Exact option chain unavailable'
    if (reasons) return reasons.slice(0, 96)
    if (structures.length) return `${structures.length} structures evaluated`
    return 'No eligible structure'
  }
  if (key === 'no_trade') return String(family?.reason || (family?.preferred ? 'Stand aside is currently preferred' : 'Valid alternative; does not override another selected family'))
  const reason = (family?.rejection_reasons || family?.blocks || [])[0]
  if (reason) return String(reason)
  const structure = (family?.structures || [])[0]
  if (structure?.structure) return String(structure.structure).replace(/_/g, ' ').toLowerCase()
  const word = familyWord(key, family)
  if (word === 'READY') return 'Mechanics resolved and current'
  if (word === 'WAIT') return 'Conditions are not yet confirmed'
  if (word === 'UNAVAILABLE') return 'Required evidence unavailable'
  if (word === 'REJECTED') return 'Eligibility or risk constraints failed'
  return 'No active construction'
}
function quietStateTone(word: string, preferred: boolean): string {
  if (!preferred) return BB.text2
  if (word === 'READY') return BB.green
  if (word === 'REJECTED') return BB.red
  if (word === 'WAIT' || word === 'PREFERRED' || word === 'CHAIN STALE') return BB.amber
  return BB.text1
}

export default function DecisionPacketBand({ packet, generatedAt, actionPolicy, held, onRefresh, onRefreshStrategy, refreshing, onPrimary, onAlert }: Props) {
  const [details, setDetails] = useState(false)
  const [whyOpen, setWhyOpen] = useState(false)
  const [prevOpen, setPrevOpen] = useState(false)
  const base = buildOperatorPresentation({ packet, actionPolicy, held })
  if (!base) return null
  const pres = { ...base } as OperatorPresentation
  const op = packet?.operator_presentation
  if (op?.header_state && op.header_state !== pres.state) {
    pres.state = op.header_state as OperatorState
    if (op.header_note) pres.headline = op.header_note
  }
  const mechanicsAllowed = op ? Boolean(op.display_current_mechanics) : !pres.stale
  if (op && !mechanicsAllowed) pres.mechanics = null
  const accent = operatorStateColor(pres.state)
  const tech = packet?.technical_state || {}
  const builtAt = generatedAt || packet?.evaluated_at || packet?.generated_at
  const inputsAt = packet?.freshness?.last_input_refresh_at || packet?.current_input_snapshot?.computed_at
  const validUntil = packet?.freshness?.valid_until || actionPolicy?.valid_until
  const nextDue = packet?.freshness?.next_refresh_due_at || actionPolicy?.next_refresh_due_at
  const invalidatedAt = packet?.freshness?.invalidated_at || packet?.current_validity?.invalidated_at
  const tier = String(packet?.analysis_tier || (['BLIND', 'SINGLE_LANE'].includes(String(packet?.model_review?.mode)) ? 'STANDARD_BLIND' : 'LOCAL_QUANT'))
  const analysisMode = tier === 'LOCAL_QUANT' ? 'LOCAL QUANT · NO LLM' : tier.replace(/_/g, ' ')
  const families = pres.audit?.families || {}
  const preferredKey = pres.primaryFamily?.key === 'refresh' ? '' : String(pres.primaryFamily?.key || '')

  return (
    <section aria-label="Decision strategy desk" onClick={event => event.stopPropagation()} style={{ borderLeft: `3px solid ${accent}`, borderBottom: `1px solid ${BB.border}`, background: BB.bg }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.55fr) minmax(300px,.75fr)', gap: 16, padding: '13px 16px 11px', borderBottom: `1px solid ${BB.border}` }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, fontWeight: 950, letterSpacing: '.10em', color: accent }}>{pres.state}</span>
            <span style={{ fontSize: 18, fontWeight: 850, color: BB.text0 }}>{pres.headline}</span>
          </div>
          <div style={{ marginTop: 5, fontSize: 11.5, lineHeight: 1.45, color: BB.text2, fontWeight: 650 }}>{pres.thesisLine}</div>
          {pres.whyLines.length > 0 && <div style={{ marginTop: 7, display: 'flex', gap: 8, flexWrap: 'wrap' }}>{pres.whyLines.slice(0, 2).map((line, index) => <span key={index} style={{ fontSize: 10.5, color: BB.text1, borderBottom: `1px solid ${BB.border}`, paddingBottom: 2 }}>{line}</span>)}</div>}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '7px 12px', alignContent: 'start', paddingLeft: 14, borderLeft: `1px solid ${BB.border}` }}>
          <Meta label="Strategy built" value={`${clock(builtAt)} · ${age(builtAt)}`} />
          <Meta label="Analysis" value={analysisMode} />
          <Meta label="Inputs refreshed" value={clock(inputsAt)} />
          <Meta label="Technical snapshot" value={tech?.computed_at ? `${clock(tech.computed_at)} · ${tech.overall_freshness || '—'}` : 'Unavailable'} />
          <Meta label={pres.stale ? 'Invalidated' : 'Valid until'} value={pres.stale ? clock(invalidatedAt) : clock(validUntil)} tone={pres.stale ? BB.amber : undefined} />
          <Meta label="Next review" value={clock(nextDue)} />
        </div>
      </div>

      <div style={{ padding: '10px 16px', borderBottom: `1px solid ${BB.border}` }}>
        <SectionTitle title="Strategies evaluated" note="Only the selected family drives mechanics and the primary action." />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,minmax(125px,1fr))', borderTop: `1px solid ${BB.border}`, borderLeft: `1px solid ${BB.border}` }}>
          {FAMILY_ORDER.map(([key, label]) => {
            const family = families[key] || {}
            const word = familyWord(key, family, op?.tile_overrides)
            const preferred = Boolean(preferredKey) && (preferredKey === key || preferredKey.startsWith(key.split('_')[0]))
            return <button key={key} onClick={event => { event.stopPropagation(); setDetails(true) }} title={`${label}: ${word}. ${familyReason(key, family)}`} style={{ minHeight: 66, textAlign: 'left', cursor: 'pointer', border: 'none', borderRight: `1px solid ${BB.border}`, borderBottom: `1px solid ${BB.border}`, background: preferred ? 'rgba(148,163,184,.07)' : 'transparent', padding: '8px 9px', boxShadow: preferred ? `inset 0 2px 0 ${accent}` : undefined }}><div style={{ display: 'flex', gap: 6, alignItems: 'center' }}><span style={{ fontSize: 10.5, fontWeight: 900, color: preferred ? BB.text0 : BB.text2 }}>{label}</span>{preferred && <span style={{ fontSize: 9, color: BB.text3 }}>PRIMARY</span>}</div><div style={{ marginTop: 4, fontSize: 10.5, fontWeight: 900, color: quietStateTone(word, preferred) }}>{word}</div><div style={{ marginTop: 2, fontSize: 10, lineHeight: 1.25, color: BB.text3 }}>{familyReason(key, family).slice(0, 76)}</div></button>
          })}
        </div>
      </div>

      <div style={{ padding: '10px 16px', borderBottom: `1px solid ${BB.border}` }}>
        <SectionTitle title="Technical setup" note={tech?.source_hash ? `${tech.overall_direction || 'UNRESOLVED'} · source ${tech.source_hash}` : 'Canonical technical snapshot unavailable'} />
        <TechnicalSummary tech={tech} onOpen={() => setDetails(true)} />
      </div>

      <TicketVerification packet={packet} symbol={packet?.symbol} />

      <div style={{ display: 'grid', gridTemplateColumns: pres.mechanics ? 'minmax(0,1.2fr) minmax(280px,.8fr)' : '1fr', gap: 18, padding: '10px 16px', borderBottom: `1px solid ${BB.border}` }}>
        {pres.mechanics && <div style={{ opacity: pres.stale || pres.mechanics.previous ? .6 : 1 }}><SectionTitle title={pres.stale ? 'Previous mechanics — not current' : 'Current mechanics'} /><div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,minmax(76px,1fr))', gap: 0, borderTop: `1px solid ${BB.border}`, borderLeft: `1px solid ${BB.border}` }}>{([
          ['Entry', pres.mechanics.entry], ['Limit', pres.mechanics.limit], ['Stop', pres.mechanics.stop], ['Target', pres.mechanics.target], ['R:R', pres.mechanics.rr],
        ] as const).map(([label, value]) => <div key={label} style={{ padding: '7px 9px', minHeight: 44, borderRight: `1px solid ${BB.border}`, borderBottom: `1px solid ${BB.border}` }}><div style={{ fontSize: 9.5, fontWeight: 850, color: BB.text3, textTransform: 'uppercase', letterSpacing: '.06em' }}>{label}</div><div style={{ ...numStyle, marginTop: 2, fontSize: 14, fontWeight: 850, color: BB.text0 }}>{value || '—'}</div></div>)}</div></div>}
        <div><SectionTitle title="What changes the decision" /><div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>{(packet?.horizons?.tactical?.trigger || packet?.horizons?.swing?.trigger) && <Condition label="Trigger" text={packet?.horizons?.tactical?.trigger || packet?.horizons?.swing?.trigger} />}{(packet?.horizons?.tactical?.invalidation || packet?.horizons?.swing?.invalidation) && <Condition label="Invalidation" text={packet?.horizons?.tactical?.invalidation || packet?.horizons?.swing?.invalidation} warning />}{!packet?.horizons?.tactical?.trigger && !packet?.horizons?.swing?.trigger && <Condition label="Next" text={pres.primaryFamily?.why || pres.whyLines[0] || 'Review the full evidence'} />}</div></div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '9px 16px' }}>
        <button onClick={event => { event.stopPropagation(); if (pres.state === 'REFRESH') { if (onRefreshStrategy) onRefreshStrategy(event); else if (onRefresh) onRefresh(event) } else if (pres.state === 'WAIT' && onAlert) onAlert(pres, event); else if (onPrimary) onPrimary(pres, event) }} disabled={refreshing && pres.state === 'REFRESH'} style={{ ...terminalButton(pres.state === 'READY' || pres.state === 'REFRESH' ? 'primary' : 'secondary'), fontSize: 11, padding: '5px 10px', ...(refreshing && pres.state === 'REFRESH' ? { opacity: .6, cursor: 'wait' } : {}) }}>{refreshing && pres.state === 'REFRESH' ? 'Refreshing strategy…' : pres.primaryCta}</button>
        {!pres.stale && onRefreshStrategy && <button onClick={event => { event.stopPropagation(); onRefreshStrategy(event) }} disabled={refreshing} style={{ ...terminalButton('ghost'), fontSize: 10.5 }}>{refreshing ? 'Refreshing…' : 'Refresh Strategy'}</button>}
        {onRefresh && <button onClick={event => { event.stopPropagation(); onRefresh(event) }} style={{ ...terminalButton('ghost'), fontSize: 10.5 }}>Refresh Inputs</button>}
        {pres.stale && pres.mechanics?.previous && <button onClick={event => { event.stopPropagation(); setPrevOpen(value => !value) }} style={{ ...terminalButton('ghost'), fontSize: 10.5 }}>{prevOpen ? 'Hide Previous Strategy' : 'View Previous Strategy'}</button>}
        {pres.whyNot.length > 0 && <button onClick={event => { event.stopPropagation(); setWhyOpen(value => !value) }} style={{ ...terminalButton('ghost'), fontSize: 10.5 }}>{whyOpen ? 'Hide alternatives' : 'Why not alternatives?'}</button>}
        <button onClick={event => { event.stopPropagation(); setDetails(value => !value) }} style={{ ...terminalButton('ghost'), fontSize: 10.5 }}>{details ? 'Hide audit' : 'Details & audit'}</button>
        <span style={{ marginLeft: 'auto', fontSize: 10, color: BB.text3 }}>Advisory only · proposal review remains separate</span>
      </div>

      {prevOpen && pres.mechanics?.previous && <div style={{ margin: '0 16px 10px', padding: '7px 9px', fontSize: 10.5, color: BB.text3, borderTop: `1px solid ${BB.border}` }}>Previous strategy: {pres.mechanics.summary}</div>}
      {whyOpen && <div style={{ margin: '0 16px 10px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 8 }}>{pres.whyNot.map(item => <div key={item.title} style={{ padding: '7px 9px', borderTop: `1px solid ${BB.border}` }}><div style={{ fontSize: 10, fontWeight: 850, color: BB.text2 }}>{item.title}</div><div style={{ marginTop: 2, fontSize: 10, color: BB.text3 }}>{item.reason}</div></div>)}</div>}
      {details && <AuditDrawer pres={pres} tech={tech} />}
    </section>
  )
}

function SectionTitle({ title, note }: { title: string; note?: string }) { return <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}><span style={{ fontSize: 10, fontWeight: 900, color: BB.text2, textTransform: 'uppercase', letterSpacing: '.08em' }}>{title}</span>{note && <span style={{ fontSize: 10, color: BB.text3 }}>{note}</span>}</div> }
function Meta({ label, value, tone }: { label: string; value: string; tone?: string }) { return <div style={{ minWidth: 0 }}><div style={{ fontSize: 9.5, fontWeight: 850, color: BB.text3, textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</div><div style={{ marginTop: 1, fontSize: 10, color: tone || BB.text1, fontWeight: 650, overflow: 'hidden', textOverflow: 'ellipsis' }} title={value}>{value}</div></div> }
function Condition({ label, text, warning }: { label: string; text: string; warning?: boolean }) { return <div style={{ display: 'grid', gridTemplateColumns: '78px 1fr', gap: 8, alignItems: 'start' }}><span style={{ fontSize: 9.5, fontWeight: 900, color: warning ? BB.red : BB.text2, textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</span><span style={{ fontSize: 10.5, color: BB.text1, lineHeight: 1.35 }}>{text}</span></div> }

function TechnicalSummary({ tech, onOpen }: { tech: any; onOpen: () => void }) {
  const pills: any[] = tech?.pills || []
  const verdict = tech?.verdict
  if (!pills.length) {
    const fresh = String(tech?.overall_freshness || '').toUpperCase()
    const message = !tech || !tech.schema_version || tech.schema_version === 'unavailable' && !tech.error ? 'Legacy packet — technical snapshot not built. Refresh Strategy.' : tech.error || fresh === 'FAILED' ? `Technical analysis failed — ${String(tech.error || 'unknown error')}` : fresh === 'STALE' ? `Technical data stale — computed ${String(tech.computed_at || '').slice(0, 16)}` : fresh === 'REFRESHING' ? 'Technical refresh currently running…' : tech.unavailable?.length ? `Unavailable timeframes: ${tech.unavailable.join(', ')}` : 'Technical snapshot unavailable.'
    return <div style={{ padding: '7px 0', color: BB.text3, fontSize: 10.5 }}>{message}</div>
  }
  return <div>{verdict && <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr', gap: 10, padding: '6px 0 8px', borderBottom: `1px solid ${BB.border}` }}><div style={{ fontSize: 10, fontWeight: 900, color: verdict.state === 'OPPOSED' ? BB.red : verdict.state === 'SUPPORTIVE' ? BB.green : BB.amber }}>{String(verdict.state || 'MIXED')}</div><div><div style={{ fontSize: 10.5, color: BB.text1, fontWeight: 750 }}>{verdict.line}</div><div style={{ marginTop: 2, fontSize: 10, color: BB.text3 }}>{[...(verdict.supporting || []).slice(0, 2), ...(verdict.conflicting || []).slice(0, 2)].join(' · ')}</div></div></div>}<div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,minmax(115px,1fr))', borderTop: verdict ? 'none' : `1px solid ${BB.border}`, borderLeft: `1px solid ${BB.border}` }}>{pills.slice(0, 6).map((pill, index) => <button key={`${pill.kind || 'tech'}-${index}`} onClick={event => { event.stopPropagation(); onOpen() }} title={`${pill.tooltip || ''} · ${pill.lifecycle || ''} · ${pill.freshness || ''}`} style={{ minHeight: 57, textAlign: 'left', cursor: 'pointer', background: 'transparent', border: 'none', borderRight: `1px solid ${BB.border}`, borderBottom: `1px solid ${BB.border}`, padding: '7px 8px' }}><div style={{ fontSize: 9.5, color: BB.text3, fontWeight: 850, textTransform: 'uppercase', letterSpacing: '.05em' }}>{String(pill.kind || 'technical').replace(/_/g, ' ')}</div><div style={{ marginTop: 3, fontSize: 10.5, color: BB.text1, fontWeight: 900 }}>{pill.label}</div><div style={{ marginTop: 2, fontSize: 10, color: BB.text3 }}>{pill.kind === 'freshness' && pill.as_of ? clock(pill.as_of) : pill.value || String(pill.lifecycle || '').replace(/_/g, ' ') || '—'}</div></button>)}</div></div>
}

function TicketVerification({ packet, symbol }: { packet: any; symbol?: string }) {
  const [busy, setBusy] = useState(false)
  const review = packet?.ticket_review
  const plan = packet?.current_actionable_plan
  const validation = plan?.ticket_validation || {}
  const reconciled = review?.reconciled || {}
  const reviews = review?.reviews || {}
  const overall = reconciled.state || (validation.state === 'FAIL' ? 'DETERMINISTIC_FAIL' : !review && !plan ? 'UNVERIFIED_LEGACY' : 'UNVALIDATED')
  const failure = /FAIL|REJECT|BLOCK/.test(String(overall))
  const runFree = async () => {
    if (!symbol || busy) return
    setBusy(true)
    try { await fetch('/api/v2/watch/ticket-review/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol }) }) } finally { window.setTimeout(() => setBusy(false), 60_000) }
  }
  return <div style={{ padding: '9px 16px', borderBottom: `1px solid ${BB.border}` }}><div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}><span style={{ fontSize: 10, fontWeight: 900, letterSpacing: '.08em', color: BB.text3 }}>TICKET VERIFICATION</span><span style={{ fontSize: 10.5, fontWeight: 900, color: failure ? BB.red : reconciled.proposal_allowed ? BB.green : BB.text1 }}>{String(overall).replace(/_/g, ' ')}</span>{reconciled.detail && <span style={{ fontSize: 10, color: BB.text3 }}>{String(reconciled.detail).slice(0, 100)}</span>}<button onClick={event => { event.stopPropagation(); void runFree() }} disabled={busy} style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 800, padding: '2px 8px', cursor: busy ? 'wait' : 'pointer', background: 'transparent', color: BB.text2, border: `1px solid ${BB.border}`, borderRadius: 3 }}>{busy ? 'Reviewing…' : 'Run free review'}</button></div><div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 5, fontSize: 10, color: BB.text3 }}><span>Deterministic <b style={{ color: validation.state === 'FAIL' ? BB.red : validation.state === 'PASS' ? BB.green : BB.text2 }}>{validation.state || review?.tickets_validated?.[0]?.state || 'NOT RUN'}</b></span><span>Local <b style={{ color: BB.text2 }}>{reviews.local?.verdict || 'NOT RUN'}</b></span><span>Grok OAuth <b style={{ color: BB.text2 }}>{reviews.grok?.verdict || 'NOT RUN'}</b></span><span>ChatGPT OAuth <b style={{ color: BB.text2 }}>{reviews.chatgpt?.verdict || 'NOT RUN'}</b></span><span>Premium <b style={{ color: BB.text2 }}>NOT RUN</b></span></div>{validation.hard_failures?.length > 0 && <div style={{ marginTop: 4, fontSize: 10, color: BB.red }}>{validation.hard_failures.slice(0, 2).join(' · ')}</div>}</div>
}

function AuditDrawer({ pres, tech }: { pres: OperatorPresentation; tech: any }) {
  const audit = pres.audit
  return <div style={{ margin: '0 16px 12px', padding: '9px 0 0', borderTop: `1px solid ${BB.border}`, display: 'flex', flexDirection: 'column', gap: 7 }}><div style={{ fontSize: 10, fontWeight: 900, color: BB.text2, letterSpacing: '.07em', textTransform: 'uppercase' }}>Details & audit — not the primary decision</div><div style={{ fontSize: 10, color: BB.text3 }}>Packet {audit.packet?.packet_version || '—'} · policy {audit.actionPolicy?.policy_version || '—'}{audit.inputHashes.packet ? ` · packet ${audit.inputHashes.packet}` : ''}{audit.inputHashes.current ? ` · current ${audit.inputHashes.current}` : ''}{tech?.source_hash ? ` · technical ${tech.source_hash}` : ''}</div><div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,minmax(150px,1fr))', gap: 8 }}>{FAMILY_ORDER.map(([key, label]) => <div key={key} style={{ padding: '7px 0', borderTop: `1px solid ${BB.border}` }}><div style={{ fontSize: 10, fontWeight: 850, color: BB.text2 }}>{label} · {familyWord(key, audit.families?.[key] || {})}</div><div style={{ marginTop: 2, fontSize: 10, color: BB.text3 }}>{familyReason(key, audit.families?.[key] || {})}</div></div>)}</div></div>
}
