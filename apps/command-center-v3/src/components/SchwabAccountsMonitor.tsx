import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import SnapTradeCredsModal from './SnapTradeCredsModal'

// Stage 2a Part C2 — ALL-Schwab-accounts monitor, thinkorswim-desktop styling. READ-ONLY data
// (/api/v2/schwab/accounts-live, 30s server cache). "Edit" builds a DRAFT modification routed through
// preview/translate — it NEVER touches a live order via API (that write path does not exist).
// 2026-06-12 operator additions: account filter pills + sub-tabs (Positions / Working Orders / History —
// most of what Schwab's read window returns is history: FILLED/CANCELED/REJECTED).
const mono = { fontFamily: 'JetBrains Mono, monospace' as const }
const tos = {
  panel: { background: '#0d0d0d', border: '1px solid #2c2c2c', borderRadius: 6 } as const,
  label: { fontSize: 8.5, color: '#8a8a8a', textTransform: 'uppercase' as const, letterSpacing: 0.6 },
  cell: { fontSize: 10.5, color: '#e0e0e0', padding: '3px 8px', ...mono } as const,
  head: { fontSize: 8.5, color: '#8a8a8a', textTransform: 'uppercase' as const, letterSpacing: 0.5, padding: '4px 8px', textAlign: 'left' as const, borderBottom: '1px solid #2c2c2c' },
}

const WORKING_STATUSES = ['WORKING', 'QUEUED', 'ACCEPTED', 'PENDING_ACTIVATION', 'AWAITING_PARENT_ORDER', 'AWAITING_CONDITION', 'PENDING_CANCEL', 'PENDING_REPLACE']
const STATUS_C: Record<string, string> = {
  WORKING: '#ffa726', QUEUED: '#ffa726', ACCEPTED: '#ffa726', PENDING_ACTIVATION: '#ffa726',
  AWAITING_PARENT_ORDER: '#ffa726', AWAITING_CONDITION: '#ffa726', PENDING_CANCEL: '#ffee58', PENDING_REPLACE: '#ffee58',
  FILLED: '#66bb6a', CANCELED: '#757575', REJECTED: '#ef5350', EXPIRED: '#757575',
}

const SUBTABS = ['Positions', 'Working Orders', 'Order History'] as const

