import ListPager, { useListOffset } from '../components/ListPager'
/** Watch — your prospects, in the order you should look at them (Gate 3 mockup, operator directive 2026-10-22).
 *
 *  Reads ONE projection: GET /api/v3/data-broker/watch-prospects (scripts/lib/data_broker/watch_prospects.py) — the
 *  CIO prospect record when its store is live, an interim adapter until then (labelled on the page). The server owns
 *  lane, conviction, stance, conflicts, trigger and the one next step; this page renders them.
 *
 *  Actions reuse existing operator flows only: Propose → WatchlistProposeModal (POST /api/v2/watchlist/:sym/propose,
 *  you size it, it goes to Proposals for approval); Set alert → ReEntryAlertArmModal (POST /api/v2/watch/alerts,
 *  advisory notifications); Protect first → Open Trades; Ask the CIO → POST /api/v2/cio/ask, then the thesis queue
 *  as a secondary note. Nothing here sizes, orders or stops on its own. */
import ProspectusLink from '../components/prospectus/ProspectusLink'
import './WatchLayout.css'
import './W9Mobile.css'
import ConflictLine from '../components/conflicts/ConflictLine'
import ConflictSheet, {useConflictSheet, type ConflictSection} from '../components/conflicts/ConflictSheet'
import WatchReviewRequest from '../components/watch/WatchConflictPanel'
import {MobileDetailSheet, useMobilePageDetail} from '../components/MobileDetailSheet'
import { WatchCompanyFacts, companyDisplayName } from '../components/watch/WatchCompanyFacts'
import WatchRecordCard, { WatchCardHeader } from '../components/watch/WatchRecordCard'
import WatchMarketFacts from '../components/watch/WatchMarketFacts'
import { AskPhaseStatus, CioMemoryChip, CioReviewPanel, ReviewStateChip, currentReviewState, useCioReview, type CioReviewController } from '../components/watch/CioReview'
import { blockingReasons, cardRail, rowMarketFacts, rowZone } from '../lib/watchRecordCardModel'
import { AccountChip } from '../components/AccountChip'
import { ACCOUNT_NAMES, accountName, canonicalAccountKey } from '../lib/accountLabels'
import { useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { fmtAsOf } from '../lib/asOfDisplay'
import { FONT, RADIUS, TOKENS, TYPE, chipStyle, numStyle, toneFromVerdict, toneVars, type Tone } from '../lib/designTokens'
import {
  LANE_ORDER, LANE_TONE, TOOLTIPS, ageDays, alertIntel, alertLabel, asksCio, convictionTone, detailNextLine, drawers, etStamp, headerChips, laneById,
  proposeSeed, stanceLabel, stanceTone, stepTone, tieAlerts, unwrap,
  type LaneId, type ProspectRow, type ProspectsPayload, type TiedAlerts,
} from '../lib/watchProspectsModel'
import WatchlistProposeModal, { type WatchlistProposeSeed } from '../components/WatchlistProposeModal'
import ReEntryAlertArmModal from '../components/reentry/ReEntryAlertArmModal'
import PositionFilterBar from '../components/watch/PositionFilterBar'
import { StarToggle } from '../components/watch/MineControls'
import {
  alertLevelsLabel, money, positionChip, positionQuery, readinessTone, reentryLabel, resultTone, roundTripLabel,
  roundTripPath, withQuery, type ListRow,
} from '../lib/watchListsModel'

const panel: CSSProperties = {
  background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, minWidth: 0,
}
const label: CSSProperties = {
  fontSize: TYPE.xs, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: TOKENS.text[2],
}

// Storage keys are not display names. Keep the shared alias/digit checks, but never humanize an unknown key.
function displayAccountName(key: unknown, supplied?: unknown): string {
  const known = canonicalAccountKey(key)
  return accountName(Object.prototype.hasOwnProperty.call(ACCOUNT_NAMES, known) ? known : '', supplied)
}
function heldDisplayNames(r: ListRow): string[] {
  return (r.held_accounts || []).map((key, i) => displayAccountName(key, r.held_account_labels?.[i]))
}
function soldDisplayName(r: ListRow): string {
  const key = r.last_sell_account || r.last_round_trip?.account || ''
  const supplied = r.last_sell_account_label || r.last_round_trip?.account_label || ''
  return key || supplied ? displayAccountName(key, supplied) : ''
}

/** Preserve the backend envelope; a missing producer is an explicit gap, never an empty result. */
export function conflictSection(row: ProspectRow): ConflictSection {
  const r = row as ProspectRow & {conflict_section?: ConflictSection; conflict_section_gap?: {reason?: string} | null}
  // W2's server read names why a section is missing (conflict_section_gap); show that reason, not a generic one.
  return r.conflict_section
    ?? {findings: [], headline: null, gap: {reason: r.conflict_section_gap?.reason || 'engine result not supplied for this security'}}
}

/** AGENTS §28.11 transition: until the conflict engine (W10) supplies a section, the existing Watch producer's
 *  flags stay visible with the existing review request. Shown only when the engine section is a gap; never mixed
 *  with, or used to classify, engine findings. */
export function legacyConflicts(row: ProspectRow) {
  const section = conflictSection(row)
  return !section.headline && section.gap ? row.conflicts || [] : []
}

function LegacyConflictFlags({ r, cio }: { r: ProspectRow; cio: CioReviewController }) {
  const flags = legacyConflicts(r)
  if (!flags.length) return null
  const when = (at: string | null) => etStamp(at) || 'time unknown'
  return <div data-testid="watch-detail-conflicts" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
    <span style={label} title={TOOLTIPS.conflicts}>Flags from the current Watch check — shown until the conflict engine ships</span>
    {flags.map((c, i) => <div key={i} data-testid="watch-detail-conflict" style={{ fontSize: TYPE.base, lineHeight: 1.45, border: `1px solid ${toneVars('warning').border}`, borderRadius: RADIUS.md, padding: 8 }}>
      <div style={{ color: TOKENS.warning, fontWeight: 700 }}>{c.summary}</div>
      <div><b>{String(c.a?.value ?? '—')}</b> · {c.a?.source || '—'} · {when(c.a?.at ?? null)}</div>
      <div><b>{String(c.b?.value ?? '—')}</b> · {c.b?.source || '—'} · {when(c.b?.at ?? null)}</div>
    </div>)}
    <CioReviewPanel row={r} cio={cio} />
  </div>
}

export function WatchConflictDetail({row, onBack, onRefresh}: {row: ProspectRow; onBack?: () => void; onRefresh?: () => void}) {
  return <ConflictSheet title={`${row.symbol} · recorded conflict`} section={conflictSection(row)} onBack={onBack}>
    {(record, refresh) => <>
      <ReviewStateChip state={currentReviewState(row)} />
      <WatchReviewRequest symbol={row.symbol} securityGuid={row.security_guid} record={record} onRefresh={() => {refresh(); onRefresh?.()}} />
      <Link className="mobile-detail-primary" to={`/watch/intelligence/${encodeURIComponent(row.symbol)}`} onClick={() => window.scrollTo(0, 0)}>Open evidence →</Link>
    </>}
  </ConflictSheet>
}

function Bar({ value, tone, height = 4 }: { value: number | null; tone: Tone; height?: number }) {
  const w = value == null ? 0 : Math.max(0, Math.min(100, value))
  return (
    <span aria-hidden="true" style={{ display: 'block', height, background: TOKENS.bg[3], borderRadius: RADIUS.sm, overflow: 'hidden' }}>
      <span style={{ display: 'block', height, width: `${w}%`, background: toneVars(tone).color }} />
    </span>
  )
}

/** Row "Ask the CIO to review": an engine finding opens its recorded conflict (whose sheet asks with the finding);
 *  otherwise the record opens and the request is sent unless one is already open — the record shows the state. */
export function askFromRow(r: ProspectRow, cio: CioReviewController, openConflict: (row: ProspectRow, key: string) => void,
  select: (symbol: string) => void) {
  const key = conflictSection(r).findings[0]?.key
  if (key) {openConflict(r, key); return}
  select(r.symbol)
  if (!currentReviewState(r, cio)?.open) void cio.ask(r)
}

export function StepButton({ row, onStep }: { row: ProspectRow; onStep: (r: ProspectRow) => void }) {
  const navigate = useNavigate()
  const a = row.next_action
  const t = toneVars(stepTone(a.kind))
  const style: CSSProperties = {
    whiteSpace: 'normal', fontSize: TYPE.base + 1, fontWeight: 600, padding: '8px 12px', borderRadius: RADIUS.md,
    minHeight: 44, boxSizing: 'border-box', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    background: t.bg, border: `1px solid ${t.border}`, color: t.color, cursor: 'pointer', textDecoration: 'none',
  }
  if (a.kind === 'none') return <button type="button" disabled style={{ ...style, color: TOKENS.text[2], cursor: 'default' }} title={a.reason}>{a.label === '—' ? 'No action' : a.label || 'No action'}</button>
  if (a.href && (a.kind === 'protect' || a.kind === 'decide' || a.kind === 'open_position' || a.kind === 'review_add')) {
    const to = a.href.replace(/^\/v3/, '')
    return <button type="button" onClick={() => navigate(to)} title={a.reason} style={style} data-testid="watch-step" data-step={a.kind} data-href={a.href}>{a.label}</button>
  }
  return (
    <button type="button" title={a.reason} style={style} onClick={() => onStep(row)} data-testid="watch-step" data-step={a.kind}>
      {asksCio(a.kind) ? 'Ask the CIO to review' : a.label}
    </button>
  )
}

function Chip({ tone, children, tip, testId }: { tone: Tone; children: ReactNode; tip?: string; testId?: string }) {
  return (
    <span title={tip} data-testid={testId} style={{ ...chipStyle(tone, 'soft', 'md'), fontSize: TYPE.base, padding: '5px 10px', cursor: tip ? 'help' : undefined }}>
      {children}
    </span>
  )
}

/** Whole hours since a row's own `expires_at` — the one timestamp the server marks `stale` against.
 *  Returns null when the age cannot be derived, so the badge falls back to a bare "STALE". */
function staleAgeHours(expiresAt: string | null | undefined, now: Date): number | null {
  if (!expiresAt) return null
  const t = Date.parse(String(expiresAt))
  if (!Number.isFinite(t)) return null
  const h = Math.floor((now.getTime() - t) / 3_600_000)
  return h < 0 ? null : h
}

/** A visible "STALE · N h ago" badge in the row list, from the row's own expiry. Display-only: never
 *  hides the row (a held name stays visible), never writes, re-runs, or calls a broker. */
function StaleBadge({ expiresAt }: { expiresAt: string | null }) {
  const h = staleAgeHours(expiresAt, new Date())
  const age = h == null ? '' : h < 1 ? ' · <1 h ago' : ` · ${h} h ago`
  return (
    <span data-testid="watch-row-stale"
      title={`Review expired ${fmtAsOf(expiresAt) ?? '—'}. Still shown — a held name stays visible until new evidence arrives.`}
      style={{
        display: 'inline-flex', alignItems: 'center', alignSelf: 'flex-start',
        whiteSpace: 'normal', textAlign: 'left', fontSize: TYPE.sm, fontWeight: 700, lineHeight: 1.35,
        padding: '3px 8px', borderRadius: RADIUS.pill,
        background: toneVars('warning').bg, color: toneVars('warning').color, border: `1px solid ${toneVars('warning').border}`,
      }}>
      STALE{age}
    </span>
  )
}

export function Row({ r, selected, onSelect, onStep, alerts, onMineChanged, extra, retained = false, onAlert, onOpenConflict, cio }: {
  r: ProspectRow; selected: boolean; onSelect: () => void; onStep: (r: ProspectRow) => void; alerts: number
  cio?: CioReviewController
  onOpenConflict?: (row: ProspectRow, key: string) => void
  onMineChanged?: (msg: string) => void; extra?: ReactNode; retained?: boolean; onAlert?: (r: ProspectRow) => void
}) {
  const lr = r as ListRow
  const names = lr.position_state === 'held' ? heldDisplayNames(lr) : lr.position_state === 'formerly_held' ? [soldDisplayName(lr)].filter(Boolean) : []
  const accountKeys = lr.position_state === 'held' ? lr.held_accounts || [] : [lr.last_sell_account || lr.last_round_trip?.account || '']
  const ownership = lr.position_state === 'held' ? 'Held in' : lr.position_state === 'formerly_held'
    ? `Formerly held${lr.last_sell_at ? ` · sold ${String(lr.last_sell_at).slice(5, 10).replace('-', '/')}` : ''} ·` : ''
  const accounts = names.length ? names : ownership ? ['Unlabelled account'] : []
  const section = conflictSection(r)
  // §28.11 transition: while the engine section is a gap, the card keeps the existing blocking reason
  // (Trade AI gate or Watch flag) and rail; engine findings replace them once W10 supplies a section.
  const transitional = !section.headline && !!section.gap
  const reasons = transitional ? blockingReasons(lr) : []
  const warning = toneVars('warning')
  const stanceToneName = ['ADD', 'RE_ENTER', 'RE-ENTER'].includes(String(r.stance || '').toUpperCase()) ? 'info' : toneFromVerdict(r.stance)
  const stance = toneVars(stanceToneName)
  const score = r.conviction != null && Number.isFinite(r.conviction) ? r.conviction : null
  const stage = ({ actionable: 'Actionable', reentry: 'Re-entry near', forming: 'Forming', manage: 'Held', expired: 'Signal invalidated / expired' } as Record<string, string>)[r.lane] || r.stage?.replace(/_/g, ' ') || 'No setup'
  const ticker = <><StarToggle symbol={r.symbol} on={!!lr.mine} onChanged={onMineChanged} surface="watch.row" size="sm" />
    <button type="button" onClick={onSelect} aria-pressed={selected} title={`Open the ${r.symbol} record`}
      style={{ background: 'none', border: 'none', padding: 0, fontFamily: FONT.mono, fontSize: TYPE.lg, fontWeight: 600, color: TOKENS.text[0], cursor: 'pointer' }}>{r.symbol}</button>
    {alerts > 0 && <span title={`${alerts} armed Watch alerts`} aria-label={`${alerts} armed Watch alerts`}>🔔{alerts}</span>}</>
  const ownershipNode = ownership ? <>{ownership} <span data-testid="watch-row-account-names" role="group" aria-label={lr.position_state === 'held' ? 'Held accounts' : 'Last sell account'}>
    {accounts.map((name, i) => <AccountChip key={`${accountKeys[i]}-${i}`} account={accountKeys[i]} label={name} compact />)}</span></> : null
  const phoneOwnership = ownership ? <span className="watch-mobile-facts" data-testid="watch-phone-ownership"><span><b>{lr.position_state === 'held' ? 'Held in' : 'Sold in'}</b> {accounts.join(', ')}</span></span> : null
  return <WatchRecordCard symbol={r.symbol} selected={selected} lane={r.lane} rail={section.headline ? 'attention' : transitional ? cardRail(lr) : 'neutral'}
    company={<WatchCompanyFacts facts={r.company_facts} symbol={r.symbol} part="company" ticker={ticker} ownership={ownershipNode} />}
    setup={<>
      <div style={{ fontSize: TYPE.md, color: TOKENS.text[0] }}><b style={{ fontWeight: 600 }}>{stage}</b> · <span className="watch-card-why" title={r.why}>{r.why}</span></div>
      {r.stale && <StaleBadge expiresAt={r.expires_at} />}
      <WatchCompanyFacts facts={r.company_facts} symbol={r.symbol} part="catalyst" />
      {reasons.length > 0 && <div className="watch-card-block" data-testid="watch-blocking-reason" style={{ background: warning.bg, color: warning.color,
        border: `1px solid ${warning.border}`, borderRadius: RADIUS.sm, padding: '6px 10px', fontSize: TYPE.base }}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>
        <span>Not actionable: {reasons[0]}</span>
      </div>}
      <ConflictLine section={section} onOpen={key => onOpenConflict ? onOpenConflict(r, key) : onSelect()} />
      <ReviewStateChip state={currentReviewState(r, cio)} testId="watch-row-review-state" compact />
      {cio?.entries[r.symbol] && <AskPhaseStatus entry={cio.entries[r.symbol]} testId="watch-row-ask-phase" />}
      <CioMemoryChip state={currentReviewState(r, cio)} testId="watch-row-cio-memory" />
      {r.whats_missing.length > 0 && <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>Missing: {r.whats_missing.join(' · ')}</div>}
    </>}
    market={<WatchMarketFacts facts={rowMarketFacts(lr)} retained={retained} zone={rowZone(lr)} ownership={phoneOwnership} testId={lr.market_facts ? 'watch-market-facts' : 'watch-record-market'} />}
    conviction={<>
      <div><span style={{ ...numStyle, fontSize: TYPE.xl, fontWeight: 600 }} data-testid="watch-conviction">{score == null ? 'n/a' : score.toFixed(0)}</span> <span className="watch-card-score-denominator" style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>/ 100</span></div>
      {score != null && <div className="watch-card-score-bar" aria-label={`Conviction ${score} of 100`}><span style={{ width: `${Math.max(0, Math.min(100, score))}%`, background: score >= 75 ? TOKENS.success : TOKENS.warning }} /></div>}
      <span className="watch-card-stance" style={{ color: stance.color, background: stance.bg, borderRadius: RADIUS.sm, fontSize: TYPE.base, fontWeight: 600, padding: '3px 8px' }}>{r.stance ? stanceLabel(r.stance) : 'no stance'}</span>
    </>}
    primary={<StepButton row={r} onStep={onStep} />}
    secondary={<>{onAlert && <button type="button" onClick={() => onAlert(r)} style={{ ...chipStyle('info', 'outline', 'md'), cursor: 'pointer' }}>Set alert</button>}{extra}
      <button type="button" onClick={onSelect} style={{ ...chipStyle('neutral', 'outline', 'md'), cursor: 'pointer' }}>View record</button></>} />
}

export function Detail({ r, onOpenConflict, cio: shared }: { r: ProspectRow | null; onAskCio?: (r: ProspectRow) => void; cioMsg?: string; onOpenConflict?: (key: string) => void; cio?: CioReviewController }) {
  const sheet = useConflictSheet()
  const own = useCioReview()
  const cio = shared || own
  if (!r) return <div style={{ color: TOKENS.text[2], fontSize: TYPE.base }}>Click a symbol to see its full record and where it appears.</div>
  return (
    <div data-testid="watch-detail" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontFamily: FONT.mono, fontWeight: 700, fontSize: TYPE.lg + 2 }}>{r.symbol}</span>
        <span style={{ fontSize: TYPE.base, color: TOKENS.text[2], textAlign: 'right' }}>{companyDisplayName({ value: r.company ?? null, display_name: r.company_facts?.company?.display_name }) || ''}</span>
      </div>
      <div style={{ fontSize: TYPE.base + 1, lineHeight: 1.5 }}>{r.summary}</div>
      <div><ProspectusLink symbol={r.symbol} testId="watch-detail-prospectus" /></div>
      <WatchCompanyFacts facts={r.company_facts} symbol={r.symbol} />
      <div data-testid="watch-detail-why" style={{ fontSize: TYPE.base, lineHeight: 1.5 }}><b>Why here:</b> {r.why}</div>
      {(r as ListRow).expiry_suggestion && <div style={{ color: TOKENS.warning, fontSize: TYPE.base }}>Review suggested: {(r as ListRow).expiry_suggestion?.suggest}</div>}
      <PositionDetail r={r as ListRow} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }} data-testid="watch-components">
        <span style={label} title={TOOLTIPS.conviction}>
          Conviction {r.conviction == null ? 'n/a' : r.conviction.toFixed(0)} — what it's made of
        </span>
        {r.conviction_components.length === 0 && <span style={{ fontSize: TYPE.base, color: TOKENS.text[3] }}>Conviction factors not recorded.</span>}
        {r.conviction_components.map(c => (
          <div key={c.key} title={[c.detail, c.source ? `source: ${c.source}` : null, c.weight != null ? `weight ${Math.round(c.weight * 100)}%` : null].filter(Boolean).join(' · ')}
            style={{ display: 'grid', gridTemplateColumns: '120px 1fr 40px', gap: 8, alignItems: 'center', fontSize: TYPE.base }}>
            <span style={{ color: TOKENS.text[1] }}>{c.label}</span>
            <Bar value={c.value} tone="info" height={6} />
            <span style={{ ...numStyle, textAlign: 'right' }}>{c.value == null ? '—' : c.value.toFixed(0)}</span>
          </div>
        ))}
        {r.conviction_missing.length > 0 && <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>Not scored: {r.conviction_missing.join(', ')}</span>}
      </div>
      <section aria-label="What disagrees">
        <h2 tabIndex={-1} data-detail-focus style={{fontSize: TYPE.lg}}>What disagrees</h2>
        <ConflictLine section={conflictSection(r)} onOpen={onOpenConflict ?? sheet.open} />
        <LegacyConflictFlags r={r} cio={cio} />
      </section>
      {sheet.key && !onOpenConflict && <WatchConflictDetail row={r} onBack={sheet.close} />}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }} data-testid="watch-same-record">
        <span style={label} title={TOOLTIPS.sameRecord}>Same record everywhere</span>
        {r.surfaces.map(s => (
          <div key={s.surface} title={s.source ? `source: ${s.source}` : 'not read by this page yet'}
            style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: TYPE.base }}>
            <span style={{ color: TOKENS.text[1] }}>{s.surface}</span>
            <span style={{ fontWeight: 700, color: s.joined ? TOKENS.text[0] : TOKENS.text[3] }}>{s.value}</span>
          </div>
        ))}
      </div>
      {r.whats_missing.length > 0 && (
        <div style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>
          <span style={label}>What's missing</span>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{r.whats_missing.map((m, i) => <li key={i}>{m}</li>)}</ul>
        </div>
      )}
      <div data-testid="watch-detail-next" style={{ display: 'grid', gap: 8, fontSize: TYPE.base + 1, lineHeight: 1.5, background: TOKENS.bg[2], borderRadius: RADIUS.md, padding: 10 }}>
        <span><b>Next:</b> {detailNextLine(r.next_action, conflictSection(r))}</span>
        {/* Never a dead end: a step that asks the CIO always carries the button (the flags block carries it when shown). */}
        {(asksCio(r.next_action.kind) || currentReviewState(r, cio)?.publication_verified) && !legacyConflicts(r).length && <CioReviewPanel row={r} cio={cio} conflictKey={conflictSection(r).findings[0]?.key} />}
        {!asksCio(r.next_action.kind) && !currentReviewState(r, cio)?.publication_verified && !legacyConflicts(r).length && <ReviewStateChip state={currentReviewState(r, cio)} />}
      </div>
      <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>
        Evidence {fmtAsOf(r.evidence_at) || '—'} · expires {fmtAsOf(r.expires_at) || '—'}
        {r.stale ? ' · stale' : ''}. The CIO sets stance and priority; it never sizes or places orders.
      </span>
    </div>
  )
}

