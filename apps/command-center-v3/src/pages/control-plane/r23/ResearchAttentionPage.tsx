/**
 * Research Attention — R23 side-by-side, GET /api/v3/control-plane/research.
 * Intended route: /control-plane/research (NOT registered).
 * Renders item keys from CONTROL_PLANE_API_V1_BASELINE collection data.
 * Missing fields display "absent". Does not decide materiality, wake, or LLM eligibility.
 * Does not fall back to ControlPlane@v1.0.0 preview JSON. live_claim=false.
 */

import { ControlPlaneFrame, emptyCollectionMessage, extraKeysCell, panelStyle, sectionLabel, tableStyle, tableWrap, tdMono, tdStyle, thStyle } from './ControlPlaneFrame'
import { displayItemField, presentItemKeys } from './display'
import {
  CANONICAL_RUNTIME_FILES,
  CONTROL_PLANE_SUMMARY_GET,
  type ControlPlaneApiV1Envelope,
} from './fetchControlPlaneSummary'
import { R23_INTENDED_ROUTES } from './r23Routes'
import { useControlPlaneSummary } from './useControlPlaneSummary'

const RESEARCH_ITEM_KEYS = [
  'subject_id',
  'state',
  'universe',
  'active_set',
  'due',
  'event_woken',
  'why_now',
  'why_not_now',
  'research_gap_id',
  'source_usage',
  'llm_eligibility',
  'cost',
  'yield',
  'freshness',
  'cadence',
  'route',
  'evidence_class',
] as const

interface Props {
  envelope?: ControlPlaneApiV1Envelope
}

export function ResearchAttentionPage({ envelope }: Props) {
  const summary = useControlPlaneSummary(CONTROL_PLANE_SUMMARY_GET.research, envelope)
  const rows = summary.items

  return (
    <ControlPlaneFrame
      title="Research Attention"
      intendedRoute={R23_INTENDED_ROUTES.research}
      getUrl={CONTROL_PLANE_SUMMARY_GET.research}
      canonicalFile={CANONICAL_RUNTIME_FILES.research}
      envelope={summary.envelope}
      viewState={summary.viewState}
      error={summary.error}
    >
      <div style={panelStyle} data-testid="research-universe">
        <div style={sectionLabel}>Universe</div>
        <div style={{ marginTop: 6, fontFamily: 'var(--mono)', fontSize: 12 }}>
          Collection envelope has items/pagination only — not a payload.universe field.
          Per-item universe is rendered in the table; missing item keys display absent.
          Adaptive cadence is not invented.
        </div>
      </div>

      <div style={sectionLabel}>Attention rows</div>
      <div style={tableWrap}>
        <table style={tableStyle} data-testid="research-attention-table">
          <thead>
            <tr>
              <th style={thStyle}>Subject</th>
              <th style={thStyle}>State</th>
              <th style={thStyle}>Universe</th>
              <th style={thStyle}>Active set</th>
              <th style={thStyle}>Due</th>
              <th style={thStyle}>Event-woken</th>
              <th style={thStyle}>Why now</th>
              <th style={thStyle}>Why not now</th>
              <th style={thStyle}>Research gap</th>
              <th style={thStyle}>Source usage</th>
              <th style={thStyle}>LLM eligibility</th>
              <th style={thStyle}>Cost</th>
              <th style={thStyle}>Yield</th>
              <th style={thStyle}>Freshness</th>
              <th style={thStyle}>Cadence</th>
              <th style={thStyle}>Route</th>
              <th style={thStyle}>Evidence class</th>
              <th style={thStyle}>Present keys</th>
              <th style={thStyle}>Other keys</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0
              ? emptyCollectionMessage(summary.viewState, 19)
              : rows.map((row, index) => (
                <tr key={`${index}:${displayItemField(row, 'subject_id')}`}>
                  <td style={tdMono}>{displayItemField(row, 'subject_id')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'state')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'universe')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'active_set')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'due')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'event_woken')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'why_now')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'why_not_now')}</td>
                  <td style={tdMono}>{displayItemField(row, 'research_gap_id')}</td>
                  <td style={tdMono}>{displayItemField(row, 'source_usage')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'llm_eligibility')}</td>
                  <td style={tdMono}>{displayItemField(row, 'cost')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'yield')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'freshness')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'cadence')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'route')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'evidence_class')}</td>
                  <td style={tdMono}>{presentItemKeys(row)}</td>
                  <td style={tdMono}>{extraKeysCell(row, RESEARCH_ITEM_KEYS)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </ControlPlaneFrame>
  )
}

export default ResearchAttentionPage
