/** Inline prospectus report icon-links for portfolio holding + watchlist cards and drawer.
 *  Icon links (PDF / Word / open / regenerate) with a rich hover tooltip showing date created etc. */
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { requestAnalystReportMapRefetch, type AnalystReportEntry } from '../hooks/useAnalystReportMap'
import './HoldingReportLinks.css'

type Props = {
  symbol: string
  entry?: AnalystReportEntry
  compact?: boolean
  reportType?: 'symbol_holding' | 'symbol_watchlist'
}

const iconBtn = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  minWidth: 30,
  height: 26,
  padding: '0 9px',
  gap: 4,
  fontSize: 16,
  fontWeight: 800 as const,
  lineHeight: 1,
  textDecoration: 'none' as const,
  borderRadius: 6,
  cursor: 'pointer' as const,
}

function relTime(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const mins = Math.round((Date.now() - d.getTime()) / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.round(hrs / 24)}d ago`
}

/** Multi-line native tooltip: date created + generation + editorial/oversight state. */
function tooltip(sym: string, e?: AnalystReportEntry): string {
  if (!e?.generated_at) return `Generate a summary prospectus for ${sym}`
  const created = new Date(e.generated_at)
  const lines = [
    `${sym} — Analyst Prospectus`,
    `Created: ${created.toLocaleString()} (${relTime(e.generated_at)})`,
  ]
  if (e.generation) lines.push(`Generation: #${e.generation}`)
  if (e.recommendation) lines.push(`Stance: ${e.recommendation}`)
  if (e.oversight_verdict) lines.push(`Cloud oversight: ${e.oversight_verdict}`)
  lines.push(e.grok_edited ? 'Grok editorial: applied' : 'Grok editorial: none')
  lines.push('Click PDF/Word to open · ↻ to regenerate')
  return lines.join('\n')
}

