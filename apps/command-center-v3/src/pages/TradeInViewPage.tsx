/** /v3/journal — TradeInView. The per-trade journey view is the page (operator directive 2026-10-22); the previous
 *  journal (analytics, tagging queue, costs, import, …) stays one click away as "Classic journal" (?view=classic) and
 *  every legacy deep link that names a tab (?tab=Options, …) opens it as before. */
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { DrillContext } from '../components/DetailDrawer'
import JournalHub from './JournalHub'
import TradeJourney from './TradeJourney'
import { TOKENS, TYPE } from '../lib/designTokens'

export default function TradeInViewPage({ onDrill }: { onDrill: (ctx: DrillContext) => void }) {
  const [params] = useSearchParams()
  // A hand-off that names a classic tab through sessionStorage (StrategyHub → Backtesting, AI critique → Trades)
  // opens the classic journal; JournalHub consumes and clears the key.
  const [handoff, setHandoff] = useState(() => { try { return !!sessionStorage.getItem('journal_tab') } catch { return false } })
  const classic = params.get('view') === 'classic' || params.has('tab') || handoff
  if (!classic) return <TradeJourney />
  const sym = params.get('symbol')
  const back = sym ? `/journal?symbol=${encodeURIComponent(sym)}` : '/journal'
  return (
    <div>
      <div style={{ marginBottom: 8, fontSize: TYPE.base }}>
        <Link to={back} data-testid="tj-back" onClick={() => setHandoff(false)} style={{ color: TOKENS.info }}>← Trade journeys</Link>
        <span style={{ color: TOKENS.text[3] }}> · Classic journal</span>
      </div>
      <JournalHub onDrill={onDrill} />
    </div>
  )
}
