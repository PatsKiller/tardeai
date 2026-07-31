import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import ReEntryAnalystEvidence from '../components/reentry/ReEntryAnalystEvidence'
import ReEntryAnalystLookthroughBoard from '../components/reentry/ReEntryAnalystLookthroughBoard'
import ReEntryClassificationOverlay from '../components/reentry/ReEntryClassificationOverlay'
import ReEntryCurrentIntelligence, { parseLane } from '../components/reentry/ReEntryCurrentIntelligence'
import ReEntryEvidenceContractPanel from '../components/reentry/ReEntryEvidenceContractPanel'
import ReEntryExitDetailLedger from '../components/reentry/ReEntryExitDetailLedger'
import ReEntryExitWorkbench from '../components/reentry/ReEntryExitWorkbench'
import ReEntryHelpGuide from '../components/reentry/ReEntryHelpGuide'
import ReEntryResistanceBoard from '../components/reentry/ReEntryResistanceBoard'
import ReEntryRotationWorkspace from '../components/reentry/ReEntryRotationWorkspace'
import type { ReEntryLane } from '../lib/reentryDecisionScorecard'

export default function ReEntryPageV4() {
  const [params, setParams] = useSearchParams()
  const lane = parseLane(params.get('lane')) ?? 'NOW'
  const focusSymbol = (params.get('symbol') ?? '').trim().toUpperCase() || undefined

  const onLaneChange = useCallback((next: ReEntryLane) => {
    setParams(prev => {
      const nextParams = new URLSearchParams(prev)
      if (next === 'NOW') nextParams.delete('lane')
      else nextParams.set('lane', next)
      return nextParams
    }, { replace: true })
  }, [setParams])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <ReEntryHelpGuide compact />
      <ReEntryClassificationOverlay />
      <ReEntryEvidenceContractPanel />
      <ReEntryCurrentIntelligence
        lane={lane}
        onLaneChange={onLaneChange}
        focusSymbol={focusSymbol}
      />
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
