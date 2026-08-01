import { useSearchParams } from 'react-router-dom'
import ReEntryAnalystEvidence from '../components/reentry/ReEntryAnalystEvidence'
import ReEntryAnalystLookthroughBoard from '../components/reentry/ReEntryAnalystLookthroughBoard'
import ReEntryClassificationOverlay from '../components/reentry/ReEntryClassificationOverlay'
import ReEntryCurrentIntelligence from '../components/reentry/ReEntryCurrentIntelligence'
import ReEntryEvidenceContractPanel from '../components/reentry/ReEntryEvidenceContractPanel'
import ReEntryExitDetailLedger from '../components/reentry/ReEntryExitDetailLedger'
import ReEntryExitWorkbench from '../components/reentry/ReEntryExitWorkbench'
import ReEntryHelpGuide from '../components/reentry/ReEntryHelpGuide'
import ReEntryResistanceBoard from '../components/reentry/ReEntryResistanceBoard'
import ReEntryRotationWorkspace from '../components/reentry/ReEntryRotationWorkspace'

export default function ReEntryPageV4() {
  const [params] = useSearchParams()
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <ReEntryClassificationOverlay />
      <ReEntryCurrentIntelligence />
      <details style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 5, padding: '8px 12px' }}>
        <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 850, color: 'var(--text2)' }}>
          Evidence & process — help, contract, exits, analyst, resistance, rotation
        </summary>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 10 }}>
          <ReEntryHelpGuide compact />
          <ReEntryEvidenceContractPanel />
          <ReEntryExitWorkbench />
          <ReEntryExitDetailLedger />
          <ReEntryAnalystEvidence />
          <ReEntryResistanceBoard />
          <ReEntryAnalystLookthroughBoard />
          <div id="rotation-workspace">
            <ReEntryRotationWorkspace mode="full" initialSymbol={params.get('symbol') ?? ''} />
          </div>
        </div>
      </details>
    </div>
  )
}
