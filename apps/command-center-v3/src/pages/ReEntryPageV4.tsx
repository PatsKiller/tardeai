import { useSearchParams } from 'react-router-dom'
import ReEntryRotationWorkspace from '../components/reentry/ReEntryRotationWorkspace'

export default function ReEntryPageV4() {
  const [params] = useSearchParams()
  return <ReEntryRotationWorkspace mode="full" initialSymbol={params.get('symbol') ?? ''} />
}
