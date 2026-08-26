/**
 * Identity — R23 side-by-side, GET /api/v3/control-plane/identity.
 * Intended route: /control-plane/identity (NOT registered).
 * Renders issuer / security / listing / ticker alias and CIK / FIGI / ISIN / CUSIP.
 * NEVER mint security_guid from ticker. GUI has no mint control.
 * Do not manufacture entity_id from ticker alias. Missing fields display "absent".
 * live_claim=false.
 */

import { ControlPlaneFrame, emptyCollectionMessage, extraKeysCell, panelStyle, sectionLabel, tableStyle, tableWrap, tdMono, tdStyle, thStyle } from './ControlPlaneFrame'
import { displayItemField, displayNestedField, presentItemKeys } from './display'
import {
  CANONICAL_RUNTIME_FILES,
  CONTROL_PLANE_SUMMARY_GET,
  type ControlPlaneApiV1Envelope,
} from './fetchControlPlaneSummary'
import { R23_INTENDED_ROUTES } from './r23Routes'
import { useControlPlaneSummary } from './useControlPlaneSummary'

const IDENTITY_STATES = [
  'CONFIRMED',
  'CANDIDATE',
  'UNRESOLVED_WITH_REASON',
] as const

const IDENTITY_ITEM_KEYS = [
  'entity_id',
  'issuer',
  'security',
  'listing',
  'aliases',
  'identifiers',
  'state',
  'unresolved_reason',
  'source',
  'as_of',
] as const

interface Props {
  envelope?: ControlPlaneApiV1Envelope
}

export function IdentityPage({ envelope }: Props) {
  const summary = useControlPlaneSummary(CONTROL_PLANE_SUMMARY_GET.identity, envelope)
  const rows = summary.items

  return (
    <ControlPlaneFrame
      title="Identity"
      intendedRoute={R23_INTENDED_ROUTES.identity}
      getUrl={CONTROL_PLANE_SUMMARY_GET.identity}
      canonicalFile={CANONICAL_RUNTIME_FILES.identity}
      envelope={summary.envelope}
      viewState={summary.viewState}
      error={summary.error}
    >
      <div style={{ ...panelStyle, borderColor: 'var(--amber)' }} data-testid="no-mint-control">
        <div style={sectionLabel}>NO MINT CONTROL</div>
        <div style={{ marginTop: 6 }}>
          NEVER mint security_guid from ticker. Identity states are contract values
          CONFIRMED / CANDIDATE / UNRESOLVED_WITH_REASON. This GUI has no mint control
          and does not manufacture entity_id, issuer, security, listing, or identifiers.
          Empty entity_id is displayed as given — not filled from ticker alias.
        </div>
        <div style={{ marginTop: 6, fontFamily: 'var(--mono)' }}>
          never_mint_from_ticker=true (GUI policy, not an API field; this page has NO MINT CONTROL)
        </div>
      </div>

      <div style={panelStyle}>
        <div style={sectionLabel}>Contract identity states</div>
        <div style={{ marginTop: 6, fontFamily: 'var(--mono)' }}>
          {IDENTITY_STATES.join(' · ')}
        </div>
      </div>

      <div style={sectionLabel}>Identity spine</div>
      <div style={tableWrap}>
        <table style={tableStyle} data-testid="identity-table">
          <thead>
            <tr>
              <th style={thStyle}>Entity</th>
              <th style={thStyle}>Issuer</th>
              <th style={thStyle}>Security</th>
              <th style={thStyle}>Listing</th>
              <th style={thStyle}>Ticker alias</th>
              <th style={thStyle}>CIK</th>
              <th style={thStyle}>FIGI</th>
              <th style={thStyle}>ISIN</th>
              <th style={thStyle}>CUSIP</th>
              <th style={thStyle}>State</th>
              <th style={thStyle}>Unresolved reason</th>
              <th style={thStyle}>Source</th>
              <th style={thStyle}>As of</th>
              <th style={thStyle}>Present keys</th>
              <th style={thStyle}>Other keys</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0
              ? emptyCollectionMessage(summary.viewState, 15)
              : rows.map((row, index) => (
                <tr key={`${index}:${displayItemField(row, 'entity_id')}`}>
                  <td style={tdMono}>{displayItemField(row, 'entity_id')}</td>
                  <td style={tdMono}>{displayItemField(row, 'issuer')}</td>
                  <td style={tdMono}>{displayItemField(row, 'security')}</td>
                  <td style={tdMono}>{displayItemField(row, 'listing')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'aliases')}</td>
                  <td style={tdMono}>{displayNestedField(row, 'identifiers', 'cik')}</td>
                  <td style={tdMono}>{displayNestedField(row, 'identifiers', 'figi')}</td>
                  <td style={tdMono}>{displayNestedField(row, 'identifiers', 'isin')}</td>
                  <td style={tdMono}>{displayNestedField(row, 'identifiers', 'cusip')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'state')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'unresolved_reason')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'source')}</td>
                  <td style={tdMono}>{displayItemField(row, 'as_of')}</td>
                  <td style={tdMono}>{presentItemKeys(row)}</td>
                  <td style={tdMono}>{extraKeysCell(row, IDENTITY_ITEM_KEYS)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </ControlPlaneFrame>
  )
}

export default IdentityPage
