import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import { BB } from '../lib/holdingsTerminalTokens'
import {
  ARCHETYPE_LABELS,
  plansFromEvent,
  rejectedFromEvent,
  type InstitutionalPlan,
  type RedeployEventDetail,
  type RedeployPlanLeg,
} from '../lib/redeployDeskTypes'

export type { RedeployEventDetail, RedeployTarget } from '../lib/redeployDeskTypes'

type TabId = 'overview' | 'plans' | 'entries' | 'rejected' | 'memo' | 'legacy'

interface Props {
  event: RedeployEventDetail
  onClose: () => void
  onDismiss: (id: number) => void
  onPropose: (symbol: string, sleeve: string, rationale: string) => void
}

const fmtDate = (s?: string) => {
  if (!s) return '—'
  const d = new Date(`${String(s).slice(0, 10)}T12:00:00`)
  return isNaN(+d) ? String(s).slice(0, 10) : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

const fmtPx = (n?: number | null) => (n == null || Number.isNaN(n) ? '—' : `$${Number(n).toFixed(2)}`)

export default function RedeployEventModal({ event, onClose, onDismiss, onPropose }: Props) {
  const ev = event
  const sale = ev.metadata?.sale_context
  const geo = ev.metadata?.market_context?.geopolitical
  const regime = ev.metadata?.market_context?.regime_posture ?? ev.metadata?.phase_c?.regime_posture
  const gaps = ev.metadata?.sleeve_gaps ?? []
  const phaseA = ev.metadata?.phase_a
  const recon = phaseA?.reconciliation
  const exposure = phaseA?.exposure_loss
  const exportReady = ev.export_readiness ?? ev.metadata?.phase_c?.export_readiness

  const metaPlans = plansFromEvent(ev)
  const needFetch = metaPlans.length === 0
  const { data: plansApi } = useApi<{ plans?: InstitutionalPlan[] }>(
    `/api/v2/deploy/plans?event_id=${ev.id}`,
    60_000,
    { enabled: needFetch },
  )

  const plans = useMemo(() => {
    if (metaPlans.length) return [...metaPlans].sort((a, b) => (b.composite_rank ?? 0) - (a.composite_rank ?? 0))
    return [...(plansApi?.plans ?? [])].map(p => ({
      ...p,
      plan_archetype: p.plan_archetype ?? (p as { plan_archetype?: string }).plan_archetype ?? '?',
    }))
  }, [metaPlans, plansApi])

  const primaryArch = ev.primary_plan_archetype ?? ev.metadata?.phase_b?.primary_archetype ?? plans[0]?.plan_archetype ?? 'F'
  const [tab, setTab] = useState<TabId>('overview')
  const [selectedArch, setSelectedArch] = useState(primaryArch)
  const [exportMsg, setExportMsg] = useState('')

  const selectedPlan = plans.find(p => p.plan_archetype === selectedArch) ?? plans[0] ?? null
  const rejected = rejectedFromEvent(ev)
  const pmMemo = ev.pm_memo ?? ev.metadata?.phase_b?.pm_memo ?? selectedPlan?.hermes_narrative

  const TABS: { id: TabId; label: string }[] = [
    { id: 'overview', label: 'OVERVIEW' },
    { id: 'plans', label: 'PLANS' },
    { id: 'entries', label: 'ENTRIES' },
    { id: 'rejected', label: 'REJECTED' },
    { id: 'memo', label: 'MEMO' },
    { id: 'legacy', label: 'LEGACY v1' },
  ]

  async function exportPlan(fmt: 'json' | 'csv', forceStale = false) {
    setExportMsg('')
    const arch = selectedPlan?.plan_archetype ?? primaryArch
    const qs = new URLSearchParams({
      event_id: String(ev.id),
      archetype: arch,
      format: fmt,
      ...(forceStale ? { force_stale: '1' } : {}),
    })
    try {
      const r = await fetch(`/api/v2/deploy/export?${qs}`)
      const j = await r.json()
      if (!j.ok && j.error === 'stale_quotes') {
        setExportMsg(`STALE: ${(j.stale_symbols ?? []).join(', ')} — use PREVIEW export`)
        return
      }
      if (j.format === 'csv' && j.content) {
        downloadText(j.content, `redeploy-${ev.symbol}-plan-${arch}.csv`, 'text/csv')
        setExportMsg(`Exported CSV plan ${arch}`)
        return
      }
      if (j.trade_plan) {
        downloadText(JSON.stringify(j.trade_plan, null, 2), `redeploy-${ev.symbol}-plan-${arch}.json`, 'application/json')
        setExportMsg(`Exported JSON plan ${arch}`)
        return
      }
      setExportMsg(j.error ? `ERR ${j.error}` : 'Export failed')
    } catch {
      setExportMsg('ERR export request failed')
    }
  }

  const deployable = recon?.deployable_cash_usd ?? ev.deployable_cash_usd
  const reconStatus = recon?.reconciliation_status ?? ev.reconciliation_status

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 1100, display: 'flex', justifyContent: 'flex-end', background: 'rgba(2,6,12,.6)' }}
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 'min(780px, 96vw)', height: '100vh', background: BB.bg,
          borderLeft: `1px solid ${BB.border}`, display: 'flex', flexDirection: 'column',
          boxShadow: '-12px 0 40px rgba(0,0,0,.65)', fontFamily: BB.mono, fontSize: BB.fontSm,
        }}
      >
        <header style={{ padding: '14px 18px', borderBottom: `1px solid ${BB.border}`, flexShrink: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <div style={{ fontSize: 18, fontWeight: 800, color: BB.amber }}>
                REDEPLOY DESK · {ev.symbol}
              </div>
              <div style={{ fontSize: 10, color: BB.text3, marginTop: 4 }}>
                {fmtDate(ev.sold_at)} · {(ev.account ?? '').replace(/_/g, ' ')}
                · net {fmt$(Number(recon?.net_proceeds_usd ?? ev.proceeds_usd ?? 0), 0)}
                {deployable != null && <> · deployable <b style={{ color: BB.green }}>{fmt$(deployable, 0)}</b></>}
                {ev.proxy_symbol ? ` · proxy ${ev.proxy_symbol}` : ''}
              </div>
            </div>
            <button type="button" onClick={onClose} aria-label="Close" style={{ background: 'transparent', border: 'none', color: BB.text3, cursor: 'pointer', fontSize: 22 }}>×</button>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
            <Tag label={(ev.tier ?? sale?.tier ?? 'moderate').toUpperCase()} color={BB.amber} />
            {reconStatus && (
              <Tag
                label={reconStatus.toUpperCase()}
                color={reconStatus === 'verified' ? BB.green : reconStatus === 'unsettled' ? BB.amberAlt : BB.blue}
              />
            )}
            {plans.length > 0 && <Tag label={`${plans.length} PLANS`} color={BB.blue} />}
            {exportReady?.export_allowed === false && <Tag label="QUOTES STALE" color={BB.amberAlt} />}
            {regime && <Tag label={`REGIME ${String(regime).toUpperCase()}`} color={BB.blue} />}
            {geo?.posture && geo.posture !== 'neutral' && <Tag label={`GEO ${String(geo.posture).toUpperCase()}`} color={BB.amberAlt} />}
            {(sale?.reduced_themes ?? []).slice(0, 3).map(t => <Tag key={t} label={`−${t}`} color={BB.red} />)}
          </div>
          <div style={{ display: 'flex', gap: 4, marginTop: 12, flexWrap: 'wrap' }}>
            {TABS.map(t => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                style={tabBtn(tab === t.id)}
              >{t.label}</button>
            ))}
          </div>
        </header>

        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {tab === 'overview' && (
            <>
              <Section title="PROCEEDS & RECONCILIATION">
                <Kv k="Net proceeds" v={fmt$(recon?.net_proceeds_usd ?? ev.proceeds_usd ?? 0, 0)} />
                <Kv k="Deployable cash" v={fmt$(deployable ?? 0, 0)} accent={BB.green} />
                <Kv k="Planned-not-actionable" v={fmt$(recon?.planned_not_actionable_usd ?? 0, 0)} />
                <Kv k="Reconciliation" v={reconStatus ?? '—'} />
                {phaseA?.portfolio_context?.is_major_sale && (
                  <div style={{ marginTop: 6, fontSize: BB.fontXs, color: BB.amberAlt }}>Major sale — oversight required before operator-ready</div>
                )}
              </Section>

              {(exposure?.sectors ?? []).length > 0 && (
                <Section title="WHAT CHANGED — EXPOSURE REMOVED">
                  {(exposure?.sectors ?? []).slice(0, 8).map(s => (
                    <div key={s.sector} style={{ fontSize: BB.fontXs, color: BB.text2, marginBottom: 3 }}>
                      {s.sector}: <b style={{ color: BB.red }}>{fmt$(s.usd_removed ?? 0, 0)}</b>
                      <span style={{ color: BB.text3 }}> ({s.weight_pct}%)</span>
                    </div>
                  ))}
                  <div style={{ fontSize: BB.fontXs, color: BB.text3, marginTop: 4 }}>
                    Income status: <b style={{ color: exposure?.income_status === 'unknown' ? BB.amber : BB.text1 }}>{exposure?.income_status ?? 'unknown'}</b>
                    {exposure?.income_usd_removed != null && exposure.income_status !== 'unknown' && (
                      <> · {fmt$(exposure.income_usd_removed, 0)}/yr removed</>
                    )}
                  </div>
                </Section>
              )}

              {(ev.lookthrough_delta ?? []).length > 0 && (
                <Section title="LOOK-THROUGH DELTA">
                  {(ev.lookthrough_delta ?? []).map((d, i) => (
                    <div key={i} style={{ color: BB.text2, fontSize: BB.fontXs, marginBottom: 4 }}>
                      {d.theme}: <b style={{ color: BB.red }}>{d.delta_pct}%</b>
                      {d.note ? <span style={{ color: BB.text3 }}> — {d.note}</span> : null}
                    </div>
                  ))}
                </Section>
              )}

              {gaps.length > 0 && (
                <Section title="PORTFOLIO GAPS">
                  {gaps.slice(0, 5).map(g => (
                    <div key={g.theme} style={{ fontSize: BB.fontXs, color: BB.text2, marginBottom: 3 }}>
                      {g.theme} <span style={{ color: BB.amber }}>{g.gap_pct}% under floor</span>
                      <span style={{ color: BB.text3 }}> ≈ {fmt$(g.gap_usd ?? 0, 0)}</span>
                    </div>
                  ))}
                </Section>
              )}
            </>
          )}

          {tab === 'plans' && (
            <>
              {plans.length === 0 ? (
                <div style={{ color: BB.text3, fontSize: BB.fontXs }}>No institutional plans — run RECOMPUTE</div>
              ) : (
                <>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
                    {plans.map(p => {
                      const arch = p.plan_archetype
                      const active = arch === selectedArch
                      return (
                        <button
                          key={arch}
                          type="button"
                          onClick={() => setSelectedArch(arch)}
                          style={{
                            ...tabBtn(active),
                            borderColor: active ? BB.amber : BB.border,
                            color: active ? BB.amber : BB.text2,
                          }}
                        >
                          {arch} {ARCHETYPE_LABELS[arch] ?? p.plan_type}
                          {arch === primaryArch ? ' ★' : ''}
                        </button>
                      )
                    })}
                  </div>
                  {selectedPlan && <PlanCard plan={selectedPlan} primary={selectedPlan.plan_archetype === primaryArch} />}
                </>
              )}
            </>
          )}

          {tab === 'entries' && (
            selectedPlan ? (
              <EntriesTable legs={selectedPlan.legs ?? []} />
            ) : (
              <div style={{ color: BB.text3, fontSize: BB.fontXs }}>Select a plan in PLANS tab</div>
            )
          )}

          {tab === 'rejected' && (
            <Section title="REJECTED ALTERNATIVES">
              {rejected.length === 0 ? (
                <div style={{ color: BB.text3, fontSize: BB.fontXs }}>None recorded</div>
              ) : rejected.map((r, i) => (
                <div key={`${r.symbol}-${i}`} style={{ marginBottom: 8, padding: 8, background: BB.bgRow, border: `1px solid ${BB.border}`, borderRadius: 2 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                    <b style={{ color: BB.text0 }}>{r.symbol}</b>
                    <Tag label={r.reason_code ?? 'RPL-ALT'} color={BB.amberAlt} />
                    {r.score != null && <span style={{ color: BB.text3, fontSize: BB.fontXs }}>score {r.score}</span>}
                  </div>
                  <div style={{ marginTop: 4, fontSize: BB.fontXs, color: BB.text2, lineHeight: 1.4 }}>{r.reason}</div>
                </div>
              ))}
            </Section>
          )}

          {tab === 'memo' && (
            <Section title="PM MEMO">
              {pmMemo ? (
                <div style={{ fontSize: BB.fontSm, color: BB.text1, lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>{pmMemo}</div>
              ) : (
                <div style={{ color: BB.text3, fontSize: BB.fontXs }}>No memo — recompute after Phase B</div>
              )}
              {selectedPlan?.hermes_narrative && selectedPlan.hermes_narrative !== pmMemo && (
                <div style={{ marginTop: 12, fontSize: BB.fontXs, color: BB.text2, lineHeight: 1.45 }}>
                  <div style={{ color: BB.text3, marginBottom: 4 }}>Plan {selectedPlan.plan_archetype} narrative</div>
                  {selectedPlan.hermes_narrative}
                </div>
              )}
            </Section>
          )}

          {tab === 'legacy' && (
            <Section title="LEGACY v1 TARGETS">
              {(ev.redeploy_plan ?? []).length === 0 ? (
                <div style={{ color: BB.text3, fontSize: BB.fontXs }}>No scored targets</div>
              ) : (ev.redeploy_plan ?? []).map((t, i) => (
                <div
                  key={t.symbol}
                  style={{
                    marginBottom: 10, padding: 10, background: i === 0 ? BB.greenDim : BB.bgRow,
                    border: `1px solid ${BB.border}`, borderRadius: 2,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 800, color: i === 0 ? BB.green : BB.text0, fontSize: 13 }}>{t.symbol}</span>
                    <span style={{ color: BB.blue }}>score {t.score}</span>
                    {t.sleeve && <span style={{ color: BB.text3, fontSize: BB.fontXs }}>{t.sleeve}</span>}
                    <span style={{ flex: 1 }} />
                    <button onClick={() => onPropose(t.symbol, t.sleeve || 'Redeploy', t.rationale || '')} style={actionBtn(BB.green)}>PROPOSE</button>
                  </div>
                  <div style={{ marginTop: 6, color: BB.text2, fontSize: BB.fontXs, lineHeight: 1.45 }}>{t.rationale}</div>
                </div>
              ))}
            </Section>
          )}

          {ev.metadata?.methodology && tab === 'overview' && (
            <div style={{ fontSize: 9, color: BB.text3, marginTop: 8, lineHeight: 1.4 }}>{ev.metadata.methodology}</div>
          )}
        </div>

        <footer style={{ padding: '12px 18px', borderTop: `1px solid ${BB.border}`, flexShrink: 0 }}>
          {exportMsg && (
            <div style={{ fontSize: BB.fontXs, color: /ERR|STALE/.test(exportMsg) ? BB.amberAlt : BB.green, marginBottom: 8 }}>{exportMsg}</div>
          )}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <button onClick={() => void exportPlan('json')} style={actionBtn(BB.green)} title="Requires fresh quotes">EXPORT JSON</button>
            <button onClick={() => void exportPlan('csv')} style={actionBtn(BB.blue)}>EXPORT CSV</button>
            {exportReady?.export_allowed === false && (
              <button onClick={() => void exportPlan('json', true)} style={actionBtn(BB.amberAlt)}>PREVIEW (stale)</button>
            )}
            <button onClick={() => onDismiss(ev.id)} style={actionBtn(BB.text3)}>DISMISS</button>
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 8, color: BB.text3 }}>ADVISORY · NO BROKER</span>
            <button onClick={onClose} style={actionBtn(BB.amber)}>CLOSE</button>
          </div>
        </footer>
      </div>
    </div>
  )
}

function PlanCard({ plan, primary }: { plan: InstitutionalPlan; primary?: boolean }) {
  const arch = plan.plan_archetype
  return (
    <div style={{ padding: 12, background: primary ? BB.amberDim : BB.bgRow, border: `1px solid ${primary ? BB.amber : BB.border}`, borderRadius: 2 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'baseline', marginBottom: 8 }}>
        <span style={{ fontSize: 15, fontWeight: 800, color: BB.amber }}>Plan {arch}</span>
        <span style={{ color: BB.text2 }}>{ARCHETYPE_LABELS[arch] ?? plan.plan_type}</span>
        <Tag label={plan.operator_status ?? 'draft'} color={plan.operator_status === 'operator_ready' ? BB.green : BB.text3} />
        <Tag label={`oversight ${plan.oversight_status ?? 'pending'}`} color={BB.blue} />
        <span style={{ color: BB.text3, fontSize: BB.fontXs }}>conf {plan.confidence ?? '—'}</span>
      </div>
      <div style={{ fontSize: BB.fontXs, color: BB.text1, marginBottom: 8, lineHeight: 1.45 }}>{plan.objective}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: BB.fontXs, marginBottom: 8 }}>
        <span>Deploy <b style={{ color: BB.green }}>{fmt$(plan.total_deployable_usd ?? 0, 0)}</b></span>
        <span>Reserve <b>{fmt$(plan.reserve_usd ?? 0, 0)}</b></span>
        <span>{plan.deploy_pct_of_net ?? 0}% of net</span>
        <span>{(plan.legs ?? []).filter(l => !l.is_reserve).length} equity legs</span>
      </div>
      {(plan.tags ?? []).length > 0 && (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
          {(plan.tags ?? []).map(t => <Tag key={t} label={t} color={BB.text3} />)}
        </div>
      )}
      {(
        [
          ['advantages', plan.advantages],
          ['compromises', plan.compromises],
          ['risks', plan.risks],
        ] as const
      ).map(([key, items]) => {
        if (!items?.length) return null
        return (
          <div key={key} style={{ marginBottom: 6 }}>
            <div style={{ fontSize: 8, color: BB.text3, letterSpacing: '.06em', marginBottom: 2 }}>{key.toUpperCase()}</div>
            {items.map((line, i) => (
              <div key={i} style={{ fontSize: BB.fontXs, color: BB.text2, marginLeft: 4 }}>· {line}</div>
            ))}
          </div>
        )
      })}
    </div>
  )
}

