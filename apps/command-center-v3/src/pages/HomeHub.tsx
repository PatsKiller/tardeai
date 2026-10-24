import type { DrillContext } from '../components/DetailDrawer'
import { W7HomePanels, W7Load, useW7Pages } from '../components/W7PagePanels'
import { TOKENS } from '../lib/designTokens'

interface Props { onDrill: (ctx: DrillContext) => void }

/** Approved board14: actions, protection and CIO market view. Metrics live in the header. */
export default function HomeHub(_props: Props) {
  const { data, loading, error } = useW7Pages()
  return <main data-testid="home-hub" style={{ padding: 20, color: TOKENS.text[0] }}>
    <h1 style={{ fontSize: 24, margin: '0 0 8px' }}>Home</h1>
    <p style={{ color: TOKENS.text[2], marginBottom: 20 }}>What needs you today — straight from the CIO.</p>
    {data ? <W7HomePanels data={data} /> : <W7Load loading={loading} error={error} />}
  </main>
}
