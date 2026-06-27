import { useEffect, useState, type CSSProperties } from 'react'
import SetupFamilyPicker from './SetupFamilyPicker'
import PsychologyBeforePicker from './PsychologyBeforePicker'
import MarketRegimePicker from './MarketRegimePicker'
import IndustryPicker from './IndustryPicker'
import TradePlanPicker from './TradePlanPicker'
import TagChipGrid from './TagChipGrid'
import {
  SETUP_TYPE_GROUPS, SETUP_TYPE_CONFIG, MISTAKE_CONFIG, STRENGTH_CONFIG,
  MISTAKE_DEFAULTS, STRENGTH_DEFAULTS, planImpliesFollowed,
} from '../../lib/journalTagVocab'

const LABEL: CSSProperties = { fontSize: 12, fontWeight: 700, color: 'var(--text1)', marginBottom: 6, letterSpacing: '0.02em' }
const NUM_INPUT: CSSProperties = { width: 72, marginLeft: 6, fontSize: 14, padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }

const EMPTY_FORM = {
  setup_family: '',
  setup_types: [] as string[],
  industry: '',
  trade_plan: '',
  market_regime: '',
  emotion_before: '',
  mistake_tags: [] as string[],
  strength_tags: [] as string[],
  planned_r: null as number | null,
  realized_r: null as number | null,
  trade_rating: null as number | null,
  lesson_learned: '',
  what_went_well: '',
  what_to_improve: '',
}

