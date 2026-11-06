/** Recovery & re-entry screens (piece D): Home's high-impact card and the Risk → Recovery list.
 *  One read: GET /api/v2/recovery → `recovery_cases` (piece A's store via its accessor). Advisory only. */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { RADIUS, TOKENS, TYPE, numStyle, toneVars } from '../../lib/designTokens'
import { byImpact, homeCase, recoveryProjection, stateCounts, type RecoveryCaseView, type RecoveryProjection } from '../../lib/recoveryCases'
import { RecoveryCaseCard, useCaseGates } from './RecoveryCaseCard'

export const RECOVERY_API = '/api/v2/recovery'
const RECOVERY_LIST_PATH = '/risk?tab=Recovery'

function Unavailable({ projection, testId }: { projection: RecoveryProjection; testId: string }) {
  const t = toneVars('warning')
  return <p role="status" data-testid={testId} style={{ margin: 0, padding: 12, borderRadius: RADIUS.md, background: t.bg, border: `1px dashed ${t.border}`, color: t.color, fontSize: TYPE.base }}>
    Recovery cases unavailable — {projection.reason ?? 'the recovery source did not answer.'} The case count is unavailable, not zero.
  </p>
}

/** Pure render for Home: the one open T1 case, or nothing when the answered read has none. */
export function RecoveryHomeSection({ projection, lastGood, sourceUnavailable, gate, onReview }: {
  projection: RecoveryProjection; lastGood: RecoveryProjection | null; sourceUnavailable: boolean
  gate: (c: RecoveryCaseView) => 'fresh' | 'changed'; onReview: (c: RecoveryCaseView) => void
}) {
  const shown = projection.state === 'ok' ? projection : lastGood
  const c = shown ? homeCase(shown) : null
  const unavailable = sourceUnavailable || projection.state === 'unavailable'
  if (!c) {
    if (projection.state === 'unavailable' || (sourceUnavailable && projection.state !== 'missing')) return <Unavailable projection={projection} testId="home-recovery-unavailable" />
    return null
  }
  return <div data-testid="home-recovery" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
    <span style={{ fontSize: TYPE.xs, fontWeight: 700, letterSpacing: '0.08em', color: TOKENS.text[2] }}><span style={{ color: TOKENS.warning }}>●</span> NEEDS YOU · <span style={{ fontWeight: 400, letterSpacing: 0 }}>Recovery follow-up</span></span>
    <RecoveryCaseCard projection={{ ...(shown as RecoveryProjection), reason: projection.reason ?? (shown as RecoveryProjection).reason }} c={c} gate={gate(c)} unavailable={unavailable}
      onReview={() => onReview(c)} heading="Recovery · high-impact case" footerLink={{ to: `${RECOVERY_LIST_PATH}&case=${encodeURIComponent(c.key)}`, label: 'View recovery case' }} testId="home-recovery-card" />
  </div>
}

/** Home mount: polls the one read, keeps the last answered projection so an outage keeps the case context. */
export function RecoveryHomeCard() {
  const api = useApi<any>(RECOVERY_API, 120_000)
  const projection = recoveryProjection(api.data, api.error)
  const [lastGood, setLastGood] = useState<RecoveryProjection | null>(null)
  if (projection.state === 'ok' && !api.error && lastGood?.generatedAt !== projection.generatedAt) setLastGood(projection)
  const gates = useCaseGates(projection.state === 'ok' ? projection.cases : lastGood?.cases ?? [])
  return <RecoveryHomeSection projection={projection} lastGood={lastGood} sourceUnavailable={!!api.error || !!api.stale}
    gate={gates.gate} onReview={gates.review} />
}

const FILTERS = ['All', 'Needs review', 'Watching', 'Snoozed', 'Closed'] as const
type Filter = typeof FILTERS[number]
const inFilter = (f: Filter, c: RecoveryCaseView) => f === 'All' ? true
  : f === 'Needs review' ? ['STOPPED_OUT', 'RECOVERING', 'RE_ENTRY_READY'].includes(c.state)
  : f === 'Watching' ? c.state === 'WATCHING' : f === 'Snoozed' ? c.state === 'SNOOZED' : c.state === 'CLOSED' || c.state === 'RE_ENTERED'

