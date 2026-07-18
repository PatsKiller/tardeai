import { useState } from 'react'
import { BB, T, DASH, numStyle } from '../../lib/watchTokens'

// Defense v3 R5 — the recommendations rail. Per-account tabs, four groups, every card
// complete-or-absent (the engine's field guard enforces; this component renders what
// survives). SHADOW chips until promote. Advisory only — cards route, never execute.

const GROUPS: Array<{ key: string; label: string; color: string }> = [
  { key: 'get_into', label: 'Get Into', color: BB.green },
  { key: 'protect', label: 'Protect', color: BB.amber },
  { key: 'short_side', label: 'Short-Side', color: BB.red },
  { key: 'income', label: 'Income', color: T.link },
]

const chip: React.CSSProperties = {
  fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.05em',
  borderRadius: 2, padding: '1px 6px', border: `1px solid ${BB.border}`, color: BB.text2,
}

function Card({ c }: { c: any }) {
  const [open, setOpen] = useState(false)
  const g = GROUPS.find(x => x.key === c.group)
  return (
    <div style={{ border: `1px solid ${BB.border}`, borderLeft: `3px solid ${g?.color || BB.text3}`, borderRadius: 2, padding: '8px 10px', background: BB.bg }}>
      <div onClick={() => setOpen(o => !o)} style={{ cursor: 'pointer' }}>
        <div style={{ fontSize: DASH.data + 1, fontWeight: 700, color: BB.text1, marginBottom: 4 }}>{c.title}</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
          <span style={{ ...chip, color: BB.amber, borderColor: BB.amber }}>{c.mode}</span>
          <span style={chip}>{c.direction}</span>
          <span style={chip}>{c.size_band.split('(')[0].trim()}</span>
        </div>
        <div style={{ fontSize: DASH.data, color: BB.text2 }}>
          {c.instruments.map((i: any) => (
            <span key={i.symbol + i.kind} style={{ marginRight: 10 }}>
              <b style={{ ...numStyle, color: BB.text1 }}>{i.symbol}</b>
              <span style={{ color: BB.text3 }}> {i.kind}</span>
            </span>
          ))}
          <span style={{ color: BB.text3 }}>{open ? '▾' : '▸'} factors</span>
        </div>
      </div>
      {open && (
        <div style={{ marginTop: 6, paddingTop: 6, borderTop: `1px solid ${BB.borderHair}`, fontSize: DASH.data, color: BB.text2, display: 'flex', flexDirection: 'column', gap: 3 }}>
          {c.factors.map((f: any, i: number) => (
            <div key={i}><span style={{ color: BB.text3 }}>{f.name}:</span> <b>{String(f.value)}</b></div>
          ))}
          <div><span style={{ color: BB.text3 }}>entry:</span> {c.entry_logic}</div>
          <div><span style={{ color: BB.text3 }}>invalidation:</span> {c.invalidation}</div>
          {c.instruments.filter((i: any) => i.note).map((i: any) => (
            <div key={i.symbol}><span style={{ color: BB.text3 }}>{i.symbol}:</span> {i.note}</div>
          ))}
          {Object.entries(c.routes || {}).map(([k, v]) => (
            <div key={k}><span style={{ color: BB.text3 }}>route/{k}:</span> {String(v)}</div>
          ))}
          <div style={{ color: BB.text3 }}>as of {c.as_of} · valid: {c.accounts.join(', ')}</div>
        </div>
      )}
    </div>
  )
}

export default function RecommendationsRail({ recs }: { recs: any }) {
  const [tab, setTab] = useState<string>('all')
  const accounts: Record<string, string> = recs?.accounts || {}
  const groups: Record<string, any[]> = recs?.groups || {}
  const all = Object.values(groups).flat()
  const forTab = (cards: any[]) => tab === 'all' ? cards : cards.filter(c => c.accounts.includes(tab))
  const countFor = (key: string) => key === 'all' ? all.length : all.filter(c => c.accounts.includes(key)).length

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '10px 12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: DASH.panel, fontWeight: 800, color: BB.text1 }}>Recommendations</span>
        <span style={{ fontSize: DASH.data, color: BB.text3 }}>{recs?.shadow_note || ''}</span>
      </div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}>
        {[['all', 'All'], ...Object.entries(accounts).filter(([k]) => k !== 'alpaca_paper')].map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)} style={{
            fontSize: DASH.data, fontWeight: 700, padding: '3px 10px', cursor: 'pointer', borderRadius: 2,
            color: tab === key ? BB.text1 : BB.text3, background: tab === key ? BB.border : 'transparent',
            border: `1px solid ${BB.border}`,
          }}>
            {label} <span style={{ ...numStyle, color: tab === key ? BB.text2 : BB.text3 }}>{countFor(key)}</span>
          </button>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
        {GROUPS.map(g => {
          const cards = forTab(groups[g.key] || [])
          return (
            <div key={g.key}>
              <div style={{ fontSize: DASH.section, fontWeight: 800, color: g.color, marginBottom: 6 }}>
                {g.label} <span style={{ ...numStyle, color: BB.text3, fontSize: DASH.data }}>{cards.length}</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {cards.length === 0 && (
                  <div style={{ fontSize: DASH.data, color: BB.text3, border: `1px dashed ${BB.borderHair}`, borderRadius: 2, padding: '8px 10px' }}>
                    {tab !== 'all'
                      ? `nothing valid for ${accounts[tab] || tab} in this group today`
                      : (recs?.empty_reasons?.[g.key] || 'none today')}
                  </div>
                )}
                {cards.map(c => <Card key={c.id} c={c} />)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
