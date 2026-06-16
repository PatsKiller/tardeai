import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'

// v3 Reports — a NEWS READER for everything sent to the operator (Telegram / email / SIEM): morning
// briefs, digests, alerts, advisories, recovery, dividends, regime, paper, system. Tabbed; each item is
// a fully readable, formatted article (Telegram markdown rendered) — scroll and read, not a dump.
// Source: /api/v2/reports/* (read-only). Search · date filter · pagination · purge.

interface Props { onDrill: (ctx: DrillContext) => void }

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }
const SEV: Record<string, string> = { critical: '#dc2626', urgent: '#ef4444', warning: '#f59e0b', info: '#60a5fa' }
const sevColor = (s?: string) => SEV[(s || 'info').toLowerCase()] || '#60a5fa'
const fmtDate = (s?: string) => {
  if (!s) return '—'
  const d = new Date(s)
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) + ' · ' +
    d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

const FQDN = 'https://ms01-openclaw.tail163d14.ts.net'
const VALID = new Set(['portfolio', 'risk', 'trading', 'strategy', 'agents', 'intelligence', 'hermes', 'retirement', 'journal', 'watchlist', 'watchpool', 'sectors', 'reports', 'system', 'manual-execution'])
// every legacy/brief page slug → a REAL v3 route + friendly label (no dead links)
const PAGE: Record<string, { label: string; route: string }> = {
  risk: { label: 'Risk', route: '/v3/risk' }, approvals: { label: 'Approvals', route: '/v3/trading' },
  recovery: { label: 'Recovery', route: '/v3/risk' }, reco: { label: 'Recovery', route: '/v3/risk' },   // Recovery Watch lives in the Risk hub
  actions: { label: 'Actions', route: '/v3/' }, trading: { label: 'Trading', route: '/v3/trading' },     // Action Inbox is on Home
  journal: { label: 'Journal', route: '/v3/journal' }, system: { label: 'System', route: '/v3/system' },
  portfolio: { label: 'Portfolio', route: '/v3/portfolio' }, 'research-topics': { label: 'Research', route: '/v3/intelligence' },
  research: { label: 'Research', route: '/v3/intelligence' }, proposals: { label: 'Proposals', route: '/v3/trading' },
  'paper-proposals': { label: 'Proposals', route: '/v3/trading' }, 'paper-status': { label: 'Trading', route: '/v3/trading' },
  alerts: { label: 'System', route: '/v3/system' }, siem: { label: 'System', route: '/v3/system' },
}
function pageLink(path: string) {
  const seg = (path.split('/')[2] || '').toLowerCase()
  if (PAGE[seg]) return PAGE[seg]
  if (VALID.has(seg)) return { label: seg.charAt(0).toUpperCase() + seg.slice(1), route: `/v3/${seg}` }
  return { label: 'Open', route: '/v3/' }   // unknown slug → home, never a dead /v3/<x>
}

// ── markdown/Telegram → React: **bold** *bold* `code`, dashboard links, urls. NOTE: NO _italic_ rule —
// the data is full of snake_case (reentry_candidate, hold_for_reentry) and underscore-italic ate them. ──
function inline(text: string): ReactNode[] {
  const parts: ReactNode[] = []
  const re = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|https?:\/\/[^\s)]+|\/v[23]\/[a-z0-9-]+)/g
  let last = 0, m: RegExpExecArray | null, key = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    const tok = m[0]
    if (tok.startsWith('**')) parts.push(<b key={key++} style={{ color: 'var(--text0)', fontWeight: 800 }}>{tok.slice(2, -2)}</b>)
    else if (tok.startsWith('*')) parts.push(<b key={key++} style={{ color: 'var(--text0)', fontWeight: 800 }}>{tok.slice(1, -1)}</b>)
    else if (tok.startsWith('`')) parts.push(<code key={key++} style={{ fontFamily: 'monospace', fontSize: '.92em', background: 'var(--bg0)', padding: '1px 5px', borderRadius: 4, color: '#a5d6ff' }}>{tok.slice(1, -1)}</code>)
    else if (tok.startsWith('/v')) { const { label, route } = pageLink(tok); parts.push(<a key={key++} href={FQDN + route} target="_blank" rel="noreferrer" style={{ fontSize: 11, fontWeight: 700, padding: '1px 7px', borderRadius: 4, background: '#60a5fa18', color: '#60a5fa', textDecoration: 'none', whiteSpace: 'nowrap' }}>{label} ↗</a>) }
    else parts.push(<a key={key++} href={tok} target="_blank" rel="noreferrer" style={{ color: '#60a5fa', wordBreak: 'break-all' }}>{tok}</a>)
    last = m.index + tok.length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