function EntriesTable({ legs }: { legs: RedeployPlanLeg[] }) {
  if (!legs.length) return <div style={{ color: BB.text3, fontSize: BB.fontXs }}>No legs</div>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: BB.fontXs }}>
        <thead>
          <tr style={{ color: BB.text3, textAlign: 'left', borderBottom: `1px solid ${BB.border}` }}>
            <th style={th}>Ticker</th>
            <th style={th}>$/sh</th>
            <th style={th}>Target</th>
            <th style={th}>Preferred</th>
            <th style={th}>S1</th>
            <th style={th}>S2</th>
            <th style={th}>S3</th>
            <th style={th}>Quote</th>
          </tr>
        </thead>
        <tbody>
          {legs.map(leg => (
            <tr key={`${leg.ticker}-${leg.is_reserve}`} style={{ borderBottom: `1px solid ${BB.borderSubtle}` }}>
              <td style={td}>
                <b style={{ color: leg.is_reserve ? BB.text3 : BB.text0 }}>{leg.ticker}</b>
                {leg.is_reserve && <span style={{ color: BB.text3, marginLeft: 4 }}>RESERVE</span>}
              </td>
              <td style={td}>{leg.is_reserve ? '—' : fmtPx(leg.current_price)}</td>
              <td style={td}>{fmt$(leg.target_dollars ?? 0, 0)}{leg.target_shares ? ` / ${leg.target_shares}sh` : ''}</td>
              <td style={td}>{leg.is_reserve ? '—' : fmtPx(leg.preferred_entry)}</td>
              <td style={td}>{leg.is_reserve ? '—' : `${leg.stage_1_pct ?? '—'}% @ ${leg.stage_1_price ?? '—'}`}</td>
              <td style={td}>{leg.is_reserve ? '—' : `${leg.stage_2_pct ?? '—'}% @ ${leg.stage_2_price ?? '—'}`}</td>
              <td style={td}>{leg.is_reserve ? '—' : `${leg.stage_3_pct ?? '—'}% @ ${leg.stage_3_price ?? '—'}`}</td>
              <td style={{ ...td, color: leg.price_stale ? BB.amberAlt : BB.text3 }}>
                {leg.price_as_of ?? '—'}{leg.price_stale ? ' STALE' : ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {legs.some(l => !l.is_reserve && l.invalidation) && (
        <div style={{ marginTop: 10, fontSize: 9, color: BB.text3 }}>
          {legs.filter(l => l.invalidation).map(l => (
            <div key={l.ticker}>{l.ticker} invalidation: {l.invalidation}</div>
          ))}
        </div>
      )}
    </div>
  )
}

const th: React.CSSProperties = { padding: '4px 6px', fontWeight: 700 }
const td: React.CSSProperties = { padding: '6px 6px', color: BB.text2, verticalAlign: 'top' }

function Kv({ k, v, accent }: { k: string; v: string; accent?: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: BB.fontXs, marginBottom: 3 }}>
      <span style={{ color: BB.text3, minWidth: 140 }}>{k}</span>
      <span style={{ color: accent ?? BB.text1, fontWeight: 700 }}>{v}</span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 9, fontWeight: 800, color: BB.text3, letterSpacing: '.08em', marginBottom: 6 }}>{title}</div>
      {children}
    </div>
  )
}

function Tag({ label, color }: { label: string; color: string }) {
  return (
    <span style={{ fontSize: 8, fontWeight: 800, padding: '2px 7px', borderRadius: 2, background: `${color}18`, color, border: `1px solid ${color}44` }}>
      {label}
    </span>
  )
}

function tabBtn(active: boolean): React.CSSProperties {
  return {
    fontSize: 8, fontWeight: 800, padding: '4px 8px', borderRadius: 2,
    border: `1px solid ${active ? BB.amber : BB.border}`,
    background: active ? BB.amberDim : BB.bgRow,
    color: active ? BB.amber : BB.text3,
    cursor: 'pointer', letterSpacing: '.05em', fontFamily: BB.mono,
  }
}

function actionBtn(color: string): React.CSSProperties {
  return {
    fontSize: 9, fontWeight: 800, padding: '5px 12px', borderRadius: 2,
    border: `1px solid ${color}55`, background: `${color}14`, color, cursor: 'pointer',
    letterSpacing: '.06em', fontFamily: BB.mono,
  }
}

function downloadText(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}