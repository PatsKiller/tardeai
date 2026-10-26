/** Ticker Prospectus — built to the approved design prospectus/v001 (operator 2026-10-26, "approved push live").
 *  One prospectus per holding and Watch ticker, versioned.
 *    /v3/prospectus          list: stat tiles (ready, queued, Anthropic credit), All / Holdings / Watch / Needs rewrite,
 *                            search; desktop table (ticker, verdict, type, model, written, next rewrite, status), phone cards
 *    /v3/prospectus/:symbol  report: header (downloads, version, operator-only Rewrite now), verdict tiles, summary,
 *                            charts, relative performance, peers, estimates / ownership / risk, scenarios, narrative
 *                            sections, macro / filings / earnings call / options, source coverage, sources.
 *                            Phone (≤820): a full-screen sheet with ← Back; narrative sections tap to open.
 *  Read-only except POST /refresh, which the server accepts from the tailnet operator identity only; the button renders
 *  only when the server says this viewer is the operator (viewer.operator === true). Contract: handoffs/prospectus-20261026. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { inlineMarkdown } from '../components/PolicyRuleParts'
import ProspectusCharts from '../components/prospectus/ProspectusCharts'
import {
  CallBlock, CoverageBlock, EstimatesBlock, FilingsBlock, MacroBlock, OptionsBlock, OwnershipBlock, PeerComparisonBlock,
  RelativePerformanceBlock, RiskBlock, ScenariosBlock, VerdictTiles,
} from '../components/prospectus/ProspectusBlocks'
import {
  SECTION_TONE, SUMMARY_SECTION, allCitations, budgetView, detailPath, detailState, filePath, filterItems, indexPath,
  mdBlocks, modelLabel, normSymbol, orderedSections, pageRoute, refreshPath, rowStatus, scopeCounts, splitCitations,
  statusOf, toNumber, totals, whenEt,
  type ProspectusDoc, type ProspectusIndex, type ProspectusIndexItem, type ProspectusSection, type ScopeFilter,
} from '../lib/prospectusModel'
import './Prospectus.css'

const SCOPES: { id: ScopeFilter; label: string; phoneLabel?: string }[] = [
  { id: 'all', label: 'All' }, { id: 'holdings', label: 'Holdings' }, { id: 'watch', label: 'Watch' }, { id: 'rewrite', label: 'Needs rewrite', phoneLabel: 'Rewrite' },
]

function usePhone(): boolean {
  const q = '(max-width: 820px)'
  const [phone, setPhone] = useState(() => typeof window !== 'undefined' && window.matchMedia(q).matches)
  useEffect(() => {
    const m = window.matchMedia(q)
    const on = () => setPhone(m.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [])
  return phone
}

/** The server may wrap payloads as {ok, data}; accept both. */
function unwrap<T>(j: any, key: string): T | null {
  if (!j) return null
  if (j[key] !== undefined) return j as T
  if (j.data && j.data[key] !== undefined) return j.data as T
  return j as T
}

function Chip({ tone, children, testId, title }: { tone: string; children: React.ReactNode; testId?: string; title?: string }) {
  return <span className={`psp-chip psp-tone-${tone}`} data-testid={testId} title={title}>{children}</span>
}

function ModelChip({ model, long }: { model?: string | null; long?: boolean }) {
  const m = modelLabel(model)
  if (m.tier === 'none') return null
  const v = /(\d+)[-.](\d+)/.exec(String(model ?? ''))
  return <span className={`psp-chip psp-model psp-model-${m.tier}`} data-testid="prospectus-model" title={String(model)}>{m.label}{long && v ? ` ${v[1]}.${v[2]}` : ''}</span>
}

function TypeChip({ scope }: { scope?: string }) {
  return <span className={`psp-chip psp-type psp-tone-${scope === 'holding' ? 'success' : 'info'}`} data-testid="prospectus-type">{scope === 'holding' ? 'Holding' : 'Watch'}</span>
}