function Article({ text }: { text: string }) {
  const lines = (text || '').split('\n')
  return (
    <div style={{ fontSize: 13.5, color: 'var(--text1)', lineHeight: 1.65 }}>
      {lines.map((line, i) => {
        const t = line.trim()
        if (!t) return <div key={i} style={{ height: 9 }} />
        if (/^---+$/.test(t)) return <hr key={i} style={{ border: 'none', borderTop: '1px solid var(--border-subtle)', margin: '12px 0' }} />
        const md = t.match(/^(#{1,4})\s+(.*)$/)                 // markdown header  # / ## / ###
        const tg = /^\*[^*]+\*$/.test(t) || /^[A-Z][A-Z \/&0-9]{3,}:?$/.test(t)   // *SECTION* or ALLCAPS
        if (md || tg) {
          const lvl = md ? md[1].length : 2
          const label = (md ? md[2] : t).replace(/^\*|\*$/g, '').replace(/^#+\s*/, '')
          return <div key={i} style={{ fontSize: lvl <= 1 ? 16 : lvl === 2 ? 12.5 : 11.5, fontWeight: 900, letterSpacing: lvl >= 2 ? .4 : 0, textTransform: lvl >= 2 ? 'uppercase' : 'none', color: lvl <= 1 ? 'var(--text0)' : '#60a5fa', marginTop: i ? 14 : 0, marginBottom: 4 }}>{inline(label)}</div>
        }
        const bul = t.match(/^[•\-▪◦·*]\s+(.*)$/)
        if (bul) return <div key={i} style={{ display: 'flex', gap: 8, paddingLeft: 4, marginBottom: 3 }}><span style={{ color: 'var(--text3)' }}>•</span><span style={{ flex: 1 }}>{inline(bul[1])}</span></div>
        const num = t.match(/^(\d+)\.\s+(.*)$/)
        if (num) return <div key={i} style={{ display: 'flex', gap: 8, paddingLeft: 4, marginBottom: 3 }}><span style={{ color: '#60a5fa', fontWeight: 800 }}>{num[1]}.</span><span style={{ flex: 1 }}>{inline(num[2])}</span></div>
        return <div key={i} style={{ marginBottom: 3 }}>{inline(line)}</div>
      })}
    </div>
  )
}

export default function ReportsHub({ onDrill }: Props) {
  const { data: cats } = useApi<any>('/api/v2/reports/categories', 60_000)
  const categories = cats?.categories || []
  const [active, setActive] = useState<string>('morning_briefs')
  const [qInput, setQInput] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [days, setDays] = useState<number | ''>('')
  const [purge, setPurge] = useState(false)
  const [open, setOpen] = useState<Record<string, boolean>>({})   // collapsed long articles

  useEffect(() => { const t = setTimeout(() => { setQ(qInput); setPage(1) }, 350); return () => clearTimeout(t) }, [qInput])
  useEffect(() => { setPage(1); setOpen({}) }, [active, days, q])

  const listPath = useMemo(() =>
    `/api/v2/reports/list?category=${active}&q=${encodeURIComponent(q)}&page=${page}&per_page=15${days ? `&days=${days}` : ''}`,
    [active, q, page, days])
  const { data: list, loading } = useApi<any>(listPath, 0)
  const items = list?.items || []
  const total = list?.total ?? 0
  const pages = list?.pages ?? 1
  const activeCat = categories.find((c: any) => c.key === active)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 980, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h1 style={{ fontSize: 20, fontWeight: 900, color: 'var(--text0)', margin: 0 }}>Reports</h1>
        <span style={{ fontSize: 12, color: 'var(--text3)' }}>your briefs, alerts & advisories — full, readable, in one place</span>
        <span style={{ flex: 1 }} />
        <button onClick={() => setPurge(true)} style={{ fontSize: 11, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: '1px solid #ef444455', background: '#ef444412', color: '#f87171', cursor: 'pointer' }}>🗑 Purge old…</button>
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {categories.map((c: any) => {
          const on = c.key === active
          return (
            <button key={c.key} onClick={() => setActive(c.key)} style={{
              fontSize: 12, fontWeight: on ? 800 : 600, padding: '7px 12px', borderRadius: 8, cursor: 'pointer',
              border: `1px solid ${on ? '#60a5fa' : 'var(--border)'}`, background: on ? 'rgba(96,165,250,.10)' : 'var(--bg1)',
              color: on ? '#60a5fa' : 'var(--text2)', display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <span>{c.icon}</span>{c.label}
              <span style={{ fontSize: 10, fontWeight: 800, padding: '0 6px', borderRadius: 8, background: on ? '#60a5fa22' : 'var(--bg2)', color: on ? '#60a5fa' : 'var(--text3)' }}>{c.count}</span>
            </button>
          )
        })}
      </div>

      <div style={{ ...card, padding: 10, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', position: 'sticky', top: 0, zIndex: 5 }}>
        <input value={qInput} onChange={e => setQInput(e.target.value)} placeholder={`Search ${activeCat?.label || ''}…`}
          style={{ flex: 1, minWidth: 200, fontSize: 12, padding: '7px 10px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text0)' }} />
        <div style={{ display: 'flex', gap: 4 }}>
          {([['', 'All'], [7, '7d'], [30, '30d'], [90, '90d']] as any).map(([v, l]: any) => (
            <button key={l} onClick={() => setDays(v)} style={{ fontSize: 10, fontWeight: 700, padding: '5px 9px', borderRadius: 5, cursor: 'pointer',
              border: `1px solid ${days === v ? '#60a5fa' : 'var(--border)'}`, background: days === v ? 'rgba(96,165,250,.10)' : 'transparent', color: days === v ? '#60a5fa' : 'var(--text3)' }}>{l}</button>
          ))}
        </div>
        <span style={{ fontSize: 11, color: 'var(--text3)' }}>{total} {activeCat?.label?.toLowerCase()}</span>
      </div>

      {/* Article feed — full readable items */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {loading && items.length === 0 && <div style={{ ...card, padding: 30, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>loading…</div>}
        {!loading && items.length === 0 && <div style={{ ...card, padding: 30, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>no reports here {q ? `matching “${q}”` : ''}</div>}
        {items.map((it: any) => {
          const id = `${it.source}-${it.id}`
          const body = it.summary || ''
          const long = body.length > 1100
          const expanded = open[id]
          // cut the preview at a LINE boundary so a link/word is never truncated mid-token (e.g. "reco")
          const cut = long ? (body.lastIndexOf('\n', 1100) > 400 ? body.lastIndexOf('\n', 1100) : 1100) : body.length
          const shown = long && !expanded ? body.slice(0, cut) : body
          return (
            <article key={id} style={{ ...card, borderTop: `3px solid ${sevColor(it.severity)}`, padding: '16px 20px' }}>
              <header style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: 10, paddingBottom: 10, borderBottom: '1px solid var(--border-subtle)' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 16, fontWeight: 900, color: 'var(--text0)', lineHeight: 1.3 }}>{it.title}</div>
                  <div style={{ fontSize: 10.5, color: 'var(--text3)', marginTop: 4, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <span>{fmtDate(it.created_at)}</span>
                    <span>· {it.channel}</span>
                    <span>· {it.type}</span>
                    {it.symbol && <span style={{ fontWeight: 800, color: '#60a5fa' }}>· {it.symbol}</span>}
                  </div>
                </div>
                <span style={{ fontSize: 9.5, fontWeight: 800, padding: '3px 9px', borderRadius: 5, background: sevColor(it.severity) + '22', color: sevColor(it.severity), textTransform: 'uppercase', whiteSpace: 'nowrap' }}>{it.severity}</span>
              </header>
              <Article text={shown} />
              {long && <button onClick={() => setOpen(o => ({ ...o, [id]: !o[id] }))} style={{ marginTop: 8, fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'transparent', color: '#60a5fa', cursor: 'pointer' }}>{expanded ? '▲ show less' : '▼ read full report'}</button>}
              {(it.actions || []).length > 0 && (
                <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap', paddingTop: 10, borderTop: '1px solid var(--border-subtle)' }}>
                  {it.actions.map((a: any, i: number) => (
                    <a key={i} href={a.url} target="_blank" rel="noreferrer" style={{ fontSize: 11, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: '1px solid #60a5fa55', background: '#60a5fa14', color: '#60a5fa', textDecoration: 'none' }}>{a.label} ↗</a>
                  ))}
                </div>
              )}
            </article>
          )
        })}
      </div>

      {pages > 1 && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'center', margin: '6px 0 20px' }}>
          <button disabled={page <= 1} onClick={() => { setPage(p => Math.max(1, p - 1)); window.scrollTo(0, 0) }} style={{ fontSize: 11, padding: '6px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: page <= 1 ? 'var(--text3)' : 'var(--text1)', cursor: page <= 1 ? 'not-allowed' : 'pointer' }}>← Newer</button>
          <span style={{ fontSize: 11, color: 'var(--text3)' }}>page {page} of {pages}</span>
          <button disabled={page >= pages} onClick={() => { setPage(p => Math.min(pages, p + 1)); window.scrollTo(0, 0) }} style={{ fontSize: 11, padding: '6px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: page >= pages ? 'var(--text3)' : 'var(--text1)', cursor: page >= pages ? 'not-allowed' : 'pointer' }}>Older →</button>
        </div>
      )}

      {purge && <PurgeModal category={active} categoryLabel={activeCat?.label || ''} onClose={() => setPurge(false)} />}
    </div>
  )
}

function PurgeModal({ category, categoryLabel, onClose }: { category: string; categoryLabel: string; onClose: () => void }) {
  const [olderThan, setOlderThan] = useState(90)
  const [scope, setScope] = useState<'category' | 'all'>('category')
  const [preview, setPreview] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<any>(null)
  const run = async (apply: boolean) => {
    setBusy(true)
    try {
      const b: any = { older_than_days: olderThan, apply }
      if (scope === 'category') b.category = category
      const r = await fetch('/api/v2/reports/purge', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(x => x.json())
      if (apply) setDone(r); else setPreview(r)
    } finally { setBusy(false) }
  }
  useEffect(() => { run(false) }, [olderThan, scope]) // eslint-disable-line
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.72)', zIndex: 90, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={e => e.stopPropagation()} style={{ ...card, padding: 18, width: 'min(440px,94vw)', border: '1px solid #ef444466' }}>
        <div style={{ fontSize: 14, fontWeight: 900, color: '#f87171' }}>🗑 Purge old reports</div>
        <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 8 }}>Delete reports older than <b style={{ color: 'var(--text0)' }}>{olderThan} days</b> in:</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
          {([['category', categoryLabel], ['all', 'All categories']] as any).map(([v, l]: any) => (
            <button key={v} onClick={() => setScope(v)} style={{ fontSize: 11, fontWeight: 700, padding: '5px 10px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${scope === v ? '#ef4444' : 'var(--border)'}`, background: scope === v ? '#ef444418' : 'transparent', color: scope === v ? '#f87171' : 'var(--text2)' }}>{l}</button>
          ))}
        </div>
        <input type="range" min={7} max={365} value={olderThan} onChange={e => setOlderThan(Number(e.target.value))} style={{ width: '100%', marginTop: 12, accentColor: '#ef4444' }} />
        <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 8 }}>
          {done ? <span style={{ color: '#22c55e' }}>✓ Deleted {done.total} report(s).</span>
            : preview ? <>Would delete <b style={{ color: '#f87171' }}>{preview.total}</b> report(s).</>
              : 'calculating…'}
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 14, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ fontSize: 11, padding: '6px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer' }}>{done ? 'close' : 'cancel'}</button>
          {!done && <button disabled={busy || !preview?.total} onClick={() => run(true)} style={{ fontSize: 11, fontWeight: 800, padding: '6px 16px', borderRadius: 6, border: 'none', background: preview?.total ? '#dc2626' : 'var(--bg2)', color: preview?.total ? '#fff' : 'var(--text3)', cursor: preview?.total ? 'pointer' : 'not-allowed' }}>{busy ? '…' : `Delete ${preview?.total || 0}`}</button>}
        </div>
      </div>
    </div>
  )
}