export default function SchwabAccountsMonitor({ onEditDraft }: { onEditDraft: (intent: any) => void }) {
  const { data, refetch, loading } = useApi<any>('/api/v2/schwab/accounts-live', 120_000)
  const [sub, setSub] = useState<typeof SUBTABS[number]>('Positions')
  const [acct, setAcct] = useState<string>('all')
  const [snapOpen, setSnapOpen] = useState(false)
  const d = (data as any)?.data ?? data
  const accounts: any[] = d?.accounts ?? []
  const shown = accounts.filter((a: any) => acct === 'all' || a.account_key === acct)
  const nice = (k: string) => k.replace('schwab_', '').replace(/_/g, ' ').toUpperCase()

  const allOrders = shown.flatMap((a: any) => (a.orders ?? []).map((o: any) => ({ ...o, account_key: a.account_key })))
  const working = allOrders.filter((o: any) => WORKING_STATUSES.includes(o.status))
  const history = allOrders.filter((o: any) => !WORKING_STATUSES.includes(o.status))

  // Edit (DRAFT ONLY): seed a canonical intent from the live order and hand it to the order panel.
  const editAsDraft = (o: any) => {
    onEditDraft({
      instrument: { symbol: o.symbol, asset_type: 'EQUITY', option_legs: [] },
      direction: String(o.instruction || '').includes('SELL_SHORT') ? 'SHORT' : 'LONG',
      entry: {
        method: o.order_type === 'MARKET' ? 'MARKET' : o.order_type === 'STOP' ? 'STOP' : o.order_type === 'STOP_LIMIT' ? 'STOP_LIMIT' : 'LIMIT',
        limit_price: o.price ? Number(o.price) : null, stop_price: o.stop_price ? Number(o.stop_price) : null,
      },
      quantity: { qty: Number(o.qty) || null, notional: null, contracts: null },
      broker: 'schwab', account_key: o.account_key,
      tif: o.duration === 'GOOD_TILL_CANCEL' ? 'GTC' : 'DAY',
      session: o.session === 'NORMAL' ? 'NORMAL' : (o.session || 'NORMAL'),
      exit_policy: { stop: null, targets: [], oco: true, on_stop_place_failure: 'CLOSE_POSITION' },
      meta: { thesis: `DRAFT EDIT of live order ${o.order_id} (${o.account_key}) — drafts never modify the live order`, created_by: 'operator' },
      state: 'DRAFT',
    })
  }

  const orderTable = (rows: any[], withEdit: boolean) => (
    rows.length === 0 ? (
      <div style={{ padding: '8px 10px', fontSize: 9.5, color: '#616161' }}>
        {withEdit ? 'no working orders right now — anything you place in thinkorswim shows here within ~30s'
                  : 'no orders in the read window'}
      </div>
    ) : (
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr>
          {['account', 'status', 'symbol', 'side', 'qty (filled)', 'type', 'price', 'stop', 'TIF', 'strat', 'entered', ''].map(h => <th key={h} style={tos.head}>{h}</th>)}
        </tr></thead>
        <tbody>
          {rows.map((o: any, i: number) => (
            <tr key={i} style={{ borderBottom: '1px solid #1d1d1d' }}>
              <td style={{ ...tos.cell, color: '#ffa726', fontSize: 9 }}>{nice(o.account_key)}</td>
              <td style={{ ...tos.cell, color: STATUS_C[o.status] ?? '#bdbdbd', fontWeight: 700 }}>{o.status}</td>
              <td style={{ ...tos.cell, fontWeight: 700 }}>{o.symbol}</td>
              <td style={{ ...tos.cell, color: String(o.instruction).startsWith('BUY') ? '#66bb6a' : '#ef5350' }}>{o.instruction}</td>
              <td style={tos.cell}>{o.qty} ({o.filled_qty ?? 0})</td>
              <td style={tos.cell}>{o.order_type}{o.children ? ` +${o.children} child` : ''}</td>
              <td style={tos.cell}>{o.price ? `$${o.price}` : '—'}</td>
              <td style={tos.cell}>{o.stop_price ? `$${o.stop_price}` : '—'}</td>
              <td style={tos.cell}>{o.duration === 'GOOD_TILL_CANCEL' ? 'GTC' : o.duration}</td>
              <td style={tos.cell}>{o.strategy}</td>
              <td style={{ ...tos.cell, fontSize: 9 }}>{o.entered_time ? String(o.entered_time).slice(5, 16).replace('T', ' ') : '—'}</td>
              <td style={tos.cell}>
                {withEdit && (
                  <button onClick={() => editAsDraft(o)}
                    title="Creates a DRAFT copy in the order panel (preview/translate only). Does NOT modify the live order at Schwab."
                    style={{ fontSize: 8.5, padding: '2px 8px', borderRadius: 3, border: '1px solid #2c2c2c', background: '#1b1b1b', color: '#ffa726', cursor: 'pointer', whiteSpace: 'nowrap' }}>
                    edit → DRAFT only</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  )

  return (
    <div>
      {/* the contract of this surface, stated up front */}
      <div style={{ padding: '8px 12px', background: 'rgba(255,167,38,.07)', border: '1px solid rgba(255,167,38,.35)', borderRadius: 6, marginBottom: 10 }}>
        <span style={{ fontSize: 10.5, fontWeight: 800, color: '#ffa726' }}>READ-ONLY MONITOR — ALL SCHWAB ACCOUNTS</span>
        <div style={{ fontSize: 9, color: '#bdbdbd', marginTop: 2 }}>
          Live positions + open orders (read API, 30s cache). <b style={{ color: '#ffa726' }}>"Edit" creates a DRAFT
          modification only</b> — it routes through preview/translate and is blocked by the guard. It does NOT
          modify the live order at Schwab (that gated write path is out of scope). To actually change a live
          order: thinkorswim, manually.
        </div>
      </div>

      {/* account filter pills + sub-tabs + refresh */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
        {['all', ...accounts.map((a: any) => a.account_key)].map((k: string) => (
          <button key={k} onClick={() => setAcct(k)}
            style={{ fontSize: 9.5, fontWeight: acct === k ? 800 : 400, padding: '3px 11px', borderRadius: 4, cursor: 'pointer',
              border: `1px solid ${acct === k ? '#ffa726' : '#2c2c2c'}`,
              background: acct === k ? 'rgba(255,167,38,.13)' : '#161616',
              color: acct === k ? '#ffa726' : '#8a8a8a' }}>
            {k === 'all' ? 'ALL ACCOUNTS' : nice(k)}
          </button>
        ))}
        <span style={{ width: 14 }} />
        {SUBTABS.map(t => (
          <button key={t} onClick={() => setSub(t)}
            style={{ fontSize: 9.5, fontWeight: sub === t ? 800 : 400, padding: '3px 11px', borderRadius: 4, cursor: 'pointer',
              border: `1px solid ${sub === t ? '#64b5f6' : '#2c2c2c'}`,
              background: sub === t ? 'rgba(100,181,246,.12)' : '#161616',
              color: sub === t ? '#64b5f6' : '#8a8a8a' }}>
            {t}{t === 'Working Orders' ? ` (${working.length})` : t === 'Order History' ? ` (${history.length})` : ''}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <button onClick={() => setSnapOpen(true)} title="Add SnapTrade API keys to aggregate accounts without a direct API (e.g. the Fidelity 401k). Read-only."
          style={{ fontSize: 9, padding: '3px 10px', borderRadius: 4, border: '1px solid #1d4ed8', background: 'rgba(29,78,216,.14)', color: '#90caf9', cursor: 'pointer', fontWeight: 700 }}>
          + Connect SnapTrade
        </button>
        <button onClick={refetch} style={{ fontSize: 9, padding: '3px 10px', borderRadius: 4, border: '1px solid #2c2c2c', background: '#1b1b1b', color: '#bdbdbd', cursor: 'pointer' }}>
          {loading ? 'refreshing…' : 'refresh'}
        </button>
      </div>
      {snapOpen && <SnapTradeCredsModal onClose={() => setSnapOpen(false)} />}

      {/* ── POSITIONS ── */}
      {sub === 'Positions' && (
        <div style={{ display: 'grid', gap: 10 }}>
          {shown.map((a: any) => (
            <div key={a.account_key} style={{ ...tos.panel, padding: 0, overflow: 'hidden' }}>
              <div style={{ padding: '6px 10px', background: '#161616', borderBottom: '1px solid #2c2c2c', display: 'flex', gap: 10, alignItems: 'center' }}>
                <span style={{ fontSize: 11.5, fontWeight: 800, color: '#e0e0e0', ...mono }}>{nice(a.account_key)}</span>
                <span style={{ ...tos.label }}>positions: {a.positions_status === 'ok' ? a.positions.length : <b style={{ color: '#ef5350' }}>{a.positions_status}</b>}</span>
                <span style={{ ...tos.label }}>working: {(a.orders ?? []).filter((o: any) => WORKING_STATUSES.includes(o.status)).length}</span>
              </div>
              {a.positions.length === 0 ? (
                <div style={{ padding: '6px 10px', fontSize: 9.5, color: '#616161' }}>no positions</div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr>
                    {['symbol', 'qty', 'avg price', 'mkt value', 'unreal P/L'].map(h => <th key={h} style={tos.head}>{h}</th>)}
                  </tr></thead>
                  <tbody>
                    {a.positions.map((p: any, i: number) => (
                      <tr key={i} style={{ borderBottom: '1px solid #1d1d1d' }}>
                        <td style={{ ...tos.cell, fontWeight: 700 }}>{p.symbol}</td>
                        <td style={tos.cell}>{p.qty}</td>
                        <td style={tos.cell}>${Number(p.avg_entry_price).toFixed(2)}</td>
                        <td style={tos.cell}>${Number(p.market_value).toLocaleString()}</td>
                        <td style={{ ...tos.cell, color: Number(p.unrealized_pl) >= 0 ? '#66bb6a' : '#ef5350' }}>
                          {Number(p.unrealized_pl) >= 0 ? '+' : ''}{Number(p.unrealized_pl).toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── WORKING ORDERS (live, editable-as-draft) ── */}
      {sub === 'Working Orders' && (
        <div style={{ ...tos.panel, overflow: 'hidden' }}>
          <div style={{ padding: '6px 10px', background: '#161616', borderBottom: '1px solid #2c2c2c' }}>
            <span style={{ fontSize: 10.5, fontWeight: 800, color: '#ffa726' }}>WORKING ORDERS — live at Schwab right now</span>
            <span style={{ fontSize: 9, color: '#8a8a8a', marginLeft: 8 }}>statuses: {WORKING_STATUSES.slice(0, 4).join(', ')}…</span>
          </div>
          {orderTable(working, true)}
        </div>
      )}

      {/* ── ORDER HISTORY (filled/canceled/rejected in the read window) ── */}
      {sub === 'Order History' && (
        <div style={{ ...tos.panel, overflow: 'hidden' }}>
          <div style={{ padding: '6px 10px', background: '#161616', borderBottom: '1px solid #2c2c2c' }}>
            <span style={{ fontSize: 10.5, fontWeight: 800, color: '#bdbdbd' }}>ORDER HISTORY — recent read window (not working)</span>
          </div>
          {orderTable(history, false)}
        </div>
      )}

      <div style={{ fontSize: 8.5, color: '#616161', marginTop: 8 }}>
        Source: /api/v2/schwab/accounts-live (fenced read-only transport) · no execution or modify path exists on this surface
      </div>
    </div>
  )
}
