import { useState, useEffect, useCallback, useRef } from 'react'
import { useApi } from '../../hooks/useApi'
import { fmt$ } from '../../lib/format'
import TradeInViewDetail from './TradeInViewDetail'
import ReportingAuditPanel from './ReportingAuditPanel'

const MISSING_COLOR: Record<string, string> = {
  strategy: '#ef4444',
  setup: '#ef4444',
  review: '#ef4444',
  market_regime: '#f59e0b',
  psychology: '#f59e0b',
  operator_review: '#f97316',
}

interface Props {
  account?: string
  days: number
  acctLabel?: Record<string, string>
}

export default function TaggingQueuePanel({ account, days, acctLabel = {} }: Props) {
  const [page, setPage] = useState(1)
  const [missingFilter, setMissingFilter] = useState('')
  const [minPnl, setMinPnl] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [activeIdx, setActiveIdx] = useState(0)
  const [detailTrade, setDetailTrade] = useState<any>(null)
  const [toast, setToast] = useState('')
  const [showAudit, setShowAudit] = useState(false)
  const [bulkOpen, setBulkOpen] = useState(false)
  const [bulkTags, setBulkTags] = useState({ setup_family: '', setup_types: [] as string[], market_regime: '' })
  const [tick, setTick] = useState(0)
  const tableRef = useRef<HTMLDivElement>(null)

  const q = `/api/v2/journal/tagging-queue?days=${days}&page=${page}&limit=50`
    + `${account ? `&account=${encodeURIComponent(account)}` : ''}`
    + `${missingFilter ? `&missing=${missingFilter}` : ''}`
    + `${minPnl ? `&min_pnl=${minPnl}` : ''}`
    + `&_t=${tick}`

  const { data: raw, loading } = useApi<any>(q, 60_000)
  const d = (raw as any)?.data ?? raw
  const items: any[] = d?.items || []

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(''), 4000)
  }

  const refresh = () => setTick(t => t + 1)

  const openDetail = (row: any) => {
    setDetailTrade({
      symbol: row.symbol,
      account: row.account,
      na: row.account,
      exitDate: row.close_date,
      close_date: row.close_date,
      entryDate: row.open_date,
      trade_key: row.trade_key,
      pnl: row.net_pnl,
      shares: row.shares,
      ep: row.buy_price,
      xp: row.sell_price,
      pnlPct: row.pnl_pct,
    })
  }

  const skipReview = async (tradeKey: string) => {
    await fetch('/api/v2/journal/tagging-queue/skip', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trade_key: tradeKey, reason: 'Operator marked — no tags needed' }),
    })
    showToast('Marked reviewed (no tags). Queue updated.')
    refresh()
  }

  const bulkTag = async () => {
    const keys = [...selected]
    if (!keys.length) return
    await fetch('/api/v2/journal/tagging-queue/bulk-tag', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        trade_keys: keys,
        tags: {
          setup_family: bulkTags.setup_family || undefined,
          setup_types: bulkTags.setup_types.length ? bulkTags.setup_types : undefined,
          market_regime: bulkTags.market_regime || undefined,
        },
      }),
    })
    setBulkOpen(false)
    setSelected(new Set())
    showToast(`${keys.length} trades bulk-tagged. Reports refresh in background.`)
    refresh()
  }

  const toggleSel = (tk: string) => {
    setSelected(prev => {
      const n = new Set(prev)
      if (n.has(tk)) n.delete(tk)
      else n.add(tk)
      return n
    })
  }

  const onKeyDown = useCallback((e: KeyboardEvent) => {
    if (detailTrade || bulkOpen) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, items.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && items[activeIdx]) {
      e.preventDefault()
      openDetail(items[activeIdx])
    }
  }, [items, activeIdx, detailTrade, bulkOpen])

  useEffect(() => {
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onKeyDown])

  useEffect(() => { setActiveIdx(0); setPage(1) }, [account, days, missingFilter, minPnl])

  const health = d?.queue_health_pct ?? 0
  const need = d?.need_tagging ?? 0
  const total = d?.total_in_range ?? 0

  return (
    <div>
      {toast && (
        <div style={{ position: 'fixed', top: 16, right: 16, zIndex: 2000, background: '#166534', color: '#fff', padding: '10px 16px', borderRadius: 8, fontSize: 11, boxShadow: '0 4px 20px rgba(0,0,0,.4)' }}>
          {toast}
        </div>
      )}

      {/* Summary bar */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr', gap: 10, marginBottom: 14 }}>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Operator tagging queue</div>
          <div style={{ fontSize: 22, fontWeight: 800, color: need > 0 ? '#f59e0b' : '#22c55e' }}>
            {need} trades need tagging
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)' }}>
            {d?.need_tagging_pct ?? 0}% of recent activity · oldest {d?.oldest_trade_date || '—'}
          </div>
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 800, color: health >= 80 ? '#22c55e' : health >= 50 ? '#f59e0b' : '#ef4444' }}>{health}%</div>
          <div style={{ fontSize: 9, color: 'var(--text3)' }}>Queue health</div>
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--text0)' }}>{total}</div>
          <div style={{ fontSize: 9, color: 'var(--text3)' }}>Trades in range</div>
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, display: 'flex', flexDirection: 'column', gap: 6, justifyContent: 'center' }}>
          <button onClick={() => setShowAudit(!showAudit)} style={{ fontSize: 10, padding: '6px 10px', borderRadius: 5, border: '1px solid var(--border)', background: showAudit ? 'rgba(96,165,250,.15)' : 'var(--bg2)', cursor: 'pointer', color: '#60a5fa' }}>
            {showAudit ? 'Hide' : 'Run'} reporting audit
          </button>
          {selected.size > 0 && (
            <button onClick={() => setBulkOpen(true)} style={{ fontSize: 10, padding: '6px 10px', borderRadius: 5, border: 'none', background: '#a855f7', color: '#fff', cursor: 'pointer' }}>
              Bulk tag ({selected.size})
            </button>
          )}
        </div>
      </div>

      {showAudit && <div style={{ marginBottom: 14 }}><ReportingAuditPanel days={days} /></div>}

      {/* Filters */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 9, color: 'var(--text3)' }}>Missing:</span>
        {['', 'strategy', 'setup', 'market_regime', 'psychology', 'operator_review'].map(m => (
          <button key={m || 'all'} onClick={() => setMissingFilter(m)} style={{
            fontSize: 9, padding: '3px 8px', borderRadius: 4, border: 'none', cursor: 'pointer',
            background: missingFilter === m ? 'rgba(245,158,11,.2)' : 'var(--bg2)',
            color: missingFilter === m ? '#f59e0b' : 'var(--text3)',
          }}>{m || 'All'}</button>
        ))}
        <label style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 8 }}>
          Min |P&L|
          <input type="number" value={minPnl} onChange={e => setMinPnl(e.target.value)} placeholder="0" style={{ width: 60, marginLeft: 4, fontSize: 9, padding: 3, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
        </label>
        <span style={{ fontSize: 8, color: 'var(--text3)', marginLeft: 'auto' }}>↑↓ navigate · Enter review</span>
      </div>

      {/* Table */}
      <div ref={tableRef} style={{ overflowX: 'auto', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
          <thead>
            <tr style={{ background: 'var(--bg2)' }}>
              {['', 'Date', 'Account', 'Symbol', 'Dir', 'Size', 'P&L', 'Tags', 'Missing', ''].map(h => (
                <th key={h} style={{ padding: '6px 8px', textAlign: 'left', fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((row, i) => (
              <tr key={row.trade_key}
                onClick={() => setActiveIdx(i)}
                style={{
                  borderTop: '1px solid var(--border)',
                  background: i === activeIdx ? 'rgba(96,165,250,.08)' : 'transparent',
                  outline: i === activeIdx ? '1px solid rgba(96,165,250,.3)' : 'none',
                }}>
                <td style={{ padding: '5px 8px' }} onClick={e => e.stopPropagation()}>
                  <input type="checkbox" checked={selected.has(row.trade_key)} onChange={() => toggleSel(row.trade_key)} />
                </td>
                <td style={{ padding: '5px 8px', color: 'var(--text2)' }}>{row.close_date}</td>
                <td style={{ padding: '5px 8px', fontSize: 9 }}>{acctLabel[row.account] ?? row.account}</td>
                <td style={{ padding: '5px 8px', fontFamily: 'monospace', fontWeight: 700 }}>{row.symbol}</td>
                <td style={{ padding: '5px 8px', color: row.direction === 'short' ? '#f97316' : '#60a5fa' }}>{row.direction}</td>
                <td style={{ padding: '5px 8px' }}>{row.shares ?? '—'}</td>
                <td style={{ padding: '5px 8px', color: (row.net_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>{fmt$(row.net_pnl, 0)}</td>
                <td style={{ padding: '5px 8px' }}>
                  <span style={{ fontWeight: 600 }}>{row.tag_count}</span>
                  <span style={{ color: 'var(--text3)', fontSize: 8, marginLeft: 4 }}>{row.tag_summary}</span>
                  {row.auto_stub && <span style={{ marginLeft: 4, fontSize: 7, color: '#f59e0b' }}>AI stub</span>}
                </td>
                <td style={{ padding: '5px 8px' }}>
                  <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                    {(row.missing || []).map((m: string) => (
                      <span key={m} style={{ fontSize: 7, padding: '1px 5px', borderRadius: 8, background: (MISSING_COLOR[m] || '#ef4444') + '22', color: MISSING_COLOR[m] || '#ef4444', border: `1px solid ${MISSING_COLOR[m] || '#ef4444'}44` }}>{m}</span>
                    ))}
                  </div>
                </td>
                <td style={{ padding: '5px 8px', whiteSpace: 'nowrap' }}>
                  <button onClick={() => openDetail(row)} style={{ fontSize: 9, padding: '3px 8px', borderRadius: 4, border: 'none', background: '#60a5fa', color: '#fff', cursor: 'pointer', marginRight: 4 }}>Review & Tag</button>
                  <button onClick={() => skipReview(row.trade_key)} style={{ fontSize: 8, padding: '3px 6px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer' }}>Skip</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading && <div style={{ padding: 16, textAlign: 'center', color: 'var(--text3)' }}>Loading queue…</div>}
        {!loading && items.length === 0 && (
          <div style={{ padding: 24, textAlign: 'center', color: '#22c55e', fontSize: 12, fontWeight: 600 }}>
            Queue clear — all trades tagged for this filter.
          </div>
        )}
      </div>

      {/* Pagination */}
      {(d?.total_queue ?? 0) > 50 && (
        <div style={{ display: 'flex', gap: 8, marginTop: 10, justifyContent: 'center' }}>
          <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} style={{ fontSize: 9, padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', cursor: page > 1 ? 'pointer' : 'default' }}>Prev</button>
          <span style={{ fontSize: 9, color: 'var(--text3)', lineHeight: '24px' }}>Page {page} · {d?.total_queue} in queue</span>
          <button disabled={page * 50 >= (d?.total_queue ?? 0)} onClick={() => setPage(p => p + 1)} style={{ fontSize: 9, padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', cursor: 'pointer' }}>Next</button>
        </div>
      )}

      {/* Bulk modal */}
      {bulkOpen && (
        <>
          <div onClick={() => setBulkOpen(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', zIndex: 1100 }} />
          <div style={{ position: 'fixed', top: '20%', left: '50%', transform: 'translateX(-50%)', width: 400, background: 'var(--bg0)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, zIndex: 1101 }}>
            <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 10 }}>Bulk tag {selected.size} trades</div>
            <input placeholder="Strategy / setup family" value={bulkTags.setup_family} onChange={e => setBulkTags(t => ({ ...t, setup_family: e.target.value }))} style={{ width: '100%', marginBottom: 8, fontSize: 10, padding: 6, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
            <input placeholder="Market regime" value={bulkTags.market_regime} onChange={e => setBulkTags(t => ({ ...t, market_regime: e.target.value }))} style={{ width: '100%', marginBottom: 8, fontSize: 10, padding: 6, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={bulkTag} style={{ flex: 1, fontSize: 10, padding: 8, borderRadius: 5, border: 'none', background: '#a855f7', color: '#fff', cursor: 'pointer' }}>Apply tags</button>
              <button onClick={() => setBulkOpen(false)} style={{ fontSize: 10, padding: 8, borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', cursor: 'pointer' }}>Cancel</button>
            </div>
          </div>
        </>
      )}

      {detailTrade && (
        <TradeInViewDetail
          trade={detailTrade}
          initialTab="Review"
          focusTagging
          onClose={() => setDetailTrade(null)}
          onSaved={() => {
            setDetailTrade(null)
            showToast('Trade tagged successfully. Affected reports will refresh in the background.')
            refresh()
          }}
        />
      )}
    </div>
  )
}