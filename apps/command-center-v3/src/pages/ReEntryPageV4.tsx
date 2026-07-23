import { useSearchParams } from 'react-router-dom'
import ReEntryAnalystEvidence from '../components/reentry/ReEntryAnalystEvidence'
import ReEntryAnalystLookthroughBoard from '../components/reentry/ReEntryAnalystLookthroughBoard'
import ReEntryCurrentIntelligence from '../components/reentry/ReEntryCurrentIntelligence'
import ReEntryExitDetailLedger from '../components/reentry/ReEntryExitDetailLedger'
import ReEntryExitWorkbench from '../components/reentry/ReEntryExitWorkbench'
import ReEntryHelpGuide from '../components/reentry/ReEntryHelpGuide'
import ReEntryResistanceBoard from '../components/reentry/ReEntryResistanceBoard'
import ReEntryRotationWorkspace from '../components/reentry/ReEntryRotationWorkspace'

export default function ReEntryPageV4() {
  const [params] = useSearchParams()
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <ReEntryHelpGuide compact />
      <ReEntryCurrentIntelligence />
      <ReEntryExitWorkbench />
      <ReEntryExitDetailLedger />
      <ReEntryAnalystEvidence />
      <ReEntryResistanceBoard />
      <ReEntryAnalystLookthroughBoard />
      <div id="rotation-workspace">
        <ReEntryRotationWorkspace mode="full" initialSymbol={params.get('symbol') ?? ''} />
      </div>
    </div>
  )
}
