import BrokerIntelPanel from './BrokerIntelPanel'
import BrokerAccountPicker, { type BrokerAccount } from './BrokerAccountPicker'
import ThesisValidityBar from './ThesisValidityBar'
import ActionButton from './ActionButton'
import { brokerOf, fmtMoney, tradeEconomics } from '../lib/brokerThesis'

const MUTED = '#94a3b8'
const TEXT0 = '#f8fafc'
const TEXT1 = '#dbeafe'
const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'
const PURPLE = '#a78bfa'
const RED = '#ef4444'

const gateColor = (s: string) => s === 'PASS' ? GREEN : s === 'WARN' ? AMBER : s === 'BLOCK' ? RED : MUTED

type Props = {
  proposal: any
  accounts: BrokerAccount[]
  destAccount: string
  onDestAccountChange: (acct: string) => void
  fvMap: Record<string, any>
  detailLoading?: boolean
  refreshBusy?: boolean
  oversightBusy?: boolean
  cloudBusy?: boolean
  oversightMsg?: string
  routeMsg?: string
  acctPreviewBusy?: boolean
  onRefresh: () => void
  onEdit: () => void
  onManual: () => void
  onRoute: () => void
  onQueueOversight: () => void
  onRunCloudOversight: () => void
}

export default function BrokerProposalCard({
  proposal: p,
  accounts,
  destAccount: dest,
  onDestAccountChange,
  fvMap,
  detailLoading,
  refreshBusy,
  oversightBusy,
  cloudBusy,
  oversightMsg,
  routeMsg,
  acctPreviewBusy,
  onRefresh,
  onEdit,
  onManual,
  onRoute,
  onQueueOversight,
  onRunCloudOversight,
}: Props) {
  const preview = p._preview
  const previewForDest = Boolean(preview && preview.account === dest)
  const evalData = (previewForDest ? preview?.evaluation : null) || p.evaluation
  const fid = brokerOf(dest || p.account) === 'Fidelity' || p.execution_mode === 'manual'
  const gate = evalData?.status || p.gate_status
  const ov = evalData?.oversight || p.oversight || p.intel?.oversight || {}
  const ovStatus = ov.status || (ov.violations?.length ? 'BLOCK' : ov.warnings?.length ? 'WARN' : null)
  const savedShares = Number(p.proposed_shares) || 0
  const maxSh = evalData?.max_shares ?? p.broker_sizing?.max_shares ?? p.evaluation?.max_shares
  const recSh = evalData?.recommended_shares ?? p.broker_sizing?.recommended_shares ?? p.evaluation?.recommended_shares
  const capShares = recSh != null ? Number(recSh) : (maxSh != null ? Number(maxSh) : savedShares)
  const oversized = Boolean(savedShares && capShares && savedShares > capShares)
    || Boolean(p.broker_sizing?.oversized)
    || (evalData?.violations || []).some((v: string) => /exceed max/i.test(v))
  const gateBlocked = gate === 'BLOCK' || ovStatus === 'BLOCK'
  const sizingViolations = evalData?.violations || p.broker_sizing?.violations || p.evaluation?.violations || []
  const savedEcon = tradeEconomics(savedShares, Number(p.proposed_entry), Number(p.proposed_stop), Number(p.proposed_target1))
  const capEcon = oversized && capShares > 0 && capShares !== savedShares
    ? tradeEconomics(capShares, Number(p.proposed_entry), Number(p.proposed_stop), Number(p.proposed_target1))
    : null
  const accountLabel = dest || p.account || 'account'
  const previewNote = previewForDest && dest !== (p.account || '') ? ' (preview)' : ''
  const intel = p.intel?.ok ? {
    ...p.intel,
    oversight: { ...ov, status: ovStatus || ov.status, violations: ov.violations, warnings: ov.warnings },
  } : (p.intel?.ok === false ? null : { ok: true, oversight: ov, agent_reviews: ov.agents?.reviews || [] })

  const metricBox = {
    background: 'rgba(2,6,23,.35)',
    border: '1px solid rgba(148,163,184,.15)',
    borderRadius: 8,
    padding: '8px 10px',
  } as const

  return (
    <article style={{
      borderRadius: 14,
      background: 'linear-gradient(180deg, rgba(15,23,42,.75) 0%, rgba(15,23,42,.55) 100%)',
      border: `1px solid ${gateBlocked ? 'rgba(239,68,68,.35)' : 'rgba(148,163,184,.22)'}`,
      overflow: 'hidden',
      boxShadow: gateBlocked ? '0 0 0 1px rgba(239,68,68,.15)' : undefined,
    }}>
      {/* Header */}
      <header style={{
        display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
        padding: '12px 14px',
        borderBottom: '1px solid rgba(148,163,184,.12)',
        background: 'rgba(0,0,0,.2)',
      }}>
        <span style={{
          fontSize: 18, fontWeight: 900, color: TEXT0, fontFamily: 'ui-monospace, monospace', letterSpacing: '-.02em',
        }}>{p.symbol}</span>
        <span style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 5, background: 'rgba(249,115,22,.14)', color: '#fb923c' }}>
          {p.strategy_id}
        </span>
        <span style={{
          fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5,
          background: fid ? 'rgba(168,85,247,.18)' : 'rgba(96,165,250,.15)',
          color: fid ? PURPLE : BLUE,
        }}>{p.execution_label || (fid ? 'Manual · Fidelity FA' : 'Schwab · auto or manual')}</span>
        {gate && (
          <span style={{ fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5, background: `${gateColor(gate)}22`, color: gateColor(gate) }}>
            GATE {gate}
          </span>
        )}
        {ovStatus && (
          <span style={{ fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5, background: `${gateColor(ovStatus)}18`, color: ovStatus === 'PASS' ? PURPLE : gateColor(ovStatus) }}>
            AI {ovStatus}
          </span>
        )}
        {oversized && maxSh != null && (
          <span style={{ fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5, background: 'rgba(239,68,68,.15)', color: RED }}>
            OVERSIZED · cap {Number(maxSh).toLocaleString()} sh
          </span>
        )}
        {(() => {
          const fv = fvMap[String(p.symbol).toUpperCase()]
          if (!fv) return null
          const pc = (v: any) => v == null ? MUTED : Number(v) > 0 ? GREEN : Number(v) < 0 ? RED : MUTED
          const rsiC = fv.rsi == null ? MUTED : fv.rsi >= 70 ? RED : fv.rsi <= 30 ? GREEN : TEXT1
          return (
            <span title="Finviz daily" style={{ display: 'inline-flex', gap: 7, padding: '2px 7px', borderRadius: 5, background: 'rgba(96,165,250,.08)', border: '1px solid rgba(96,165,250,.18)', fontSize: 9, color: MUTED }}>
              RSI <b style={{ color: rsiC }}>{fv.rsi ?? '—'}</b>
              W <b style={{ color: pc(fv.perf_week) }}>{fv.perf_week != null ? `${fv.perf_week > 0 ? '+' : ''}${Number(fv.perf_week).toFixed(1)}%` : '—'}</b>
            </span>
          )
        })()}
        <span style={{ flex: 1 }} />
        <ActionButton variant="secondary" size="sm" loading={refreshBusy} onClick={onRefresh}
          style={{ border: '1px solid rgba(96,165,250,.4)', color: BLUE, fontWeight: 800 }}>
          {refreshBusy ? 'Refreshing…' : '↻ Refresh prices'}
        </ActionButton>
        <ActionButton variant="secondary" size="sm" onClick={onEdit}
          style={{ border: '1px solid rgba(245,158,11,.4)', color: AMBER, fontWeight: 800 }}>
          ✎ Edit trade
        </ActionButton>
      </header>

      {/* Body grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.2fr) minmax(0,1fr)', gap: 0 }}>
        <section style={{ padding: '12px 14px', borderRight: '1px solid rgba(148,163,184,.1)' }}>
          <ThesisValidityBar tv={p.thesis_validity} showSourceNote />
          {p.refreshed_at && (
            <div style={{ fontSize: 8.5, color: MUTED, marginTop: 6 }}>
              Refreshed {p.refreshed_at}{p.quote_provider ? ` · ${p.quote_provider}` : ''}
            </div>
          )}

          <div style={{
            marginTop: 10, padding: '8px 10px', borderRadius: 8,
            background: oversized ? 'rgba(239,68,68,.06)' : 'rgba(15,23,42,.4)',
            border: `1px solid ${oversized ? 'rgba(239,68,68,.25)' : 'rgba(148,163,184,.15)'}`,
            fontSize: 10,
          }}>
            <div style={{ fontSize: 8, fontWeight: 800, color: MUTED, textTransform: 'uppercase', marginBottom: 6 }}>Share sizing</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 16px', alignItems: 'baseline' }}>
              <span style={{ color: oversized ? RED : TEXT0 }}>
                <b style={{ fontFamily: 'monospace' }}>Queued:</b> {savedShares.toLocaleString()} sh
                {p.account && p.account !== dest ? ` · routed ${p.account}` : ''}
              </span>
              <span style={{ color: BLUE }}>
                <b style={{ fontFamily: 'monospace' }}>Cap for {accountLabel}{previewNote}:</b> {capShares.toLocaleString()} sh
              </span>
            </div>
            {oversized && (
              <div style={{ marginTop: 6, color: AMBER, fontSize: 9.5 }}>
                Queued size is paper/promote sizing — use <b>✎ Edit trade</b> to resize to {capShares.toLocaleString()} sh before routing live.
              </div>
            )}
          </div>

          {(gateBlocked || oversized) && (
            <div style={{ marginTop: 8, padding: '8px 10px', fontSize: 10, color: RED, background: 'rgba(239,68,68,.08)', borderRadius: 8, border: '1px solid rgba(239,68,68,.2)' }}>
              {(ov.violations || []).map((v: string, i: number) => <div key={i}>⛔ {v}</div>)}
              {sizingViolations.filter((v: string) => !(ov.violations || []).includes(v)).map((v: string, i: number) => <div key={`s${i}`}>⛔ {v}</div>)}
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginTop: 12 }}>
            <div style={metricBox}>
              <div style={{ fontSize: 8, color: MUTED, fontWeight: 800, textTransform: 'uppercase' }}>At queued size</div>
              <div style={{ fontSize: 12, fontWeight: 800, fontFamily: 'monospace', color: oversized ? RED : TEXT0 }}>
                {savedEcon.shares.toLocaleString()} sh @ ${Number(p.proposed_entry).toFixed(2)}
              </div>
              <div style={{ fontSize: 9, color: MUTED }}>stop ${Number(p.proposed_stop).toFixed(2)} · tgt ${Number(p.proposed_target1).toFixed(2)}</div>
            </div>
            <div style={metricBox}>
              <div style={{ fontSize: 8, color: MUTED, fontWeight: 800, textTransform: 'uppercase' }}>Risk @ queued</div>
              <div style={{ fontSize: 12, fontWeight: 800, fontFamily: 'monospace', color: RED }}>{fmtMoney(savedEcon.max_risk)}</div>
              <div style={{ fontSize: 9, color: MUTED }}>invest {fmtMoney(savedEcon.investment)}</div>
            </div>
            <div style={metricBox}>
              <div style={{ fontSize: 8, color: MUTED, fontWeight: 800, textTransform: 'uppercase' }}>Profit @ tgt</div>
              <div style={{ fontSize: 12, fontWeight: 800, fontFamily: 'monospace', color: GREEN }}>+{fmtMoney(savedEcon.profit_at_target)}</div>
              <div style={{ fontSize: 9, color: MUTED }}>R:R {p.live_rr ?? p.proposed_rr ?? '—'}{p.live_rr ? ' live' : ''}</div>
            </div>
          </div>
          {capEcon && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginTop: 8, opacity: 0.92 }}>
              <div style={{ ...metricBox, borderColor: 'rgba(96,165,250,.25)' }}>
                <div style={{ fontSize: 8, color: BLUE, fontWeight: 800, textTransform: 'uppercase' }}>If resized to cap</div>
                <div style={{ fontSize: 11, fontWeight: 800, fontFamily: 'monospace', color: BLUE }}>
                  {capEcon.shares.toLocaleString()} sh @ ${Number(p.proposed_entry).toFixed(2)}
                </div>
              </div>
              <div style={{ ...metricBox, borderColor: 'rgba(96,165,250,.25)' }}>
                <div style={{ fontSize: 8, color: BLUE, fontWeight: 800, textTransform: 'uppercase' }}>Risk @ cap</div>
                <div style={{ fontSize: 11, fontWeight: 800, fontFamily: 'monospace', color: BLUE }}>{fmtMoney(capEcon.max_risk)}</div>
              </div>
              <div style={{ ...metricBox, borderColor: 'rgba(96,165,250,.25)' }}>
                <div style={{ fontSize: 8, color: BLUE, fontWeight: 800, textTransform: 'uppercase' }}>Profit @ cap</div>
                <div style={{ fontSize: 11, fontWeight: 800, fontFamily: 'monospace', color: BLUE }}>+{fmtMoney(capEcon.profit_at_target)}</div>
              </div>
            </div>
          )}
        </section>

        <section style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <BrokerAccountPicker
            accounts={accounts}
            value={dest}
            onChange={onDestAccountChange}
            disabled={acctPreviewBusy}
            compact
          />
          {(detailLoading || acctPreviewBusy) && (
            <div style={{ fontSize: 9, color: MUTED, fontStyle: 'italic' }}>Updating sizing & gates…</div>
          )}
        </section>
      </div>

      {/* Intel + oversight — always show oversight controls */}
      <section style={{ padding: '10px 14px', borderTop: '1px solid rgba(148,163,184,.12)', background: 'rgba(15,23,42,.35)' }}>
        {detailLoading && !intel && (
          <div style={{ fontSize: 10, color: MUTED, fontStyle: 'italic', marginBottom: 8 }}>Loading decision context…</div>
        )}
        <BrokerIntelPanel
          intel={intel || { ok: true, oversight: ov, agent_reviews: ov.agents?.reviews || [] }}
          compact
          onQueueOversight={onQueueOversight}
          onRunCloudOversight={onRunCloudOversight}
          oversightBusy={oversightBusy}
          cloudBusy={cloudBusy}
        />
        {oversightMsg && (
          <div style={{ fontSize: 9.5, marginTop: 6, color: oversightMsg.startsWith('✅') ? GREEN : AMBER }}>{oversightMsg}</div>
        )}
      </section>

      {/* Actions */}
      <footer style={{
        display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
        padding: '10px 14px', background: 'rgba(0,0,0,.25)', borderTop: '1px solid rgba(148,163,184,.1)',
      }}>
        {routeMsg && (
          <span style={{ fontSize: 10, color: routeMsg.startsWith('✅') || routeMsg.startsWith('📝') ? GREEN : routeMsg.startsWith('🔒') ? PURPLE : AMBER, flex: '1 1 100%' }}>
            {routeMsg}
          </span>
        )}
        <ActionButton variant="secondary" size="md" onClick={onManual}
          style={{ border: `1px solid ${BLUE}`, color: BLUE, fontWeight: 800 }}
          title="Log fill after executing in FA or Schwab">
          ✓ Executed manually
        </ActionButton>
        <span style={{ flex: 1 }} />
        <ActionButton
          variant={gateBlocked && !fid ? 'disabled' : 'primary'}
          size="md"
          disabled={gateBlocked && !fid}
          onClick={onRoute}
          title={gateBlocked ? 'Blocked — edit trade or resolve gates first' : (fid ? 'Record-only at Fidelity' : 'Schwab auto submit (2FA)')}
          style={fid ? { background: `${PURPLE}33`, color: PURPLE, border: `1px solid ${PURPLE}` } : { background: `${AMBER}22`, color: AMBER, border: `1px solid ${AMBER}` }}
        >
          {fid ? 'Record proposal' : 'Auto route (2FA)'}
        </ActionButton>
      </footer>
    </article>
  )
}

