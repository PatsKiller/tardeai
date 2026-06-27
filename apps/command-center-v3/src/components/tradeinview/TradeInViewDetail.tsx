import { useEffect, useState, type CSSProperties } from 'react'
import { fmt$ } from '../../lib/format'
import SetupFamilyPicker from './SetupFamilyPicker'
import PsychologyBeforePicker from './PsychologyBeforePicker'
import MarketRegimePicker from './MarketRegimePicker'
import TradeReportReadiness from './TradeReportReadiness'
import AiTradeCritique from './AiTradeCritique'
import IndustryPicker from './IndustryPicker'
import TradePlanPicker from './TradePlanPicker'
import TagChipGrid from './TagChipGrid'
import {
  SETUP_TYPE_GROUPS, SETUP_TYPE_CONFIG, MISTAKE_CONFIG, STRENGTH_CONFIG,
  MISTAKE_DEFAULTS, STRENGTH_DEFAULTS, planImpliesFollowed,
} from '../../lib/journalTagVocab'

type Tab = 'Overview' | 'Review' | 'Reflection'

const LABEL: CSSProperties = { fontSize: 12, fontWeight: 700, color: 'var(--text1)', marginBottom: 6, letterSpacing: '0.02em' }
const INPUT: CSSProperties = { width: '100%', marginBottom: 12, fontSize: 14, padding: '10px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }
const NUM_INPUT: CSSProperties = { width: 72, marginLeft: 6, fontSize: 14, padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }

export default function TradeInViewDetail({ trade, onClose, onReplay, onSaved, initialTab, focusTagging }: {
  trade: any
  onClose: () => void
  onReplay?: () => void
  onSaved?: () => void
  initialTab?: Tab
  focusTagging?: boolean
}) {
  const [tab, setTab] = useState<Tab>(initialTab || 'Overview')
  const [form, setForm] = useState<any>({})
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [attachments, setAttachments] = useState<any[]>([])
  const [tagScore, setTagScore] = useState<any>(null)

  const tradeKey = trade.trade_key || `${trade.symbol}:${trade.account ?? trade.na}:${trade.exitDate ?? trade.close_date}`

  useEffect(() => {
    if (!trade) return
    const enc = tradeKey.replace(/:/g, '__')
    fetch(`/api/v2/journal/review/${enc}`).then(r => r.json()).then(d => {
      const r = d?.data?.review || d?.review || {}
      setTagScore(d?.data?.tagging_score ?? d?.tagging_score ?? null)
      setForm({
        trade_key: tradeKey, symbol: trade.symbol, account: trade.account ?? trade.na,
        closed_date: trade.exitDate ?? trade.close_date,
        setup_types: r.setup_types || [], setup_family: r.setup_family || '',
        industry: r.payload?.industry || r.catalyst_type || '',
        trade_plan: r.payload?.trade_plan || '',
        market_regime: r.market_regime || '', planned_r: r.planned_r, realized_r: r.realized_r,
        emotion_before: r.emotion_before || '', emotion_during: r.emotion_during || '', emotion_after: r.emotion_after || '',
        followed_plan: r.followed_plan, lesson_learned: r.lesson_learned || '', review_notes: r.review_notes || '',
        what_went_well: r.payload?.what_went_well || '', what_to_improve: r.payload?.what_to_improve || '',
        trade_rating: r.payload?.trade_rating || null,
        mistake_tags: r.mistake_tags || [], strength_tags: r.strength_tags || [],
      })
    }).catch(() => {
      setTagScore(null)
      setForm({ trade_key: tradeKey, symbol: trade.symbol, account: trade.account ?? trade.na, closed_date: trade.exitDate, mistake_tags: [], strength_tags: [], setup_types: [] })
    })
    fetch(`/api/v2/journal/attachments?trade_key=${encodeURIComponent(tradeKey)}`).then(r => r.json())
      .then(d => setAttachments(d?.attachments || []))
  }, [trade, tradeKey])

  useEffect(() => {
    if (initialTab) setTab(initialTab)
  }, [initialTab, tradeKey])

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
    const payload = {
      ...form,
      catalyst_type: form.industry || undefined,
      followed_plan: planImpliesFollowed(form.trade_plan) ?? form.followed_plan,
      payload: {
        what_went_well: form.what_went_well,
        what_to_improve: form.what_to_improve,
        trade_rating: form.trade_rating,
        industry: form.industry || undefined,
        trade_plan: form.trade_plan || undefined,
        operator_reviewed: true,
        operator_confirmed: true,
      },
    }
    const r = await fetch('/api/v2/journal/review', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).then(x => x.json())
    setSaving(false)
    if (r.ok) {
      const enc = tradeKey.replace(/:/g, '__')
      fetch(`/api/v2/journal/review/${enc}`).then(x => x.json()).then(d => {
        setTagScore(d?.data?.tagging_score ?? d?.tagging_score ?? null)
      }).catch(() => {})
      setMsg(r.tagging_complete ? '✓ saved — reports unlocked for this trade' : '✓ saved — finish missing tags to unlock reports')
      onSaved?.()
    } else setMsg('⛔ failed')
  }

  if (!trade) return null

  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)', zIndex: 1000 }} />
      <div style={{ position: 'fixed', top: '4vh', left: '50%', transform: 'translateX(-50%)', width: 920, maxWidth: '96vw', maxHeight: '92vh', overflow: 'auto', background: 'var(--bg0)', border: '1px solid var(--border)', borderRadius: 12, zIndex: 1001, boxShadow: '0 20px 60px rgba(0,0,0,.6)' }}>
        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', position: 'sticky', top: 0, background: 'var(--bg0)', zIndex: 2 }}>
          <div>
            <span style={{ fontSize: 20, fontWeight: 800, fontFamily: 'monospace' }}>{trade.symbol}</span>
            <span style={{ marginLeft: 10, fontSize: 14, fontWeight: 700, color: (trade.pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(trade.pnl, 2)}</span>
            <span style={{ marginLeft: 8, fontSize: 13, fontWeight: 600, color: 'var(--text1)' }}>{trade.na ?? trade.account} · {trade.exitDate ?? 'open'}</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {onReplay && (
              <button
                onClick={onReplay}
                style={{ fontSize: 13, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: '1px solid rgba(34,197,94,.5)', background: 'rgba(34,197,94,.12)', color: '#86efac', cursor: 'pointer' }}
              >
                📈 Replay
              </button>
            )}
            <button onClick={onClose} style={{ fontSize: 16, background: 'none', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text3)', cursor: 'pointer', width: 28, height: 28 }}>×</button>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4, padding: '8px 18px', borderBottom: '1px solid var(--border)' }}>
          {(['Overview', 'Review', 'Reflection'] as Tab[]).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{ fontSize: 13, padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', background: tab === t ? 'rgba(96,165,250,.2)' : 'var(--bg2)', color: tab === t ? '#60a5fa' : 'var(--text1)', fontWeight: tab === t ? 700 : 500 }}>{t}</button>
          ))}
        </div>
        <div style={{ padding: 18 }}>
          {tab === 'Overview' && (
            <>
            <TradeReportReadiness score={tagScore} />
            <AiTradeCritique tradeKey={tradeKey} symbol={trade.symbol} />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, fontSize: 10 }}>
              {[['Entry', trade.ep ?? trade.buy_price], ['Exit', trade.xp ?? trade.sell_price], ['Shares', trade.shares], ['Strategy', trade.strat], ['Entry grade', trade.eg], ['Exit grade', trade.xg], ['Hold', trade.holdDays != null ? `${trade.holdDays}d` : trade.holdMin], ['Source', trade.source]].map(([l, v]) => (
                <div key={String(l)} style={{ background: 'var(--bg1)', padding: 8, borderRadius: 6 }}>
                  <div style={{ fontSize: 8, color: 'var(--text3)' }}>{l}</div>
                  <div style={{ fontWeight: 600 }}>{v ?? '—'}</div>
                </div>
              ))}
            </div>
            </>
          )}
          {tab === 'Review' && (
            <div style={focusTagging ? { border: '2px solid rgba(96,165,250,.5)', borderRadius: 10, padding: 14, background: 'rgba(96,165,250,.06)' } : undefined}>
              <TradeReportReadiness score={tagScore} />
              {focusTagging && <div style={{ fontSize: 15, fontWeight: 800, color: '#93c5fd', marginBottom: 14, lineHeight: 1.4 }}>Complete tagging — required for report accuracy</div>}
              <div style={LABEL}>Strategy / setup family</div>
              <SetupFamilyPicker
                value={form.setup_family || ''}
                onChange={v => setForm((f: any) => ({ ...f, setup_family: v }))}
              />
              <div style={LABEL}>Industry / sector</div>
              <IndustryPicker
                value={form.industry || ''}
                onChange={v => setForm((f: any) => ({ ...f, industry: v }))}
              />
              <TagChipGrid
                label="Setup types (tap all that apply)"
                groups={SETUP_TYPE_GROUPS}
                config={SETUP_TYPE_CONFIG}
                selected={form.setup_types || []}
                onChange={tags => setForm((f: any) => ({ ...f, setup_types: tags }))}
                color="#60a5fa"
              />
              <div style={LABEL}>Trade plan</div>
              <TradePlanPicker
                value={form.trade_plan || ''}
                onChange={v => setForm((f: any) => ({ ...f, trade_plan: v, followed_plan: planImpliesFollowed(v) ?? f.followed_plan }))}
              />
              <div style={LABEL}>Psychology (before entry)</div>
              <PsychologyBeforePicker
                value={form.emotion_before || ''}
                onChange={v => setForm((f: any) => ({ ...f, emotion_before: v }))}
              />
              <div style={LABEL}>Market regime</div>
              <MarketRegimePicker
                value={form.market_regime || ''}
                onChange={v => setForm((f: any) => ({ ...f, market_regime: v }))}
              />
              <TagChipGrid
                label="Mistakes"
                flat={[...MISTAKE_DEFAULTS]}
                config={MISTAKE_CONFIG}
                selected={form.mistake_tags || []}
                onChange={tags => setForm((f: any) => ({ ...f, mistake_tags: tags }))}
                color="#ef4444"
              />
              <TagChipGrid
                label="Strengths"
                flat={[...STRENGTH_DEFAULTS]}
                config={STRENGTH_CONFIG}
                selected={form.strength_tags || []}
                onChange={tags => setForm((f: any) => ({ ...f, strength_tags: tags }))}
                color="#22c55e"
              />
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
                <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text1)' }}>Planned R <input type="number" step="0.1" value={form.planned_r ?? ''} onChange={e => setForm((f: any) => ({ ...f, planned_r: e.target.value ? Number(e.target.value) : null }))} style={NUM_INPUT} /></label>
                <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text1)' }}>Realized R <input type="number" step="0.1" value={form.realized_r ?? ''} onChange={e => setForm((f: any) => ({ ...f, realized_r: e.target.value ? Number(e.target.value) : null }))} style={NUM_INPUT} /></label>
                <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text1)' }}>Rating (1–5) <input type="number" min={1} max={5} value={form.trade_rating ?? ''} onChange={e => setForm((f: any) => ({ ...f, trade_rating: e.target.value ? Number(e.target.value) : null }))} style={{ ...NUM_INPUT, width: 56 }} /></label>
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
          <div style={{ marginTop: 16 }}>
            <div style={LABEL}>Attachments (screenshot / file)</div>
            <input type="file" accept="image/*,.pdf,.txt" onChange={e => { const f = e.target.files?.[0]; if (f) uploadAttachment(f) }} style={{ fontSize: 13, color: 'var(--text1)' }} />
            {attachments.length > 0 && <div style={{ fontSize: 12, marginTop: 6, color: 'var(--text1)' }}>{attachments.map((a: any) => a.filename).join(', ')}</div>}
          </div>
          <div style={{ marginTop: 18, display: 'flex', gap: 12, alignItems: 'center' }}>
            <button disabled={saving} onClick={save} style={{ fontSize: 15, fontWeight: 800, padding: '10px 22px', borderRadius: 8, border: 'none', background: '#60a5fa', color: '#fff', cursor: 'pointer' }}>{saving ? 'Saving…' : 'Save review'}</button>
            {msg && <span style={{ fontSize: 13, fontWeight: 600, color: msg.startsWith('✓') ? '#22c55e' : '#ef4444' }}>{msg}</span>}
          </div>
        </div>
      </div>
    </>
  )
}