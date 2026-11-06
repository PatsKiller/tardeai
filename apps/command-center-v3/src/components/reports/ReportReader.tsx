/**
 * Report reader (Reports redesign v001, operator-approved 2026-11-06, mapping rows 11–12, 14).
 * Phone: a full-screen sheet — ‹ back, sticky section chips, collapsible sections (Bottom line + the first
 * section open), the as-of / gaps box, Word ⤓ only when the exact-date file exists, and the report's
 * extracted follow-ups as the last section. Desktop: the same reader in the right pane.
 * Body text is rendered through RichText (tickers bold, −% red, +% green, look-at sentences italic).
 */
import { useEffect, useMemo, useRef } from 'react'
import { useApi } from '../../hooks/useApi'
import { parseReport, extractAsOf, isMarketReport } from './reportFormat'
import { ReportBody, RichInline } from './RichText'
import { relUrl } from './reportLinks'

const ACT_ROUTE: Record<string, string> = {
  stop_triggered: '/v3/risk', unprotected_position: '/v3/risk', risk_review: '/v3/risk',
  approval_needed: '/v3/trading', broker_manual: '/v3/trading', hermes_review: '/v3/hermes',
  system_health: '/v3/system', cron_or_backup: '/v3/system', llm_review: '/v3/system',
}

export const fmtWhen = (s?: string | null) => {
  if (!s) return '—'
  const d = new Date(s)
  if (!Number.isFinite(d.getTime())) return String(s)
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) + ' · ' +
    d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

export interface ReaderRef { source: string; id: string | number; category?: string; title?: string; created_at?: string }