function StatusChip({ it, testId = 'prospectus-status' }: { it: Pick<ProspectusIndexItem, 'status' | 'stale'>; testId?: string }) {
  const s = rowStatus(it)
  return <Chip tone={s.tone} testId={testId}>{s.label}</Chip>
}

function verdictText(it: ProspectusIndexItem): string {
  const st = statusOf(it.status)
  if (st === 'failed') return it.failure_reason || 'Last run failed'
  if (it.verdict_line) return it.verdict_line
  return st === 'missing' ? 'Not written yet — queued' : st === 'queued' ? 'Queued for writing' : st === 'running' ? 'Writing now…' : ''
}

function nextText(it: ProspectusIndexItem): string {
  if (!it.next_due) return '—'
  if (it.stale) return 'Overdue'
  return whenEt(it.next_due)
}

// ── List ────────────────────────────────────────────────────────────────────────────────────────────────────────

function StatTiles({ idx, phone }: { idx: ProspectusIndex | null; phone: boolean }) {
  const t = totals(idx)
  const b = budgetView(idx?.budget)
  const n = idx?.items?.length ?? 0
  return (
    <div className="psp-stats" data-testid="prospectus-strip">
      <div className="psp-stat" data-testid="prospectus-total-ready"><div className="psp-tile-k">Ready</div><div className="psp-stat-v psp-tone-success">{t.ready + t.partial} / {n}</div></div>
      <div className="psp-stat" data-testid="prospectus-total-queued"><div className="psp-tile-k">Queued</div><div className="psp-stat-v psp-tone-info">{t.queued + t.running}</div></div>
      <div className="psp-stat psp-stat-credit" data-testid="prospectus-budget" title="Anthropic credit for prospectus writing">
        <div className="psp-tile-k">{phone ? 'Credit' : 'Anthropic credit'}</div>
        <div className="psp-stat-v psp-stat-credit-v">{b.remaining}{phone ? '' : ' left'}</div>
        {!phone && <div className="psp-tile-sub" data-testid="prospectus-budget-today">today {b.used} of {b.cap} cap</div>}
        {!phone && b.fill != null && <span className="psp-meter" aria-hidden="true"><span className={`psp-meter-fill psp-bg-${b.tone}`} style={{ width: `${Math.round(b.fill * 100)}%` }} /></span>}
      </div>
      <span className="psp-sr-totals" data-testid="prospectus-total-failed" hidden>{t.failed}</span>
    </div>
  )
}

function DesktopTable({ rows, linkSearch }: { rows: ProspectusIndexItem[]; linkSearch: string }) {
  return (
    <div className="psp-tbl" data-testid="prospectus-list" role="table" aria-label="Prospectuses">
      <div className="psp-tbl-head" role="row">
        {['Ticker', 'Verdict (one line)', 'Type', 'Model', 'Written', 'Next rewrite', 'Status'].map(h => <div key={h} role="columnheader">{h}</div>)}
      </div>
      {rows.map(it => (
        <Link key={it.symbol} role="row" to={{ pathname: pageRoute(it.symbol), search: linkSearch }} className="psp-tbl-row"
          data-testid="prospectus-row" data-symbol={it.symbol} data-status={statusOf(it.status)}>
          <div role="cell"><div className="psp-sym">{it.symbol}</div><div className="psp-name">{it.name || ''}</div></div>
          <div role="cell" className="psp-verdict" data-testid="prospectus-verdict">{verdictText(it)}</div>
          <div role="cell"><TypeChip scope={it.scope} /></div>
          <div role="cell"><ModelChip model={it.model} /></div>
          <div role="cell" className="psp-date">{it.generated_at ? whenEt(it.generated_at) : '—'}</div>
          <div role="cell" className="psp-date">{nextText(it)}</div>
          <div role="cell"><StatusChip it={it} />{it.stale && <span data-testid="prospectus-stale" hidden>stale</span>}</div>
        </Link>
      ))}
    </div>
  )
}

