/** ProspectusBatchPanel — automated BUY/STRONG BUY holding prospectus generation + registry. */
import { useCallback, useEffect, useState } from 'react'

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }

type EligibleRow = {
  symbol: string
  recommendation: string
  market_value: number
  portfolio_pct: number
  fingerprint: string
  needs_refresh?: boolean
  last_generated?: string
}

type RegistryRow = {
  id: string
  symbol?: string
  title?: string
  recommendation?: string
  fingerprint?: string
  grok_edited?: boolean
  generated_at?: string
  exports?: Record<string, string | { error?: string }>
}

function exportUrl(val: string | { error?: string } | undefined): string | null {
  if (!val || typeof val !== 'object') return typeof val === 'string' ? val : null
  return null
}

export default function ProspectusBatchPanel() {
  const [eligible, setEligible] = useState<EligibleRow[]>([])
  const [registry, setRegistry] = useState<RegistryRow[]>([])
  const [needsRefresh, setNeedsRefresh] = useState(0)
  const [residualOpen, setResidualOpen] = useState(false)
  // config floor (env-overridable server-side later if needed); sub-floor rows fold, never peers
  const RESIDUAL_FLOOR = 1000
  const heldAction: Record<string, string> = Object.fromEntries(
    eligible.filter(r => r.recommendation).map(r => [r.symbol, String(r.recommendation)]))
  const [loading, setLoading] = useState(true)
  const [batchRunning, setBatchRunning] = useState(false)
  const [singleSym, setSingleSym] = useState('')
  const [grokEdit, setGrokEdit] = useState(true)
  const [forceRefresh, setForceRefresh] = useState(false)
  const [error, setError] = useState('')
  const [batchResult, setBatchResult] = useState<any>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [eligR, regR] = await Promise.all([
        fetch('/api/v2/reports/analyst/eligible?stale_days=6&_ts=' + Date.now(), { cache: 'no-store' }),
        fetch('/api/v2/reports/analyst/registry?type=symbol_holding&limit=30&_ts=' + Date.now(), { cache: 'no-store' }),
      ])
      const eligJ = await eligR.json()
      const regJ = await regR.json()
      const eligData = eligJ?.data ?? eligJ
      const regData = regJ?.data ?? regJ
      setEligible(eligData?.eligible || [])
      setNeedsRefresh(eligData?.needs_refresh ?? 0)
      setRegistry(regData?.reports || [])
    } catch (e: any) {
      setError(e?.message || 'Failed to load prospectus registry')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const runBatch = async () => {
    setBatchRunning(true)
    setError('')
    setBatchResult(null)
    try {
      const r = await fetch('/api/v2/reports/analyst/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'batch_holdings', grok_edit: grokEdit, force: forceRefresh }),
      })
      const j = await r.json()
      const res = j?.data ?? j
      if (!r.ok || res?.ok === false) throw new Error(res?.error || `HTTP ${r.status}`)
      setBatchResult(res)
      await refresh()
    } catch (e: any) {
      setError(e?.message || 'Batch generation failed')
    } finally {
      setBatchRunning(false)
    }
  }

  const runSingle = async () => {
    const sym = singleSym.trim().toUpperCase()
    if (!sym) return
    setBatchRunning(true)
    setError('')
    try {
      const r = await fetch('/api/v2/reports/analyst/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'symbol_holding', symbol: sym, grok_edit: grokEdit }),
      })
      const j = await r.json()
      const res = j?.data ?? j
      if (!r.ok || res?.ok === false) throw new Error(res?.error || `HTTP ${r.status}`)
      setBatchResult({ generated: [{ symbol: sym, exports: res?.exports }], skipped: [], failed: [] })
      await refresh()
    } catch (e: any) {
      setError(e?.message || 'Single prospectus failed')
    } finally {
      setBatchRunning(false)
    }
  }

  const fmtDate = (iso?: string) => {
    if (!iso) return '—'
    try { return new Date(iso).toLocaleString() } catch { return iso }
  }

  const fmtUsd = (n: number) => n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${n.toFixed(0)}`

  return (
    <div style={card}>
      <div style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)', marginBottom: 4 }}>
        Summary Prospectus — Holdings Automation
      </div>
      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12, lineHeight: 1.5 }}>
        Auto-generates JEPQ-style prospectus reports for all <b style={{ color: '#22c55e' }}>BUY / STRONG BUY / ADD</b> holdings.
        Weekly cron (Sun 21:15) refreshes with latest data when fingerprint changes or report is ≥6 days old. Optional <b style={{ color: '#60a5fa' }}>Grok OAuth</b> editorial polish.
      </div>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12, alignItems: 'center' }}>
        <label style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', color: 'var(--text2)' }}>
          <input type="checkbox" checked={grokEdit} onChange={e => setGrokEdit(e.target.checked)} />
          Grok editorial polish
        </label>
        <label style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', color: 'var(--text2)' }}>
          <input type="checkbox" checked={forceRefresh} onChange={e => setForceRefresh(e.target.checked)} />
          Force regenerate all
        </label>
        <button onClick={runBatch} disabled={batchRunning || loading} style={{
          fontSize: 11, fontWeight: 800, padding: '6px 14px', borderRadius: 6, cursor: 'pointer',
          border: 'none', background: '#22c55e', color: '#fff', opacity: batchRunning ? 0.6 : 1,
        }}>
          {batchRunning ? 'Generating…' : `Generate ${eligible.length} Holdings`}
        </button>
        <button onClick={refresh} disabled={loading} style={{
          fontSize: 10, fontWeight: 700, padding: '5px 10px', borderRadius: 6, cursor: 'pointer',
          border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)',
        }}>Refresh</button>
        {!loading && (
          <span style={{ fontSize: 9, color: needsRefresh > 0 ? '#f59e0b' : '#22c55e', fontWeight: 700 }}>
            {needsRefresh > 0 ? `${needsRefresh} of ${eligible.length} eligible symbols' reports need refresh` : 'All up to date'}
          </span>
        )}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <input
          value={singleSym}
          onChange={e => setSingleSym(e.target.value.toUpperCase())}
          placeholder="Single symbol (e.g. RKLB)"
          style={{ flex: 1, maxWidth: 160, fontSize: 11, padding: '5px 8px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text0)', fontFamily: 'monospace' }}
        />
        <button onClick={runSingle} disabled={batchRunning || !singleSym.trim()} style={{
          fontSize: 10, fontWeight: 700, padding: '5px 10px', borderRadius: 6, cursor: 'pointer',
          border: '1px solid #60a5fa', background: 'rgba(96,165,250,.1)', color: '#60a5fa',
        }}>Generate one</button>
      </div>

      {batchResult && (
        <div style={{ fontSize: 10, padding: '8px 10px', borderRadius: 6, marginBottom: 10, background: 'rgba(34,197,94,.08)', border: '1px solid #22c55e44', color: '#22c55e' }}>
          Generated: {(batchResult.generated || []).length} · Skipped: {(batchResult.skipped || []).length} · Failed: {(batchResult.failed || []).length}
        </div>
      )}
      {error && <div style={{ fontSize: 10, color: '#ef4444', marginBottom: 8 }}>{error}</div>}

      {loading ? (
        <div style={{ fontSize: 10, color: 'var(--text3)' }}>Loading eligible holdings…</div>
      ) : (
        <>
          <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', marginBottom: 6, textTransform: 'uppercase' }}>
            Eligible holdings ({eligible.filter(r => (r.market_value ?? 0) >= RESIDUAL_FLOOR).length})
          </div>
          <div style={{ display: 'grid', gap: 4, marginBottom: 14, maxHeight: 140, overflowY: 'auto' }}>
            {eligible.filter(r => (r.market_value ?? 0) >= RESIDUAL_FLOOR).map(row => (
              <div key={row.symbol} style={{
                display: 'flex', gap: 8, alignItems: 'center', fontSize: 10, padding: '4px 8px',
                borderRadius: 5, background: 'var(--bg2)', border: '1px solid var(--border)',
              }}>
                <span style={{ fontWeight: 800, fontFamily: 'monospace', color: 'var(--text0)', minWidth: 48 }}>{row.symbol}</span>
                <span style={{ color: '#22c55e', fontWeight: 700, minWidth: 72 }}>{row.recommendation}</span>
                <span style={{ color: 'var(--text3)' }}>{fmtUsd(row.market_value)} · {row.portfolio_pct?.toFixed(1)}%</span>
                {row.needs_refresh
                  ? <span style={{ color: '#f59e0b', fontWeight: 700, marginLeft: 'auto' }}>stale</span>
                  : <span style={{ color: 'var(--text4)', marginLeft: 'auto' }}>current</span>}
              </div>
            ))}
            {eligible.length === 0 && <div style={{ fontSize: 10, color: 'var(--text4)' }}>No BUY/STRONG BUY holdings above threshold.</div>}
          </div>

          {eligible.some(r => (r.market_value ?? 0) < RESIDUAL_FLOOR) && (
            <div style={{ marginBottom: 14 }}>
              <button onClick={() => setResidualOpen(o => !o)} style={{
                fontSize: 9, fontWeight: 700, color: 'var(--text3)', background: 'transparent',
                border: '1px solid var(--border)', borderRadius: 5, padding: '3px 8px', cursor: 'pointer', textTransform: 'uppercase',
              }}>
                {residualOpen ? '▾' : '▸'} Residual positions ({eligible.filter(r => (r.market_value ?? 0) < RESIDUAL_FLOOR).length}) — under ${RESIDUAL_FLOOR.toLocaleString()} · stopped-out scraps, still generatable, not peers
              </button>
              {residualOpen && (
                <div style={{ display: 'grid', gap: 4, marginTop: 6, maxHeight: 120, overflowY: 'auto' }}>
                  {eligible.filter(r => (r.market_value ?? 0) < RESIDUAL_FLOOR).map(row => (
                    <div key={row.symbol} style={{
                      display: 'flex', gap: 8, alignItems: 'center', fontSize: 10, padding: '4px 8px',
                      borderRadius: 5, background: 'var(--bg2)', border: '1px dashed var(--border)', opacity: 0.75,
                    }}>
                      <span style={{ fontWeight: 800, fontFamily: 'monospace', color: 'var(--text2)', minWidth: 48 }}>{row.symbol}</span>
                      <span style={{ color: 'var(--text3)' }}>{fmtUsd(row.market_value)}</span>
                      {row.needs_refresh
                        ? <span style={{ color: '#f59e0b', fontWeight: 700, marginLeft: 'auto' }}>stale</span>
                        : <span style={{ color: 'var(--text4)', marginLeft: 'auto' }}>current</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', marginBottom: 6, textTransform: 'uppercase' }}>
            Generated prospectus ({registry.length})
          </div>
          <div style={{ display: 'grid', gap: 4, maxHeight: 200, overflowY: 'auto' }}>
            {registry.map(row => {
              const docx = exportUrl(row.exports?.docx)
              const pdf = exportUrl(row.exports?.pdf)
              return (
                <div key={row.id} style={{
                  display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 10, padding: '5px 8px',
                  borderRadius: 5, background: 'var(--bg2)', border: '1px solid var(--border)',
                }}>
                  <span style={{ fontWeight: 800, fontFamily: 'monospace', color: 'var(--text0)' }}>{row.symbol}</span>
                  {(() => {
                    // D3 (v3): held names show the CURRENT holdings-vocabulary action; the original
                    // registry verb stays in the tooltip (display-layer only — registry untouched).
                    const cur = row.symbol ? heldAction[row.symbol] : undefined
                    return cur && cur !== row.recommendation
                      ? <span title={`registry: ${row.recommendation || '—'} · ${fmtDate(row.generated_at)}`}
                              style={{ color: '#22c55e', fontWeight: 700, cursor: 'help' }}>{cur}</span>
                      : <span style={{ color: 'var(--text3)' }}>{row.recommendation || '—'}</span>
                  })()}
                  <span style={{ color: 'var(--text4)', fontSize: 9 }}>{fmtDate(row.generated_at)}</span>
                  {row.grok_edited && <span style={{ fontSize: 8, fontWeight: 700, color: '#60a5fa', padding: '1px 5px', borderRadius: 3, background: 'rgba(96,165,250,.12)' }}>Grok</span>}
                  <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                    {docx && <a href={docx} target="_blank" rel="noreferrer" style={{ fontWeight: 700, color: '#60a5fa', textDecoration: 'none' }}>DOCX</a>}
                    {pdf && <a href={pdf} target="_blank" rel="noreferrer" style={{ fontWeight: 700, color: '#f59e0b', textDecoration: 'none' }}>PDF</a>}
                  </span>
                </div>
              )
            })}
            {registry.length === 0 && <div style={{ fontSize: 10, color: 'var(--text4)' }}>No prospectus generated yet — run batch above.</div>}
          </div>
        </>
      )}
    </div>
  )
}