export default function HoldingReportLinks({ symbol, entry, compact, reportType }: Props) {
  const sym = symbol.toUpperCase()
  const stop = (ev: React.MouseEvent) => ev.stopPropagation()
  const rtype = reportType || entry?.report_type || 'symbol_holding'
  const buildHref = `/v3/reports?mode=analyst&generate=1&symbol=${encodeURIComponent(sym)}&type=${rtype}`
  const tip = tooltip(sym, entry)
  const [genBusy, setGenBusy] = useState(false)
  const [genErr, setGenErr] = useState('')

  const [confirming, setConfirming] = useState(false)

  // Generating starts a model run, so a tap only opens the confirm sheet; nothing is sent until
  // "Generate report" is pressed (site sweep 2026-10-25: the bare 📄 fired the POST on first tap).
  const askToGenerate = (ev: React.MouseEvent) => {
    stop(ev)
    if (!genBusy) setConfirming(true)
  }

  const runInlineGenerate = async () => {
    setConfirming(false)
    if (genBusy) return
    setGenBusy(true)
    setGenErr('')
    try {
      const r = await fetch('/api/v2/reports/analyst/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: rtype, symbol: sym, grok_edit: false, oversight: true }),
      })
      const j = await r.json()
      const res = j?.data ?? j
      if (!r.ok || res?.ok === false) throw new Error(res?.error || res?.block_reason || `HTTP ${r.status}`)
      requestAnalystReportMapRefetch()
      const url = res?.exports?.pdf || res?.exports?.docx
      if (url) window.open(url, '_blank', 'noopener,noreferrer')
      else window.location.href = buildHref
    } catch (e: any) {
      setGenErr(String(e?.message || e).slice(0, 80))
      window.location.href = buildHref
    } finally {
      setGenBusy(false)
    }
  }

  // No report yet → generate inline (falls back to Analyst Reports tab on failure).
  if (!entry?.docx && !entry?.pdf) {
    return (
      <span onClick={stop} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        <button
          type="button"
          onClick={askToGenerate}
          disabled={genBusy}
          title={genErr ? `${tip}\n${genErr}` : tip}
          aria-label={genBusy ? `Generating analyst report for ${sym}` : `Analyst report for ${sym} — asks before generating`}
          aria-haspopup="dialog"
          data-testid="report-generate"
          className={compact ? 'hrl-generate hrl-generate--compact' : 'hrl-generate'}
          style={{ ...iconBtn, padding: '0 10px', color: '#94a3b8', background: 'rgba(148,163,184,.1)', border: '1px solid rgba(148,163,184,.25)', fontWeight: 700, fontSize: 12, opacity: genBusy ? 0.6 : 1 }}
        >
          <span aria-hidden="true">📄</span><span className="hrl-generate-label" style={{ fontSize: 11 }}>{genBusy ? 'Generating…' : 'Analyst report'}</span>
        </button>
        {confirming && <GenerateConfirmSheet symbol={sym} onCancel={() => setConfirming(false)} onConfirm={runInlineGenerate} />}
      </span>
    )
  }

  const verdictColor =
    entry.oversight_verdict === 'BLOCK' ? '#ef4444'
    : entry.oversight_verdict === 'PUBLISH' ? '#22c55e'
    : '#f59e0b'

  return (
    <span onClick={stop} title={tip} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <span
        aria-hidden
        title={tip}
        style={{ width: 6, height: 6, borderRadius: '50%', background: verdictColor, flex: '0 0 auto' }}
      />
      {entry.pdf && (
        <a
          href={entry.pdf}
          target="_blank"
          rel="noreferrer"
          onClick={stop}
          className="hrl-icon"
          aria-label={`Open ${sym} prospectus PDF`}
          title={tip}
          style={{ ...iconBtn, color: '#f59e0b', background: 'rgba(245,158,11,.12)', border: '1px solid rgba(245,158,11,.35)' }}
        >
          📕{!compact && <span style={{ fontSize: 10.5, fontWeight: 800 }}>PDF</span>}
        </a>
      )}
      {entry.docx && (
        <a
          href={entry.docx}
          target="_blank"
          rel="noreferrer"
          onClick={stop}
          className="hrl-icon"
          aria-label={`Open ${sym} prospectus Word`}
          title={tip}
          style={{ ...iconBtn, color: '#60a5fa', background: 'rgba(96,165,250,.12)', border: '1px solid rgba(96,165,250,.35)' }}
        >
          📘{!compact && <span style={{ fontSize: 10.5, fontWeight: 800 }}>Word</span>}
        </a>
      )}
      <a
        href={`/v3/reports?mode=analyst&generate=1&symbol=${encodeURIComponent(sym)}&type=${rtype}`}
        onClick={stop}
        className="hrl-icon"
        aria-label={`Regenerate ${sym} prospectus`}
        title={`Regenerate / preview ${sym} in Reports`}
        style={{ ...iconBtn, color: '#94a3b8', background: 'transparent', border: '1px solid var(--border)' }}
      >
        ↻
      </a>
      {!compact && (
        <span style={{ fontSize: 9.5, color: '#64748b', whiteSpace: 'nowrap' }}>{relTime(entry.generated_at)}</span>
      )}
    </span>
  )
}

/** In-page confirm step before a paid/queued report run (never window.confirm). Bottom sheet on a phone. */
function GenerateConfirmSheet({ symbol, onCancel, onConfirm }: { symbol: string; onCancel: () => void; onConfirm: () => void }) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const previous = document.activeElement
    cancelRef.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
    }
  }, [onCancel])
  return createPortal(
    <div className="hrl-confirm-backdrop" data-testid="report-generate-confirm-backdrop"
      onClick={e => { e.stopPropagation(); if (e.target === e.currentTarget) onCancel() }}>
      <section role="alertdialog" aria-modal="true" aria-labelledby="hrl-confirm-title" aria-describedby="hrl-confirm-body"
        className="hrl-confirm" data-testid="report-generate-confirm">
        <h2 id="hrl-confirm-title" className="hrl-confirm-title">Generate analyst report for {symbol}?</h2>
        <p id="hrl-confirm-body" className="hrl-confirm-body">
          This starts a new analyst report run (model work with cloud oversight). It can take a few minutes.
          When it finishes the report opens; nothing is sent until you choose Generate report.
        </p>
        <div className="hrl-confirm-actions">
          <button ref={cancelRef} type="button" data-testid="report-generate-cancel" onClick={onCancel}>Cancel</button>
          <button type="button" data-testid="report-generate-confirm-go" className="hrl-confirm-primary" onClick={onConfirm}>Generate report</button>
        </div>
      </section>
    </div>,
    document.body,
  )
}