function PhoneCards({ rows, linkSearch }: { rows: ProspectusIndexItem[]; linkSearch: string }) {
  return (
    <ul className="psp-list" data-testid="prospectus-list">
      {rows.map(it => (
        <li key={it.symbol}>
          <Link to={{ pathname: pageRoute(it.symbol), search: linkSearch }} className="psp-row" data-testid="prospectus-row" data-symbol={it.symbol} data-status={statusOf(it.status)}>
            <div className="psp-row-top"><span className="psp-sym">{it.symbol}</span><StatusChip it={it} />{it.stale && <span data-testid="prospectus-stale" hidden>stale</span>}</div>
            <div className="psp-verdict" data-testid="prospectus-verdict">{verdictText(it)}</div>
            <div className="psp-date">{[it.scope === 'holding' ? 'Holding' : 'Watch', modelLabel(it.model).tier !== 'none' ? modelLabel(it.model).label : null, it.generated_at ? whenEt(it.generated_at).replace(/ \d\d:\d\d ET$/, '') : null].filter(Boolean).join(' · ')}<span data-testid="prospectus-model" hidden>{modelLabel(it.model).label}</span></div>
          </Link>
        </li>
      ))}
    </ul>
  )
}

// ── Report pieces ───────────────────────────────────────────────────────────────────────────────────────────────

function MdText({ text, ids }: { text: string; ids: Set<string> }) {
  return <>{splitCitations(text, ids).map((p, i) => 'cite' in p
    ? <a key={i} href={`#cite-${p.cite}`} className="psp-cite-inline" data-testid="prospectus-cite-inline">{p.cite}</a>
    : <span key={i}>{inlineMarkdown(p.text, `t${i}`)}</span>)}</>
}

function SectionBody({ s }: { s: ProspectusSection }) {
  const cites = s.citations ?? []
  const ids = new Set(cites.map(c => c.id))
  const items: React.ReactNode[] = []
  let list: { ordered: boolean; nodes: React.ReactNode[] } | null = null
  const flush = () => { if (list) { items.push(list.ordered ? <ol key={`l${items.length}`}>{list.nodes}</ol> : <ul key={`l${items.length}`}>{list.nodes}</ul>); list = null } }
  mdBlocks(s.body_md).forEach((b, i) => {
    if (b.kind === 'li' || b.kind === 'oli') {
      const ordered = b.kind === 'oli'
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, nodes: [] } }
      list.nodes.push(<li key={i}><MdText text={b.text} ids={ids} /></li>)
      return
    }
    flush()
    items.push(b.kind === 'h' ? <h4 key={i} className="psp-h"><MdText text={b.text} ids={ids} /></h4> : <p key={i}><MdText text={b.text} ids={ids} /></p>)
  })
  flush()
  return (
    <>
      <div className="psp-body">{items}</div>
      {cites.length > 0 && (
        <div className="psp-cites" data-testid="prospectus-citations">
          {cites.map(c => {
            const label = <>{c.source}{c.as_of ? <span className="psp-cite-asof"> · {whenEt(c.as_of)}</span> : null}</>
            return c.url
              ? <a key={c.id} className="psp-cite" href={c.url} target="_blank" rel="noopener noreferrer" data-testid="prospectus-cite"><b>{c.id}</b> {label}</a>
              : <span key={c.id} className="psp-cite" data-testid="prospectus-cite"><b>{c.id}</b> {label}</span>
          })}
        </div>
      )}
    </>
  )
}

function SectionBlock({ s, phone }: { s: ProspectusSection; phone: boolean }) {
  const tone = SECTION_TONE[s.id] || 'neutral'
  if (phone) {
    return (
      <details className={`psp-section psp-details psp-accent-${tone}`} data-testid="prospectus-section" data-section={s.id}>
        <summary className={`psp-summary psp-tone-${tone}`}>{s.title}</summary>
        <SectionBody s={s} />
      </details>
    )
  }
  return (
    <article className={`psp-section psp-accent-${tone}`} data-testid="prospectus-section" data-section={s.id} aria-labelledby={`psp-s-${s.id}`}>
      <h2 id={`psp-s-${s.id}`} className={`psp-section-title psp-tone-${tone}`}>{s.title}</h2>
      <SectionBody s={s} />
    </article>
  )
}

