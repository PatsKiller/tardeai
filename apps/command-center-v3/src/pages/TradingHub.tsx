import type { DrillContext } from '../components/DetailDrawer'
import ManualTosDesk from './ManualTosDesk'

interface Props { onDrill: (ctx: DrillContext) => void }

export default function TradingHub(_props: Props) {
  return <ManualTosDesk />
}
