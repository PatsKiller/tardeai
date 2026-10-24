/** Watch — your prospects, in the order you should look at them (Gate 3 mockup, operator directive 2026-10-22).
 *
 *  Reads ONE projection: GET /api/v3/data-broker/watch-prospects (scripts/lib/data_broker/watch_prospects.py) — the
 *  CIO prospect record when its store is live, an interim adapter until then (labelled on the page). The server owns
 *  lane, conviction, stance, conflicts, trigger and the one next step; this page renders them.
 *
 *  Actions reuse existing operator flows only: Propose → WatchlistProposeModal (POST /api/v2/watchlist/:sym/propose,
 *  you size it, it goes to Proposals for approval); Set alert → ReEntryAlertArmModal (POST /api/v2/watch/alerts,
 *  advisory notifications); Protect first → Open Trades; Ask the CIO → POST /api/v3/opportunities/:sym/review-request.
 *  Nothing here sizes, orders or stops on its own. */
import { AccountChip } from '../components/AccountChip'
import { useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, chipStyle, numStyle, toneVars, type Tone } from '../lib/designTokens'
import {
  LANE_ORDER, LANE_TONE, TOOLTIPS, ageDays, alertIntel, alertLabel, convictionTone, drawers, headerChips, laneById,
  proposeSeed, stanceLabel, stanceTone, stepTone, tieAlerts, unwrap,
  type LaneId, type ProspectRow, type ProspectsPayload, type TiedAlerts,
} from '../lib/watchProspectsModel'
import WatchlistProposeModal, { type WatchlistProposeSeed } from '../components/WatchlistProposeModal'
import ReEntryAlertArmModal from '../components/reentry/ReEntryAlertArmModal'
import PositionFilterBar from '../components/watch/PositionFilterBar'
import { StarToggle } from '../components/watch/MineControls'
import {
  alertLevelsLabel, money, positionChip, soldByName, positionQuery, readinessTone, reentryLabel, resultTone, roundTripLabel,
  roundTripPath, withQuery, type ListRow,
} from '../lib/watchListsModel'

const panel: CSSProperties = {
  background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, minWidth: 0,
}
const label: CSSProperties = {
  fontSize: TYPE.xs, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: TOKENS.text[2],
}
export const GRID = '96px 104px 84px minmax(180px, 1fr) 160px 130px'

function Bar({ value, tone, height = 4 }: { value: number | null; tone: Tone; height?: number }) {
  const w = value == null ? 0 : Math.max(0, Math.min(100, value))
  return (
    <span aria-hidden="true" style={{ display: 'block', height, background: TOKENS.bg[3], borderRadius: RADIUS.sm, overflow: 'hidden' }}>
      <span style={{ display: 'block', height, width: `${w}%`, background: toneVars(tone).color }} />
    </span>
  )
}

