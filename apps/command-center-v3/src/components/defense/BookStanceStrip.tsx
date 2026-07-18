import { useEffect, useState } from 'react'
import { BB, T, DASH, numStyle } from '../../lib/watchTokens'

// Defense v4 L3 — every ≥$10K position carries an explicit stance, INCLUDING HOLD.
// v6 C1/C2 — the ★CORE registry lives here: operator-owned checkboxes (distinct from
// the core_holding strategy enum), one-time seed-confirm modal, instant persist.
// After confirmation the system NEVER auto-designates — only these toggles write.

const STANCE_COLOR: Record<string, string> = {
  HOLD: BB.green, ADD: T.link, TRIM: BB.red, 'TRIM-WATCH': BB.amber, ROTATE: BB.amber, HEDGED: BB.text2,
}

export default function BookStanceStrip({ stances, notDecomposed, ladders }: { stances: any[]; notDecomposed?: any; ladders?: any[] }) {
  const [open, setOpen] = useState<string | null>(null)
  const [coreData, setCoreData] = useState<any>(null)
  const [seedChecks, setSeedChecks] = useState<Record<string, boolean>>({})
  const [toast, setToast] = useState<string | null>(null)

  const loadCore = async () => {
    try {
      const r = await fetch('/api/v2/defense/core')
      const j = await r.json()
      const d = j.data ?? j
      setCoreData(d)
      if (!d.seed_confirmed && d.seed_proposal?.length) {
        setSeedChecks(Object.fromEntries(d.seed_proposal.map((p: any) => [p.symbol, true])))
      }
    } catch { /* fail-open — strip renders without core UI */ }
  }
  useEffect(() => { loadCore() }, [])

  const coreSet = new Set((coreData?.core || []).map((c: any) => c.symbol + '|' + (c.account ?? '')))
  const isCore = (sym: string, acct: string) => coreSet.has(sym + '|') || coreSet.has(sym + '|' + acct)

  const toggleCore = async (sym: string, on: boolean) => {
    await fetch('/api/v2/defense/core/toggle', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, on }),
    })
    setToast(`${sym} ${on ? '★ marked CORE' : 'core designation removed'}`)
    setTimeout(() => setToast(null), 2500)
    loadCore()
  }

  const confirmSeed = async () => {
    const items = Object.entries(seedChecks).filter(([, v]) => v).map(([symbol]) => ({ symbol }))
    await fetch('/api/v2/defense/core/confirm', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm_seed: true, items }),
    })
    setToast(`core registry confirmed — ${items.length} holdings marked ★CORE`)
    setTimeout(() => setToast(null), 3000)
    loadCore()
  }

  if (!stances?.length) return null
  const showSeedModal = coreData && !coreData.seed_confirmed && (coreData.seed_proposal?.length || 0) > 0
  // v5 EL3 — ladder progress inline on the stance chip
  const ladderFor = (sym: string, acct: string) => {
    const lad = (ladders || []).find(l => l.symbol === sym && l.account === acct && l.status === 'open')
    if (!lad) return null
    const armed = (lad.tranches || []).filter((t: any) => t.status === 'armed').length
    const fired = (lad.tranches || []).filter((t: any) => t.status === 'fired').length
    return `T1 ${lad.t1_fraction}% ${lad.t1_status === 'executed' ? '✓' : 'advised'}`
      + (fired ? ` · ${fired} FIRED` : armed ? ` · T2 armed` : '')
  }
  const counts: Record<string, number> = {}
  stances.forEach(s => { counts[s.stance] = (counts[s.stance] || 0) + 1 })
  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '10px 12px', position: 'relative' }}>
      {toast && (
        <div style={{ position: 'absolute', top: 8, right: 12, fontSize: DASH.data, fontWeight: 700, color: BB.text1, background: BB.border, borderRadius: 2, padding: '4px 10px', zIndex: 5 }}>{toast}</div>
      )}
      {showSeedModal && (
        <div style={{ border: `1px solid ${BB.amber}`, borderRadius: 2, padding: '12px 14px', marginBottom: 10 }}>
          <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text1, marginBottom: 4 }}>
            Mark your core holdings — the desk treats these differently
          </div>
          <div style={{ fontSize: DASH.data, color: BB.text2, marginBottom: 8 }}>
            ★CORE positions never receive full-exit advice: trim-ladders only, every confirmed tranche opens a patient
            ({'>'}90-session) re-entry watch, and cleanup never touches them. Suggestions below are pre-checked
            (≥$25K positions + the income sleeve) — confirm once; after that only YOU toggle.
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
            {(coreData.seed_proposal || []).map((p: any) => (
              <label key={p.symbol} style={{ display: 'flex', gap: 5, alignItems: 'center', fontSize: DASH.data, color: BB.text1, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '3px 8px', cursor: 'pointer' }}>
                <input type="checkbox" checked={!!seedChecks[p.symbol]}
                  onChange={e => setSeedChecks(s => ({ ...s, [p.symbol]: e.target.checked }))} />
                <b>{p.symbol}</b>
                <span style={{ ...numStyle, color: BB.text3 }}>${Math.round(p.value / 1000)}K</span>
                <span style={{ fontSize: DASH.chip, color: BB.text3 }}>{p.why}</span>
              </label>
            ))}
          </div>
          <button onClick={confirmSeed} style={{ fontSize: DASH.data, fontWeight: 800, color: BB.text0, background: BB.amber, border: 'none', borderRadius: 2, padding: '5px 14px', cursor: 'pointer' }}>
            Confirm core registry ({Object.values(seedChecks).filter(Boolean).length} selected)
          </button>
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: DASH.panel, fontWeight: 800, color: BB.text1 }}>
          Your book <span style={{ fontSize: DASH.data, color: BB.text3, fontWeight: 600 }}>· every position ≥$10K has a stance · ★ = your core registry</span>
        </span>
        <span style={{ fontSize: DASH.data, color: BB.text3 }}>
          {Object.entries(counts).map(([k, n]) => (
            <span key={k} style={{ marginLeft: 10 }}><b style={{ color: STANCE_COLOR[k] || BB.text2 }}>{n}</b> {k}</span>
          ))}
          {notDecomposed?.dollars ? <span style={{ marginLeft: 10 }}>· ${Math.round(notDecomposed.dollars / 1000)}K not decomposed</span> : null}
        </span>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {stances.map(s => {
          const key = `${s.symbol}-${s.account}`
          const c = STANCE_COLOR[s.stance] || BB.text2
          const isOpen = open === key
          return (
            <div key={key} onClick={() => setOpen(isOpen ? null : key)} style={{
              border: `1px solid ${isCore(s.symbol, s.account) ? BB.amber : BB.border}`, borderLeft: `3px solid ${c}`, borderRadius: 2,
              padding: '4px 9px', cursor: 'pointer', minWidth: isOpen ? '100%' : undefined,
            }}>
              {coreData?.seed_confirmed && (
                <span onClick={e => { e.stopPropagation(); toggleCore(s.symbol, !isCore(s.symbol, s.account)) }}
                  title={isCore(s.symbol, s.account) ? 'remove core designation' : 'mark ★CORE — trim-ladder-only semantics'}
                  style={{ fontSize: DASH.data, fontWeight: 800, color: isCore(s.symbol, s.account) ? BB.amber : BB.text3, marginRight: 5, cursor: 'pointer' }}>★</span>
              )}
              <span title={s.reason} style={{ fontSize: DASH.data, fontWeight: 800, color: BB.text1, cursor: 'help' }}>{s.symbol}</span>
              <span style={{ ...numStyle, fontSize: DASH.data, color: BB.text2, marginLeft: 6 }}>${Math.round(s.value / 1000)}K</span>
              <span title={`${s.stance}: ${s.reason}`} style={{ fontSize: DASH.chip, fontWeight: 800, color: c, marginLeft: 8, textTransform: 'uppercase', cursor: 'help' }}>{s.stance}</span>
              <span style={{ fontSize: DASH.chip, color: BB.text3, marginLeft: 6 }}>{s.account_label}</span>
              {ladderFor(s.symbol, s.account) && (
                <span title="ladder progress — T1 is the advised trim, T2 arms with frozen triggers; fills auto-detect from Schwab ingest (~12h)" style={{ fontSize: DASH.chip, fontWeight: 700, color: BB.amber, marginLeft: 6, cursor: 'help' }}>{ladderFor(s.symbol, s.account)}</span>
              )}
              {isOpen && (
                <div style={{ fontSize: DASH.data, color: BB.text2, marginTop: 4 }}>
                  {s.reason}
                  {s.on_trigger && <div style={{ color: BB.amber, marginTop: 3 }}>{s.on_trigger}</div>}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
