import { Navigate, useLocation } from 'react-router-dom'
import DeskBoard from '../../components/DeskBoard'

/** Approved board 1 (desks redesign 2026-10-24). Read-only; classic page stays at /portfolio/re-entry/classic. */
export const REENTRY_TABS = [
  { id: 'ready-now', label: 'Ready now' },
  { id: 'exits-review', label: 'Exits review' },
  { id: 'resistance-levels', label: 'Resistance & levels' },
  { id: 'analyst-evidence', label: 'Analyst evidence' },
] as const

/** Symbol-focused deep links (?symbol=, ?classify=, ?lane=) keep opening the classic workbench that reads them. */
const CLASSIC_PARAMS = ['symbol', 'classify', 'lane']

export default function ReEntryDesk() {
  const location = useLocation()
  const params = new URLSearchParams(location.search)
  if (CLASSIC_PARAMS.some(key => params.has(key))) return <Navigate to={`/portfolio/re-entry/classic${location.search}${location.hash}`} replace />
  return <DeskBoard desk="reentry" testId="reentry-desk" title="Re-Entry"
    purpose="Names you sold: is it time to get back in, and at what level?"
    tabs={REENTRY_TABS} tabAliases={{ ready: 'ready-now', exits: 'exits-review', resistance: 'resistance-levels', analyst: 'analyst-evidence' }}
    classicHref="/portfolio/re-entry/classic" />
}
