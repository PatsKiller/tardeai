/** Ticker Prospectus (operator 2026-10-26: "fully colored with graphs and everything. PDFs and Word documents besides
 *  the HTML version"). One prospectus per holding and Watch ticker, versioned.
 *    /v3/prospectus          list: Holdings / Watch / All, status, stale, model, date, verdict, search, budget strip
 *    /v3/prospectus/:symbol  report: colored sections + citation pills, charts, version picker, downloads,
 *                            operator-only "Rewrite now". Phone (≤820): a full-screen sheet with ← Back.
 *  Read-only except POST /refresh, which the server accepts from the tailnet operator identity only; the button renders
 *  only when the server says this viewer is the operator (viewer.operator === true). Contract: handoffs/prospectus-20261026. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { inlineMarkdown } from '../components/PolicyRuleParts'
import ProspectusCharts from '../components/prospectus/ProspectusCharts'
import {
  SECTION_TONE, STATUS_LABEL, STATUS_TONE, budgetView, detailPath, detailState, filePath, filterItems, indexPath, mdBlocks,
  modelLabel, normSymbol, orderedSections, pageRoute, refreshPath, scopeCounts, splitCitations, statusOf, totals, whenEt,
  type ProspectusDoc, type ProspectusIndex, type ProspectusIndexItem, type ProspectusSection, type ScopeFilter,
} from '../lib/prospectusModel'
import './Prospectus.css'

const SCOPES: { id: ScopeFilter; label: string }[] = [{ id: 'holdings', label: 'Holdings' }, { id: 'watch', label: 'Watch' }, { id: 'all', label: 'All' }]

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

function ModelChip({ model }: { model?: string | null }) {
  const m = modelLabel(model)
  if (m.tier === 'none') return null
  return <span className={`psp-chip psp-model psp-model-${m.tier}`} data-testid="prospectus-model" title={String(model)}>{m.label}</span>
}

// ── List ────────────────────────────────────────────────────────────────────────────────────────────────────────

function HeaderStrip({ idx }: { idx: ProspectusIndex | null }) {
  const t = totals(idx)
  const b = budgetView(idx?.budget)
  return (
    <div className="psp-strip" data-testid="prospectus-strip">
      <div className="psp-totals">
        {(['ready', 'queued', 'running', 'failed', 'missing'] as const).map(s => (
          <span key={s} className={`psp-total psp-tone-${STATUS_TONE[s]}`} data-testid={`prospectus-total-${s}`}>
            <b>{t[s]}</b> {STATUS_LABEL[s]}
          </span>
        ))}
      </div>
      <div className="psp-budget" data-testid="prospectus-budget" title="Anthropic credit for prospectus writing">
        <span className="psp-budget-k">Credit left</span> <b className="psp-num">{b.remaining}</b>
        <span className="psp-budget-sep">·</span>
        <span className="psp-budget-k">Today</span> <b className="psp-num" data-testid="prospectus-budget-today">{b.used} / {b.cap}</b>
        {b.fill != null && (
          <span className="psp-meter" aria-hidden="true"><span className={`psp-meter-fill psp-bg-${b.tone}`} style={{ width: `${Math.round(b.fill * 100)}%` }} /></span>
        )}
      </div>
    </div>
  )
}

function Row({ it, active, linkSearch }: { it: ProspectusIndexItem; active: boolean; linkSearch: string }) {
  const st = statusOf(it.status)
  return (
    <li>
      <Link to={{ pathname: pageRoute(it.symbol), search: linkSearch }} className={`psp-row${active ? ' psp-row-active' : ''}`}
        data-testid="prospectus-row" data-symbol={it.symbol} data-status={st} aria-current={active ? 'true' : undefined}>
        <div className="psp-row-top">
          <span className="psp-sym">{it.symbol}</span>
          <span className="psp-name">{it.name || ''}</span>
          <span className="psp-row-chips">
            <Chip tone={STATUS_TONE[st]} testId="prospectus-status">{STATUS_LABEL[st]}</Chip>
            {it.stale && <Chip tone="warning" testId="prospectus-stale" title={it.next_due ? `Rewrite was due ${whenEt(it.next_due)}` : 'Rewrite due'}>Stale</Chip>}
            <ModelChip model={it.model} />
          </span>
        </div>
        <div className="psp-row-bottom">
          <span className="psp-verdict" data-testid="prospectus-verdict">
            {st === 'failed' ? (it.failure_reason || 'Last run failed') : it.verdict_line || (st === 'missing' ? 'Not written yet — queued' : st === 'queued' ? 'Queued for writing' : st === 'running' ? 'Being written now' : '')}
          </span>
          <span className="psp-date">{it.generated_at ? whenEt(it.generated_at) : it.scope === 'holding' ? 'Holding' : 'Watch'}</span>
        </div>
      </Link>
    </li>
  )
}

// ── Report ──────────────────────────────────────────────────────────────────────────────────────────────────────

function MdText({ text, ids }: { text: string; ids: Set<string> }) {
  return <>{splitCitations(text, ids).map((p, i) => 'cite' in p
    ? <a key={i} href={`#cite-${p.cite}`} className="psp-cite-inline" data-testid="prospectus-cite-inline">{p.cite}</a>
    : <span key={i}>{inlineMarkdown(p.text, `t${i}`)}</span>)}</>
}

function SectionBlock({ s }: { s: ProspectusSection }) {
  const tone = SECTION_TONE[s.id] || 'neutral'
  const cites = s.citations ?? []
  const ids = new Set(cites.map(c => c.id))
  const blocks = mdBlocks(s.body_md)
  const items: React.ReactNode[] = []
  let list: { ordered: boolean; nodes: React.ReactNode[] } | null = null
  const flush = () => { if (list) { items.push(list.ordered ? <ol key={`l${items.length}`}>{list.nodes}</ol> : <ul key={`l${items.length}`}>{list.nodes}</ul>); list = null } }
  blocks.forEach((b, i) => {
    if (b.kind === 'li' || b.kind === 'oli') {
      const ordered = b.kind === 'oli'
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, nodes: [] } }
      list.nodes.push(<li key={i}><MdText text={b.text} ids={ids} /></li>)
      return
    }
    flush()
    if (b.kind === 'h') items.push(<h4 key={i} className="psp-h"><MdText text={b.text} ids={ids} /></h4>)
    else items.push(<p key={i}><MdText text={b.text} ids={ids} /></p>)
  })
  flush()
  return (
    <section className={`psp-section psp-accent-${tone}`} data-testid="prospectus-section" data-section={s.id} aria-labelledby={`psp-s-${s.id}`}>
      <h3 id={`psp-s-${s.id}`} className={`psp-section-title psp-tone-${tone}`}>{s.title}</h3>
      <div className="psp-body">{items}</div>
      {cites.length > 0 && (
        <div className="psp-cites" data-testid="prospectus-citations">
          {cites.map(c => {
            const label = <>{c.source}{c.as_of ? <span className="psp-cite-asof"> · {whenEt(c.as_of)}</span> : null}</>
            return c.url
              ? <a key={c.id} id={`cite-${c.id}`} className="psp-cite" href={c.url} target="_blank" rel="noopener noreferrer" data-testid="prospectus-cite"><b>{c.id}</b> {label}</a>
              : <span key={c.id} id={`cite-${c.id}`} className="psp-cite" data-testid="prospectus-cite"><b>{c.id}</b> {label}</span>
          })}
        </div>
      )}
    </section>
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

function RewriteButton({ symbol, onQueued }: { symbol: string; onQueued: () => void }) {
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
      <button type="button" className="psp-btn psp-btn-rewrite" data-testid="prospectus-rewrite" disabled={busy} onClick={() => setConfirming(true)} aria-haspopup="dialog">
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

function Report({ symbol, row, viewerOperator, onBack, phone }: { symbol: string; row: ProspectusIndexItem | null; viewerOperator: boolean; onBack: () => void; phone: boolean }) {
  const [sp, setSp] = useSearchParams()
  const version = sp.get('version')
  const [nonce, setNonce] = useState(0)
  const { doc, status, loading, error } = useDetail(symbol, version, nonce)
  const state = detailState({ loading, httpStatus: status, error, doc, row })
  const scope = doc?.scope ?? row?.scope
  const sections = orderedSections(doc?.sections, scope)
  const versions = doc?.versions ?? []
  const currentVersion = version || doc?.version || versions[0]?.version || null
  const stale = doc?.stale ?? row?.stale ?? false
  const canDownload = state === 'ready'
  const isOperator = viewerOperator || doc?.viewer?.operator === true
  const name = doc?.name || row?.name || ''
  const backRef = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (phone) backRef.current?.focus() }, [phone, symbol])

  const pickVersion = (v: string) => {
    const n = new URLSearchParams(sp)
    if (!v || v === versions[0]?.version) n.delete('version'); else n.set('version', v)
    setSp(n, { replace: true })
  }

  return (
    <article className="psp-report" data-testid="prospectus-report" data-state={state} aria-labelledby="psp-report-title">
      <header className="psp-report-head">
        <div className="psp-report-titlebar">
          <button ref={backRef} type="button" className="psp-btn psp-back" onClick={onBack} data-testid="prospectus-back" aria-label={phone ? 'Back to the list' : 'Close the report'}>
            {phone ? '← Back' : '✕ Close'}
          </button>
          <h2 id="psp-report-title" className="psp-report-title"><span className="psp-sym">{symbol}</span> <span className="psp-name">{name}</span></h2>
        </div>
        <div className="psp-report-meta">
          <ModelChip model={doc?.model ?? row?.model} />
          {state !== 'loading' && <Chip tone={STATUS_TONE[statusOf(doc?.status ?? row?.status ?? (state === 'ready' ? 'ready' : 'missing'))]} testId="prospectus-detail-status">{STATUS_LABEL[statusOf(doc?.status ?? row?.status ?? (state === 'ready' ? 'ready' : 'missing'))]}</Chip>}
          {stale && <Chip tone="warning" testId="prospectus-detail-stale">Stale</Chip>}
          {(doc?.generated_at || row?.generated_at) && <span className="psp-muted">Written {whenEt(doc?.generated_at ?? row?.generated_at)}</span>}
          {versions.length > 0 && (
            <label className="psp-version">
              <span className="psp-muted">Version</span>
              <select value={currentVersion ?? ''} onChange={e => pickVersion(e.target.value)} data-testid="prospectus-version">
                {versions.map(v => <option key={v.version} value={v.version}>{whenEt(v.generated_at) !== '—' ? whenEt(v.generated_at) : v.version} · {modelLabel(v.model).label}</option>)}
              </select>
            </label>
          )}
        </div>
        <div className="psp-actions" data-testid="prospectus-actions">
          {canDownload && <>
            <a className="psp-btn psp-btn-pdf" href={filePath(symbol, 'pdf', version)} data-testid="prospectus-dl-pdf" download>Download PDF</a>
            <a className="psp-btn psp-btn-docx" href={filePath(symbol, 'docx', version)} data-testid="prospectus-dl-docx" download>Download Word</a>
            <a className="psp-btn psp-btn-html" href={filePath(symbol, 'html', version)} data-testid="prospectus-open-html" target="_blank" rel="noopener noreferrer">Open HTML</a>
          </>}
          {isOperator && <RewriteButton symbol={symbol} onQueued={() => setNonce(n => n + 1)} />}
        </div>
      </header>

      {stale && state === 'ready' && (
        <div className="psp-banner psp-tone-warning psp-bg-soft-warning" data-testid="prospectus-stale-banner" role="note">
          Stale: a rewrite is due{row?.next_due ? ` (${whenEt(row.next_due)})` : ''}. This is the last good version.
        </div>
      )}
      {state === 'loading' && <div className="psp-skeleton" data-testid="prospectus-loading" aria-busy="true"><div /><div /><div /></div>}
      {state === 'missing' && (
        <div className="psp-empty" data-testid="prospectus-missing">
          <b>Not written yet — queued.</b>
          <span>{row?.next_due ? `Expected around ${whenEt(row.next_due)}.` : 'It will be written in the next pass; holdings go first.'}</span>
        </div>
      )}
      {(state === 'queued' || state === 'running') && (
        <div className="psp-empty" data-testid={`prospectus-${state}`}>
          <b>{state === 'running' ? 'Being written now.' : 'Queued for writing.'}</b>
          <span>{state === 'queued' && row?.next_due ? `Expected around ${whenEt(row.next_due)}.` : 'Check back shortly.'}</span>
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
      {state === 'ready' && (
        <>
          {(doc?.verdict_line || row?.verdict_line) && <p className="psp-verdict-banner" data-testid="prospectus-verdict-banner">{doc?.verdict_line || row?.verdict_line}</p>}
          <ProspectusCharts charts={doc?.charts ?? []} />
          <div className="psp-sections">{sections.map(s => <SectionBlock key={s.id} s={s} />)}</div>
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
  const scope = (['holdings', 'watch', 'all'].includes(sp.get('scope') || '') ? sp.get('scope') : 'all') as ScopeFilter
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
        <h1 className="psp-title">Prospectus</h1>
        <p className="psp-sub">A written research prospectus for every holding and Watch ticker, versioned. Tap a row to read it.</p>
      </header>
      <HeaderStrip idx={idx} />
      <div className="psp-controls">
        <div className="psp-filters" role="group" aria-label="Which tickers">
          {SCOPES.map(s => (
            <button key={s.id} type="button" className={`psp-filter${scope === s.id ? ' psp-filter-on' : ''}`} aria-pressed={scope === s.id}
              data-testid={`prospectus-filter-${s.id}`} onClick={() => setParam('scope', s.id === 'all' ? null : s.id)}>
              {s.label} <span className="psp-count">{counts[s.id]}</span>
            </button>
          ))}
        </div>
        <input type="search" className="psp-search" placeholder="Search ticker, name or verdict" aria-label="Search prospectuses"
          value={q} onChange={e => setParam('q', e.target.value || null)} data-testid="prospectus-search" />
      </div>
      {loading && !idx && <div className="psp-skeleton" data-testid="prospectus-list-loading" aria-busy="true"><div /><div /><div /></div>}
      {error && !idx && (
        <div className="psp-empty psp-tone-danger" role="alert" data-testid="prospectus-list-error">
          <b>Could not load the prospectus list.</b><span>{String(error)}</span>
          <button type="button" className="psp-btn" onClick={refetch}>Retry</button>
        </div>
      )}
      {idx && shown.length === 0 && <div className="psp-empty" data-testid="prospectus-list-empty"><b>No tickers match.</b><span>Try All, or clear the search.</span></div>}
      {shown.length > 0 && (
        <ul className="psp-list" data-testid="prospectus-list">
          {shown.map(it => <Row key={it.symbol} it={it} active={normSymbol(it.symbol) === symbol} linkSearch={listSearch} />)}
        </ul>
      )}
    </section>
  )

  const report = symbol ? <Report key={symbol} symbol={symbol} row={row} viewerOperator={viewerOperator} onBack={back} phone={phone} /> : null

  if (phone) {
    return (
      <div className="psp-page psp-phone" data-testid="prospectus-page">
        {list}
        {report && <PhoneSheet onClose={back}>{report}</PhoneSheet>}
      </div>
    )
  }
  return (
    <div className={`psp-page psp-desktop${symbol ? ' psp-has-detail' : ''}`} data-testid="prospectus-page">
      {list}
      {report
        ? <div className="psp-detail-pane">{report}</div>
        : <aside className="psp-detail-pane psp-detail-empty" aria-label="No ticker selected"><p className="psp-muted">Pick a ticker to read its prospectus.</p></aside>}
    </div>
  )
}