/** Last round trip and re-entry advice (CIO prospect lifecycle) for a formerly held name; membership for yours. */
export function PositionDetail({ r }: { r: ListRow }) {
  const rt = r.last_round_trip
  const a = r.reentry
  if (!rt && !a && !(r.membership || []).length) return null
  return (
    <div data-testid="watch-position-detail" style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: TYPE.base }}>
      {(r.membership || []).length > 0 && (
        <div><span style={label}>Why it's yours</span>
          {(r.membership || []).map((m, i) => <div key={i}>{m.label}{m.at ? ` · since ${String(m.at).slice(0, 10)}` : ''}</div>)}
        </div>
      )}
      {rt && (
        <div data-testid="watch-round-trip">
          <span style={label} title="The last closed round trip, from the CIO prospect lifecycle (fills, observed stop path, exit cause).">Last trade · {r.position_label}</span>
          <div style={{ fontFamily: FONT.mono }}>{roundTripPath(rt)}</div>
          {soldDisplayName(r) && <div data-testid="watch-sold-account" style={{ color: TOKENS.text[2] }}>Sold in <AccountChip account={r.last_sell_account || rt.account} label={soldDisplayName(r)} compact /></div>}
          <div style={{ color: toneVars(resultTone(rt)).color, fontWeight: 700 }}>{roundTripLabel(rt)}</div>
          <div style={{ color: TOKENS.text[2] }} title={rt.r_basis ? `R measured against the ${rt.r_basis}` : undefined}>
            {rt.stop_raised != null ? `Stop raised ${rt.stop_raised}× (${money(rt.stop_initial)} → ${money(rt.stop_last)})` : 'No stop history'}
            {rt.noise_vs_trend ? ` · exit reads as ${rt.noise_vs_trend.replace('_', ' ')}` : ''}
          </div>
          {rt.noise_vs_trend_basis && <div style={{ color: TOKENS.text[3], fontSize: TYPE.xs }}>{rt.noise_vs_trend_basis}</div>}
        </div>
      )}
      {a && (
        <div data-testid="watch-reentry-advice">
          <span style={label} title="Same classifier as the Re-Entry Decision Desk (reentry_rules.derive_intel_state).">Re-entry · {a.state}</span>
          <div style={{ color: toneVars(readinessTone(a)).color, fontWeight: 700 }}>{reentryLabel(a)}</div>
          <div style={{ color: TOKENS.text[2] }}>Alert levels {alertLevelsLabel(a)}</div>
          <ul style={{ margin: '2px 0 0', paddingLeft: 16, color: TOKENS.text[2] }}>
            {a.conditions.map(c => <li key={c.id}>{c.met === true ? '✓' : c.met === false ? '✗' : '?'} {c.text}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

function AlertsBody({ t, now }: { t: TiedAlerts; now: Date }) {
  return (
    <div data-testid="watch-drawer-alerts-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div>
        <span style={label}>Belong to a prospect ({t.tied.length})</span>
        {t.tied.length === 0 && <div style={{ color: TOKENS.text[3] }}>None.</div>}
        {t.tied.map(x => (
          <div key={x.alert.id} style={{ fontFamily: FONT.mono }}>{alertLabel(x.alert)} <span style={{ color: TOKENS.text[3] }}>· {x.lane}</span></div>
        ))}
      </div>
      <div>
        <span style={label} title="Armed alerts whose symbol is not a prospect on this page. Listed so you can keep or disarm them on the alert screen; this page changes nothing.">
          Orphaned ({t.orphans.length})
        </span>
        {t.orphans.map(x => (
          <div key={x.alert.id} data-testid="watch-orphan-alert">
            <span style={{ fontFamily: FONT.mono }}>{alertLabel(x.alert)}</span>
            <span style={{ color: TOKENS.text[3] }}> · {x.why}{ageDays(x.alert.created_at, now) != null ? ` · ${ageDays(x.alert.created_at, now)} d old` : ''}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function WatchProspects() {
  const [params, setParams] = useSearchParams()
  const pq = positionQuery(params)
  const paging = useListOffset(JSON.stringify(pq) + (params.get('lane') || 'actionable'))
  const requestedLane = params.get('lane') || 'actionable'
  const { data: raw, loading, error, refetch } = useApi<any>(withQuery('/api/v3/data-broker/watch-prospects', { ...pq, lane: requestedLane, offset: String(paging.offset), limit: '25' }), 120_000)
  const { data: alertsRaw } = useApi<any>('/api/v2/watch/alerts/list', 120_000)
  const p: ProspectsPayload | null = useMemo(() => unwrap(raw), [raw])
  const lane = (LANE_ORDER.includes(params.get('lane') as LaneId) ? params.get('lane') : 'actionable') as LaneId
  const detail = useMobilePageDetail('symbol')
  const sheet = useConflictSheet()
  const sel = detail.id
  const setSel = (symbol: string | null) => symbol ? detail.open(symbol) : detail.close()
  const openConflict = (row: ProspectRow, key = conflictSection(row).findings[0]?.key) => {
    if (!key) {detail.open(row.symbol); return}
    const next = new URLSearchParams(params); next.set('symbol', row.symbol); next.set('conflict', key)
    setParams(next, {state: {w9DetailOpened: true}})
  }
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [proposeFor, setProposeFor] = useState<WatchlistProposeSeed | null>(null)
  const [alertFor, setAlertFor] = useState<ProspectRow | null>(null)
  const [toast, setToast] = useState('')
  const tied = useMemo(() => tieAlerts(p, alertsRaw), [p, alertsRaw])
  const cio = useCioReview(refetch)
  const now = new Date()

  const pickLane = (id: LaneId) => {
    paging.reset()
    const next = new URLSearchParams(params)
    next.set('lane', id)
    setParams(next, { replace: true })
  }

  if (!p) {
    return (
      <div className="w9-page" data-testid="watch-prospects" style={{ ...panel, padding: 16, color: TOKENS.text[2] }}>
        {loading ? 'Loading prospects…' : `Prospects unavailable${error ? ` — ${String(error)}` : ''}.`}
        {!loading && <button type="button" onClick={() => refetch()} style={{ marginLeft: 8, ...chipStyle('info', 'outline', 'md'), cursor: 'pointer' }}>Retry</button>}
      </div>
    )
  }

  const current = laneById(p, lane)
  const allItems = p.lanes.flatMap(l => l.items)
  const selected = allItems.find(r => r.symbol === sel) || null

  const onStep = (r: ProspectRow) => {
    if (asksCio(r.next_action.kind)) {askFromRow(r, cio, openConflict, setSel); return}
    setSel(r.symbol)
    if (r.next_action.kind === 'propose') setProposeFor(proposeSeed(r) as WatchlistProposeSeed)
    else if (r.next_action.kind === 'set_alert') setAlertFor(r)
  }

  return (
    <div className="w9-page" data-testid="watch-prospects" style={{ display: 'flex', flexDirection: 'column', gap: 14, fontSize: TYPE.md, color: TOKENS.text[0] }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
        <div style={{ fontSize: TYPE.base + 1, color: TOKENS.text[1], maxWidth: 820 }}>
          Your prospects, in the order you should look at them. One record per security — the same conviction, stage and
          next step on every page{p.interim ? ' once the CIO prospect store is live' : ''}.
        </div>
        {p.interim && (
          <span data-testid="watch-interim" title={TOOLTIPS.source(p)}
            style={{ fontFamily: FONT.mono, fontSize: TYPE.sm, color: TOKENS.warning, border: `1px dashed ${toneVars('warning').border}`, borderRadius: RADIUS.md, padding: '3px 7px' }}>
            {p.source_label}
          </span>
        )}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        {headerChips(p).map(c => (
          <Chip key={c.key} tone={c.tone} tip={c.tip} testId={`watch-chip-${c.key}`}><b>{c.label}</b>&nbsp;{c.value}</Chip>
        ))}
      </div>

      <div className="watch-stage-grid" role="group" aria-label="Stages">
        {p.lanes.map(l => {
          const on = l.id === lane
          const tone = toneVars(LANE_TONE[l.id])
          return (
            <button key={l.id} type="button" aria-pressed={on} onClick={() => pickLane(l.id)} data-testid={`watch-lane-${l.id}`}
              title={TOOLTIPS.lane[l.id]}
              style={{
                display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'flex-start', textAlign: 'left', cursor: 'pointer',
                borderRadius: RADIUS.lg, padding: '6px 10px', minHeight: 60, color: TOKENS.text[0],
                background: on ? TOKENS.bg[2] : TOKENS.bg[1], border: `1px solid ${on ? tone.color : TOKENS.border}`,
              }}>
              <span style={{ fontFamily: FONT.mono, fontSize: TYPE.xl, fontWeight: 700, color: tone.color }}>{l.count}</span>
              <span style={{ fontSize: TYPE.base + 1, fontWeight: 700 }}>{l.label}</span>
              <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{l.hint}</span>
            </button>
          )
        })}
      </div>

      <PositionFilterBar specs={(p as any).position_filters} facets={(p as any).position_facets} testId="prospects-position-filters" />
      <ListPager page={(p as any).pagination} previous={paging.previous} next={paging.next} busy={loading} gap={(current as any)?.payload_gap} />
      <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>Filters, sorts and facet counts cover the curated prospect window across all pages. Names below each lane cap remain listed as overflow. My Watchlist evaluates every name in your list.</div>

      {toast && <div role="status" style={{ ...chipStyle('success', 'soft', 'md'), alignSelf: 'flex-start' }}>{toast}</div>}

      <div className="watch-card-list-viewport">
        <section className="watch-record-panel" aria-label="Prospects" style={{ minWidth: 0 }}>
          <div className="watch-record-table watch-card-list">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '12px 16px', flexWrap: 'wrap', gap: 6, borderBottom: `1px solid ${TOKENS.border}` }}>
              <h2 style={{ margin: 0, fontSize: TYPE.md + 2 }} data-testid="watch-list-title">
                {current?.label} · {(p as any).counts?.filtered ? 'filtered ' : ''}{current?.count ?? 0}{current && current.items.length < current.count ? ` (${current.items.length} on this page)` : ''}
              </h2>
              <span style={{ fontSize: TYPE.base, color: TOKENS.text[2] }} title={p.curation?.sort_order}>sorted by conviction, then priority</span>
            </div>
            <WatchCardHeader />
            {(current?.items || []).length === 0 && (
              <div style={{ padding: 16, color: TOKENS.text[2] }}>Nothing in {current?.label ?? 'this lane'} right now.</div>
            )}
            {(current?.items || []).map(r => (
              <Row key={r.symbol} r={r} selected={sel === r.symbol} onSelect={() => setSel(r.symbol)} onStep={onStep} onOpenConflict={openConflict} cio={cio}
                onAlert={r => setAlertFor(r)} alerts={(tied.bySymbol[r.symbol] || []).length} onMineChanged={m => { setToast(m); refetch() }} />
            ))}
            {current && current.overflow.length > 0 && (
              <div data-testid="watch-overflow" style={{ padding: '10px 16px', fontSize: TYPE.base, color: TOKENS.text[2] }}
                title="The lane is capped so it stays readable; these rows are below the cap by conviction, not hidden by judgment.">
                {current.overflow.length} more below the {current.cap}-row cap{(p as any).counts?.filtered ? ' (not evaluated against active filters)' : ''}: {current.overflow.slice(0, 30).join(', ')}{current.overflow.length > 30 ? '…' : ''}
              </div>
            )}
          </div>
        </section>

        {selected && !sheet.key && !detail.mobile && <aside className="watch-card-detail" aria-label="Prospect record" style={panel}>
          <button type="button" autoFocus onClick={() => setSel(null)} style={{ ...chipStyle('neutral', 'outline', 'md'), minHeight: 44, cursor: 'pointer' }}>Back to list</button>
          <Detail r={selected} cio={cio} onOpenConflict={key => openConflict(selected, key)} />
        </aside>}
        {selected && !sheet.key && detail.mobile && <MobileDetailSheet title={`${selected.symbol} · prospect record`} onBack={detail.close}>
          <Detail r={selected} cio={cio} onOpenConflict={key => openConflict(selected, key)} />
        </MobileDetailSheet>}
        {selected && sheet.key && <WatchConflictDetail row={selected} onBack={sheet.close} onRefresh={refetch} />}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {drawers(p, tied).map(d => (
          <div key={d.id} style={panel} data-testid={`watch-drawer-${d.id}`}>
            <button type="button" aria-expanded={!!open[d.id]} onClick={() => setOpen(o => ({ ...o, [d.id]: !o[d.id] }))}
              style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, background: 'none', border: 'none', color: TOKENS.text[0], padding: '12px 16px', cursor: 'pointer', fontSize: TYPE.md, minHeight: 46, textAlign: 'left' }}>
              <span><b>{d.title}</b> <span style={{ color: TOKENS.text[2] }}>· {d.summary}</span></span>
              <span aria-hidden="true" style={{ color: TOKENS.info, whiteSpace: 'nowrap' }}>{open[d.id] ? 'Hide ▴' : 'Show ▾'}</span>
            </button>
            {open[d.id] && (
              <div style={{ borderTop: `1px solid ${TOKENS.border}`, padding: '12px 16px', fontSize: TYPE.base + 1, lineHeight: 1.6, color: TOKENS.text[1] }}>
                {d.id === 'alerts' && <AlertsBody t={tied} now={now} />}
                {d.id === 'expired' && (
                  <div data-testid="watch-drawer-expired-body">
                    Signals past their window close automatically; a held name with an expired signal stays in Manage, not here.
                    <div style={{ fontFamily: FONT.mono, marginTop: 6 }}>
                      {[...(laneById(p, 'expired')?.items || []).map(r => r.symbol), ...(laneById(p, 'expired')?.overflow || [])].join(' · ') || 'None.'}
                    </div>
                  </div>
                )}
                {d.id === 'how' && (
                  <div data-testid="watch-drawer-how-body" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <span>
                      n8n gathers prices, positions, scans, catalysts and research on schedule. The CIO agent writes one record per
                      security: stage, conviction (with its parts), stance, next trigger and next step. Every page reads that record,
                      so Home, Watch, Trade AI, Options, Open Trades and Telegram agree. Conflicting inputs are shown, never silently resolved.
                    </span>
                    {p.interim && (
                      <span style={{ color: TOKENS.warning }}>
                        Today ({p.source_label}): this page builds the record itself from the CIO opportunity projection (conviction),
                        the Watch decision standards (stage, expiry), the Trade AI decision projection, the broker-synced held reader and
                        the re-entry desk. Curation: one lane per security, held names always in Manage, at most{' '}
                        {Object.entries(p.curation?.caps || {}).map(([k, v]) => `${v} ${k}`).join(' · ')} rows per lane, expired
                        signals auto-closed.
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {proposeFor && (
        <WatchlistProposeModal
          seed={proposeFor}
          onClose={() => setProposeFor(null)}
          onProposed={res => { setToast(res.message || `${res.symbol} queued as proposal #${res.proposal_id}`); refetch() }}
        />
      )}
      {alertFor && (
        <ReEntryAlertArmModal
          symbol={alertFor.symbol}
          intel={alertIntel(alertFor)}
          noteTag="watch-prospect"
          onClose={() => setAlertFor(null)}
          onArmed={summary => { setToast(`${alertFor.symbol}: armed ${summary}`); setAlertFor(null) }}
        />
      )}
    </div>
  )
}
