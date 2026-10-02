import { useState } from 'react'
import CioProjectionBlock, { CioProjectionGroup } from './CioProjectionBlock'

/** Product health & learning blocks of GET /api/v3/cio/investment-product.
 *
 * Read-only. InvestmentBooksPanel already fetches the product; this renders the
 * blocks it did not: identity coverage, holdings data quality, Surface-A
 * status, checkpoint lineage health, research verdict counts and failure
 * histogram, provisional lessons, today's thesis changes, the re-entry thesis
 * decision gate and the held-instrument id set. Each keeps its own labels.
 */
export default function CioProductHealthPanel({ data }: { data: any }) {
  const [open, setOpen] = useState(false)
  const product = data?.product || {}
  const lessons = product.provisional_lessons || null
  const gate = product.confidence?.thesis_decision_gate ?? null
  const held = product.holdings_thesis_coverage || null
  return (
    <CioProjectionGroup
      title="Product health & learning — identity, data quality, lineage, research quality, lessons"
      testId="cio-product-health"
      open={open}
      onToggle={setOpen}
      note="Provisional lessons are candidates, never rules. Behavior influence 0."
    >
      <CioProjectionBlock title="Identity coverage" block={product.identity_coverage ?? null} testId="cio-product-identity-coverage" />
      <CioProjectionBlock title="Holdings data quality" block={product.holdings_data_quality ?? null} testId="cio-product-holdings-quality" />
      <CioProjectionBlock title="Surface-A status" block={product.surface_a_status ?? null} testId="cio-product-surface-a" />
      <CioProjectionBlock title="Checkpoint lineage health" block={product.checkpoint_lineage ?? null} testId="cio-product-checkpoint-lineage" />
      <CioProjectionBlock title="Research verdict counts" block={product.research_quality_counts ?? null} testId="cio-product-research-verdicts" />
      <CioProjectionBlock title="Research failure histogram" block={product.research_fail_histogram ?? null} testId="cio-product-research-fails" />
      <CioProjectionBlock
        title="Provisional lessons"
        block={lessons}
        rows={lessons?.items}
        rowsLabel="lesson candidates (PROVISIONAL — not rules)"
        testId="cio-product-provisional-lessons"
      />
      <CioProjectionBlock title="Thesis changes today" block={product.thesis_changes_today ?? null} testId="cio-product-thesis-changes" />
      <CioProjectionBlock title="Re-entry thesis decision gate" block={gate} testId="cio-product-thesis-gate" />
      <CioProjectionBlock
        title="Held-instrument thesis coverage"
        block={held}
        rows={held?.instrument_ids}
        rowsLabel="held instrument ids"
        testId="cio-product-held-ids"
      />
    </CioProjectionGroup>
  )
}
