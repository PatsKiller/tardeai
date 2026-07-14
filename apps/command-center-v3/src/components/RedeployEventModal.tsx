import { fmt$ } from '../lib/format'
import { BB } from '../lib/holdingsTerminalTokens'

export type RedeployTarget = {
  symbol: string
  score: number
  sleeve?: string
  rationale?: string
  review_amount_range?: { low?: number; high?: number; basis?: string }
  evidence?: Record<string, unknown>
  hermes?: {
    composite?: number | null
    rank?: number | null
    research_count?: number
    external_lane_count?: number
    research_snippets?: { title?: string; summary?: string }[]
  }
}

export type RedeployEventDetail = {
  id: number
  symbol: string
  account: string
  sold_at: string
  proceeds_usd?: number
  proxy_symbol?: string
  proxy_sleeve?: string
  tier?: string
  redeploy_plan?: RedeployTarget[]
  lookthrough_delta?: { theme?: string; delta_pct?: number; note?: string }[]
  metadata?: {
    sale_context?: { tier?: string; reduced_themes?: string[]; proceeds_usd?: number; proxy_symbol?: string }
    advisory_note?: string
    sleeve_gaps?: { theme?: string; gap_pct?: number; gap_usd?: number }[]
    market_context?: {
      geopolitical?: { posture?: string; catalyst_count?: number; active_themes?: string[] }
      regime_posture?: string
      regime?: { label?: string }
    }
    methodology?: string
  }
}

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

export default function RedeployEventModal({ event, onClose, onDismiss, onPropose }: Props) {
  const ev = event
  const sale = ev.metadata?.sale_context
  const geo = ev.metadata?.market_context?.geopolitical
  const regime = ev.metadata?.market_context?.regime_posture
  const gaps = ev.metadata?.sleeve_gaps ?? []

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 1100, display: 'flex', justifyContent: 'flex-end', background: 'rgba(2,6,12,.6)' }}
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 'min(640px, 96vw)', height: '100vh', background: BB.bg,
          borderLeft: `1px solid ${BB.border}`, display: 'flex', flexDirection: 'column',
          boxShadow: '-12px 0 40px rgba(0,0,0,.65)', fontFamily: BB.mono, fontSize: BB.fontSm,
        }}
      >
        <div style={{ padding: '14px 18px', borderBottom: `1px solid ${BB.border}`, flexShrink: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <div style={{ fontSize: 18, fontWeight: 800, color: BB.amber }}>
                REDEPLOY · {ev.symbol}
              </div>
              <div style={{ fontSize: 10, color: BB.text3, marginTop: 4 }}>
                {fmtDate(ev.sold_at)} · {(ev.account ?? '').replace(/_/g, ' ')} · {fmt$(Number(ev.proceeds_usd ?? 0), 0)}
                {ev.proxy_symbol ? ` · proxy ${ev.proxy_symbol}` : ''}
              </div>
            </div>
            <button type="button" onClick={onClose} aria-label="Close" style={{ background: 'transparent', border: 'none', color: BB.text3, cursor: 'pointer', fontSize: 22 }}>×</button>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
            <Tag label={(ev.tier ?? sale?.tier ?? 'moderate').toUpperCase()} color={BB.amber} />
            {regime && <Tag label={`REGIME ${String(regime).toUpperCase()}`} color={BB.blue} />}
            {geo?.posture && geo.posture !== 'neutral' && <Tag label={`GEO ${String(geo.posture).toUpperCase()}`} color={BB.amberAlt} />}
            {(sale?.reduced_themes ?? []).map(t => <Tag key={t} label={`−${t}`} color={BB.red} />)}
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {(ev.lookthrough_delta ?? []).length > 0 && (
            <Section title="LOOK-THROUGH IMPACT">
              {(ev.lookthrough_delta ?? []).map((d, i) => (
                <div key={i} style={{ color: BB.text2, fontSize: BB.fontXs, marginBottom: 4 }}>
                  {d.theme}: <b style={{ color: BB.red }}>{d.delta_pct}%</b>
                  {d.note ? <span style={{ color: BB.text3 }}> — {d.note}</span> : null}
                </div>
              ))}
            </Section>
          )}

          {gaps.length > 0 && (
            <Section title="PORTFOLIO GAPS (rotation context)">
              {gaps.slice(0, 5).map(g => (
                <div key={g.theme} style={{ fontSize: BB.fontXs, color: BB.text2, marginBottom: 3 }}>
                  {g.theme} <span style={{ color: BB.amber }}>{g.gap_pct}% under floor</span>
                  <span style={{ color: BB.text3 }}> ≈ {fmt$(g.gap_usd ?? 0, 0)}</span>
                </div>
              ))}
            </Section>
          )}

          {ev.metadata?.advisory_note && (
            <Section title="ADVISORY">
              <div style={{ color: BB.text3, fontSize: BB.fontXs, fontStyle: 'italic' }}>{ev.metadata.advisory_note}</div>
            </Section>
          )}

          <Section title="REDEPLOY TARGETS">
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
                  {t.review_amount_range?.low != null && (
                    <span style={{ color: BB.text1, fontSize: BB.fontXs }}>
                      review {fmt$(t.review_amount_range.low, 0)}–{fmt$(t.review_amount_range.high ?? 0, 0)}
                    </span>
                  )}
                  <span style={{ flex: 1 }} />
                  <button
                    onClick={() => onPropose(t.symbol, t.sleeve || 'Redeploy', t.rationale || '')}
                    style={actionBtn(BB.green)}
                  >PROPOSE</button>
                </div>
                <div style={{ marginTop: 6, color: BB.text2, fontSize: BB.fontXs, lineHeight: 1.45 }}>
                  {t.evidence?.fills_sale_gap ? <span style={{ color: BB.green, marginRight: 6 }}>▸ REPLACES</span> : null}
                  {t.evidence?.rotation_to_portfolio_gap ? <span style={{ color: BB.amber, marginRight: 6 }}>▸ ROTATION</span> : null}
                  {t.rationale}
                </div>
                {t.hermes && (
                  <div style={{ marginTop: 6, fontSize: 9, color: BB.text3 }}>
                    Hermes {t.hermes.composite ?? '—'} · rank #{t.hermes.rank ?? '—'}
                    · research {t.hermes.research_count ?? 0} · lanes {t.hermes.external_lane_count ?? 0}
                  </div>
                )}
                {t.evidence && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                    {Object.entries(t.evidence).filter(([k]) => !['sleeve', 'instrument_type'].includes(k)).slice(0, 6).map(([k, v]) => (
                      <Tag key={k} label={`${k.replace(/_/g, ' ')}: ${v}`} color={BB.text3} />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </Section>

          {ev.metadata?.methodology && (
            <div style={{ fontSize: 9, color: BB.text3, marginTop: 8, lineHeight: 1.4 }}>
              {ev.metadata.methodology}
            </div>
          )}
        </div>

        <div style={{ padding: '12px 18px', borderTop: `1px solid ${BB.border}`, display: 'flex', gap: 10, flexShrink: 0 }}>
          <button onClick={() => onDismiss(ev.id)} style={actionBtn(BB.text3)}>DISMISS</button>
          <span style={{ flex: 1 }} />
          <button onClick={onClose} style={actionBtn(BB.amber)}>CLOSE</button>
        </div>
      </div>
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

function actionBtn(color: string): React.CSSProperties {
  return {
    fontSize: 9, fontWeight: 800, padding: '5px 12px', borderRadius: 2,
    border: `1px solid ${color}55`, background: `${color}14`, color, cursor: 'pointer',
    letterSpacing: '.06em', fontFamily: BB.mono,
  }
}