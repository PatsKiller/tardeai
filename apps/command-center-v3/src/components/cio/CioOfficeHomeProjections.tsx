import { useState } from 'react'
import CioProjectionBlock, { CioProjectionGroup } from './CioProjectionBlock'

/** Office-home blocks of GET /api/v3/cio/home that had no renderer.
 *
 * Read-only. The home payload is already fetched by CioHub; this component
 * renders six of its blocks with their own schema/state/clock labels: the
 * operator product view, record narrative coverage, 1-hop graph impact, the notification block,
 * the capital plan's strategy/research context and the cash-sleeve letter.
 */
export default function CioOfficeHomeProjections({ home }: { home: any }) {
  const [open, setOpen] = useState(false)
  const h = home || {}
  const graph = h.graph_impact || null
  const narratives = h.record_narrative_coverage || null
  const notify = h.notifications || null
  const letter = h.cash_letter || null
  const strategy = h.strategy_context || null
  const product = h.operator_product || null
  return (
    <CioProjectionGroup
      title="Office home projections — narratives, graph impact, notifications, strategy context, cash letter"
      testId="cio-office-home-projections"
      open={open}
      onToggle={setOpen}
      note="From the office-home payload. Labels are the payload's own; advisory only, no order authority."
    >
      <CioProjectionBlock
        title="Operator product (Command Center rendering)"
        block={product}
        rows={product?.decisions}
        rowsLabel="product decisions"
        testId="cio-home-operator-product"
      />
      <CioProjectionBlock
        title="Record narrative coverage"
        block={narratives}
        rows={narratives?.sections ? Object.keys(narratives.sections) : undefined}
        rowsLabel="sections"
        testId="cio-home-record-narratives"
      />
      <CioProjectionBlock
        title="Graph impact (1-hop, held names)"
        block={graph}
        rows={graph?.items}
        rowsLabel="impacted names"
        testId="cio-home-graph-impact"
      />
      <CioProjectionBlock
        title="Notification block"
        block={notify}
        rows={notify?.items || notify?.rows}
        rowsLabel="routing decisions"
        testId="cio-home-notifications"
      />
      <CioProjectionBlock
        title="Strategy & research context (capital plan inputs)"
        block={strategy}
        rows={strategy?.context_lines}
        rowsLabel="context lines (advisory context, not policy)"
        testId="cio-home-strategy-context"
      />
      <CioProjectionBlock
        title="Cash-sleeve letter"
        block={letter}
        rows={letter?.rows}
        rowsLabel="letter rows"
        testId="cio-home-cash-letter"
      />
    </CioProjectionGroup>
  )
}
