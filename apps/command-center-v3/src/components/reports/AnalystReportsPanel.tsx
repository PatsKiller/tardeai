/** AnalystReportsPanel — on-demand analyst-grade reports + DOCX/PDF export. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useApi } from '../../hooks/useApi'
import AnalystReportViewer from './AnalystReportViewer'
import ProspectusBatchPanel from './ProspectusBatchPanel'

declare const __ANALYST_UI_VERSION__: string
const UI_VERSION = typeof __ANALYST_UI_VERSION__ !== 'undefined' ? __ANALYST_UI_VERSION__ : 'dev'

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }

const REPORT_TYPES = [
  { key: 'symbol_watchlist', label: 'Watchlist Item' },
  { key: 'symbol_holding', label: 'Portfolio Holding' },
  { key: 'symbol_custom', label: 'Custom Instrument' },
  { key: 'sector_theme', label: 'Sector & Theme' },
  { key: 'intelligence_deep', label: 'Intelligence Deep Dive' },
  { key: 'event_driven', label: 'Event-Driven Alerts' },
  { key: 'daily_digest', label: 'Daily Intelligence Digest' },
  { key: 'weekly_review', label: 'Weekly Review' },
]

const EVENT_FILTERS = [
  { key: 'all', label: 'All events' },
  { key: 'stop_hit', label: 'Stop hits' },
  { key: 'thesis_invalidation', label: 'Thesis invalidations' },
  { key: 'large_move', label: 'Large moves' },
]

const SECTION_OPTS = [
  { id: 'header_context', label: 'Identification & Personal Context' },
  { id: 'executive_summary', label: 'Executive Summary & Action' },
  { id: 'personal_performance', label: 'Personal Performance & Entry' },
  { id: 'report_continuity', label: 'Report Continuity' },
  { id: 'news_catalysts', label: 'News & Catalysts' },
  { id: 'technical_analysis', label: 'Technical & Price Action' },
  { id: 'fundamental_valuation', label: 'Fundamental & Valuation' },
  { id: 'intelligence_view', label: 'Synthesized Agent & Intelligence' },
  { id: 'risk_assessment', label: 'Risk & Thesis Validity' },
  { id: 'action_plan', label: 'Recommendation & Action Plan' },
  { id: 'peer_comparison', label: 'Peer Comparison' },
  { id: 'options_strategy', label: 'Options Greeks & Strategy' },
]

const AUTO_LOAD_TYPES = new Set([
  'daily_digest', 'weekly_review', 'intelligence_deep', 'event_driven',
  'symbol_holding', 'symbol_watchlist', 'symbol_custom', 'sector_theme',
])

function readAnalystUrlParams() {
  try {
    const q = new URLSearchParams(window.location.search)
    const sym = (q.get('symbol') || '').trim().toUpperCase()
    const typ = (q.get('type') || '').trim()
    const validTyp = typ && REPORT_TYPES.some(t => t.key === typ) ? typ : ''
    return { sym, typ: validTyp, autoGenerate: q.get('generate') === '1' }
  } catch {
    return { sym: '', typ: '', autoGenerate: false }
  }
}

export default function AnalystReportsPanel() {
  const urlInit = useMemo(() => readAnalystUrlParams(), [])
  const [staleBundle, setStaleBundle] = useState(false)
  const [serverVersion, setServerVersion] = useState('')

  useEffect(() => {
    fetch('/v3/build-meta.json', { cache: 'no-store' })
      .then(r => r.json())
      .then(meta => {
        const sv = String(meta?.ui_version || '')
        setServerVersion(sv)
        const serverBase = String(meta?.base_version || sv.split('+')[0] || '')
        const clientBase = UI_VERSION.split('+')[0]
        // Stale only when the base major version changed — not when client label omits the +stamp.
        if (serverBase && clientBase && serverBase !== clientBase) setStaleBundle(true)
        else if (sv && UI_VERSION.includes('+') && sv !== UI_VERSION) setStaleBundle(true)
      })
      .catch(() => {})
  }, [])

  const { data: symData } = useApi<any>('/api/v2/reports/analyst/symbols', 120_000)
  const symbols: string[] = symData?.symbols || []

  const [reportType, setReportType] = useState(urlInit.typ || 'symbol_holding')
  const [symbol, setSymbol] = useState(urlInit.sym || '')
  const [sections, setSections] = useState<string[]>(SECTION_OPTS.map(s => s.id))
  const [preview, setPreview] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState('')
  const [exportUrl, setExportUrl] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [eventFilter, setEventFilter] = useState('all')
  const [hours, setHours] = useState(24)
  const [grokEdit, setGrokEdit] = useState(false)

  const needsSymbol = reportType.startsWith('symbol_')
  const needsSector = reportType === 'sector_theme'
  const isEventDriven = reportType === 'event_driven'
  const isPortfolioReport = reportType === 'daily_digest' || reportType === 'weekly_review'
  const symbolOptional = isEventDriven || reportType === 'intelligence_deep' || needsSymbol || needsSector
  const filterOptional = (needsSymbol || needsSector) && !symbol.trim()

  const previewPath = useMemo(() => {
    const params = new URLSearchParams({ type: reportType })
    if (needsSymbol && symbol.trim()) params.set('symbol', symbol.toUpperCase())
    if (needsSector && symbol.trim()) params.set('sector', symbol)
    if (reportType === 'intelligence_deep' && symbol.trim()) params.set('topic', symbol)
    if (isEventDriven) {
      if (symbol.trim()) params.set('symbol', symbol.toUpperCase())
      params.set('event_filter', eventFilter)
      params.set('hours', String(hours))
    }
    if (sections.length && !isEventDriven && !isPortfolioReport && reportType !== 'intelligence_deep') {
      params.set('sections', sections.join(','))
    }
    return `/api/v2/reports/analyst/preview?${params}`
  }, [reportType, symbol, sections, needsSymbol, needsSector, isEventDriven, isPortfolioReport, eventFilter, hours])

  const loadPreview = useCallback(async () => {
    setLoading(true)
    setError('')
    setPreview(null)
    try {
      const r = await fetch(`${previewPath}&_ts=${Date.now()}`, { cache: 'no-store' })
      const j = await r.json()
      if (!r.ok) throw new Error(j?.error || `HTTP ${r.status}`)
      const data = j?.data ?? j
      if (data?.error) throw new Error(data.error)
      if (data?.ok === false && data?.error) throw new Error(data.error)
      setPreview(data?.meta ? data : data)
    } catch (e: any) {
      setError(e?.message || 'Preview failed')
      setPreview(null)
    } finally {
      setLoading(false)
    }
  }, [previewPath])

  useEffect(() => {
    if (AUTO_LOAD_TYPES.has(reportType)) loadPreview()
  }, [previewPath, reportType, loadPreview])

  const doExport = async (format: 'docx' | 'pdf') => {
    setExporting(format)
    setError('')
    setExportUrl(null)
    try {
      const body: Record<string, unknown> = { type: reportType, format, sections }
      if (needsSymbol && symbol.trim()) body.symbol = symbol.toUpperCase()
      if (needsSector && symbol.trim()) body.sector = symbol
      if (reportType === 'intelligence_deep' && symbol.trim()) body.topic = symbol
      if (isEventDriven) {
        if (symbol.trim()) body.symbol = symbol.toUpperCase()
        body.event_filter = eventFilter
        body.hours = hours
      }
      const r = await fetch('/api/v2/reports/analyst/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const j = await r.json()
      if (!r.ok) throw new Error(j?.error || `HTTP ${r.status}`)
      const res = j?.data ?? j
      if (res?.ok === false && res?.error) throw new Error(res.error)
      const url = res?.url || (format === 'pdf' ? res?.path : null) || res?.docx?.url
      if (url) setExportUrl(url)
    } catch (e: any) {
      setError(e?.message || 'Export failed')
    } finally {
      setExporting('')
    }
  }

  const toggleSection = (id: string) => {
    setSections(prev => prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id])
  }

  const placeholder = isEventDriven ? 'Symbol filter (optional)' :
    reportType === 'intelligence_deep' ? 'Topic filter (optional)' :
    needsSector ? 'Sector (blank = all sectors)' :
    needsSymbol ? 'Symbol (blank = entire universe)' : 'Filter'

  const generateProspectus = useCallback(async (opts?: { grok?: boolean }) => {
    if (!symbol.trim() || !needsSymbol) return
    const useGrok = opts?.grok ?? grokEdit
    setExporting(useGrok ? 'grok' : 'prospectus')
    setError('')
    setExportUrl(null)
    try {
      const r = await fetch('/api/v2/reports/analyst/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: reportType,
          symbol: symbol.toUpperCase(),
          grok_edit: useGrok,
          oversight: true,
        }),
      })
      const j = await r.json()
      const res = j?.data ?? j
      if (!r.ok || res?.ok === false) throw new Error(res?.error || res?.block_reason || `HTTP ${r.status}`)
      const exp = res?.exports || {}
      const url = exp.docx || exp.pdf || res?.registry_entry?.docx || res?.registry_entry?.pdf
      if (url && typeof url === 'string') setExportUrl(url)
      if (res?.report) setPreview(res.report)
    } catch (e: any) {
      setError(e?.message || 'Prospectus generation failed')
    } finally {
      setExporting('')
    }
  }, [symbol, needsSymbol, reportType, grokEdit])

  const autoGenDone = useRef(false)
  useEffect(() => {
    if (!urlInit.autoGenerate || autoGenDone.current || !symbol.trim() || !needsSymbol) return
    autoGenDone.current = true
    generateProspectus({ grok: false })
  }, [urlInit.autoGenerate, symbol, needsSymbol, generateProspectus])

  if (staleBundle) {
    return (
      <div style={{
        ...card, borderColor: '#ef444488', textAlign: 'center', padding: 28,
      }}>
        <div style={{ fontSize: 16, fontWeight: 900, color: '#ef4444', marginBottom: 8 }}>Stale UI bundle detected</div>
        <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 16, lineHeight: 1.5 }}>
          Your browser has v{UI_VERSION} but the server has v{serverVersion || '?'}.<br />
          Click Reload to get Action Queue, modals, and the latest report layouts.
        </div>
        <button
          onClick={() => {
            try {
              sessionStorage.removeItem('cc_v3_build')
              sessionStorage.clear()
            } catch { /* */ }
            const base = window.location.pathname.replace(/\/v3.*/, '/v3/') || '/v3/'
            window.location.replace(`${base}?_cc_reload=${Date.now()}`)
          }}
          style={{ fontSize: 13, fontWeight: 800, padding: '10px 24px', borderRadius: 8, border: 'none', background: '#1d4ed8', color: '#fff', cursor: 'pointer' }}
        >
          Reload Command Center v{serverVersion || 'latest'}
        </button>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <AnalystTruthBand />
      <ProspectusBatchPanel />
      <div style={{
        fontSize: 10, padding: '8px 12px', borderRadius: 8,
        background: 'rgba(34,197,94,.08)', border: '1px solid #22c55e44', color: '#22c55e',
      }}>
        Reports UI v{UI_VERSION} active — Action Queue + address modals enabled.
      </div>
      <div style={card}>
        <div style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)', marginBottom: 4 }}>Analyst Report Builder</div>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8 }}>
          Blank filter = full universe report. Weekly/Daily digests surface an <b style={{ color: '#f59e0b' }}>Action Queue</b> — click any item to open the address modal.
          <span style={{ marginLeft: 8, fontWeight: 800, color: '#22c55e' }}>UI v{UI_VERSION}</span>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          {[
            { type: 'daily_digest', label: '⚡ Daily Digest' },
            { type: 'weekly_review', label: '📆 Weekly Review' },
            { type: 'intelligence_deep', label: '🔬 Intel Deep Dive' },
            { type: 'event_driven', label: '🚨 Event Alerts' },
          ].map(q => (
            <button key={q.type} onClick={() => { setReportType(q.type); setSymbol(''); setPreview(null); setError('') }} style={{
              fontSize: 9, fontWeight: 700, padding: '4px 8px', borderRadius: 5, cursor: 'pointer',
              border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)',
            }}>{q.label}</button>
          ))}
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
          {REPORT_TYPES.map(t => (
            <button key={t.key} onClick={() => { setReportType(t.key); setPreview(null); setError('') }} style={{
              fontSize: 10, fontWeight: reportType === t.key ? 800 : 600, padding: '5px 10px', borderRadius: 6, cursor: 'pointer',
              border: `1px solid ${reportType === t.key ? '#60a5fa' : 'var(--border)'}`,
              background: reportType === t.key ? 'rgba(96,165,250,.12)' : 'var(--bg2)',
              color: reportType === t.key ? '#60a5fa' : 'var(--text2)',
            }}>{t.label}</button>
          ))}
        </div>

        {isEventDriven && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            {EVENT_FILTERS.map(f => (
              <button key={f.key} onClick={() => setEventFilter(f.key)} style={{
                fontSize: 9, fontWeight: eventFilter === f.key ? 800 : 600, padding: '4px 8px', borderRadius: 5, cursor: 'pointer',
                border: `1px solid ${eventFilter === f.key ? '#f59e0b' : 'var(--border)'}`,
                background: eventFilter === f.key ? 'rgba(245,158,11,.12)' : 'var(--bg2)',
                color: eventFilter === f.key ? '#f59e0b' : 'var(--text3)',
              }}>{f.label}</button>
            ))}
            <select value={hours} onChange={e => setHours(Number(e.target.value))} style={{
              fontSize: 10, padding: '4px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)',
            }}>
              <option value={24}>Last 24h</option>
              <option value={48}>Last 48h</option>
              <option value={168}>Last 7d</option>
            </select>
          </div>
        )}

        {symbolOptional && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
            <input
              list={needsSymbol || isEventDriven ? 'analyst-symbols' : undefined}
              value={symbol}
              onChange={e => setSymbol((needsSymbol || isEventDriven) ? e.target.value.toUpperCase() : e.target.value)}
              placeholder={placeholder}
              style={{ flex: 1, maxWidth: 240, fontSize: 12, padding: '6px 10px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text0)', fontFamily: needsSymbol || isEventDriven ? 'monospace' : 'inherit' }}
            />
            {(needsSymbol || isEventDriven) && (
              <datalist id="analyst-symbols">
                {symbols.map(s => <option key={s} value={s} />)}
              </datalist>
            )}
            {filterOptional && (
              <span style={{ fontSize: 9, fontWeight: 700, color: '#22c55e' }}>→ ALL report</span>
            )}
            {(needsSymbol || isEventDriven) && <span style={{ fontSize: 9, color: 'var(--text4)' }}>{symbols.length} symbols</span>}
          </div>
        )}

        {!isEventDriven && !isPortfolioReport && reportType !== 'intelligence_deep' && <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', marginBottom: 6, textTransform: 'uppercase' }}>Sections to include</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {SECTION_OPTS.map(s => (
              <label key={s.id} style={{ fontSize: 9, display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', color: sections.includes(s.id) ? 'var(--text1)' : 'var(--text4)' }}>
                <input type="checkbox" checked={sections.includes(s.id)} onChange={() => toggleSection(s.id)} />
                {s.label}
              </label>
            ))}
          </div>
        </div>}

        {needsSymbol && symbol.trim() && (
          <label style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 5, marginBottom: 10, cursor: 'pointer', color: 'var(--text2)' }}>
            <input type="checkbox" checked={grokEdit} onChange={e => setGrokEdit(e.target.checked)} />
            Grok OAuth editorial polish on export
          </label>
        )}

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {needsSymbol && symbol.trim() && (
            <button onClick={() => generateProspectus({ grok: false })} disabled={!!exporting} style={{
              fontSize: 11, fontWeight: 800, padding: '6px 14px', borderRadius: 6, cursor: 'pointer',
              border: 'none', background: '#22c55e', color: '#fff', opacity: exporting ? 0.6 : 1,
            }}>{exporting === 'prospectus' ? 'Generating prospectus…' : `Generate prospectus · ${symbol.toUpperCase()}`}</button>
          )}
          <button onClick={loadPreview} disabled={loading} style={{
            fontSize: 11, fontWeight: 700, padding: '6px 14px', borderRadius: 6, cursor: 'pointer',
            border: 'none', background: '#60a5fa', color: '#fff', opacity: loading ? 0.6 : 1,
          }}>{loading ? 'Generating…' : filterOptional ? 'Generate ALL report' : 'Generate preview'}</button>
          <button onClick={() => doExport('docx')} disabled={!!exporting || !preview} style={{
            fontSize: 11, fontWeight: 700, padding: '6px 14px', borderRadius: 6, cursor: 'pointer',
            border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)',
          }}>{exporting === 'docx' ? 'Exporting…' : 'Export Word'}</button>
          <button onClick={() => doExport('pdf')} disabled={!!exporting || !preview} style={{
            fontSize: 11, fontWeight: 700, padding: '6px 14px', borderRadius: 6, cursor: 'pointer',
            border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)',
          }}>{exporting === 'pdf' ? 'Exporting…' : 'Export PDF'}</button>
          {needsSymbol && symbol.trim() && grokEdit && (
            <button onClick={() => generateProspectus({ grok: true })} disabled={!!exporting} style={{
              fontSize: 11, fontWeight: 700, padding: '6px 14px', borderRadius: 6, cursor: 'pointer',
              border: '1px solid #60a5fa', background: 'rgba(96,165,250,.12)', color: '#60a5fa',
            }}>{exporting === 'grok' ? 'Generating…' : 'Generate + Grok'}</button>
          )}
          {exportUrl && (
            <a href={exportUrl} target="_blank" rel="noreferrer" style={{ fontSize: 11, fontWeight: 700, color: '#22c55e', alignSelf: 'center' }}>
              Download ↗
            </a>
          )}
        </div>
        {error && <div style={{ fontSize: 10, color: '#ef4444', marginTop: 8 }}>{error}</div>}
      </div>

      {preview && <AnalystReportViewer report={preview} />}
    </div>
  )
}
// Reports Desk v1 (WS-C): the truth band — every count defined on-page from
// /api/v2/reports/analyst/status (one registry pass); unmapped CUSIP instruments
// fold (real $0 rows, never hidden, never rendered as peers of equities);
// former-holdings fold; stale · Nd semantics + the Sun 21:15 schedule stated.
function AnalystTruthBand() {
  const { data: st } = useApi<any>('/api/v2/reports/analyst/status', 120_000)
  const [unmappedOpen, setUnmappedOpen] = useState(false)
  const [formerOpen, setFormerOpen] = useState(false)
  if (!st?.ok) return null
  const chip = (label: string, tip: string): JSX.Element => (
    <span title={tip} style={{ fontSize: 10, fontFamily: "'JetBrains Mono', ui-monospace, monospace", color: 'var(--text2)', border: '1px solid var(--border)', borderRadius: 2, padding: '1px 8px', cursor: 'help' }}>{label}</span>
  )
  const former = (st.former_holdings || []).filter((s: string) => !/^\d/.test(s))
  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderLeft: '3px solid #ffb000', borderRadius: 2, padding: '8px 12px' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.06em', color: 'var(--text3)' }}>COVERAGE TRUTH</span>
        {chip(`eligible holdings ${st.eligible_holdings ?? '—'}`, 'live eligible_holding_symbols() — holdings above value floor with actionable stance')}
        {chip(`symbols covered ${st.symbols_covered}`, `registry.json latest report per symbol (${st.reports_total} total artifacts)`)}
        {chip(`fresh ${st.fresh}`, 'latest report younger than 7d')}
        {chip(`need refresh ${st.need_refresh}`, st.need_refresh_definition)}
        <span style={{ fontSize: 10, color: 'var(--text3)' }}>{st.schedule}</span>
      </div>
      <div style={{ display: 'flex', gap: 10, marginTop: 6, flexWrap: 'wrap' }}>
        {(st.unmapped_instruments?.length ?? 0) > 0 && (
          <button onClick={() => setUnmappedOpen(o => !o)}
            style={{ fontSize: 10, fontWeight: 800, color: '#ffb000', background: 'rgba(255,176,0,.1)', border: '1px solid rgba(255,176,0,.4)', borderRadius: 2, padding: '2px 8px', cursor: 'pointer' }}>
            {unmappedOpen ? '▾' : '▸'} Unmapped instruments ({st.unmapped_instruments.length}) — awaiting instrument mapping
          </button>
        )}
        {former.length > 0 && (
          <button onClick={() => setFormerOpen(o => !o)}
            style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)', background: 'transparent', border: '1px solid var(--border)', borderRadius: 2, padding: '2px 8px', cursor: 'pointer' }}>
            {formerOpen ? '▾' : '▸'} Former holdings ({former.length})
          </button>
        )}
      </div>
      {unmappedOpen && (
        <div style={{ marginTop: 6, fontSize: 10, color: 'var(--text2)', fontFamily: "'JetBrains Mono', ui-monospace, monospace" }}>
          {st.unmapped_instruments.map((u: any, i: number) => (
            <div key={i}>{u.symbol} · ${u.market_value ?? 0} · {u.description || 'no description in feed'} — real holdings.json row; awaiting instrument mapping (dated basis export outstanding)</div>
          ))}
        </div>
      )}
      {formerOpen && (
        <div style={{ marginTop: 6, fontSize: 10, color: 'var(--text3)', fontFamily: "'JetBrains Mono', ui-monospace, monospace" }}>
          {former.join(' · ')} — reports retained (never deleted); excluded from freshness pressure
        </div>
      )}
    </div>
  )
}