export function StepButton({ row, onStep }: { row: ProspectRow; onStep: (r: ProspectRow) => void }) {
  const a = row.next_action
  const t = toneVars(stepTone(a.kind))
  const style: CSSProperties = {
    whiteSpace: 'nowrap', fontSize: TYPE.base, fontWeight: 700, padding: '3px 8px', borderRadius: RADIUS.md,
    minHeight: 26, boxSizing: 'border-box', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    background: t.bg, border: `1px solid ${t.border}`, color: t.color, cursor: 'pointer', textDecoration: 'none',
  }
  if (a.kind === 'none') return <span style={{ color: TOKENS.text[3] }} title={a.reason}>—</span>
  if (a.href && (a.kind === 'protect' || a.kind === 'decide' || a.kind === 'open_position' || a.kind === 'review_add')) {
    const to = a.href.replace(/^\/v3/, '')
    return <Link to={to} title={a.reason} style={style} data-testid="watch-step" data-step={a.kind}>{a.label}</Link>
  }
  return (
    <button type="button" title={a.reason} style={style} onClick={() => onStep(row)} data-testid="watch-step" data-step={a.kind}>
      {a.label}
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

export function Row({ r, selected, onSelect, onStep, alerts, onMineChanged, extra }: {
  r: ProspectRow; selected: boolean; onSelect: () => void; onStep: (r: ProspectRow) => void; alerts: number
  onMineChanged?: (msg: string) => void; extra?: ReactNode
}) {
  const ct = convictionTone(r.conviction)
  const lr = r as ListRow
  const pchip = positionChip(lr)
  return (
    <div
      data-testid="watch-row" data-symbol={r.symbol} data-lane={r.lane}
      style={{
        display: 'grid', gridTemplateColumns: GRID, gap: 8, padding: '3px 12px', alignItems: 'center',
        borderBottom: `1px solid ${TOKENS.borderSubtle}`,
        background: selected ? TOKENS.bg[2] : undefined,
        borderLeft: `3px solid ${selected ? TOKENS.info : 'transparent'}`,
      }}
    >
      <span style={{ display: 'flex', gap: 4, alignItems: 'flex-start', minWidth: 0 }}>
      <StarToggle symbol={r.symbol} on={!!lr.mine} onChanged={onMineChanged} surface="watch.row" size="sm" />
      <button
        type="button" onClick={onSelect} aria-pressed={selected} title={`Open the ${r.symbol} record`}
        style={{ background: 'none', border: 'none', padding: 0, textAlign: 'left', cursor: 'pointer', color: TOKENS.text[0], fontFamily: FONT.mono, fontWeight: 700, fontSize: TYPE.md, minHeight: 26 }}
      >
        {r.symbol}
        {lr.mine && !lr.starred && <span title={(lr.membership || []).map(m => m.label).join(' · ') || 'Your name'} style={{ marginLeft: 3, fontSize: TYPE.xs, color: TOKENS.info }}>●</span>}
        {alerts > 0 && <span title={`${alerts} armed Watch alert(s) on this symbol`} style={{ marginLeft: 4, fontSize: TYPE.xs, color: TOKENS.warning }}>🔔{alerts}</span>}
        {pchip && <span title={pchip.tip} data-testid="watch-position-chip" style={{ display: 'block', fontFamily: FONT.sans, fontWeight: 600, fontSize: TYPE.xs, color: toneVars(pchip.tone).color }}>{pchip.label}</span>}
      </button>
      </span>
      <span style={{ display: 'flex', flexDirection: 'column', gap: 3 }} title={TOOLTIPS.conviction}>
        <span style={{ ...numStyle, fontWeight: 700, color: r.conviction == null ? TOKENS.text[3] : TOKENS.text[0] }}>
          {r.conviction == null ? 'n/a' : r.conviction.toFixed(0)}
          {r.conviction_stale && <span style={{ color: TOKENS.warning, fontSize: TYPE.xs }}> stale</span>}
        </span>
        <Bar value={r.conviction} tone={ct} />
      </span>
      <span title={TOOLTIPS.stance} style={{ fontSize: TYPE.base, fontWeight: 700, color: toneVars(stanceTone(r.stance)).color }}>{stanceLabel(r.stance)}</span>
      <span style={{ fontSize: TYPE.base, lineHeight: 1.35, color: TOKENS.text[1] }}>
        {r.why}
        {lr.expiry_suggestion && <span style={{ display: 'block', color: TOKENS.warning }} title="Your names never expire off the page; an expired signal only suggests a review.">Review suggested: {lr.expiry_suggestion.suggest}</span>}
        {lr.last_round_trip && <span data-testid="watch-last-trade" style={{ display: 'block', color: toneVars(resultTone(lr.last_round_trip)).color }} title={`Last round trip ${roundTripPath(lr.last_round_trip)}. ${lr.last_round_trip.exit_cause_evidence || ''}`}>Last trade {roundTripLabel(lr.last_round_trip)}</span>}
        {lr.reentry && <span style={{ display: 'block', color: toneVars(readinessTone(lr.reentry)).color }} title={`Re-Entry Desk classifier: ${lr.reentry.state}. Alert levels ${alertLevelsLabel(lr.reentry)}.`}>Re-entry {reentryLabel(lr.reentry)}</span>}
        {r.whats_missing[0] && <span style={{ display: 'block', color: TOKENS.text[3] }}>Missing: {r.whats_missing[0]}</span>}
        {r.conflicts.map((c, i) => (
          <span key={i} data-testid="watch-conflict" style={{ display: 'block', color: TOKENS.warning }}>⚠ {c.summary}</span>
        ))}
      </span>
      <span title={TOOLTIPS.trigger} style={{ fontFamily: FONT.mono, fontSize: TYPE.base, color: TOKENS.text[1] }}>{r.next_trigger.label}</span>
      <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}><StepButton row={r} onStep={onStep} />{extra}</span>
    </div>
  )
}

export function Detail({ r, onAskCio, cioMsg }: { r: ProspectRow | null; onAskCio: (r: ProspectRow) => void; cioMsg: string }) {
  if (!r) return <div style={{ color: TOKENS.text[2], fontSize: TYPE.base }}>Click a symbol to see its full record and where it appears.</div>
  return (
    <div data-testid="watch-detail" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontFamily: FONT.mono, fontWeight: 700, fontSize: TYPE.lg + 2 }}>{r.symbol}</span>
        <span style={{ fontSize: TYPE.base, color: TOKENS.text[2], textAlign: 'right' }}>{r.company || ''}</span>
      </div>
      <div style={{ fontSize: TYPE.base + 1, lineHeight: 1.5 }}>{r.summary}</div>
      <PositionDetail r={r as ListRow} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }} data-testid="watch-components">
        <span style={label} title={TOOLTIPS.conviction}>
          Conviction {r.conviction == null ? 'n/a' : r.conviction.toFixed(0)} — what it's made of
        </span>
        {r.conviction_components.length === 0 && <span style={{ fontSize: TYPE.base, color: TOKENS.text[3] }}>No components — not in the CIO curator universe yet.</span>}
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
      {r.conflicts.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }} data-testid="watch-detail-conflicts">
          <span style={label} title={TOOLTIPS.conflicts}>Conflicts — shown, not resolved</span>
          {r.conflicts.map((c, i) => (
            <div key={i} style={{ fontSize: TYPE.base, lineHeight: 1.45, border: `1px solid ${toneVars('warning').border}`, borderRadius: RADIUS.md, padding: 8 }}>
              <div style={{ color: TOKENS.warning, fontWeight: 700 }}>{c.summary}</div>
              <div><b>{String(c.a.value)}</b> · {c.a.source || '—'} · {c.a.at ? c.a.at.slice(0, 16).replace('T', ' ') : 'time unknown'}</div>
              <div><b>{String(c.b.value)}</b> · {c.b.source || '—'} · {c.b.at ? c.b.at.slice(0, 16).replace('T', ' ') : 'time unknown'}</div>
            </div>
          ))}
          <button type="button" onClick={() => onAskCio(r)} data-testid="watch-ask-cio"
            title="Queues a CIO symbol review (POST /api/v3/opportunities/{symbol}/review-request). It does not change the record."
            style={{ ...chipStyle('warning', 'outline', 'md'), cursor: 'pointer', alignSelf: 'flex-start', padding: '6px 10px', minHeight: 32 }}>
            Ask the CIO to review
          </button>
          {cioMsg && <span style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{cioMsg}</span>}
        </div>
      )}
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
      <div style={{ fontSize: TYPE.base + 1, lineHeight: 1.5, background: TOKENS.bg[2], borderRadius: RADIUS.md, padding: 10 }}>
        <b>Next:</b> {r.next_action.label === '—' ? 'nothing until new evidence arrives.' : `${r.next_action.label} — ${r.next_action.reason}`}
      </div>
      <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>
        Evidence {r.evidence_at ? r.evidence_at.slice(0, 16).replace('T', ' ') : '—'} · expires {r.expires_at ? r.expires_at.slice(0, 16).replace('T', ' ') : '—'}
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
          {soldByName(r) && <div data-testid="watch-sold-account" style={{ color: TOKENS.text[2] }}>Sold in <AccountChip account={r.last_sell_account || rt.account} label={soldByName(r)} compact /></div>}
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
  delete pq.sort
  const { data: raw, loading, error, refetch } = useApi<any>(withQuery('/api/v3/data-broker/watch-prospects', pq), 120_000)
  const { data: alertsRaw } = useApi<any>('/api/v2/watch/alerts/list', 120_000)
  const p: ProspectsPayload | null = useMemo(() => unwrap(raw), [raw])
  const lane = (LANE_ORDER.includes(params.get('lane') as LaneId) ? params.get('lane') : 'actionable') as LaneId
  const [sel, setSel] = useState<string | null>(params.get('symbol'))
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [proposeFor, setProposeFor] = useState<WatchlistProposeSeed | null>(null)
  const [alertFor, setAlertFor] = useState<ProspectRow | null>(null)
  const [toast, setToast] = useState('')
  const [cioMsg, setCioMsg] = useState('')
  const tied = useMemo(() => tieAlerts(p, alertsRaw), [p, alertsRaw])
  const now = new Date()

  const pickLane = (id: LaneId) => {
    const next = new URLSearchParams(params)
    next.set('lane', id)
    setParams(next, { replace: true })
  }

  if (!p) {
    return (
      <div data-testid="watch-prospects" style={{ ...panel, padding: 16, color: TOKENS.text[2] }}>
        {loading ? 'Loading prospects…' : `Prospects unavailable${error ? ` — ${String(error)}` : ''}.`}
        {!loading && <button type="button" onClick={() => refetch()} style={{ marginLeft: 8, ...chipStyle('info', 'outline', 'md'), cursor: 'pointer' }}>Retry</button>}
      </div>
    )
  }

  const current = laneById(p, lane)
  const allItems = p.lanes.flatMap(l => l.items)
  const selected = allItems.find(r => r.symbol === sel) || null

  const onStep = (r: ProspectRow) => {
    setSel(r.symbol)
    if (r.next_action.kind === 'propose') setProposeFor(proposeSeed(r) as WatchlistProposeSeed)
    else if (r.next_action.kind === 'set_alert') setAlertFor(r)
    else if (r.next_action.kind === 'resolve_conflict') setCioMsg('')
  }
  const askCio = async (r: ProspectRow) => {
    setCioMsg('Queuing…')
    try {
      const res = await fetch(`/api/v3/opportunities/${encodeURIComponent(r.symbol)}/review-request`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: `Watch conflict: ${r.conflicts.map(c => c.summary).join(' | ')}`.slice(0, 240) }),
      }).then(x => x.json())
      const d = res?.data ?? res
      setCioMsg(d?.ok ? (d.already_open ? 'A CIO review is already queued for this symbol.' : 'CIO review queued.') : `Could not queue: ${d?.error || 'error'}`)
    } catch (e) {
      setCioMsg(`Could not queue: ${String(e).slice(0, 80)}`)
    }
  }

  return (
    <div data-testid="watch-prospects" style={{ display: 'flex', flexDirection: 'column', gap: 14, fontSize: TYPE.md, color: TOKENS.text[0] }}>
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

      <div role="group" aria-label="Stages" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
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

      <PositionFilterBar specs={(p as any).position_filters} facets={(p as any).position_facets} sortable={false} testId="prospects-position-filters" />

      {toast && <div role="status" style={{ ...chipStyle('success', 'soft', 'md'), alignSelf: 'flex-start' }}>{toast}</div>}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-start' }}>
        <section aria-label="Prospects" style={{ ...panel, flex: '999 1 700px', overflowX: 'auto' }}>
          <div style={{ minWidth: 800 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '12px 16px', borderBottom: `1px solid ${TOKENS.border}` }}>
              <h2 style={{ margin: 0, fontSize: TYPE.md + 2 }} data-testid="watch-list-title">
                {current?.label} · {current?.count ?? 0}{current && current.items.length < current.count ? ` (top ${current.items.length} shown)` : ''}
              </h2>
              <span style={{ fontSize: TYPE.base, color: TOKENS.text[2] }} title={p.curation?.sort_order}>sorted by conviction, then priority</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: GRID, gap: 10, padding: '8px 16px', borderBottom: `1px solid ${TOKENS.borderSubtle}`, ...label }}>
              <span>Symbol</span>
              <span title={TOOLTIPS.conviction}>Conviction</span>
              <span title={TOOLTIPS.stance}>Stance</span>
              <span title={TOOLTIPS.why}>Why it's here · what's missing</span>
              <span title={TOOLTIPS.trigger}>Next trigger</span>
              <span title={TOOLTIPS.step}>Next step</span>
            </div>
            {(current?.items || []).length === 0 && (
              <div style={{ padding: 16, color: TOKENS.text[2] }}>Nothing in {current?.label ?? 'this lane'} right now.</div>
            )}
            {(current?.items || []).map(r => (
              <Row key={r.symbol} r={r} selected={sel === r.symbol} onSelect={() => setSel(r.symbol)} onStep={onStep}
                alerts={(tied.bySymbol[r.symbol] || []).length} onMineChanged={m => { setToast(m); refetch() }} />
            ))}
            {current && current.overflow.length > 0 && (
              <div data-testid="watch-overflow" style={{ padding: '10px 16px', fontSize: TYPE.base, color: TOKENS.text[2] }}
                title="The lane is capped so it stays readable; these rows are below the cap by conviction, not hidden by judgment.">
                {current.overflow.length} more below the {current.cap}-row cap: {current.overflow.slice(0, 30).join(', ')}{current.overflow.length > 30 ? '…' : ''}
              </div>
            )}
          </div>
        </section>

        <aside aria-label="Prospect record" style={{ ...panel, flex: '1 1 320px', maxWidth: 460, padding: 16 }}>
          <Detail r={selected} onAskCio={askCio} cioMsg={cioMsg} />
        </aside>
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
