import { useSearchParams } from 'react-router-dom'
import AuthoritativeExitUniverse from '../components/reentry/AuthoritativeExitUniverse'
import ReEntryAnalystLookthroughBoard from '../components/reentry/ReEntryAnalystLookthroughBoard'
import ReEntryResistanceBoard from '../components/reentry/ReEntryResistanceBoard'
import ReEntryRotationWorkspace from '../components/reentry/ReEntryRotationWorkspace'

export default function ReEntryPageV4() {
  const [params] = useSearchParams()
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <AuthoritativeExitUniverse />
      <ReEntryResistanceBoard />
      <ReEntryAnalystLookthroughBoard />
      <ReEntryRotationWorkspace mode="full" initialSymbol={params.get('symbol') ?? ''} />
    </div>
  )
}
