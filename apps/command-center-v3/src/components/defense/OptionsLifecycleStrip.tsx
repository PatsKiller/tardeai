import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BB, DASH, numStyle, T } from '../../lib/watchTokens'

// Defense-page COMPACT lifecycle summary — counts only, deep-links to the full
// Options Lifecycle view (never duplicates its detail here).

export default function OptionsLifecycleStrip() {
  const [d, setD] = useState<any>(null)
  useEffect(() => {
    fetch('/api/v2/options/lifecycle').then(r => r.json())
      .then(r => setD(r?.data || null)).catch(() => setD(null))
  }, [])
  const c = d?.counts || {}
  const failed = (d?.health || []).filter((h: any) => !h.ok).length
  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'baseline', flexWrap: 'wrap', background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '7px 11px' }}>
      <span style={{ fontSize: DASH.data, fontWeight: 800, color: BB.text1 }}>Options Lifecycle</span>
      {c.open_strategies ? (
        <>
          <span style={{ fontSize: DASH.data, color: BB.text3 }}>open <b style={{ ...numStyle, color: BB.text1 }}>{c.open_strategies}</b></span>
          {c.action_now > 0 && <span style={{ fontSize: DASH.data, color: BB.red, fontWeight: 800 }}>{c.action_now} ACTION NOW</span>}
          {c.harvest_review > 0 && <span style={{ fontSize: DASH.data, color: BB.amber }}>{c.harvest_review} harvest</span>}
          {c.data_blocked > 0 && <span style={{ fontSize: DASH.data, color: BB.amber }}>{c.data_blocked} data-blocked</span>}
        </>
      ) : (
        <span style={{ fontSize: DASH.data, color: BB.text3 }}>no open option strategies — desk armed</span>
      )}
      {failed > 0 && <span style={{ fontSize: DASH.data, color: BB.red }}>⛔ {failed} health check(s) failing</span>}
      <Link to="/trading?tab=Options&otab=Lifecycle" style={{ marginLeft: 'auto', fontSize: DASH.chip, fontWeight: 800, color: T.link, textDecoration: 'none', textTransform: 'uppercase' }}>
        open the lifecycle desk →
      </Link>
    </div>
  )
}
