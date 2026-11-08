import { Link, useNavigate } from 'react-router-dom'
import OpsDeskFrame from '../components/OpsDeskFrame'
import { JobAuditContext, JobCatalogView } from '../components/JobCatalogViews'
import { JobsN8nStyles } from '../components/JobsN8nViews'
import { N8nAuditHeaderView } from '../components/N8nCatalogViews'
import { useApi } from '../hooks/useApi'
import { TOKENS, TYPE } from '../lib/designTokens'
import { AUDIT_LINK_TEXT, N8N_AUDIT_PATH } from '../lib/jobCatalogAudit'
import { JOBS_N8N_PATH, OPS_CONTROLS_PATH } from '../lib/jobsN8n'
import { N8N_CATALOG_API, type N8nCatalogWire } from '../lib/n8nCatalog'
import { auditNavHref } from '../lib/n8nCatalogApproved'

/** Ops › Job catalog (operator 2026-11-06: "There should be another page that categorizes all of the jobs").
 *  Read-only: GET /api/v2/jobs-catalog for the category cards, GET /api/v2/jobs-history for a category's jobs.
 *  `?category=<key>` opens that category as a full-screen sheet.
 *  LQ-20261107-506 (operator 2026-11-07: "I need the desktop to have all of that same information that the phone has"):
 *  the n8n audit header and its six stat tiles sit at the top, from the same GET /api/v2/ops/n8n-catalog the
 *  Jobs & n8n > n8n audit tab reads, and every job card carries its n8n audit verdict badge. */
export default function JobCatalogPage() {
  const audit = useApi<N8nCatalogWire>(N8N_CATALOG_API, 60_000)
  const navigate = useNavigate()
  return <main style={{ padding: 'clamp(12px, 3vw, 20px)', background: TOKENS.bg[0], minWidth: 0 }}>
    <OpsDeskFrame page="jobsCatalog">
      <JobsN8nStyles />
      <JobAuditContext.Provider value={audit.data}>
        <div style={{ display: 'grid', gap: 12, minWidth: 0 }} data-testid="job-catalog-page">
          {audit.data
            ? <N8nAuditHeaderView data={audit.data} onNav={n => navigate(auditNavHref(n))} />
            : <p role="status" data-testid="n8n-audit-header-status" style={{ color: audit.error ? TOKENS.warning : TOKENS.text[2], fontSize: TYPE.sm, margin: 0 }}>
              {audit.error ? `The n8n audit could not be read: ${audit.error}. Job verdict badges are unavailable.` : 'Loading the n8n audit…'}</p>}
          <Link to={N8N_AUDIT_PATH} data-testid="job-catalog-audit-link" style={{ minHeight: 44, display: 'flex', alignItems: 'center', color: TOKENS.info, fontSize: TYPE.base, textDecoration: 'none' }}>{AUDIT_LINK_TEXT} →</Link>
          <JobCatalogView />
          <p data-testid="job-catalog-readonly-note" style={{ color: TOKENS.text[2], fontSize: TYPE.sm, margin: 0 }}>
            Read-only page. Runs, misses and fixes are in <Link to={JOBS_N8N_PATH} style={{ color: TOKENS.info }}>Jobs &amp; n8n</Link>; the switches stay in <Link to={OPS_CONTROLS_PATH} style={{ color: TOKENS.info }}>Ops Controls</Link>.
          </p>
        </div>
      </JobAuditContext.Provider>
    </OpsDeskFrame>
  </main>
}
