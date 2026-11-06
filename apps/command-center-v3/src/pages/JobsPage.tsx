import { useSearchParams } from 'react-router-dom'
import JobsHealth from '../components/JobsHealth'
import OpsDeskFrame from '../components/OpsDeskFrame'
import IntelligenceWorkflow from '../components/IntelligenceWorkflow'
import type { DrillContext } from '../components/DetailDrawer'
import { TOKENS } from '../lib/designTokens'

const noDrill = () => {}

/** Board 16 on the board 0 frame: the one job-execution view; Health, Releases, Ops Controls, Coordination and
 *  System embed the same component and data in their Jobs tab.
 *  `?view=workflow` shows the intelligence workflow (moved here from the retired Intelligence page, intel/v001). */
export default function JobsPage({ onDrill }: { onDrill?: (ctx: DrillContext) => void } = {}) {
  const [sp] = useSearchParams()
  const workflow = sp.get('view') === 'workflow'
  return <main style={{ padding: 20, background: TOKENS.bg[0], minWidth: 0 }}>
    <OpsDeskFrame page="jobs">
      {workflow
        ? <section aria-label="Intelligence workflow" data-testid="jobs-workflow" style={{ minWidth: 0 }}><IntelligenceWorkflow onDrill={onDrill ?? noDrill} /></section>
        : <JobsHealth />}
    </OpsDeskFrame>
  </main>
}
