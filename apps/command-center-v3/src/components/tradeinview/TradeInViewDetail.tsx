import { useEffect, useState } from 'react'
import { fmt$ } from '../../lib/format'

type Tab = 'Overview' | 'Review' | 'Reflection'

const SETUPS = ['Breakout', 'Pullback', 'Trend Follow', 'Mean Reversion', 'Momentum', 'Earnings Play', 'Swing', 'Scalp']
const MISTAKES = ['FOMO', 'Revenge', 'Oversize', 'Chased', 'Moved Stop', 'Early Exit (fear)', 'No Stop', 'Overtrading']
const STRENGTHS = ['Patient Entry', 'Good Size', 'Let Winner Run', 'Cut Loss Fast', 'Followed Plan']

export default function TradeInViewDetail({ trade, onClose, onReplay, onSaved }: {
  trade: any
  onClose: () => void
  onReplay?: () => void
  onSaved?: () => void
}) {
  const [tab, setTab] = useState<Tab>('Overview')
  const [form, setForm] = useState<any>({})
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [attachments, setAttachments] = useState<any[]>([])

  const tradeKey = trade.trade_key || `${trade.symbol}:${trade.account ?? trade.na}:${trade.exitDate ?? trade.close_date}`

  useEffect(() => {
    if (!trade) return
    const enc = tradeKey.replace(/:/g, '__')
    fetch(`/api/v2/journal/review/${enc}`).then(r => r.json()).then(d => {
      const r = d?.data?.review || d?.review || {}
      setForm({
        trade_key: tradeKey, symbol: trade.symbol, account: trade.account ?? trade.na,
        closed_date: trade.exitDate ?? trade.close_date,
        setup_types: r.setup_types || [], setup_family: r.setup_family || '',
        market_regime: r.market_regime || '', planned_r: r.planned_r, realized_r: r.realized_r,
        emotion_before: r.emotion_before || '', emotion_during: r.emotion_during || '', emotion_after: r.emotion_after || '',
        followed_plan: r.followed_plan, lesson_learned: r.lesson_learned || '', review_notes: r.review_notes || '',
        what_went_well: r.payload?.what_went_well || '', what_to_improve: r.payload?.what_to_improve || '',
        trade_rating: r.payload?.trade_rating || null,
        mistake_tags: r.mistake_tags || [], strength_tags: r.strength_tags || [],
      })
    }).catch(() => setForm({ trade_key: tradeKey, symbol: trade.symbol, account: trade.account ?? trade.na, closed_date: trade.exitDate, mistake_tags: [], strength_tags: [], setup_types: [] }))
    fetch(`/api/v2/journal/attachments?trade_key=${encodeURIComponent(tradeKey)}`).then(r => r.json())
      .then(d => setAttachments(d?.attachments || []))
  }, [trade, tradeKey])

  const uploadAttachment = (file: File) => {
    const r = new FileReader()
    r.onload = async () => {
      const b64 = String(r.result || '')
      await fetch('/api/v2/journal/attachments', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trade_key: tradeKey, filename: file.name, content_b64: b64, mime_type: file.type, kind: file.type.startsWith('image/') ? 'screenshot' : 'file' }),
      })
      const d = await fetch(`/api/v2/journal/attachments?trade_key=${encodeURIComponent(tradeKey)}`).then(x => x.json())
      setAttachments(d?.attachments || [])
    }
    r.readAsDataURL(file)
  }

  const save = async () => {
    setSaving(true)
    const payload = { ...form, payload: { what_went_well: form.what_went_well, what_to_improve: form.what_to_improve, trade_rating: form.trade_rating } }
    const r = await fetch('/api/v2/journal/review', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).then(x => x.json())
    setSaving(false)
    if (r.ok) { setMsg('✓ saved'); onSaved?.() } else setMsg('⛔ failed')
  }

  const tog = (arr: string[], v: string) => arr.includes(v) ? arr.filter(x => x !== v) : [...arr, v]
  const Chip = ({ label, on, color, click }: any) => (
    <button onClick={click} style={{ fontSize: 8, padding: '2px 6px', borderRadius: 10, border: `1px solid ${on ? color : 'var(--border)'}`, background: on ? color + '22' : 'var(--bg2)', color: on ? color : 'var(--text3)', cursor: 'pointer' }}>{label}</button>
  )

  if (!trade) return null

  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)', zIndex: 1000 }} />
      <div style={{ position: 'fixed', top: '4vh', left: '50%', transform: 'translateX(-50%)', width: 920, maxWidth: '96vw', maxHeight: '92vh', overflow: 'auto', background: 'var(--bg0)', border: '1px solid var(--border)', borderRadius: 12, zIndex: 1001, boxShadow: '0 20px 60px rgba(0,0,0,.6)' }}>
        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', position: 'sticky', top: 0, background: 'var(--bg0)', zIndex: 2 }}>
          <div>
            <span style={{ fontSize: 20, fontWeight: 800, fontFamily: 'monospace' }}>{trade.symbol}</span>
            <span style={{ marginLeft: 10, fontSize: 14, fontWeight: 700, color: (trade.pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(trade.pnl, 2)}</span>
            <span style={{ marginLeft: 8, fontSize: 10, color: 'var(--text3)' }}>{trade.na ?? trade.account} · {trade.exitDate ?? 'open'}</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {onReplay && <button onClick={onReplay} style={{ fontSize: 10, padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', cursor: 'pointer' }}>📈 Replay</button>}
            <button onClick={onClose} style={{ fontSize: 16, background: 'none', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text3)', cursor: 'pointer', width: 28, height: 28 }}>×</button>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4, padding: '8px 18px', borderBottom: '1px solid var(--border)' }}>
          {(['Overview', 'Review', 'Reflection'] as Tab[]).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{ fontSize: 10, padding: '4px 12px', borderRadius: 4, border: 'none', cursor: 'pointer', background: tab === t ? 'rgba(96,165,250,.2)' : 'var(--bg2)', color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400 }}>{t}</button>
          ))}
        </div>
        <div style={{ padding: 18 }}>
          {tab === 'Overview' && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, fontSize: 10 }}>
              {[['Entry', trade.ep ?? trade.buy_price], ['Exit', trade.xp ?? trade.sell_price], ['Shares', trade.shares], ['Strategy', trade.strat], ['Entry grade', trade.eg], ['Exit grade', trade.xg], ['Hold', trade.holdDays != null ? `${trade.holdDays}d` : trade.holdMin], ['Source', trade.source]].map(([l, v]) => (
                <div key={String(l)} style={{ background: 'var(--bg1)', padding: 8, borderRadius: 6 }}>
                  <div style={{ fontSize: 8, color: 'var(--text3)' }}>{l}</div>
                  <div style={{ fontWeight: 600 }}>{v ?? '—'}</div>
                </div>
              ))}
            </div>
          )}
          {tab === 'Review' && (
            <div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 6 }}>SETUP TYPES</div>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}>{SETUPS.map(s => <Chip key={s} label={s} on={(form.setup_types || []).includes(s)} color="#60a5fa" click={() => setForm((f: any) => ({ ...f, setup_types: tog(f.setup_types || [], s) }))} />)}</div>
              <input value={form.market_regime || ''} onChange={e => setForm((f: any) => ({ ...f, market_regime: e.target.value }))} placeholder="Market regime" style={{ width: '100%', marginBottom: 8, fontSize: 10, padding: 6, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
              <div style={{ fontSize: 9, color: '#ef4444', marginBottom: 4 }}>MISTAKES</div>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}>{MISTAKES.map(m => <Chip key={m} label={m} on={(form.mistake_tags || []).includes(m)} color="#ef4444" click={() => setForm((f: any) => ({ ...f, mistake_tags: tog(f.mistake_tags || [], m) }))} />)}</div>
              <div style={{ fontSize: 9, color: '#22c55e', marginBottom: 4 }}>STRENGTHS</div>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}>{STRENGTHS.map(s => <Chip key={s} label={s} on={(form.strength_tags || []).includes(s)} color="#22c55e" click={() => setForm((f: any) => ({ ...f, strength_tags: tog(f.strength_tags || [], s) }))} />)}</div>
              <div style={{ display: 'flex', gap: 12 }}>
                <label style={{ fontSize: 10 }}>Planned R <input type="number" step="0.1" value={form.planned_r ?? ''} onChange={e => setForm((f: any) => ({ ...f, planned_r: e.target.value ? Number(e.target.value) : null }))} style={{ width: 60, marginLeft: 4 }} /></label>
                <label style={{ fontSize: 10 }}>Realized R <input type="number" step="0.1" value={form.realized_r ?? ''} onChange={e => setForm((f: any) => ({ ...f, realized_r: e.target.value ? Number(e.target.value) : null }))} style={{ width: 60, marginLeft: 4 }} /></label>
                <label style={{ fontSize: 10 }}>Rating (1-5) <input type="number" min={1} max={5} value={form.trade_rating ?? ''} onChange={e => setForm((f: any) => ({ ...f, trade_rating: e.target.value ? Number(e.target.value) : null }))} style={{ width: 40, marginLeft: 4 }} /></label>
              </div>
            </div>
          )}
          {tab === 'Reflection' && (
            <div>
              <textarea value={form.what_went_well || ''} onChange={e => setForm((f: any) => ({ ...f, what_went_well: e.target.value }))} placeholder="What I did well…" style={{ width: '100%', minHeight: 60, marginBottom: 8, fontSize: 11, padding: 8, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
              <textarea value={form.what_to_improve || ''} onChange={e => setForm((f: any) => ({ ...f, what_to_improve: e.target.value }))} placeholder="What I'll improve…" style={{ width: '100%', minHeight: 60, marginBottom: 8, fontSize: 11, padding: 8, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
              <textarea value={form.lesson_learned || ''} onChange={e => setForm((f: any) => ({ ...f, lesson_learned: e.target.value }))} placeholder="Lesson learned…" style={{ width: '100%', minHeight: 50, fontSize: 11, padding: 8, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
            </div>
          )}
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>Attachments (screenshot / file)</div>
            <input type="file" accept="image/*,.pdf,.txt" onChange={e => { const f = e.target.files?.[0]; if (f) uploadAttachment(f) }} style={{ fontSize: 9 }} />
            {attachments.length > 0 && <div style={{ fontSize: 9, marginTop: 4, color: 'var(--text2)' }}>{attachments.map((a: any) => a.filename).join(', ')}</div>}
          </div>
          <div style={{ marginTop: 14, display: 'flex', gap: 10, alignItems: 'center' }}>
            <button disabled={saving} onClick={save} style={{ fontSize: 11, fontWeight: 700, padding: '6px 16px', borderRadius: 6, border: 'none', background: '#60a5fa', color: '#fff', cursor: 'pointer' }}>{saving ? 'Saving…' : 'Save review'}</button>
            {msg && <span style={{ fontSize: 10, color: msg.startsWith('✓') ? '#22c55e' : '#ef4444' }}>{msg}</span>}
          </div>
        </div>
      </div>
    </>
  )
}