type DetailFetch = { doc: ProspectusDoc | null; status: number | null; loading: boolean; error: string | null }

function useDetail(symbol: string, version: string | null, nonce: number): DetailFetch {
  const [st, setSt] = useState<DetailFetch>({ doc: null, status: null, loading: true, error: null })
  useEffect(() => {
    if (!symbol) return
    const ctl = new AbortController()
    setSt(s => ({ doc: s.doc && s.doc.symbol === symbol ? s.doc : null, status: null, loading: true, error: null }))
    fetch(detailPath(symbol, version), { signal: ctl.signal, credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(async r => {
        const j = await r.json().catch(() => null)
        if (!r.ok) { setSt({ doc: j ? unwrap<ProspectusDoc>(j, 'symbol') : null, status: r.status, loading: false, error: `HTTP ${r.status}` }); return }
        setSt({ doc: unwrap<ProspectusDoc>(j, 'symbol'), status: r.status, loading: false, error: null })
      })
      .catch(e => { if (!ctl.signal.aborted) setSt({ doc: null, status: null, loading: false, error: String(e?.message || e) }) })
    return () => ctl.abort()
  }, [symbol, version, nonce])
  return st
}

function RewriteButton({ symbol, onQueued, big }: { symbol: string; onQueued: () => void; big?: boolean }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const go = async () => {
    setConfirming(false); setBusy(true); setMsg(null)
    try {
      const r = await fetch(refreshPath(symbol), { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const j = await r.json().catch(() => ({}))
      const d = j?.data ?? j
      if (!r.ok || d?.ok === false) throw new Error(d?.error || d?.reason || `HTTP ${r.status}`)
      setMsg({ ok: true, text: d?.message || `Rewrite queued${d?.position != null ? ` · #${d.position} in line` : ''}` })
      onQueued()
    } catch (e: any) {
      setMsg({ ok: false, text: `Not queued: ${String(e?.message || e).slice(0, 120)}` })
    } finally { setBusy(false) }
  }
  return (
    <>
      <button type="button" className={`psp-btn psp-btn-rewrite${big ? ' psp-btn-rewrite-big' : ''}`} data-testid="prospectus-rewrite" disabled={busy} onClick={() => setConfirming(true)} aria-haspopup="dialog">
        {busy ? 'Queuing…' : 'Rewrite now'}
      </button>
      {msg && <span className={`psp-msg psp-tone-${msg.ok ? 'success' : 'danger'}`} data-testid="prospectus-rewrite-msg" role="status">{msg.text}</span>}
      {confirming && createPortal(
        <div className="psp-confirm-backdrop" onClick={e => { if (e.target === e.currentTarget) setConfirming(false) }}>
          <section role="alertdialog" aria-modal="true" aria-labelledby="psp-confirm-title" className="psp-confirm" data-testid="prospectus-rewrite-confirm">
            <h2 id="psp-confirm-title">Rewrite the {symbol} prospectus now?</h2>
            <p>This queues a fresh model run paid from the Anthropic credit. The current version stays available until the new one is ready.</p>
            <div className="psp-confirm-actions">
              <button type="button" className="psp-btn" onClick={() => setConfirming(false)} data-testid="prospectus-rewrite-cancel" autoFocus>Cancel</button>
              <button type="button" className="psp-btn psp-btn-rewrite" onClick={go} data-testid="prospectus-rewrite-confirm-go">Queue rewrite</button>
            </div>
          </section>
        </div>, document.body)}
    </>
  )
}

function VersionPicker({ doc, current, onPick }: { doc: ProspectusDoc | null; current: string | null; onPick: (v: string) => void }) {
  const versions = doc?.versions ?? []
  if (!versions.length) return null
  const n = versions.length
  return (
    <label className="psp-version">
      <span className="psp-muted">Version</span>
      <select value={current ?? ''} onChange={e => onPick(e.target.value)} data-testid="prospectus-version">
        {versions.map((v, i) => <option key={v.version} value={v.version}>v{n - i} · {whenEt(v.generated_at) !== '—' ? whenEt(v.generated_at) : v.version} · {modelLabel(v.model).label}</option>)}
      </select>
    </label>
  )
}

function Report({ symbol, row, viewerOperator, onBack, phone, listSearch }: { symbol: string; row: ProspectusIndexItem | null; viewerOperator: boolean; onBack: () => void; phone: boolean; listSearch: string }) {
  const [sp, setSp] = useSearchParams()
  const version = sp.get('version')
  const [nonce, setNonce] = useState(0)
  const { doc, status, loading, error } = useDetail(symbol, version, nonce)
  const state = detailState({ loading, httpStatus: status, error, doc, row })
  const scope = doc?.scope ?? row?.scope
  const sections = orderedSections(doc?.sections, scope)
  const summary = sections.find(s => s.id === SUMMARY_SECTION)
  const narrative = sections.filter(s => s.id !== SUMMARY_SECTION)
  const versions = doc?.versions ?? []
  const currentVersion = version || doc?.version || versions[0]?.version || null
  const stale = doc?.stale ?? row?.stale ?? false
  const hasReport = state === 'ready' || state === 'partial'
  const isOperator = viewerOperator || doc?.viewer?.operator === true
  const name = doc?.name || row?.name || ''
  const blocks = doc?.blocks
  const price = toNumber((doc?.facts ?? []).find(f => /^Last close/i.test(f.label))?.value)
  const backRef = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (phone) backRef.current?.focus() }, [phone, symbol])
  const vIndex = versions.findIndex(v => v.version === currentVersion)
  const vLabel = vIndex >= 0 ? `v${versions.length - vIndex}` : null

  const pickVersion = (v: string) => {
    const n = new URLSearchParams(sp)
    if (!v || v === versions[0]?.version) n.delete('version'); else n.set('version', v)
    setSp(n, { replace: true })
  }
  const dl = hasReport && (
    <>
      <a className="psp-btn psp-btn-pdf" href={filePath(symbol, 'pdf', version)} data-testid="prospectus-dl-pdf" download aria-label={`Download ${symbol} PDF`}>{phone ? 'PDF' : 'Download PDF'}</a>
      <a className="psp-btn psp-btn-docx" href={filePath(symbol, 'docx', version)} data-testid="prospectus-dl-docx" download aria-label={`Download ${symbol} Word`}>{phone ? 'Word' : 'Download Word'}</a>
      <a className="psp-btn psp-btn-html" href={filePath(symbol, 'html', version)} data-testid="prospectus-open-html" target="_blank" rel="noopener noreferrer" aria-label={`Open ${symbol} HTML`}>{phone ? 'HTML' : 'Open HTML'}</a>
    </>
  )
  const model = doc?.model ?? row?.model
  const written = doc?.generated_at ?? row?.generated_at
  const nextDue = doc?.next_due ?? row?.next_due

  const header = phone ? (
    <header className="psp-report-head psp-report-head-phone">
      <div className="psp-phone-top">
        <button ref={backRef} type="button" className="psp-back-link" onClick={onBack} data-testid="prospectus-back" aria-label="Back to the list">← Back</button>
        <VersionPicker doc={doc} current={currentVersion} onPick={pickVersion} />
      </div>
      <h1 id="psp-report-title" className="psp-report-sym">{symbol}</h1>
      <div className="psp-report-name">{name}</div>
      <div className="psp-report-meta">
        <TypeChip scope={scope} />
        <ModelChip model={model} long />
        {nextDue && <span className="psp-chip psp-tone-neutral">Next: {whenEt(nextDue)}</span>}
        {state !== 'loading' && <StatusChip it={{ status: doc?.status ?? row?.status ?? (hasReport ? 'ready' : 'missing'), stale }} testId="prospectus-detail-status" />}
        {stale && <span data-testid="prospectus-detail-stale" hidden>stale</span>}
      </div>
      {dl && <div className="psp-dl3" data-testid="prospectus-actions">{dl}</div>}
    </header>
  ) : (
    <>
      <Link to={{ pathname: pageRoute(), search: listSearch }} className="psp-back-link" data-testid="prospectus-back">← All prospectuses</Link>
      <header className="psp-report-head">
        <div className="psp-report-id">
          <div className="psp-report-titlebar"><h1 id="psp-report-title" className="psp-report-sym">{symbol}</h1><span className="psp-report-name">{name}</span></div>
          <div className="psp-report-meta">
            <span className="psp-meta-pill">{scope === 'holding' ? 'Holding' : 'Watch'}</span>
            {modelLabel(model).tier !== 'none' && <span className="psp-meta-pill psp-meta-model" data-testid="prospectus-model">Written by <ModelChip model={model} long /></span>}
            {written && <span className="psp-meta-pill">{whenEt(written)}{vLabel ? ` · ${vLabel}` : ''}</span>}
            {nextDue && <span className="psp-meta-pill">Next rewrite {whenEt(nextDue)} or on earnings</span>}
            {state !== 'loading' && <StatusChip it={{ status: doc?.status ?? row?.status ?? (hasReport ? 'ready' : 'missing'), stale }} testId="prospectus-detail-status" />}
            {stale && <span data-testid="prospectus-detail-stale" hidden>stale</span>}
          </div>
        </div>
        <div className="psp-actions" data-testid="prospectus-actions">
          {dl}
          <VersionPicker doc={doc} current={currentVersion} onPick={pickVersion} />
          {isOperator && <RewriteButton symbol={symbol} onQueued={() => setNonce(n => n + 1)} />}
        </div>
      </header>
    </>
  )

  const cites = allCitations(sections)
  return (
    <article className={`psp-report${phone ? ' psp-report-phone' : ''}`} data-testid="prospectus-report" data-state={state} aria-labelledby="psp-report-title">
      {header}
      {state === 'partial' && (
        <div className="psp-banner psp-tone-warning psp-bg-soft-warning" data-testid="prospectus-partial-banner" role="note">
          Partial: {(doc?.partial_gaps ?? doc?.source_coverage?.key_gaps ?? []).join('; ') || 'a key source was missing'}.
        </div>
      )}
      {stale && hasReport && (
        <div className="psp-banner psp-tone-warning psp-bg-soft-warning" data-testid="prospectus-stale-banner" role="note">
          Needs rewrite: a rewrite is due{nextDue ? ` (${whenEt(nextDue)})` : ''}. This is the last good version.
        </div>
      )}
      {state === 'loading' && <div className="psp-skeleton" data-testid="prospectus-loading" aria-busy="true"><div /><div /><div /></div>}
      {state === 'missing' && (
        <div className="psp-empty" data-testid="prospectus-missing">
          <b>Not written yet — queued.</b>
          <span>{nextDue ? `Expected around ${whenEt(nextDue)}.` : 'It will be written in the next pass; holdings go first.'}</span>
        </div>
      )}
      {(state === 'queued' || state === 'running') && (
        <div className="psp-empty" data-testid={`prospectus-${state}`}>
          <b>{state === 'running' ? 'Being written now.' : 'Queued for writing.'}</b>
          <span>{state === 'queued' && nextDue ? `Expected around ${whenEt(nextDue)}.` : 'Check back shortly.'}</span>
        </div>
      )}
      {state === 'failed' && (
        <div className="psp-empty psp-tone-danger psp-bg-soft-danger" data-testid="prospectus-failed" role="alert">
          <b>The last run failed.</b>
          <span>{doc?.failure_reason || row?.failure_reason || 'No reason was recorded.'}</span>
        </div>
      )}
      {state === 'error' && (
        <div className="psp-empty psp-tone-danger" data-testid="prospectus-error" role="alert">
          <b>Could not load the prospectus.</b><span>{error}</span>
          <button type="button" className="psp-btn" onClick={() => setNonce(n => n + 1)}>Retry</button>
        </div>
      )}
      {hasReport && doc && (
        <>
          <VerdictTiles doc={doc} />
          <section className="psp-card psp-summary-card" data-testid="prospectus-summary" aria-label="Summary">
            <h2 className="psp-card-title">Summary</h2>
            {(doc.verdict_line || row?.verdict_line) && <p className="psp-verdict-banner" data-testid="prospectus-verdict-banner">{doc.verdict_line || row?.verdict_line}</p>}
            {summary ? <SectionBody s={summary} /> : null}
          </section>
          {!phone && <ProspectusCharts charts={doc.charts ?? []} symbol={symbol} />}
          <RelativePerformanceBlock blocks={blocks} symbol={symbol} phone={phone} />
          <PeerComparisonBlock blocks={blocks} phone={phone} />
          {phone ? (
            <>
              <ScenariosBlock blocks={blocks} price={price} />
              <MacroBlock blocks={blocks} />
              <FilingsBlock blocks={blocks} />
              <EstimatesBlock blocks={blocks} withCall />
              <OptionsBlock blocks={blocks} withOwnership />
              <RiskBlock blocks={blocks} phone />
              {(doc.charts ?? []).length > 0 && (
                <details className="psp-section psp-details psp-accent-info" data-testid="prospectus-charts-details">
                  <summary className="psp-summary psp-tone-info">Charts</summary>
                  <ProspectusCharts charts={doc.charts ?? []} symbol={symbol} />
                </details>
              )}
              <div className="psp-sections">{narrative.map(s => <SectionBlock key={s.id} s={s} phone />)}</div>
              <CoverageBlock doc={doc} />
              {isOperator && <div className="psp-rewrite-row"><RewriteButton symbol={symbol} onQueued={() => setNonce(n => n + 1)} big /></div>}
            </>
          ) : (
            <>
              <div className="psp-grid3">
                <EstimatesBlock blocks={blocks} />
                <OwnershipBlock blocks={blocks} />
                <RiskBlock blocks={blocks} />
              </div>
              <ScenariosBlock blocks={blocks} price={price} />
              <div className="psp-sections psp-grid2">{narrative.map(s => <SectionBlock key={s.id} s={s} phone={false} />)}</div>
              <div className="psp-grid2">
                <MacroBlock blocks={blocks} />
                <FilingsBlock blocks={blocks} />
                <CallBlock blocks={blocks} />
                <OptionsBlock blocks={blocks} />
              </div>
              <CoverageBlock doc={doc} />
              {cites.length > 0 && (
                <section className="psp-card" aria-label="Sources" data-testid="prospectus-sources">
                  <h2 className="psp-card-title">Sources</h2>
                  <ol className="psp-sources">
                    {cites.map(c => (
                      <li key={c.id} id={`cite-${c.id}`}><b>{c.id}</b> {c.url ? <a className="psp-link" href={c.url} target="_blank" rel="noopener noreferrer">{c.source}</a> : c.source}{c.as_of ? <span className="psp-muted"> · {whenEt(c.as_of)}</span> : null}</li>
                    ))}
                  </ol>
                </section>
              )}
            </>
          )}
        </>
      )}
    </article>
  )
}

function PhoneSheet({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const main = document.querySelector('.app-shell') as HTMLElement | null
    if (main) main.inert = true
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => { document.body.style.overflow = prev; if (main) main.inert = false; window.removeEventListener('keydown', onKey) }
  }, [onClose])
  return createPortal(
    <div className="psp-sheet cc-terminal-ui" role="dialog" aria-modal="true" aria-labelledby="psp-report-title" data-testid="prospectus-sheet">{children}</div>,
    document.body)
}

// ── Page ────────────────────────────────────────────────────────────────────────────────────────────────────────

export default function ProspectusPage() {
  const params = useParams()
  const symbol = params.symbol ? normSymbol(params.symbol) : ''
  const [sp, setSp] = useSearchParams()
  const navigate = useNavigate()
  const phone = usePhone()
  const scope = (['holdings', 'watch', 'all', 'rewrite'].includes(sp.get('scope') || '') ? sp.get('scope') : 'all') as ScopeFilter
  const q = sp.get('q') || ''
  const { data, loading, error, refetch } = useApi<any>(indexPath(), 60_000)
  const idx = useMemo(() => unwrap<ProspectusIndex>(data, 'items'), [data])
  const items = idx?.items ?? []
  const shown = useMemo(() => filterItems(items, scope, q), [items, scope, q])
  const counts = scopeCounts(items)
  const row = items.find(i => normSymbol(i.symbol) === symbol) ?? null
  const viewerOperator = idx?.viewer?.operator === true

  const setParam = (k: string, v: string | null) => {
    const n = new URLSearchParams(sp)
    if (v) n.set(k, v); else n.delete(k)
    n.delete('version')
    setSp(n, { replace: true })
  }
  const listSearch = (() => { const n = new URLSearchParams(sp); n.delete('version'); const s = n.toString(); return s ? `?${s}` : '' })()
  const back = useCallback(() => navigate({ pathname: pageRoute(), search: listSearch }), [navigate, listSearch])

  const list = (
    <section className="psp-list-pane" aria-label="Prospectus list">
      <header className="psp-head">
        <div className="psp-head-text">
          <h1 className="psp-title">Prospectus</h1>
          {!phone && <p className="psp-sub">A full, sourced report on every ticker you hold or watch. Holdings rewritten monthly and after earnings; Watch quarterly; big news or an 8% move rewrites at once.</p>}
        </div>
        <StatTiles idx={idx} phone={phone} />
      </header>
      <div className="psp-controls">
        <div className="psp-filters" role="group" aria-label="Which tickers">
          {SCOPES.map(s => (
            <button key={s.id} type="button" className={`psp-filter${scope === s.id ? ' psp-filter-on' : ''}`} aria-pressed={scope === s.id}
              data-testid={`prospectus-filter-${s.id}`} onClick={() => setParam('scope', s.id === 'all' ? null : s.id)}>
              {phone ? (s.phoneLabel ?? s.label) : s.label}{!phone && <span className="psp-count"> {counts[s.id]}</span>}
            </button>
          ))}
        </div>
        <label className="psp-search-label">{!phone && <span>Search</span>}
          <input type="search" className="psp-search" placeholder="Ticker or company" aria-label="Search prospectuses"
            value={q} onChange={e => setParam('q', e.target.value || null)} data-testid="prospectus-search" />
        </label>
      </div>
      {loading && !idx && <div className="psp-skeleton" data-testid="prospectus-list-loading" aria-busy="true"><div /><div /><div /></div>}
      {error && !idx && (
        <div className="psp-empty psp-tone-danger" role="alert" data-testid="prospectus-list-error">
          <b>Could not load the prospectus list.</b><span>{String(error)}</span>
          <button type="button" className="psp-btn" onClick={refetch}>Retry</button>
        </div>
      )}
      {idx && shown.length === 0 && <div className="psp-empty" data-testid="prospectus-list-empty"><b>No tickers match.</b><span>Try All, or clear the search.</span></div>}
      {shown.length > 0 && (phone ? <PhoneCards rows={shown} linkSearch={listSearch} /> : <DesktopTable rows={shown} linkSearch={listSearch} />)}
    </section>
  )

  if (phone) {
    return (
      <div className="psp-page psp-phone" data-testid="prospectus-page">
        {list}
        {symbol && <PhoneSheet onClose={back}><Report key={symbol} symbol={symbol} row={row} viewerOperator={viewerOperator} onBack={back} phone listSearch={listSearch} /></PhoneSheet>}
      </div>
    )
  }
  return (
    <div className="psp-page psp-desktop" data-testid="prospectus-page">
      {symbol
        ? <Report key={symbol} symbol={symbol} row={row} viewerOperator={viewerOperator} onBack={back} phone={false} listSearch={listSearch} />
        : list}
    </div>
  )
}
