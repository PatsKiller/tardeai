import { useCallback, useEffect, useState } from 'react'

type CritiqueMeta = {
  status?: string
  generated_at?: string
  stale?: boolean
  stale_fields?: string[]
  tag_fingerprint?: string
  history_count?: number
  llm_enhanced?: boolean
  deterministic?: boolean
  error_message?: string
}

type Critique = {
  generated_at?: string
  trade_classification?: any
  execution_quality?: any
  risk_sizing?: any
  opportunity_cost?: any
  narrative?: {
    summary?: string
    strengths?: string[]
    improvements?: string[]
    takeaways?: string[]
    suggested_tags?: string[]
    what_if_scenarios?: { scenario: string; outcome: string }[]
    llm_enhanced?: boolean
    deterministic?: boolean
  }
}

const SEC: React.CSSProperties = { marginBottom: 14 }
const H: React.CSSProperties = { fontSize: 11, fontWeight: 800, color: '#a78bfa', marginBottom: 6, letterSpacing: '0.04em', textTransform: 'uppercase' }
const P: React.CSSProperties = { fontSize: 12, color: 'var(--text1)', lineHeight: 1.55, margin: 0 }
const LI: React.CSSProperties = { fontSize: 12, color: 'var(--text1)', lineHeight: 1.5, marginBottom: 4 }

function Bullets({ items, color }: { items?: string[]; color?: string }) {
  if (!items?.length) return <div style={{ ...P, color: 'var(--text3)' }}>—</div>
  return (
    <ul style={{ margin: 0, paddingLeft: 18 }}>
      {items.map((t, i) => <li key={i} style={{ ...LI, color: color || 'var(--text1)' }}>{t}</li>)}
    </ul>
  )
}

function fmtTs(iso?: string) {
  if (!iso) return ''
  return iso.slice(0, 16).replace('T', ' ')
}

function goToJournalTab(tab: string, critiqueQ?: string) {
  try {
    sessionStorage.setItem('journal_tab', tab)
    if (critiqueQ) sessionStorage.setItem('journal_critique_q', critiqueQ)
  } catch { /* */ }
  window.location.href = '/v3/journal'
}

