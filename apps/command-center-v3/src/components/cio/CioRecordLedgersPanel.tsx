import { useState } from 'react'
import { useApi } from '../../hooks/useApi'
import CioProjectionBlock, { CioProjectionGroup } from './CioProjectionBlock'

const SLOW_POLL_MS = 300_000 // never faster than 5 min; nothing loads until opened

/** The CIO's own record ledgers (GET /api/v3/cio/records): newest outcome
 * checkpoints and observations, thesis revisions and change cards, instrument
 * records and beliefs, the belief-writer receipt, held-book thesis coverage,
 * research-driven reassessments, lesson binds, linked feedback and feedback
 * ingests, goal predicates and verdicts, the persisted operator-product
 * envelope header, the Telegram stance-hold summary, and the CIO
 * reconciliation (GET /api/v3/intelligence/reconciliation).
 * Each block shows the store's own state (PRESENT / EMPTY / MISSING) and
 * source_as_of. Read-only; beliefs and lessons never carry order authority.
 */
export default function CioRecordLedgersPanel() {
  const [open, setOpen] = useState(false)
  const { data, loading, error } = useApi<any>('/api/v3/cio/records', SLOW_POLL_MS, { enabled: open })
  const { data: recon, loading: reconLoading, error: reconError } = useApi<any>('/api/v3/intelligence/reconciliation', SLOW_POLL_MS, { enabled: open })
  const d = data || null
  const common = { loading, error }
  return (
    <CioProjectionGroup
      title="CIO record ledgers — outcomes, lessons, thesis revisions, beliefs, goals, feedback, reassessments, reconciliation"
      testId="cio-record-ledgers"
      open={open}
      onToggle={setOpen}
      note={`Newest rows from bounded tail reads. composed ${d?.composition_as_of || 'NOT_IN_PAYLOAD'}${d?.ok === false ? ` · ok=false ${d?.error || ''}` : ''}`}
    >
      <CioProjectionBlock title="Outcome checkpoints" block={d?.outcome_checkpoints ?? null} rows={d?.outcome_checkpoints?.rows} rowsLabel="newest checkpoints" testId="cio-records-checkpoints" {...common} />
      <CioProjectionBlock title="Outcome observations" block={d?.outcome_observations ?? null} rows={d?.outcome_observations?.rows} rowsLabel="newest observations" testId="cio-records-observations" {...common} />
      <CioProjectionBlock title="Lesson binds (lesson + hypothesis -> bound checkpoint)" block={d?.lesson_binds ?? null} rows={d?.lesson_binds?.rows} rowsLabel="newest binds" testId="cio-records-lesson-binds" {...common} />
      <CioProjectionBlock title="Thesis revision ledger" block={d?.thesis_revisions ?? null} rows={d?.thesis_revisions?.rows} rowsLabel="newest revisions" testId="cio-records-thesis-revisions" {...common} />
      <CioProjectionBlock title="Thesis change cards" block={d?.thesis_change_cards ?? null} rows={d?.thesis_change_cards?.rows} rowsLabel="newest change cards" testId="cio-records-thesis-changes" {...common} />
      <CioProjectionBlock title="Held-book thesis coverage" block={d?.held_thesis_coverage ?? null} testId="cio-records-held-coverage" {...common}>
        {d?.held_thesis_coverage?.report && <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>report {d.held_thesis_coverage.report.schema} · as of {String(d.held_thesis_coverage.report.as_of || d.held_thesis_coverage.report.generated_at || 'NOT_IN_PAYLOAD')}</div>}
      </CioProjectionBlock>
      <CioProjectionBlock title="Instrument records" block={d?.instrument_records ?? null} rows={d?.instrument_records?.rows?.map((r: any) => ({ symbol: r.subject_key, summary: r.next_research_question || r.kind }))} rowsLabel="newest records" testId="cio-records-instruments" {...common} />
      <CioProjectionBlock title="Instrument beliefs (from settled outcomes)" block={d?.instrument_beliefs ?? null} rows={d?.instrument_beliefs?.rows?.map((b: any) => ({ symbol: b.subject_key, state: b.recommendation, summary: `success ${b.success_rate ?? 'n/a'} of ${b.sample_size ?? 'n/a'}` }))} rowsLabel="newest beliefs (context only, live_mutation=false)" testId="cio-records-beliefs" {...common} />
      <CioProjectionBlock title="Belief writer — latest run receipt" block={d?.belief_writer ?? null} testId="cio-records-belief-writer" {...common} />
      <CioProjectionBlock title="Product reassessments after research" block={d?.reassessments ?? null} rows={d?.reassessments?.rows?.map((r: any) => ({ id: r.reassessment_id, status: r.status, summary: r.impact }))} rowsLabel="newest reassessments" testId="cio-records-reassessments" {...common} />
      <CioProjectionBlock title="Operator feedback linked to decisions" block={d?.linked_feedback ?? null} rows={d?.linked_feedback?.rows} rowsLabel="newest feedback" testId="cio-records-linked-feedback" {...common} />
      <CioProjectionBlock title="Conversational feedback ingests" block={d?.feedback_ingests ?? null} rows={d?.feedback_ingests?.rows} rowsLabel="what feedback became (candidates only)" testId="cio-records-feedback-ingests" {...common} />
      <CioProjectionBlock
        title={`Goal predicates (${d?.goal_predicates?.goal_count ?? 'n/a'} goals)`}
        block={d?.goal_predicates ?? null}
        rows={d?.goal_predicates?.rows?.map((g: any) => ({ id: g.goal_id, state: g.last_outcome, summary: (g.predicate?.terms || []).join(', ') }))}
        rowsLabel="goals and predicate terms"
        testId="cio-records-goal-predicates" {...common}
      />
      <CioProjectionBlock title="Goal predicate verdicts" block={d?.goal_verdicts ?? null} rows={d?.goal_verdicts?.rows?.map((v: any) => ({ id: v.goal_id, verdict: v.verdict ?? v.status ?? v.result }))} rowsLabel="newest verdicts" testId="cio-records-goal-verdicts" {...common} />
      <CioProjectionBlock title="Operator product envelope (persisted)" block={d?.operator_product ?? null} testId="cio-records-operator-product" {...common}>
        {d?.operator_product?.envelope && <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>
          {d.operator_product.envelope.schema} · {String(d.operator_product.envelope.status ?? 'status NOT_IN_PAYLOAD')} · generation {String(d.operator_product.envelope.generation_id ?? 'n/a')} · {String(d.operator_product.envelope.decisions_n ?? 0)} decisions
          {d.operator_product.envelope.executive_summary && <div style={{ marginTop: 2 }}>{String(d.operator_product.envelope.executive_summary)}</div>}
        </div>}
      </CioProjectionBlock>
      <CioProjectionBlock title="CIO reconciliation (internal consistency)" block={recon} testId="cio-records-reconciliation" loading={reconLoading} error={reconError} />
      <CioProjectionBlock title="Telegram stance holds (missing CIO stance)" block={d?.stance_holds ?? null} testId="cio-records-stance-holds" {...common} />
    </CioProjectionGroup>
  )
}
