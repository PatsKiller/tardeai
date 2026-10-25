import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import DeskBoard from '../../components/DeskBoard'
import AgentsHub from '../AgentsHub'
import type { DrillContext } from '../../components/DetailDrawer'

/** Approved board 4. Evidence merged into Learning; old `?tab=workflow` links open Legacy analytics → Workflow. */
export const AGENTS_TABS = [
  { id: 'runtime', label: 'Runtime' },
  { id: 'learning', label: 'Learning' },
  { id: 'calibration', label: 'Calibration' },
  { id: 'memory', label: 'Memory' },
  { id: 'promotion-cases', label: 'Promotion & cases' },
  { id: 'legacy-analytics', label: 'Legacy analytics' },
] as const

const LEGACY_SUBTABS: Record<string, 'Roster' | 'Calibration' | 'Workflow' | 'Weekly Learning'> = {
  workflow: 'Workflow', roster: 'Roster', 'weekly-learning': 'Weekly Learning',
}

export default function AgentsDesk({ onDrill }: { onDrill: (ctx: DrillContext) => void }) {
  const location = useLocation()
  // Captured before the frame normalizes the alias, so ?tab=workflow still lands on Workflow.
  const [legacyTab] = useState(() => LEGACY_SUBTABS[(new URLSearchParams(location.search).get('tab') ?? '').toLowerCase()])
  return <DeskBoard desk="agents" testId="agents-desk" title="Agents"
    purpose="Are the agents running, learning, and calibrated — and what have they produced?"
    tabs={AGENTS_TABS}
    tabAliases={{ workflow: 'legacy-analytics', roster: 'legacy-analytics', 'weekly-learning': 'legacy-analytics', evidence: 'learning', promotion: 'promotion-cases', cases: 'promotion-cases' }}
    classicHref="/agents/classic"
    extras={{ 'legacy-analytics': <section aria-label="Legacy analytics detail" data-testid="agents-legacy"><AgentsHub onDrill={onDrill} initialTab={legacyTab} /></section> }} />
}