export default function BulkTagModal({
  tradeKeys,
  label,
  symbol,
  days,
  account,
  onClose,
  onApplied,
}: {
  tradeKeys: string[]
  label: string
  symbol?: string
  days: number
  account?: string
  onClose: () => void
  onApplied: (count: number) => void
}) {
  const [form, setForm] = useState(EMPTY_FORM)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [seedKey, setSeedKey] = useState('')

  useEffect(() => {
    const tk = tradeKeys[0]
    if (!tk) {
      setLoading(false)
      return
    }
    setSeedKey(tk)
    const enc = tk.replace(/:/g, '__')
    setLoading(true)
    fetch(`/api/v2/journal/review/${enc}`)
      .then(r => r.json())
      .then(d => {
        const r = d?.data?.review || d?.review || {}
        setForm({
          setup_family: r.setup_family || '',
          setup_types: r.setup_types || [],
          industry: r.payload?.industry || r.catalyst_type || '',
          trade_plan: r.payload?.trade_plan || '',
          market_regime: r.market_regime || '',
          emotion_before: r.emotion_before || '',
          mistake_tags: r.mistake_tags || [],
          strength_tags: r.strength_tags || [],
          planned_r: r.planned_r ?? null,
          realized_r: r.realized_r ?? null,
          trade_rating: r.payload?.trade_rating ?? null,
          lesson_learned: r.lesson_learned || '',
          what_went_well: r.payload?.what_went_well || '',
          what_to_improve: r.payload?.what_to_improve || '',
        })
      })
      .catch(() => setForm(EMPTY_FORM))
      .finally(() => setLoading(false))
  }, [tradeKeys.join('|')])

  const applyAll = async () => {
    setSaving(true)
    try {
      const followed = planImpliesFollowed(form.trade_plan)
      const r = await fetch('/api/v2/journal/tagging-queue/bulk-tag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trade_keys: tradeKeys,
          symbol: symbol || undefined,
          days,
          account: account || undefined,
          tags: {
            setup_family: form.setup_family || undefined,
            setup_types: form.setup_types.length ? form.setup_types : undefined,
            market_regime: form.market_regime || undefined,
            emotion_before: form.emotion_before || undefined,
            industry: form.industry || undefined,
            mistake_tags: form.mistake_tags.length ? form.mistake_tags : undefined,
            strength_tags: form.strength_tags.length ? form.strength_tags : undefined,
            planned_r: form.planned_r ?? undefined,
            realized_r: form.realized_r ?? undefined,
            lesson_learned: form.lesson_learned || undefined,
            trade_plan: form.trade_plan || undefined,
            followed_plan: followed ?? undefined,
            trade_rating: form.trade_rating ?? undefined,
            what_went_well: form.what_went_well || undefined,
            what_to_improve: form.what_to_improve || undefined,
          },
        }),
      }).then(x => x.json())
      const res = r?.data ?? r
      onApplied(res?.applied ?? tradeKeys.length)
    } finally {
      setSaving(false)
    }
  }

  const title = symbol ? `Tag all ${symbol} — ${tradeKeys.length} trades` : `Bulk tag — ${tradeKeys.length} trades`

  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)', zIndex: 1100 }} />
      <div style={{
        position: 'fixed', top: '3vh', left: '50%', transform: 'translateX(-50%)',
        width: 920, maxWidth: '96vw', maxHeight: '94vh', overflow: 'auto',
        background: 'var(--bg0)', border: '1px solid var(--border)', borderRadius: 12,
        zIndex: 1101, boxShadow: '0 20px 60px rgba(0,0,0,.6)',
      }}>
        <div style={{
          padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex',
          justifyContent: 'space-between', alignItems: 'center', position: 'sticky', top: 0,
          background: 'var(--bg0)', zIndex: 2,
        }}>
          <div>
            <div style={{ fontSize: 20, fontWeight: 800, color: symbol ? '#e9d5ff' : 'var(--text0)' }}>{title}</div>
            <div style={{ fontSize: 13, color: 'var(--text2)', marginTop: 4 }}>
              {label} — edit tags below (loaded from first trade), then <strong>Apply to all {tradeKeys.length}</strong>
            </div>
          </div>
          <button onClick={onClose} style={{ fontSize: 16, background: 'none', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text3)', cursor: 'pointer', width: 32, height: 32 }}>×</button>
        </div>

        <div style={{ padding: 18, borderBottom: '1px solid var(--border)', background: 'rgba(168,85,247,.08)' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#e9d5ff', lineHeight: 1.5 }}>
            Edit once → apply to every selected trade. Template from: <span style={{ fontFamily: 'monospace' }}>{seedKey || '—'}</span>
          </div>
        </div>

        {loading ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text2)' }}>Loading tags from first trade…</div>
        ) : (
          <div style={{ padding: 18 }}>
            <div style={LABEL}>Strategy / setup family</div>
            <SetupFamilyPicker value={form.setup_family} onChange={v => setForm(f => ({ ...f, setup_family: v }))} />

            <div style={LABEL}>Industry / sector</div>
            <IndustryPicker value={form.industry} onChange={v => setForm(f => ({ ...f, industry: v }))} />

            <TagChipGrid
              label="Setup types (tap all that apply)"
              groups={SETUP_TYPE_GROUPS}
              config={SETUP_TYPE_CONFIG}
              selected={form.setup_types}
              onChange={tags => setForm(f => ({ ...f, setup_types: tags }))}
              color="#60a5fa"
            />

            <div style={LABEL}>Trade plan</div>
            <TradePlanPicker value={form.trade_plan} onChange={v => setForm(f => ({ ...f, trade_plan: v }))} />

            <div style={LABEL}>Psychology (before entry)</div>
            <PsychologyBeforePicker value={form.emotion_before} onChange={v => setForm(f => ({ ...f, emotion_before: v }))} />

            <div style={LABEL}>Market regime</div>
            <MarketRegimePicker value={form.market_regime} onChange={v => setForm(f => ({ ...f, market_regime: v }))} />

            <TagChipGrid
              label="Mistakes"
              flat={[...MISTAKE_DEFAULTS]}
              config={MISTAKE_CONFIG}
              selected={form.mistake_tags}
              onChange={tags => setForm(f => ({ ...f, mistake_tags: tags }))}
              color="#ef4444"
            />

            <TagChipGrid
              label="Strengths"
              flat={[...STRENGTH_DEFAULTS]}
              config={STRENGTH_CONFIG}
              selected={form.strength_tags}
              onChange={tags => setForm(f => ({ ...f, strength_tags: tags }))}
              color="#22c55e"
            />

            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
              <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text1)' }}>
                Planned R
                <input type="number" step="0.1" value={form.planned_r ?? ''} onChange={e => setForm(f => ({ ...f, planned_r: e.target.value ? Number(e.target.value) : null }))} style={NUM_INPUT} />
              </label>
              <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text1)' }}>
                Realized R
                <input type="number" step="0.1" value={form.realized_r ?? ''} onChange={e => setForm(f => ({ ...f, realized_r: e.target.value ? Number(e.target.value) : null }))} style={NUM_INPUT} />
              </label>
              <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text1)' }}>
                Rating (1–5)
                <input type="number" min={1} max={5} value={form.trade_rating ?? ''} onChange={e => setForm(f => ({ ...f, trade_rating: e.target.value ? Number(e.target.value) : null }))} style={{ ...NUM_INPUT, width: 56 }} />
              </label>
            </div>

            <div style={LABEL}>Lesson learned (optional — same on all)</div>
            <textarea
              value={form.lesson_learned}
              onChange={e => setForm(f => ({ ...f, lesson_learned: e.target.value }))}
              placeholder="Lesson applied to all selected trades…"
              style={{ width: '100%', minHeight: 50, marginBottom: 12, fontSize: 13, padding: 10, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }}
            />
          </div>
        )}

        <div style={{
          padding: '14px 18px', borderTop: '1px solid var(--border)', display: 'flex', gap: 12,
          alignItems: 'center', position: 'sticky', bottom: 0, background: 'var(--bg0)',
        }}>
          <button
            disabled={saving || loading}
            onClick={applyAll}
            style={{ fontSize: 16, fontWeight: 800, padding: '12px 24px', borderRadius: 8, border: 'none', background: '#a855f7', color: '#fff', cursor: saving ? 'wait' : 'pointer' }}
          >
            {saving ? 'Applying…' : `Apply to all ${tradeKeys.length} trades`}
          </button>
          <button onClick={onClose} style={{ fontSize: 14, padding: '10px 16px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg2)', cursor: 'pointer' }}>
            Cancel
          </button>
        </div>
      </div>
    </>
  )
}