import { Link } from 'react-router-dom'
import OpsDeskFrame from '../components/OpsDeskFrame'
import { JobCatalogView } from '../components/JobCatalogViews'
import { JobsN8nStyles } from '../components/JobsN8nViews'
import { TOKENS, TYPE } from '../lib/designTokens'
import { JOBS_N8N_PATH, OPS_CONTROLS_PATH } from '../lib/jobsN8n'

/** Ops › Job catalog (operator 2026-11-06: "There should be another page that categorizes all of the jobs").
 *  Read-only: GET /api/v2/jobs-catalog for the category cards, GET /api/v2/jobs-history for a category's jobs.
 *  `?category=<key>` opens that category as a full-screen sheet. */
export default function JobCatalogPage() {
  return <main style={{ padding: 'clamp(12px, 3vw, 20px)', background: TOKENS.bg[0], minWidth: 0 }}>
    <OpsDeskFrame page="jobsCatalog">
      <JobsN8nStyles />
      <div style={{ display: 'grid', gap: 12, minWidth: 0 }} data-testid="job-catalog-page">
        <JobCatalogView />
        <p data-testid="job-catalog-readonly-note" style={{ color: TOKENS.text[2], fontSize: TYPE.sm, margin: 0 }}>
          Read-only page. Runs, misses and fixes are in <Link to={JOBS_N8N_PATH} style={{ color: TOKENS.info }}>Jobs &amp; n8n</Link>; the switches stay in <Link to={OPS_CONTROLS_PATH} style={{ color: TOKENS.info }}>Ops Controls</Link>.
        </p>
      </div>
    </OpsDeskFrame>
  </main>
}
