/**
 * Data Integrity — R23 side-by-side, GET /api/v3/control-plane/stores.
 * Intended route: /control-plane/data (NOT registered).
 * Renders CanonicalStoreRegistry-shaped items from CONTROL_PLANE_API_V1_BASELINE.
 * Does not recompute freshness, duplicates, quarantine, or orphans.
 * Missing fields display "absent". Does not fall back to preview JSON. live_claim=false.
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

const STORE_ITEM_KEYS = [
  'logical_store',
  'physical_root',
  'persistent_root',
  'writer',
  'readers',
  'freshness',
  'duplicate_count',
  'quarantine_count',
  'orphan_count',
  'schema_version',
  'last_write',
  'record_count',
  'source_sha',
  'authority',
] as const

interface Props {
  envelope?: ControlPlaneApiV1Envelope
}

export function DataIntegrityPage({ envelope }: Props) {
  const summary = useControlPlaneSummary(CONTROL_PLANE_SUMMARY_GET.stores, envelope)
  const stores = summary.items

  return (
    <ControlPlaneFrame
      title="Data Integrity"
      intendedRoute={R23_INTENDED_ROUTES.data}
      getUrl={CONTROL_PLANE_SUMMARY_GET.stores}
      canonicalFile={CANONICAL_RUNTIME_FILES.stores}
      envelope={summary.envelope}
      viewState={summary.viewState}
      error={summary.error}
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 8 }}>
        <div style={panelStyle} data-testid="persistent-root">
          <div style={sectionLabel}>Persistent root</div>
          <div style={{ marginTop: 6, fontFamily: 'var(--mono)', fontSize: 11 }}>
            absent at collection envelope — not a payload.persistent_root field.
            Per-item persistent_root / physical_root rendered below; missing keys display absent.
          </div>
        </div>
        <div style={panelStyle}>
          <div style={sectionLabel}>Legacy root</div>
          <div style={{ marginTop: 6, fontFamily: 'var(--mono)', fontSize: 11 }}>
            absent — not recomputed from CanonicalStoreRegistry.
          </div>
        </div>
      </div>

      <div style={sectionLabel}>CanonicalStoreRegistry</div>
      <div style={tableWrap}>
        <table style={tableStyle} data-testid="canonical-store-table">
          <thead>
            <tr>
              <th style={thStyle}>Logical store</th>
              <th style={thStyle}>Physical root</th>
              <th style={thStyle}>Persistent root</th>
              <th style={thStyle}>Writer</th>
              <th style={thStyle}>Readers</th>
              <th style={thStyle}>Freshness</th>
              <th style={thStyle}>Duplicates</th>
              <th style={thStyle}>Quarantine</th>
              <th style={thStyle}>Orphans</th>
              <th style={thStyle}>Schema</th>
              <th style={thStyle}>Last write</th>
              <th style={thStyle}>Records</th>
              <th style={thStyle}>Source SHA</th>
              <th style={thStyle}>Authority</th>
              <th style={thStyle}>Present keys</th>
              <th style={thStyle}>Other keys</th>
            </tr>
          </thead>
          <tbody>
            {stores.length === 0
              ? emptyCollectionMessage(summary.viewState, 16)
              : stores.map((row, index) => (
                <tr key={`${index}:${displayItemField(row, 'logical_store')}`}>
                  <td style={tdMono}>{displayItemField(row, 'logical_store')}</td>
                  <td style={tdMono}>{displayItemField(row, 'physical_root')}</td>
                  <td style={tdMono}>{displayItemField(row, 'persistent_root')}</td>
                  <td style={tdMono}>{displayItemField(row, 'writer')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'readers')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'freshness')}</td>
                  <td style={tdMono}>{displayItemField(row, 'duplicate_count')}</td>
                  <td style={tdMono}>{displayItemField(row, 'quarantine_count')}</td>
                  <td style={tdMono}>{displayItemField(row, 'orphan_count')}</td>
                  <td style={tdMono}>{displayItemField(row, 'schema_version')}</td>
                  <td style={tdMono}>{displayItemField(row, 'last_write')}</td>
                  <td style={tdMono}>{displayItemField(row, 'record_count')}</td>
                  <td style={tdMono}>{displayItemField(row, 'source_sha')}</td>
                  <td style={tdStyle}>{displayItemField(row, 'authority')}</td>
                  <td style={tdMono}>{presentItemKeys(row)}</td>
                  <td style={tdMono}>{extraKeysCell(row, STORE_ITEM_KEYS)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </ControlPlaneFrame>
  )
}

export default DataIntegrityPage
