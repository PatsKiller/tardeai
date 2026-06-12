import { useEffect, useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'

type TicketStatus = 'READY' | 'GENERATED' | 'OPERATOR_MARKED_PLACED' | 'BROKER_OBSERVED' | 'EXCEPTION'

type ManualState = Record<string, {
  status: TicketStatus
  markedPlacedAt?: string
  notes?: string
}>

const LS_KEY = 'tradeai.manualTosTickets.v1'
const T = {
  card: 'var(--bg1)', card2: 'var(--bg2)', border: 'var(--border)', text: 'var(--text0)', dim: 'var(--text3)',
  blue: '#60a5fa', green: '#22c55e', amber: '#f59e0b', red: '#ef4444', purple: '#a78bfa'
}
const btn = (bg: string, fg = '#fff') => ({ fontSize: 10, fontWeight: 700, padding: '5px 10px', borderRadius: 5, border: 'none', background: bg, color: fg, cursor: 'pointer' as const })
const mono = { fontFamily: 'JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace' as const }

function normDraft(d: any) {
  const it = d.intent_json ?? d.intent ?? d
  const symbol = String(d.symbol ?? it.instrument?.symbol ?? '').toUpperCase()
  const account = String(it.account_key ?? d.account_key ?? 'schwab_taxable')
  const qty = Number(it.quantity?.qty ?? d.qty ?? 0)
  const side = it.direction === 'SHORT' ? 'SELL SHORT' : 'BUY'
  const entry = it.entry ?? {}
  const entryType = String(entry.method ?? 'LIMIT')
  const entryPrice = entry.limit_price ?? entry.stop_price ?? null
  const stop = it.exit_policy?.stop?.price ?? null
  const trail = it.exit_policy?.stop?.trail ?? null
  const targets = Array.isArray(it.exit_policy?.targets) ? it.exit_policy.targets : []
  const tif = String(it.tif ?? 'DAY')
  const session = String(it.session ?? 'NORMAL')
  const id = String(d.intent_id ?? it.intent_id ?? `${symbol}-${account}-${qty}-${entryType}-${entryPrice}`)
  return { id, raw: d, it, symbol, account, qty, side, entryType, entryPrice, stop, trail, targets, tif, session }
}

function ticketText(t: ReturnType<typeof normDraft>) {
  const px = t.entryPrice != null ? ` ${Number(t.entryPrice).toFixed(2)}` : ''
  const exits = [
    t.stop != null ? `STOP ${Number(t.stop).toFixed(2)}` : null,
    t.trail ? `TRAIL ${t.trail.offset}${t.trail.type === 'PERCENT' ? '%' : t.trail.type === 'VALUE' ? '$' : ' ticks'} ${t.trail.basis ?? 'LAST'}` : null,
    ...t.targets.map((x: any, i: number) => `TARGET${i + 1} ${Number(x.price).toFixed(2)}${x.qty_pct && x.qty_pct !== 100 ? ` ${x.qty_pct}%` : ''}`),
  ].filter(Boolean).join(' | ')
  return `${t.side} ${t.qty} ${t.symbol} ${t.entryType}${px} ${t.tif}${exits ? ` | ${exits}` : ''}`.trim()
}

function ticketJson(t: ReturnType<typeof normDraft>, status: TicketStatus) {
  return {
    execution_mode: 'MANUAL_TOS',
    execution_origin: 'manual_tos_operator_entered',
    broker: 'schwab',
    intent_id: t.id,
    account_key: t.account,
    symbol: t.symbol,
    side: t.side,
    qty: t.qty,
    entry_type: t.entryType,
    entry_price: t.entryPrice,
    stop_price: t.stop,
    trailing_stop: t.trail,
    targets: t.targets,
    tif: t.tif,
    session: t.session,
    ticket_status: status,
    generated_at: new Date().toISOString(),
    audit_note: 'Manual Thinkorswim setup only. Trade AI prepares and tracks; operator enters order in Thinkorswim. Schwab API remains read-only.',
  }
}

function csvEscape(v: any) {
  const s = v == null ? '' : String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

function ticketCsv(tickets: ReturnType<typeof normDraft>[]) {
  const rows = [['Symbol','Account','Side','Qty','EntryType','EntryPrice','Stop','Targets','TIF','Session','ManualTicket']]
  for (const t of tickets) rows.push([
    t.symbol, t.account, t.side, String(t.qty), t.entryType, t.entryPrice ?? '', t.stop ?? '',
    t.targets.map((x: any) => `${x.price}${x.qty_pct && x.qty_pct !== 100 ? `:${x.qty_pct}%` : ''}`).join('|'),
    t.tif, t.session, ticketText(t)
  ])
  return rows.map(r => r.map(csvEscape).join(',')).join('\n') + '\n'
}

function download(name: string, type: string, text: string) {
  const blob = new Blob([text], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove()
  URL.revokeObjectURL(url)
}

function copy(text: string, setMsg: (m: string) => void) {
  const done = () => { setMsg('copied'); setTimeout(() => setMsg(''), 1300) }
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done).catch(done)
  else { const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); done() }
}

function matchActivity(t: ReturnType<typeof normDraft>, activity: any[]) {
  const hits = activity.filter(a => String(a.symbol ?? '').toUpperCase() === t.symbol
    && String(a.account_key ?? '') === t.account
    && (!a.quantity || Number(a.quantity) === t.qty || !t.qty))
  return hits[0] ?? null
}

function statusFor(t: ReturnType<typeof normDraft>, local: ManualState, activity: any[]): TicketStatus {
  const m = matchActivity(t, activity)
  if (m) return 'BROKER_OBSERVED'
  const s = local[t.id]?.status
  if (s === 'OPERATOR_MARKED_PLACED') return 'OPERATOR_MARKED_PLACED'
  if (s === 'GENERATED') return 'GENERATED'
  return 'READY'
}

function Pill({ status }: { status: TicketStatus }) {
  const color = status === 'BROKER_OBSERVED' ? T.green : status === 'OPERATOR_MARKED_PLACED' ? T.amber : status === 'EXCEPTION' ? T.red : status === 'GENERATED' ? T.blue : T.dim
  const label = status === 'BROKER_OBSERVED' ? 'broker observed' : status === 'OPERATOR_MARKED_PLACED' ? 'marked placed' : status.toLowerCase()
  return <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 7px', borderRadius: 4, color, background: `${color}18` }}>{label}</span>
}

export default function ManualExecutionHub() {
  const { data: draftsR, refetch } = useApi<any>('/api/v2/broker-orders/drafts?broker=schwab', 30_000)
  const { data: activityR } = useApi<any>('/api/v2/broker-orders/activity', 30_000)
  const { data: reconR } = useApi<any>('/api/v2/broker-orders/shadow-recon', 60_000)
  const [local, setLocal] = useState<ManualState>({})
  const [msg, setMsg] = useState('')
  const [filter, setFilter] = useState<'ALL' | TicketStatus>('ALL')

  useEffect(() => {
    try { setLocal(JSON.parse(localStorage.getItem(LS_KEY) || '{}')) } catch { setLocal({}) }
  }, [])
  const save = (next: ManualState) => { setLocal(next); localStorage.setItem(LS_KEY, JSON.stringify(next)) }

  const drafts = useMemo(() => (((draftsR as any)?.drafts ?? []) as any[]).map(normDraft).filter(d => d.symbol), [draftsR])
  const activity = ((activityR as any)?.activity ?? []) as any[]
  const rows = drafts.map(t => ({ t, status: statusFor(t, local, activity), hit: matchActivity(t, activity) }))
  const visible = filter === 'ALL' ? rows : rows.filter(r => r.status === filter)
  const watchlistText = visible.map(r => r.t.symbol).filter((v, i, a) => a.indexOf(v) === i).join('\n') + '\n'
  const lastRun = (reconR as any)?.runs?.[0]

  const setStatus = (id: string, status: TicketStatus) => {
    const next = { ...local, [id]: { ...(local[id] ?? {}), status, markedPlacedAt: status === 'OPERATOR_MARKED_PLACED' ? new Date().toISOString() : local[id]?.markedPlacedAt } }
    save(next)
  }

  const prepare = (t: ReturnType<typeof normDraft>) => {
    setStatus(t.id, 'GENERATED')
    copy(ticketText(t), setMsg)
  }

  const exportHtml = (t: ReturnType<typeof normDraft>, status: TicketStatus) => {
    const tj = ticketJson(t, status)
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>Trade AI Manual ToS Ticket ${t.symbol}</title><style>body{font-family:Arial;background:#0b1020;color:#e5e7eb;padding:24px} .card{border:1px solid #334155;border-radius:12px;padding:18px;max-width:820px;background:#111827} .big{font-size:24px;font-weight:800} code,pre{font-family:monospace;background:#020617;padding:8px;border-radius:6px;display:block;white-space:pre-wrap} .warn{color:#f59e0b}</style></head><body><div class="card"><div class="big">${ticketText(t)}</div><p class="warn">Manual Thinkorswim setup only. Confirm account, symbol, quantity, order type, price, stop and targets before placing.</p><h3>Checklist</h3><ol><li>Open Thinkorswim.</li><li>Select account: <b>${t.account}</b>.</li><li>Enter symbol: <b>${t.symbol}</b>.</li><li>Enter ticket exactly as below.</li><li>After entry, return to Trade AI and mark placed. Schwab read-only capture must observe it before it becomes broker-confirmed.</li></ol><h3>Ticket</h3><code>${ticketText(t)}</code><h3>JSON</h3><pre>${JSON.stringify(tj, null, 2)}</pre></div></body></html>`
    download(`tradeai_manual_tos_${t.symbol}_${t.qty}sh.html`, 'text/html', html)
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 800, color: T.text }}>Manual Execution Desk</div>
          <div style={{ fontSize: 11, color: T.dim }}>Trade AI prepares proposals and Thinkorswim tickets. Operator enters orders manually. Schwab API remains read-only and is used only to recognize what happened.</div>
        </div>
        <button onClick={() => refetch()} style={btn('var(--bg2)', T.blue)}>refresh drafts</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(120px, 1fr))', gap: 8, marginBottom: 12 }}>
        {(['ALL','READY','GENERATED','OPERATOR_MARKED_PLACED','BROKER_OBSERVED'] as const).map(f => {
          const n = f === 'ALL' ? rows.length : rows.filter(r => r.status === f).length
          return <button key={f} onClick={() => setFilter(f as any)} style={{ ...btn(filter === f ? T.blue : 'var(--bg2)'), padding: '8px 10px' }}>{f.replace('OPERATOR_MARKED_PLACED','PLACED').replace('_',' ')} · {n}</button>
        })}
      </div>

      <div style={{ padding: 10, border: `1px solid ${T.border}`, borderRadius: 8, background: T.card, marginBottom: 12, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 11, color: T.dim }}>Exports for visible rows:</span>
        <button style={btn('#1d4ed8')} onClick={() => copy(watchlistText, setMsg)}>copy ToS watchlist symbols</button>
        <button style={btn('#334155')} onClick={() => download('tradeai_tos_watchlist.txt', 'text/plain', watchlistText)}>download watchlist .txt</button>
        <button style={btn('#334155')} onClick={() => download('tradeai_manual_tickets.csv', 'text/csv', ticketCsv(visible.map(r => r.t)))}>download setup CSV</button>
        {msg && <span style={{ fontSize: 10, color: T.green }}>{msg}</span>}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        <div style={{ padding: 12, border: `1px solid ${T.border}`, borderRadius: 8, background: T.card }}>
          <div style={{ fontSize: 12, fontWeight: 800, color: T.text }}>Lifecycle</div>
          <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.6, marginTop: 4 }}>READY → GENERATED → OPERATOR MARKED PLACED → BROKER OBSERVED → tracked as manual ToS / Schwab-confirmed. A click never creates truth by itself; read-only Schwab activity is the confirmation source.</div>
        </div>
        <div style={{ padding: 12, border: `1px solid ${T.border}`, borderRadius: 8, background: T.card }}>
          <div style={{ fontSize: 12, fontWeight: 800, color: T.text }}>Read-only reconciliation</div>
          <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.6, marginTop: 4 }}>Last shadow run: {lastRun ? `#${lastRun.id} · orders ${lastRun.orders_seen} · matched ${lastRun.matched} · mismatched ${lastRun.mismatched} · ${lastRun.status}` : 'none yet'}</div>
        </div>
      </div>

      {visible.length === 0 ? <div style={{ padding: 16, color: T.dim, border: `1px solid ${T.border}`, borderRadius: 8, background: T.card }}>No draft tickets in this bucket. Create one from Trading → Broker Orders, or let proposals generate Schwab/ToS drafts.</div> : null}
      {visible.map(({ t, status, hit }) => (
        <div key={t.id} style={{ border: `1px solid ${status === 'BROKER_OBSERVED' ? T.green : status === 'OPERATOR_MARKED_PLACED' ? T.amber : T.border}`, borderRadius: 9, background: T.card, padding: 12, marginBottom: 10 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 14, fontWeight: 900, color: T.text, ...mono }}>{ticketText(t)}</span>
            <Pill status={status} />
            <span style={{ fontSize: 9, color: T.amber, background: 'rgba(245,158,11,.12)', padding: '2px 7px', borderRadius: 4 }}>{t.account.replace('schwab_', '').replace(/_/g, ' ').toUpperCase()}</span>
            <span style={{ flex: 1 }} />
            <button onClick={() => prepare(t)} style={btn('#1d4ed8')}>prepare + copy ticket</button>
            <button onClick={() => exportHtml(t, status)} style={btn('#334155')}>HTML ticket</button>
            <button onClick={() => download(`tradeai_manual_tos_${t.symbol}.json`, 'application/json', JSON.stringify(ticketJson(t, status), null, 2) + '\n')} style={btn('#334155')}>JSON</button>
            <button onClick={() => setStatus(t.id, 'OPERATOR_MARKED_PLACED')} style={btn('#92400e')}>mark placed hint</button>
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 7 }}>
            {t.stop != null && <span style={{ fontSize: 9, color: T.red, background: 'rgba(239,68,68,.12)', padding: '2px 6px', borderRadius: 4 }}>stop {Number(t.stop).toFixed(2)}</span>}
            {t.trail && <span style={{ fontSize: 9, color: T.purple, background: 'rgba(167,139,250,.12)', padding: '2px 6px', borderRadius: 4 }}>trail {t.trail.offset}{t.trail.type === 'PERCENT' ? '%' : ''}</span>}
            {t.targets.map((x: any, i: number) => <span key={i} style={{ fontSize: 9, color: T.green, background: 'rgba(34,197,94,.12)', padding: '2px 6px', borderRadius: 4 }}>target {i + 1}: {Number(x.price).toFixed(2)}{x.qty_pct && x.qty_pct !== 100 ? ` (${x.qty_pct}%)` : ''}</span>)}
          </div>
          {hit ? <div style={{ marginTop: 7, fontSize: 10, color: T.green }}>Schwab read-only activity observed: {String(hit.captured_at ?? '').slice(0, 16)} · {hit.kind} · {hit.status}</div> : null}
          {status === 'OPERATOR_MARKED_PLACED' && !hit ? <div style={{ marginTop: 7, fontSize: 10, color: T.amber }}>Marked placed locally, but no matching Schwab activity has been observed yet. Keep this as pending, not active truth.</div> : null}
          <details style={{ marginTop: 8 }}>
            <summary style={{ fontSize: 9, color: T.dim, cursor: 'pointer' }}>show manual ticket JSON</summary>
            <pre style={{ fontSize: 9, color: '#cbd5e1', background: '#020617', borderRadius: 6, padding: 8, overflow: 'auto', ...mono }}>{JSON.stringify(ticketJson(t, status), null, 2)}</pre>
          </details>
        </div>
      ))}

      <div style={{ marginTop: 12, fontSize: 8.5, color: T.dim }}>Source: /api/v2/broker-orders/drafts and /api/v2/broker-orders/activity. This page creates manual tickets and exports only; it has no Schwab submit/send/place/cancel route.</div>
    </div>
  )
}
