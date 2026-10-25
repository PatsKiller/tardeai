import JobsHealth from '../components/JobsHealth'
import OpsDeskFrame from '../components/OpsDeskFrame'
import { TOKENS } from '../lib/designTokens'

/** Board 16 on the board 0 frame: the one job-execution view; Health, Releases, Ops Controls, Coordination and
 *  System embed the same component and data in their Jobs tab. */
export default function JobsPage() {
  return <main style={{ padding: 20, background: TOKENS.bg[0], minWidth: 0 }}>
    <OpsDeskFrame page="jobs"><JobsHealth /></OpsDeskFrame>
  </main>
}