export default function ReportReader({ item, sheet, onClose }: { item: ReaderRef; sheet: boolean; onClose: () => void }) {
  const { data: full, loading, error } = useApi<any>(`/api/v2/reports/item?source=${encodeURIComponent(item.source)}&id=${encodeURIComponent(String(item.id))}`, 0)
  const it = { ...item, ...(full && !full.error ? full : {}) }
  const category = it.category || item.category || ''
  const ageDays = it.created_at ? Math.max(1, Math.min(365, Math.ceil((Date.now() - new Date(it.created_at).getTime()) / 86_400_000) + 1)) : 7
  const { data: acts } = useApi<any>(
    `/api/v2/reports/action-items?${category ? `category=${encodeURIComponent(category)}&` : ''}days=${ageDays}&limit=500`, 0,
    { enabled: !!full && !full.error })
  const rid = `${item.source}-${item.id}`
  const followups = useMemo(() => {
    const seen = new Set<string>()
    return (acts?.actions || []).filter((a: any) => a.report_id === rid)
      .filter((a: any) => { const k = `${a.action_class}|${a.text}`; if (seen.has(k)) return false; seen.add(k); return true })
  }, [acts, rid])

  const body: string = it.summary || ''
  const parsed = useMemo(() => parseReport(body, it.title || ''), [body, it.title])
  const asOf = useMemo(() => extractAsOf(parsed, it.meta), [parsed, it.meta])
  const market = isMarketReport({ category, type: it.type, title: it.title })
  const title = parsed.title || it.title || 'Report'
  const scroller = useRef<HTMLDivElement>(null)

  // Phone sheet: the OS back gesture closes the reader instead of leaving the page.
  useEffect(() => {
    if (!sheet) return
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.history.pushState({ rpReader: rid }, '')
    const onPop = () => onClose()
    window.addEventListener('popstate', onPop)
    return () => {
      document.body.style.overflow = prevOverflow
      window.removeEventListener('popstate', onPop)
    }
  }, [sheet, rid]) // eslint-disable-line
  const close = () => { if (sheet && window.history.state?.rpReader === rid) window.history.back(); else onClose() }

  useEffect(() => { scroller.current?.scrollTo?.({ top: 0 }) }, [rid])

  const jump = (id: string) => {
    const el = document.getElementById(id) as HTMLDetailsElement | null
    if (!el) return
    if ('open' in el) el.open = true
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  const docx = it.docx_file
  const chips = [...parsed.sections.map(s => ({ id: s.id, label: s.chip })), ...(followups.length ? [{ id: 'rp-followups', label: 'Follow-ups' }] : [])]
  const firstNumbered = parsed.sections.findIndex(s => !/bottom line|summary/i.test(s.title))

  const content = (
    <div className={`rp-reader${sheet ? ' rp-sheet' : ' rp-card'}`} ref={scroller} role={sheet ? 'dialog' : 'region'} aria-modal={sheet || undefined}
      aria-label={title} data-testid="report-reader" style={sheet ? undefined : { padding: 0, overflow: 'hidden' }}>
      <div className="rp-bar">
        <div className="row1">
          <button type="button" className="rp-btn ghost" aria-label="Back to reports" onClick={close} data-testid="reader-back">‹</button>
          <div className="tt" title={title}>{title}</div>
          {docx?.url && (
            <a className="rp-btn ghost" href={relUrl(docx.url)} download title={`Word · ${docx.filename} (${docx.size_kb} KB)`} aria-label="Download Word file">⤓</a>
          )}
        </div>
        {chips.length > 1 && (
          <nav className="rp-toc" aria-label="Sections">
            {chips.map(c => <button key={c.id} type="button" className="rp-chip" onClick={() => jump(c.id)}>{c.label}</button>)}
          </nav>
        )}
      </div>
      <div className="rp-rbody">
        <div>
          <div className="rp-eyebrow">
            <span>{market ? 'Market report' : (it.category_label || category.replace(/_/g, ' ') || it.type)}</span>
            <span>· {fmtWhen(it.created_at)}</span>
            {it.channel && <span>· {it.channel}</span>}
          </div>
          <div className="rp-title">{title}</div>
          {(market || asOf.text || asOf.gaps.length > 0) && (
            <dl className={`rp-asof${asOf.text ? '' : ' stale'}`} data-testid="reader-asof">
              <dt>As of</dt>
              <dd>{asOf.text ? <RichInline text={asOf.text} /> : <span className="none">as-of not recorded</span>}</dd>
              {asOf.gaps.length > 0 && (<>
                <dt>Gaps</dt>
                <dd>{asOf.gaps.length} known gap{asOf.gaps.length === 1 ? '' : 's'}
                  {asOf.gapsSection && <> · <button type="button" className="rp-btn ghost" style={{ padding: '0 6px', fontSize: 12, verticalAlign: 'middle' }} onClick={() => jump(asOf.gapsSection!)}>read them</button></>}
                </dd>
              </>)}
            </dl>
          )}
        </div>
        {loading && !full && <div className="rp-empty">Loading report…</div>}
        {error && !full && <div className="rp-empty">Could not load the full text ({String(error)}). Showing the list summary.</div>}
        {parsed.intro.trim() && <div className="rp-card"><ReportBody md={parsed.intro.replace(/^\s*\*\*Data as-of:\*\*.*$/m, '').trim()} /></div>}
        {parsed.sections.map((s, i) => (
          <details key={s.id} id={s.id} className="rp-sec" open={i === 0 || i === firstNumbered || parsed.sections.length <= 2}>
            <summary>
              <span className="h">{s.title.replace(/\*\*/g, '')}</span>
              {s.summary && <span className="s">{s.summary}{s.bullets > 0 ? ` · ${s.bullets} item${s.bullets === 1 ? '' : 's'}` : ''}</span>}
            </summary>
            <div className="b"><ReportBody md={s.body} /></div>
          </details>
        ))}
        {!parsed.sections.length && !parsed.intro.trim() && !loading && <div className="rp-empty">This report has no body text.</div>}
        {followups.length > 0 && (
          <details id="rp-followups" className="rp-sec rp-followups" open>
            <summary><span className="h">Follow-ups from this report</span><span className="s">{followups.length} extracted · advisory only</span></summary>
            <div className="b rp-md">
              <ul>
                {followups.map((a: any, i: number) => (
                  <li key={i}>
                    <RichInline text={a.text || a.action_class} />{' '}
                    <a href={relUrl(a.route || ACT_ROUTE[a.action_class] || '/v3/reports')}>{a.route_label || 'Open'} →</a>
                  </li>
                ))}
              </ul>
            </div>
          </details>
        )}
        {(it.actions || []).length > 0 && (
          <div className="rp-actions">
            {(it.actions as any[]).map((a, i) => <a key={i} className="rp-btn" href={relUrl(a.url)}>{a.label}</a>)}
          </div>
        )}
      </div>
    </div>
  )
  return content
}