/** Pure render for Risk → Recovery. */
export function RecoveryListView({ projection, sourceUnavailable, selectedKey, onSelect, gate, onReview, legacyCount }: {
  projection: RecoveryProjection; sourceUnavailable: boolean; selectedKey: string | null; onSelect: (key: string) => void
  gate: (c: RecoveryCaseView) => 'fresh' | 'changed'; onReview: (c: RecoveryCaseView) => void; legacyCount: number | null
}) {
  const [filter, setFilter] = useState<Filter>('All')
  const counts = stateCounts(projection)
  const cases = [...projection.cases].sort(byImpact)
  const visible = cases.filter(c => inFilter(filter, c))
  const selected = cases.find(c => c.key === selectedKey) ?? null
  const kpi = (label: string, v: number | null | undefined, testId: string) => <div data-testid={testId} style={{ background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 12, minWidth: 0, flex: '1 1 0' }}>
    <div style={{ ...numStyle, fontSize: TYPE.xl, fontWeight: 700 }}>{v == null ? 'Unavailable' : v}</div><div style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{label}</div></div>
  return <div data-testid="recovery-list" data-projection-state={projection.state} style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 }}>
    <div>
      <h2 style={{ margin: 0, fontSize: TYPE.lg }}>Recovery &amp; re-entry</h2>
      <p style={{ margin: '4px 0 0', color: TOKENS.text[2], fontSize: TYPE.base }}>Every confirmed exit has a follow-up. Advisory only — nothing here places, changes or prepares an order.</p>
    </div>
    <div style={{ display: 'flex', gap: 8 }}>
      {kpi('Needs a review', counts?.needsReview, 'recovery-kpi-review')}
      {kpi('Watching', counts?.watching, 'recovery-kpi-watching')}
      {kpi('Snoozed', counts?.snoozed, 'recovery-kpi-snoozed')}
    </div>
    {projection.state !== 'ok' && <Unavailable projection={projection} testId="recovery-list-unavailable" />}
    {projection.state === 'ok' && sourceUnavailable && <Unavailable projection={{ ...projection, reason: 'the latest refresh failed; showing the last answered read.' }} testId="recovery-list-stale" />}
    {projection.state === 'ok' && <>
      <div role="tablist" aria-label="Filter recovery cases" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {FILTERS.map(f => { const n = cases.filter(c => inFilter(f, c)).length
          if (f !== 'All' && !n) return null
          return <button key={f} type="button" role="tab" aria-selected={filter === f} onClick={() => setFilter(f)} data-testid={`recovery-filter-${f.toLowerCase().replace(/ /g, '-')}`}
            style={{ minHeight: 44, padding: '0 12px', borderRadius: RADIUS.md, border: `1px solid ${filter === f ? TOKENS.info : TOKENS.border}`, background: TOKENS.bg[2], color: TOKENS.text[0], fontWeight: 600, fontSize: TYPE.sm, cursor: 'pointer' }}>{f} {n}</button> })}
      </div>
      <section style={{ background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, minWidth: 0 }}>
        <h3 style={{ margin: 0, padding: '12px 16px', fontSize: TYPE.base, fontWeight: 600, borderBottom: `1px solid ${TOKENS.borderSubtle}` }}>Recovery cases</h3>
        {visible.map(c => <button key={c.key} type="button" data-testid="recovery-row" data-case-key={c.key} aria-pressed={selected?.key === c.key} onClick={() => onSelect(c.key)}
          style={{ display: 'block', width: '100%', textAlign: 'left', minHeight: 44, padding: '12px 16px', background: selected?.key === c.key ? TOKENS.bg[2] : 'transparent', color: TOKENS.text[0], border: 0, borderLeft: `3px solid ${selected?.key === c.key ? TOKENS.info : 'transparent'}`, borderTop: `1px solid ${TOKENS.borderSubtle}`, cursor: 'pointer' }}>
          <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}><b>{c.symbol}</b><span style={{ fontSize: TYPE.sm, color: toneVars(c.stateTone).color }}>{c.stateLabel}</span></span>
          <span style={{ display: 'block', fontSize: TYPE.sm, color: TOKENS.text[2] }}>{c.account} · exited {c.exitDate ?? 'date unavailable'}{c.materialityTier ? ` · tier ${c.materialityTier}` : ''}{gate(c) === 'changed' ? ' · changed' : ''}</span>
        </button>)}
        {!cases.length && <p data-testid="recovery-empty" style={{ margin: 0, padding: 16, color: TOKENS.text[2] }}>The recovery case store answered with no cases.{legacyCount ? ` The legacy recovery watch still lists ${legacyCount}.` : ''}</p>}
      </section>
      <p style={{ margin: 0, fontSize: TYPE.xs, color: TOKENS.text[2] }}>Sorted by the case's recorded impact tier, then the most recent exit. Eligibility comes from the same case shown on Home.</p>
    </>}
    {selected && <RecoveryCaseCard projection={projection} c={selected} gate={gate(selected)} unavailable={sourceUnavailable} onReview={() => onReview(selected)}
      heading={selected.materialityTier === 'T1' ? 'Recovery · high-impact case' : 'Recovery case'} footerLink={{ to: `/portfolio/re-entry?symbol=${encodeURIComponent(selected.symbol)}`, label: 'Re-entry evidence' }} testId="recovery-detail" />}
    <Link to="/portfolio/re-entry" style={{ color: TOKENS.info, textDecoration: 'none', minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>Re-Entry desk evidence →</Link>
  </div>
}
