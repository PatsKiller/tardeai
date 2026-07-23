import { useSearchParams } from 'react-router-dom'
import AuthoritativeExitUniverse from '../components/reentry/AuthoritativeExitUniverse'
import ReEntryAnalystEvidence from '../components/reentry/ReEntryAnalystEvidence'
import ReEntryAnalystLookthroughBoard from '../components/reentry/ReEntryAnalystLookthroughBoard'
import ReEntryExitDetailLedger from '../components/reentry/ReEntryExitDetailLedger'
import ReEntryHelpGuide from '../components/reentry/ReEntryHelpGuide'
import ReEntryResistanceBoard from '../components/reentry/ReEntryResistanceBoard'
import ReEntryRotationWorkspace from '../components/reentry/ReEntryRotationWorkspace'

export default function ReEntryPageV4() {
  const [params] = useSearchParams()
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <ReEntryHelpGuide />
      <AuthoritativeExitUniverse />
      <ReEntryExitDetailLedger />
      <ReEntryAnalystEvidence />
      <ReEntryResistanceBoard />
      <ReEntryAnalystLookthroughBoard />
      <ReEntryRotationWorkspace mode="full" initialSymbol={params.get('symbol') ?? ''} />
    </div>
  )
}
