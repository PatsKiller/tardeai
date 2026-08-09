/**
 * Discovery & Administration — not the primary decision path.
 * Full Screener / directives / import tools live here.
 */
import type { DrillContext } from '../components/DetailDrawer'
import ScreenerFindsHub from './ScreenerFindsHub'
import { BB, TYPE, hubTitle, hubSubtitle } from '../lib/watchTokens'
import { Link } from 'react-router-dom'
import { useTerminalUi } from '../lib/terminalUi'

interface Props { onDrill?: (ctx: DrillContext) => void }

export default function WatchDiscovery({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  return (
    <div data-watch-discovery>
      <div style={{ marginBottom: 12 }}>
        <Link to="/watch" style={{ fontSize: TYPE.xs, color: BB.text3, textDecoration: 'none' }}>← Watch Intelligence</Link>
        <div style={hubTitle()}>Watch Discovery & Administration</div>
        <div style={hubSubtitle(terminalUi)}>
          Directives, screener universe, ToS import, and batch tools — not the five-second decision surface.
        </div>
      </div>
      <div style={{ border: `1px solid ${BB.border}`, background: BB.bgShift, color: BB.amber, borderRadius: 8, padding: 10, fontSize: TYPE.xs, marginBottom: 12 }}>
        Primary decisions belong on <b>/v3/watch</b>. This route is research administration only.
      </div>
      <ScreenerFindsHub onDrill={onDrill || (() => {})} embedded />
    </div>
  )
}
