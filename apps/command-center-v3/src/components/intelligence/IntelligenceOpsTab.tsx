import { useState } from 'react'
import IntelligenceSourcesTab from './IntelligenceSourcesTab'
import IntelligenceWorkflow from '../IntelligenceWorkflow'
import type { DrillContext } from '../DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }

// Ops = ingestion/RAG/pipeline health, merged from the former separate "Sources" and "Workflow" tabs.
// This is operational plumbing, not intelligence content — kept as ONE compact tab (pipeline diagram
// collapsed by default) instead of two, since neither view drives a trading decision on its own; they
// exist so an operator can tell WHY a feed looks thin/stale, not to read every day.
export default function IntelligenceOpsTab({ onDrill }: Props) {
  const [showDiagram, setShowDiagram] = useState(false)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <IntelligenceSourcesTab onDrill={onDrill} />
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
        <button onClick={() => setShowDiagram(v => !v)} style={{
          width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          border: 0, background: 'transparent', cursor: 'pointer', padding: 0,
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Pipeline diagram (ingestion → curation → LLM → RAG → jobs)</div>
          <span style={{ color: 'var(--text3)', fontSize: 10 }}>{showDiagram ? 'hide ▲' : 'show ▼'}</span>
        </button>
        {showDiagram && <div style={{ marginTop: 10 }}><IntelligenceWorkflow onDrill={onDrill} /></div>}
      </div>
    </div>
  )
}
