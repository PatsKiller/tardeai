/**
 * Notifications — R23 side-by-side, GET /api/v3/control-plane/notifications.
 * Intended route: /control-plane/notifications (NOT registered).
 * Shows candidate → classification, canary/interdict, renderer, delivery, receipt, dedupe.
 * Does not compute notification eligibility in the UI. Does not decide notification class.
 * Missing fields display "absent". Does not fall back to preview JSON. live_claim=false.
 */

import type { CSSProperties } from 'react'
import { ControlPlaneFrame, emptyCollectionMessage, extraKeysCell, panelStyle, sectionLabel, tableStyle, tableWrap, tdMono, tdStyle, thStyle } from './ControlPlaneFrame'
import { displayItemField, presentItemKeys } from './display'
import {
  CANONICAL_RUNTIME_FILES,
  CONTROL_PLANE_SUMMARY_GET,
  type ControlPlaneApiV1Envelope,
} from './fetchControlPlaneSummary'
import { R23_INTENDED_ROUTES } from './r23Routes'
import { useControlPlaneSummary } from './useControlPlaneSummary'

const PIPELINE_STAGES = [
  'Candidate',
  'Classification',
  'Canary / Interdict',
  'Renderer',
  'Delivery',
  'Receipt',
  'Dedupe',
] as const

const NOTIFICATION_ITEM_KEYS = [
  'notification_id',
  'class',
  'decision',
  'canary',
  'interdict',
  'renderer',
  'delivered_at',
  'receipt_at',
  'dedupe_key',
  'rendered_at',
  'suppression_reason',
  'evidence_class',
] as const

const stageStyle: CSSProperties = {
  fontSize: 10,
  fontWeight: 800,
  letterSpacing: '.05em',
  textTransform: 'uppercase',
  padding: '6px 8px',
  border: '1px solid var(--border)',
  background: 'var(--bg2)',
  color: 'var(--text1)',
  borderRadius: 2,
}

interface Props {
  envelope?: ControlPlaneApiV1Envelope
}

export function NotificationsPage({ envelope }: Props) {
  const summary = useControlPlaneSummary(CONTROL_PLANE_SUMMARY_GET.notifications, envelope)
  const rows = summary.items

  return (
    <ControlPlaneFrame
      title="Notifications"
      intendedRoute={R23_INTENDED_ROUTES.notifications}
      getUrl={CONTROL_PLANE_SUMMARY_GET.notifications}
      canonicalFile={CANONICAL_RUNTIME_FILES.notifications}
      envelope={summary.envelope}
      viewState={summary.viewState}
      error={summary.error}
    >
      <div style={panelStyle}>
        computes_notification_eligibility=false — this UI does not compute notification
        eligibility and does not decide notification class. class / decision / canary /
        interdict are item keys from GET /api/v3/control-plane/notifications. Funnel counts
        are not synthesized from rows.
      </div>

      <div style={sectionLabel}>Candidate → classification pipeline</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }} data-testid="notification-pipeline">
        {PIPELINE_STAGES.map((stage, index) => (
          <span key={stage} style={stageStyle}>
            {index + 1}. {stage}
          </span>
        ))}
      </div>

      <div style={sectionLabel}>Funnel (payload counts, not UI-computed)</div>
      <div style={panelStyle}>
        absent — CONTROL_PLANE_API_V1_BASELINE collection data is items/pagination only.
        Pagination total is shown on the envelope banner. This UI does not compute
        candidate / classification / canary / interdict / renderer / delivery / receipt / dedupe
        counts from rows.
      </div>

      <div style={sectionLabel}>Notification receipts</div>
      <div style={tableWrap}>
        <table style={tableStyle} data-testid="notifications-table">
          <thead>
            <tr>
              <th style={thStyle}>Notification</th>
              <th style={thStyle}>Classification</th>
              <th style={thStyle}>Decision</th>
              <th style={thStyle}>Canary</th>
              <th style={thStyle}>Interdict</th>
              <th style={thStyle}>Renderer</th>
              <th style={thStyle}>Delivery</th>
              <th style={thStyle}>Receipt</th>
              <th style={thStyle}>Dedupe</th>
              <th style={thStyle}>Rendered at</th>
              <th style={thStyle}>Suppression reason</th>
              <th style={thStyle}>Evidence class</th>
              <th style={thStyle}>Present keys</th>
              <th style={thStyle}>Other keys</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0
              ? emptyCollectionMessage(summary.viewState, 14)
              : rows.map((row, index) => (
                <tr key={`${index}:${displayItemField(row, 'notification_id')}`}>
                  <td style={tdMono}>{displayItemField(row, 'notification_id')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'class')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'decision')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'canary')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'interdict')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'renderer')}</td>
                  <td style={tdMono}>{displayItemField(row, 'delivered_at')}</td>
                  <td style={tdMono}>{displayItemField(row, 'receipt_at')}</td>
                  <td style={tdMono}>{displayItemField(row, 'dedupe_key')}</td>
                  <td style={tdMono}>{displayItemField(row, 'rendered_at')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'suppression_reason')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'evidence_class')}</td>
                  <td style={tdMono}>{presentItemKeys(row)}</td>
                  <td style={tdMono}>{extraKeysCell(row, NOTIFICATION_ITEM_KEYS)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </ControlPlaneFrame>
  )
}

export default NotificationsPage
