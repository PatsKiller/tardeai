import W7Conflicts from '../components/W7Conflicts'
import DeskPage from '../components/DeskPage'
import type { DrillContext } from '../components/DetailDrawer'
import { W7HomePanels, W7Load, useW7Pages } from '../components/W7PagePanels'
import { TOKENS } from '../lib/designTokens'

interface Props { onDrill: (ctx: DrillContext) => void }

/** Approved board14: actions, protection and CIO market view. Metrics live in the header. */
export default function HomeHub(_props: Props) {
  const { data, loading, error } = useW7Pages()
  return <DeskPage title="Home" purpose="What needs you today — straight from the CIO." sources={[
    // The CIO record is projected on each request from the holdings, stops and approval-queue sources below; it has
    // no scheduled writer of its own. cio-decision-engine is PAUSED since 2026-08-08 and is not its producer.
    { id: 'cio', label: 'CIO record', asOf: data?.do_now?.as_of, gap: data?.do_now?.gap?.reason },
    { id: 'holdings', label: 'Holdings', asOf: data?.portfolio?.positions_as_of, laneIds: ['schwab-position-sync', 'snaptrade-sync'], gap: data?.portfolio?.gap?.reason },
    { id: 'stops', label: 'Stops', asOf: data?.stops?.as_of, laneIds: ['unified-stop-supervisor', 'stop-health-check'], gap: data?.stops?.gap?.reason },
  ]} decisionGap="Review the CIO-ranked actions below.">
    <div data-testid="home-hub">
    {data && <W7Conflicts section={data.conflicts} title="CIO findings" />}
    {data ? <W7HomePanels data={data} /> : <W7Load loading={loading} error={error} />}
    </div>
  </DeskPage>
}
