import { useEffect, useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { RADIUS } from '../../lib/designTokens'
import CioProjectionBlock, { CioProjectionGroup } from './CioProjectionBlock'

/** Thesis research context for one symbol, plus the prioritized thesis-gap
 * research proposal. Read-only; nothing loads until the operator presses Load
 * (these compose RAG retrieval previews, so they are never polled).
 * The backend runs them dry: no acquisition, no embedding, no LLM call.
 */
export default function CioThesisResearchContextPanel({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(false)
  const [loadSymbol, setLoadSymbol] = useState(false)
  const [loadProposal, setLoadProposal] = useState(false)
  useEffect(() => { setLoadSymbol(false) }, [symbol])
  const sym = encodeURIComponent(symbol || '_')
  const symOn = { enabled: open && loadSymbol && Boolean(symbol) }
  const { data: ask, loading: askLoading, error: askError } = useApi<any>(`/api/v3/cio/ask-thesis/${sym}`, 0, symOn)
  const { data: context, loading: ctxLoading, error: ctxError } = useApi<any>(`/api/v3/cio/thesis-research-context/${sym}`, 0, symOn)
  const { data: pipeline, loading: pipeLoading, error: pipeError } = useApi<any>(`/api/v3/cio/thesis-ri-pipeline/${sym}`, 0, symOn)
  const { data: proposal, loading: propLoading, error: propError } = useApi<any>('/api/v3/cio/thesis-research-proposal', 0, { enabled: open && loadProposal })
  const button = { border: '1px solid var(--border)', borderRadius: RADIUS.sm, background: 'var(--bg1)', color: 'var(--text2)', padding: '2px 10px', fontSize: 11, cursor: 'pointer' } as const
  return (
    <CioProjectionGroup
      title={`Thesis research context${symbol ? ` — ${symbol}` : ''}`}
      testId="cio-thesis-research-context"
      open={open}
      onToggle={setOpen}
      note="Dry previews: retrieval only; acquisition, embedding and LLM synthesis stay off. Advisory, no order authority."
    >
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" style={button} disabled={!symbol} onClick={() => setLoadSymbol(true)} data-testid="cio-thesis-research-load-symbol">
          {symbol ? `Load ${symbol} research context` : 'Select a symbol above'}
        </button>
        <button type="button" style={button} onClick={() => setLoadProposal(true)} data-testid="cio-thesis-research-load-proposal">Load prioritized research proposal</button>
      </div>
      {loadSymbol && symbol && (
        <>
          <CioProjectionBlock
            title={`Ask-CIO thesis context · ${symbol}`}
            block={ask}
            rows={ask?.research_gaps}
            rowsLabel="research gaps"
            testId="cio-ask-thesis" loading={askLoading} error={askError}
          />
          <CioProjectionBlock
            title={`Supply plane → RAG → thesis · ${symbol}`}
            block={context}
            rows={context?.research_gap ? [context.research_gap] : undefined}
            rowsLabel="research gap"
            testId="cio-thesis-research-ctx" loading={ctxLoading} error={ctxError}
          />
          <CioProjectionBlock
            title={`RI pipeline plan (dry) · ${symbol}`}
            block={pipeline}
            rows={pipeline?.acquisition_plan?.steps || pipeline?.acquisition_plan?.sources}
            rowsLabel="acquisition plan"
            testId="cio-thesis-ri-pipeline" loading={pipeLoading} error={pipeError}
          />
        </>
      )}
      {loadProposal && (
        <CioProjectionBlock
          title="Prioritized thesis research proposal (dry, not enqueued)"
          block={proposal}
          rows={proposal?.requests}
          rowsLabel="proposed requests"
          testId="cio-thesis-research-proposal" loading={propLoading} error={propError}
        />
      )}
    </CioProjectionGroup>
  )
}
