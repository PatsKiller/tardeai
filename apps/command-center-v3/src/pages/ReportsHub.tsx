import { useEffect, useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'

// v3 Reports — one portal for everything that goes out to the operator (Telegram / email / SIEM):
// morning briefs, digests, alerts, advisories, recovery, dividends, regime, paper, system. Tabbed,
// searchable, paginated, with actionable buttons + a purge control. Source: /api/v2/reports/* (read-only).

interface Props { onDrill: (ctx: DrillContext) => void }

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }
const SEV: Record<string, string> = { critical: '#dc2626', urgent: '#ef4444', warning: '#f59e0b', info: '#60a5fa' }
const sevColor = (s?: string) => SEV[(s || 'info').toLowerCase()] || '#60a5fa'

const fmtDate = (s?: string) => {
  if (!s) return '—'
  const d = new Date(s)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

function Detail({ item, onClose }: { item: any; onClose: () => void }) {
  const { data } = useApi<any>(`/api/v2/reports/item?source=${item.source}&id=${item.id}`)
  const d = data || item
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.72)', zIndex: 90, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={e => e.stopPropagation()} style={{ ...card, padding: 18, width: 'min(720px,96vw)', maxHeight: '88vh', overflowY: 'auto', border: `1px solid ${sevColor(d.severity)}` }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ width: 9, height: 9, borderRadius: '50%', background: sevColor(d.severity), display: 'inline-block' }} />
          <span style={{ fontSize: 14, fontWeight: 900, color: 'var(--text0)' }}>{d.title}</span>
          {d.symbol && <span style={{ fontSize: 10, fontWeight: 800, padding: '2px 7px', borderRadius: 4, background: '#60a5fa22', color: '#60a5fa' }}>{d.symbol}</span>}
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 10, color: 'var(--text3)' }}>{d.type} · {fmtDate(d.created_at)}</span>
        </div>
        <pre style={{ marginTop: 12, fontSize: 12, color: 'var(--text1)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5, fontFamily: 'inherit' }}>{d.summary || '(no body)'}</pre>
        {d.payload && <details style={{ marginTop: 8 }}>
          <summary style={{ fontSize: 10, color: 'var(--text3)', cursor: 'pointer' }}>raw payload</summary>
          <pre style={{ fontSize: 10, color: 'var(--text2)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'var(--bg0)', padding: 8, borderRadius: 6, marginTop: 4 }}>{typeof d.payload === 'string' ? d.payload : JSON.stringify(d.payload, null, 2)}</pre>
        </details>}
        <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {(d.actions || []).map((a: any, i: number) => (
            <a key={i} href={a.url} target="_blank" rel="noreferrer" style={{ fontSize: 11, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: '1px solid #60a5fa', background: '#60a5fa18', color: '#60a5fa', textDecoration: 'none' }}>{a.label} ↗</a>
          ))}
          <button onClick={onClose} style={{ fontSize: 11, padding: '6px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer' }}>close</button>
        </div>
      </div>
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
  const [detail, setDetail] = useState<any>(null)
  const [purge, setPurge] = useState(false)

  // debounce search
  useEffect(() => { const t = setTimeout(() => { setQ(qInput); setPage(1) }, 350); return () => clearTimeout(t) }, [qInput])
  useEffect(() => { setPage(1) }, [active, days])

  const listPath = useMemo(() =>
    `/api/v2/reports/list?category=${active}&q=${encodeURIComponent(q)}&page=${page}&per_page=20${days ? `&days=${days}` : ''}`,
    [active, q, page, days])
  const { data: list, loading } = useApi<any>(listPath, 0)
  const items = list?.items || []
  const total = list?.total ?? 0
  const pages = list?.pages ?? 1
  const activeCat = categories.find((c: any) => c.key === active)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h1 style={{ fontSize: 20, fontWeight: 900, color: 'var(--text0)', margin: 0 }}>Reports</h1>
        <span style={{ fontSize: 12, color: 'var(--text3)' }}>{cats?.total ?? 0} total · everything sent to Telegram / email / SIEM, in one place</span>
        <span style={{ flex: 1 }} />
        <button onClick={() => setPurge(true)} style={{ fontSize: 11, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: '1px solid #ef444455', background: '#ef444412', color: '#f87171', cursor: 'pointer' }}>🗑 Purge old…</button>
      </div>

      {/* Category tabs */}
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

      {/* Controls */}
      <div style={{ ...card, padding: 10, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <input value={qInput} onChange={e => setQInput(e.target.value)} placeholder={`Search ${activeCat?.label || ''}…`}
          style={{ flex: 1, minWidth: 200, fontSize: 12, padding: '7px 10px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text0)' }} />
        <div style={{ display: 'flex', gap: 4 }}>
          {([['', 'All'], [7, '7d'], [30, '30d'], [90, '90d']] as any).map(([v, l]: any) => (
            <button key={l} onClick={() => setDays(v)} style={{ fontSize: 10, fontWeight: 700, padding: '5px 9px', borderRadius: 5, cursor: 'pointer',
              border: `1px solid ${days === v ? '#60a5fa' : 'var(--border)'}`, background: days === v ? 'rgba(96,165,250,.10)' : 'transparent', color: days === v ? '#60a5fa' : 'var(--text3)' }}>{l}</button>
          ))}
        </div>
        <span style={{ fontSize: 11, color: 'var(--text3)' }}>{total} result{total === 1 ? '' : 's'}</span>
      </div>

      {/* List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {loading && items.length === 0 && <div style={{ ...card, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>loading…</div>}
        {!loading && items.length === 0 && <div style={{ ...card, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>no reports in this category {q ? `matching “${q}”` : ''}</div>}
        {items.map((it: any) => (
          <div key={`${it.source}-${it.id}`} style={{ ...card, padding: 12, borderLeft: `4px solid ${sevColor(it.severity)}`, display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)' }}>{it.title}</span>
                {it.symbol && <span style={{ fontSize: 9, fontWeight: 800, padding: '1px 6px', borderRadius: 4, background: '#60a5fa22', color: '#60a5fa' }}>{it.symbol}</span>}
                <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, background: sevColor(it.severity) + '22', color: sevColor(it.severity), textTransform: 'uppercase' }}>{it.severity}</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4, lineHeight: 1.45, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as any }}>{it.summary}</div>
              <div style={{ fontSize: 9.5, color: 'var(--text3)', marginTop: 5 }}>{fmtDate(it.created_at)} · {it.channel} · {it.type}</div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5, alignItems: 'flex-end' }}>
              {(it.actions || []).slice(0, 2).map((a: any, i: number) => (
                <a key={i} href={a.url} target="_blank" rel="noreferrer" style={{ fontSize: 10, fontWeight: 700, padding: '4px 9px', borderRadius: 5, border: '1px solid #60a5fa55', background: '#60a5fa14', color: '#60a5fa', textDecoration: 'none', whiteSpace: 'nowrap' }}>{a.label} ↗</a>
              ))}
              <button onClick={() => setDetail(it)} style={{ fontSize: 10, fontWeight: 700, padding: '4px 9px', borderRadius: 5, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer', whiteSpace: 'nowrap' }}>Detail</button>
            </div>
          </div>
        ))}
      </div>

      {/* Pagination */}
      {pages > 1 && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'center', marginTop: 4 }}>
          <button disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))} style={{ fontSize: 11, padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: page <= 1 ? 'var(--text3)' : 'var(--text1)', cursor: page <= 1 ? 'not-allowed' : 'pointer' }}>← Prev</button>
          <span style={{ fontSize: 11, color: 'var(--text3)' }}>page {page} of {pages}</span>
          <button disabled={page >= pages} onClick={() => setPage(p => Math.min(pages, p + 1))} style={{ fontSize: 11, padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: page >= pages ? 'var(--text3)' : 'var(--text1)', cursor: page >= pages ? 'not-allowed' : 'pointer' }}>Next →</button>
        </div>
      )}

      {detail && <Detail item={detail} onClose={() => setDetail(null)} />}
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
      const body: any = { older_than_days: olderThan, apply }
      if (scope === 'category') body.category = category
      const r = await fetch('/api/v2/reports/purge', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(x => x.json())
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
            : preview ? <>Would delete <b style={{ color: '#f87171' }}>{preview.total}</b> report(s) ({preview.deleted?.notification_log || 0} notifications + {preview.deleted?.alert_events || 0} alerts).</>
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