export default function AiTradeCritique({ tradeKey, symbol }: { tradeKey: string; symbol?: string }) {
  const [open, setOpen] = useState(true)
  const [critique, setCritique] = useState<Critique | null>(null)
  const [meta, setMeta] = useState<CritiqueMeta | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [stale, setStale] = useState(false)
  const [staleFields, setStaleFields] = useState<string[]>([])
  const [cached, setCached] = useState(false)

  const load = useCallback(async (force = false) => {
    if (!tradeKey) return
    setBusy(true)
    setErr('')
    try {
      const qs = `trade_key=${encodeURIComponent(tradeKey)}&_=${Date.now()}${force ? '&force=1' : ''}`
      const r = await fetch(force ? '/api/v2/journal/ai-critique' : `/api/v2/journal/ai-critique?${qs}`, {
        method: force ? 'POST' : 'GET',
        cache: 'no-store',
        ...(force ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ trade_key: tradeKey, force: true }) } : {}),
      })
      const j = await r.json()
      const payload = j?.data ?? j
      const c = payload?.critique
      const m = payload?.meta ?? null
      setMeta(m)
      setStale(Boolean(payload?.stale ?? m?.stale))
      setStaleFields(payload?.stale_fields ?? m?.stale_fields ?? [])
      setCached(Boolean(payload?.cached))
      if (c && (c.narrative?.summary || c.trade_classification || c.execution_quality)) {
        setCritique(c)
        setErr('')
      } else if (payload?.ok === false || j?.ok === false) {
        setErr(payload?.error || m?.error_message || j?.error || 'Generation failed')
        if (!c) setCritique(null)
      } else if (!force) {
        setErr('No critique returned')
      }
    } catch (e: any) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }, [tradeKey])

  useEffect(() => { load(false) }, [load])

  const nar = critique?.narrative || {}
  const cls = critique?.trade_classification || {}
  const ex = critique?.execution_quality || {}
  const risk = critique?.risk_sizing || {}
  const opp = critique?.opportunity_cost || {}
  const sq = cls.setup_quality || {}
  const generatedAt = critique?.generated_at || meta?.generated_at
  const searchHint = nar.improvements?.[0]?.split(' ').slice(0, 3).join(' ') || symbol || ''

  return (
    <div style={{ marginTop: 16, border: '1px solid rgba(167,139,250,.35)', borderRadius: 10, background: 'rgba(167,139,250,.06)', overflow: 'hidden' }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', border: 'none', background: 'transparent', cursor: 'pointer', textAlign: 'left' }}
      >
        <span style={{ fontSize: 16 }}>🤖</span>
        <span style={{ fontSize: 14, fontWeight: 800, color: '#c4b5fd' }}>AI Trade Critique</span>
        <span style={{ fontSize: 10, color: 'var(--text3)' }}>persisted · replay + tags + execution</span>
        <span style={{ flex: 1 }} />
        {stale && <span style={{ fontSize: 9, color: '#f59e0b', fontWeight: 700 }}>STALE</span>}
        {generatedAt && <span style={{ fontSize: 9, color: 'var(--text3)' }}>{fmtTs(generatedAt)}</span>}
        {cached && <span style={{ fontSize: 8, color: 'var(--text3)', marginLeft: 4 }}>cached</span>}
        <span style={{ fontSize: 12, color: 'var(--text3)' }}>{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div style={{ padding: '0 14px 14px' }}>
          {stale && (
            <div style={{ fontSize: 11, color: '#f59e0b', background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.3)', borderRadius: 6, padding: '8px 10px', marginBottom: 10 }}>
              Tags changed since this critique was generated — regenerate for an updated review.
              {staleFields.length > 0 && (
                <div style={{ fontSize: 10, marginTop: 4, color: 'var(--text2)' }}>
                  Changed: {staleFields.join(', ')}
                </div>
              )}
            </div>
          )}
          {meta && (
            <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <span>Status: {meta.status ?? 'ok'}</span>
              {meta.history_count != null && meta.history_count > 0 && <span>{meta.history_count} prior version(s)</span>}
              {nar.llm_enhanced && <span>Grok-enhanced</span>}
              {nar.deterministic && !nar.llm_enhanced && <span>deterministic fallback</span>}
            </div>
          )}
          {busy && <div style={{ fontSize: 12, color: 'var(--text3)', padding: '8px 0' }}>Analyzing trade…</div>}
          {err && !critique && <div style={{ fontSize: 11, color: '#f59e0b', marginBottom: 8 }}>{err}</div>}
          {nar.summary && (
            <div style={{ ...SEC, padding: 10, borderRadius: 8, background: 'rgba(15,23,42,.5)', border: '1px solid rgba(148,163,184,.15)' }}>
              <p style={{ ...P, fontWeight: 600 }}>{nar.summary}</p>
            </div>
          )}
          {critique && (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div style={SEC}>
                  <div style={H}>Trade classification</div>
                  <p style={P}><b>{cls.type || '—'}</b> · {cls.setup_family || 'untagged'} · regime {cls.market_regime || '—'}</p>
                  <p style={{ ...P, fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>
                    Entry RVOL {sq.entry_rvol ?? '—'} · VWAP {sq.above_vwap == null ? '—' : sq.above_vwap ? 'above' : 'below'}
                    {sq.vwap_distance_pct != null ? ` (${sq.vwap_distance_pct}%)` : ''} · RSI {sq.rsi ?? '—'} · MACD {sq.macd_state ?? '—'}
                  </p>
                </div>
                <div style={SEC}>
                  <div style={H}>Execution quality</div>
                  <p style={P}>
                    {ex.outcome_grade}/{ex.execution_grade} · capture {ex.capture_ratio != null ? `${Math.round(ex.capture_ratio * 100)}%` : '—'}
                    · MFE {ex.mfe ?? '—'} / MAE {ex.mae ?? '—'}
                  </p>
                  <p style={{ ...P, fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>
                    {ex.pct_in_profit != null ? `${ex.pct_in_profit}% of hold in profit (${ex.minutes_in_profit}m green / ${ex.minutes_underwater}m red)` : ''}
                  </p>
                </div>
                <div style={SEC}>
                  <div style={H}>Risk & sizing</div>
                  <p style={P}>
                    {risk.shares ?? '—'} sh · ${risk.pnl ?? '—'} P&L
                    {risk.planned_r != null ? ` · planned ${risk.planned_r}R` : ''}
                    {risk.realized_r != null ? ` → realized ${risk.realized_r}R` : ''}
                  </p>
                </div>
                <div style={SEC}>
                  <div style={H}>Opportunity cost</div>
                  <p style={P}>
                    Post-exit move {opp.mfe_after_exit_pct != null ? `+${opp.mfe_after_exit_pct}%` : '—'}
                    {opp.alternative_exit?.additional_pnl != null ? ` · left ~$${opp.alternative_exit.additional_pnl} on table` : ''}
                  </p>
                  {opp.what_if_hold_to_mfe?.price != null && (
                    <p style={{ ...P, fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>
                      Hold to MFE: ${opp.what_if_hold_to_mfe.price} (+${opp.what_if_hold_to_mfe.extra_per_share}/sh)
                    </p>
                  )}
                </div>
              </div>
              {nar.what_if_scenarios?.length ? (
                <div style={SEC}>
                  <div style={H}>What-if scenarios</div>
                  {nar.what_if_scenarios.map((w, i) => (
                    <div key={i} style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 4 }}>
                      <b style={{ color: 'var(--text1)' }}>{w.scenario}</b> — {w.outcome}
                    </div>
                  ))}
                </div>
              ) : null}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div style={SEC}>
                  <div style={H}>Strengths</div>
                  <Bullets items={nar.strengths} color="#86efac" />
                </div>
                <div style={SEC}>
                  <div style={H}>Improvements</div>
                  <Bullets items={nar.improvements} color="#fca5a5" />
                </div>
              </div>
              <div style={SEC}>
                <div style={H}>Key takeaways</div>
                <Bullets items={nar.takeaways} />
              </div>
              {nar.suggested_tags?.length ? (
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                  <span style={{ fontSize: 10, color: 'var(--text3)' }}>Suggested tags:</span>
                  {nar.suggested_tags.map((t, i) => (
                    <span key={i} style={{ fontSize: 9, padding: '2px 8px', borderRadius: 4, background: 'rgba(96,165,250,.15)', color: '#93c5fd' }}>{t}</span>
                  ))}
                </div>
              ) : null}
            </>
          )}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
            <button
              type="button"
              disabled={busy}
              onClick={() => load(true)}
              style={{ fontSize: 11, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}
            >
              {busy ? '…' : '↻ Regenerate critique'}
            </button>
            <button
              type="button"
              onClick={() => goToJournalTab('Advanced', searchHint)}
              style={{ fontSize: 11, padding: '6px 12px', borderRadius: 6, border: '1px solid rgba(167,139,250,.4)', background: 'rgba(167,139,250,.1)', color: '#c4b5fd', cursor: 'pointer' }}
            >
              View in Reports
            </button>
            <button
              type="button"
              onClick={() => goToJournalTab('Behavioral')}
              style={{ fontSize: 11, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}
            >
              Use in Coaching
            </button>
          </div>
        </div>
      )}
    </div>
  )
}