import type { ReactNode } from 'react'
import { useApi } from '../../hooks/useApi'

type Brain = {
  schema?: string
  as_of?: string
  state?: string
  authority?: string
  memory_behavior_influence?: number
  unresolved_conflicts?: string[]
  operator_policy?: any
  portfolio_state?: any
  market_context?: any
  seasonality?: any
  portfolio_thesis?: any
  portfolio_thesis_delta?: any
  capital_situation?: any
  capital_plan?: any
  methodology?: any
  learning?: any
  memory?: any
  symbol_theses?: any
  research?: any
  proactive_cio?: any
  operator_value?: any
  intelligence_lifecycle?: any
  model_performance?: any
  versions?: Record<string, string | number | null>
  _serving?: {
    loaded_pin_sha?: string | null
    current_pin_sha?: string | null
    process_started_at?: string | null
    pin_match?: boolean
  }
}

function money(value: number | null | undefined): string {
  if (value == null) return 'UNVERIFIED'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value)
}

function valueOf(field: any): string {
  if (!field || field.value == null) return 'UNAVAILABLE'
  if (typeof field.value === 'object') return JSON.stringify(field.value)
  return String(field.value)
}

function Metric({ label, value, state }: { label: string; value: ReactNode; state?: string }) {
  return (
    <div className="cio-brain__metric">
      <div className="cio-brain__eyebrow">{label}</div>
      <div className="cio-brain__metric-value">{value}</div>
      {state && <div className="cio-brain__state">{state}</div>}
    </div>
  )
}

function Band({ title, state, children, testId }: { title: string; state?: string; children: ReactNode; testId: string }) {
  return (
    <section className="cio-brain__band" data-testid={testId}>
      <div className="cio-brain__band-head">
        <h2>{title}</h2>
        {state && <span>{state}</span>}
      </div>
      {children}
    </section>
  )
}

function List({ rows, empty = 'None current' }: { rows: any[] | undefined; empty?: string }) {
  const items = Array.isArray(rows) ? rows : []
  if (!items.length) return <div className="cio-brain__muted">{empty}</div>
  return (
    <ul className="cio-brain__list">
      {items.slice(0, 8).map((row, index) => (
        <li key={`${index}-${JSON.stringify(row).slice(0, 40)}`}>
          {typeof row === 'string'
            ? row
            : row.question || row.condition || row.item || row.symbol || row.role || row.reason || JSON.stringify(row)}
          {typeof row === 'object' && row.reason && (row.question || row.condition || row.item || row.role)
            ? <span> · {row.reason}</span>
            : null}
        </li>
      ))}
    </ul>
  )
}

export default function CioBrainPanel() {
  const { data, loading, error } = useApi<Brain>('/api/v3/cio/brain')
  if (loading && !data) return <div className="cio-brain__loading">Loading CIO brain…</div>
  if (error && !data) return <div className="cio-brain__error">CIO brain unavailable: {String(error)}</div>

  const brain = data || {}
  const portfolio = brain.portfolio_state || {}
  const allocation = portfolio.allocation || {}
  const market = brain.market_context || {}
  const marketFields = market.fields || {}
  const thesis = brain.portfolio_thesis || {}
  const capital = brain.capital_plan || {}
  const situation = brain.capital_situation || {}
  const canon = brain.methodology?.canon || {}
  const methodology = brain.methodology?.methodology_policy || {}
  const feedback = brain.learning?.feedback || {}
  const outcomes = brain.learning?.outcomes || {}
  const policy = brain.operator_policy || {}
  const serving = brain._serving || {}
  const cashPct = allocation.cash?.pct
  const ov = brain.operator_value || {}
  const situations = Array.isArray(ov.current_material_situations) ? ov.current_material_situations : []
  const notif = ov.notifications || brain.proactive_cio || {}
  const shadow = ov.memory_shadow || {}

  return (
    <div className="cio-brain" data-testid="cio-brain">
      <div className="cio-brain__status-row">
        <Metric label="Portfolio" value={money(portfolio.total_portfolio_value_usd)} state={portfolio.truth_quality} />
        <Metric label="Observed cash" value={money(portfolio.observed_cash_usd)} state={cashPct == null ? 'PCT UNAVAILABLE' : `${Number(cashPct).toFixed(1)}%`} />
        <Metric label="Investable cash" value={money(portfolio.investable_cash_usd)} state={portfolio.investable_cash_status} />
        <Metric label="CIO posture" value={thesis.current_posture || 'INSUFFICIENT DATA'} state={thesis.state} />
      </div>

      <Band title="What changed" state={ov.what_changed || brain.portfolio_thesis_delta?.classification} testId="cio-brain-what-changed">
        <div className="cio-brain__lead">{ov.what_changed || thesis.core_thesis || 'NO_NEW_INFO'}</div>
      </Band>

      <div className="cio-brain__pair">
        <Band title="What the CIO knows" testId="cio-brain-what-it-knows">
          <List rows={ov.what_cio_knows} empty="No current versioned planes" />
        </Band>
        <Band title="What it does not know" testId="cio-brain-what-it-does-not-know">
          <List rows={ov.what_cio_does_not_know} empty="No unresolved gaps" />
        </Band>
      </div>

      <Band title="Current material situations" testId="cio-brain-material-situations">
        <List
          rows={situations.map((row: any) => `${row.class || 'NONE'} · ${row.what_changed || row.conclusion || 'n/a'}`)}
          empty="No material situations"
        />
      </Band>

      <Band title="Current recommendation" testId="cio-brain-current-recommendation">
        <div className="cio-brain__lead">{ov.current_recommendation || capital.stance || situation.conclusion || 'NONE'}</div>
        <div className="cio-brain__split">
          <div><h3>Why</h3><p>{typeof ov.why === 'string' ? ov.why : (thesis.core_thesis || 'UNAVAILABLE')}</p></div>
          <div><h3>What would change the view</h3><List rows={ov.what_would_change_the_view} /></div>
        </div>
      </Band>

      <Band title="What needs my attention" testId="cio-brain-attention">
        <List rows={(ov.attention || situations).map((row: any) => typeof row === 'string' ? row : `${row.class || ''} · ${row.what_changed || row.conclusion || ''}`)} empty="Nothing material now" />
      </Band>
      <Band title="Uncertainty" testId="cio-brain-uncertainty">
        <List rows={ov.uncertainty} empty="No named uncertainty" />
      </Band>
      <Band title="Missing policy" testId="cio-brain-missing-policy">
        <List rows={ov.missing_policy} empty="No missing confirmed policy fields in this snapshot" />
      </Band>
      <Band title="What was suppressed" testId="cio-brain-suppressed">
        <div className="cio-brain__lead">{String(ov.what_was_suppressed || notif.why || 'n/a')}</div>
      </Band>
      <Band title="What happens next" testId="cio-brain-next">
        <div className="cio-brain__lead">{String(ov.what_happens_next || capital.next_review || 'UNSCHEDULED')}</div>
      </Band>
      <Band title="Notifications" testId="cio-brain-notifications">
        <div className="cio-brain__facts">
          <span>Sent<strong>{notif.sent ? 'YES' : 'NO'}</strong></span>
          <span>Suppressed<strong>{notif.suppressed ? 'YES' : 'NO'}</strong></span>
          <span>Why<strong>{String(notif.why || brain.proactive_cio?.suppression_reason || 'n/a')}</strong></span>
        </div>
      </Band>

      <Band title="Memory shadow" state={shadow.status} testId="cio-brain-memory-shadow">
        <div className="cio-brain__facts">
          <span>Status<strong>{shadow.status || 'ISOLATED_ONLY'}</strong></span>
          <span>Parity<strong>{String(shadow.parity ?? 'n/a')}</strong></span>
          <span>Lag<strong>{String(shadow.lag ?? 'n/a')}</strong></span>
          <span>Production authority<strong>false</strong></span>
        </div>
        <p className="cio-brain__muted">Shadow is non-authoritative. Behavior influence 0.</p>
      </Band>

      <Band title="Portfolio Thesis" state={brain.portfolio_thesis_delta?.classification} testId="cio-brain-portfolio-thesis">
        <div className="cio-brain__lead">{thesis.core_thesis || 'No current portfolio thesis.'}</div>
        <div className="cio-brain__split">
          <div><h3>Counter-thesis</h3><p>{thesis.counter_thesis || 'UNAVAILABLE'}</p></div>
          <div><h3>What changes the view</h3><List rows={thesis.what_changes_the_cio_mind} /></div>
        </div>
      </Band>

      <Band title="Capital Deployment" state={capital.stance || situation.conclusion} testId="cio-brain-capital-deployment">
        <div className="cio-brain__status-row cio-brain__status-row--compact">
          <Metric label="Available" value={money(capital.available_capital_usd)} />
          <Metric label="Reserved" value={money(capital.reserved_capital_usd)} />
          <Metric label="Policy range" value={capital.target_cash_range_pct ? JSON.stringify(capital.target_cash_range_pct) : 'POLICY REQUIRED'} />
          <Metric label="Notification" value={brain.proactive_cio?.notification_eligible ? 'ELIGIBLE' : 'SUPPRESSED'} state={brain.proactive_cio?.suppression_reason} />
        </div>
        <div className="cio-brain__columns">
          <div><h3>Do now</h3><List rows={capital.do_now} /></div>
          <div><h3>On pullback</h3><List rows={capital.do_on_pullback} /></div>
          <div><h3>Wait</h3><List rows={capital.wait} /></div>
          <div><h3>Research first</h3><List rows={capital.research_first} /></div>
          <div><h3>Keep cash</h3><List rows={capital.keep_cash_short_duration} /></div>
        </div>
        <div className="cio-brain__footline">Next review: {capital.next_review || 'UNSCHEDULED'} · Executable order: NONE</div>
      </Band>

      <div className="cio-brain__pair">
        <Band title="Market Context" state={market.truth_quality} testId="cio-brain-market-context">
          <div className="cio-brain__facts">
            <span>Regime<strong>{valueOf(marketFields.regime)}</strong></span>
            <span>Breadth<strong>{valueOf(marketFields.breadth)}</strong></span>
            <span>Fed funds<strong>{valueOf(marketFields.fed_funds_rate_pct)}</strong></span>
            <span>10Y–2Y<strong>{valueOf(marketFields.ten_two_spread_pct)}</strong></span>
            <span>VIX<strong>{valueOf(marketFields.vix_close)}</strong></span>
            <span>Valuation<strong>{valueOf(marketFields.valuation)}</strong></span>
          </div>
        </Band>
        <Band title="Seasonality" state={brain.seasonality?.truth_quality} testId="cio-brain-seasonality">
          <div className="cio-brain__lead">{brain.seasonality?.benchmark || 'SPY'} · {brain.seasonality?.instrument_count || 0} measured instruments</div>
          <p className="cio-brain__muted">Computed from verified price history. Context only; never execution authority.</p>
        </Band>
      </div>

      <Band title="Memory" state={brain.memory?.status} testId="cio-brain-memory">
        <div className="cio-brain__facts">
          <span>Durable records<strong>{brain.memory?.total ?? 0}</strong></span>
          <span>Candidates<strong>{brain.memory?.counts?.CANDIDATE ?? 0}</strong></span>
          <span>Active / admitted<strong>{brain.memory?.counts?.ADMITTED ?? 0}</strong></span>
          <span>Retrieval receipts<strong>{brain.memory?.retrieval_receipts ?? 0}</strong></span>
        </div>
        <p className="cio-brain__muted">{brain.memory?.retrieval || 'Retrieval unavailable'} · NON_AUTHORITATIVE_CONTEXT · behavior influence 0</p>
      </Band>

      <div className="cio-brain__pair">
        <Band title="Methodology" state={canon.source_claim_incomplete ? 'SOURCE CLAIM INCOMPLETE' : 'CURRENT'} testId="cio-brain-methodology">
          <div className="cio-brain__facts">
            <span>Catalog<strong>{canon.catalog_total ?? 0}</strong></span>
            <span>Source text<strong>{canon.source_text_present ?? 0}</strong></span>
            <span>Ratified<strong>{canon.claim_counts?.RATIFIED_ADVISORY ?? 0}</strong></span>
            <span>Influence<strong>{methodology.decision_influence || 'RATIFIED ONLY'}</strong></span>
          </div>
        </Band>
        <Band title="Learning" state={outcomes.observation_window} testId="cio-brain-learning">
          <div className="cio-brain__facts">
            <span>Linked feedback<strong>{feedback.linked_rows ?? 0}</strong></span>
            <span>Preference candidates<strong>{feedback.preference_candidates?.length ?? 0}</strong></span>
            <span>Frozen outcomes<strong>{outcomes.frozen ?? 0}</strong></span>
            <span>Matured outcomes<strong>{outcomes.matured ?? 0}</strong></span>
          </div>
          <p className="cio-brain__muted">Memory behavior influence: {brain.memory_behavior_influence ?? 0}</p>
        </Band>
      </div>

      <div className="cio-brain__pair">
        <Band title="Symbol Theses & Research" state={`${brain.symbol_theses?.count || 0} current decisions`} testId="cio-brain-symbol-theses">
          <div className="cio-brain__facts">
            <span>Open plans<strong>{brain.research?.open_plans ?? 0}</strong></span>
            <span>Research gaps<strong>{brain.research?.gaps?.length ?? 0}</strong></span>
          </div>
          <List rows={brain.research?.gaps} empty="No surfaced research gaps" />
        </Band>
        <Band title="Operator Policy" state={policy.status} testId="cio-brain-operator-policy">
          <div className="cio-brain__facts">
            <span>Confirmed fields<strong>{policy.confirmed_field_count ?? 0}/{policy.required_field_count ?? 0}</strong></span>
            <span>Unresolved conflicts<strong>{policy.legacy_conflicts?.length ?? 0}</strong></span>
          </div>
          <List rows={policy.missing_fields} empty="All required policy fields confirmed" />
        </Band>
      </div>

      <Band title="Intelligence lifecycle" testId="cio-brain-intelligence-lifecycle">
        <div className="cio-brain__facts">
          <span>Why awake<strong>{String(brain.intelligence_lifecycle?.projection?.WHY_AWAKE || 'SCHEDULED_OR_IDLE')}</strong></span>
          <span>Free-first<strong>{String(brain.intelligence_lifecycle?.projection?.FREE_FIRST_STATUS || 'HOURLY_BASELINE')}</strong></span>
          <span>LLM<strong>{String(brain.intelligence_lifecycle?.projection?.LLM_STATUS || 'DETERMINISTIC')}</strong></span>
          <span>Ingestion bus<strong>false</strong></span>
        </div>
        <p className="cio-brain__muted">GUI is a projection. It does not ingest office events.</p>
      </Band>
      <Band title="Graph context" testId="cio-brain-graph-context">
        <div className="cio-brain__facts">
          <span>Wake<strong>{String((brain.intelligence_lifecycle?.projection?.ENTITY_RELATIONSHIPS?.wake || []).length || 0)}</strong></span>
          <span>Context only<strong>{String((brain.intelligence_lifecycle?.projection?.ENTITY_RELATIONSHIPS?.context_only || []).length || 0)}</strong></span>
        </div>
        <p className="cio-brain__muted">No decorative relationships. Membership + exposure + freshness required.</p>
      </Band>
      <Band title="Curation history" testId="cio-brain-curation-history">
        <div className="cio-brain__facts">
          <span>Version<strong>{String(brain.intelligence_lifecycle?.projection?.CURATION_VERSION ?? 'BASELINE_OR_NONE')}</strong></span>
          <span>Thesis<strong>{String(brain.intelligence_lifecycle?.projection?.THESIS_VERSION ?? 'NONE')}</strong></span>
        </div>
      </Band>
      <Band title="Model selection" testId="cio-brain-model-performance">
        <div className="cio-brain__facts">
          <span>Policy<strong>{String(brain.intelligence_lifecycle?.model_reason?.executed_policy || 'DETERMINISTIC')}</strong></span>
          <span>Why Flash<strong>{String(brain.intelligence_lifecycle?.model_reason?.why_flash || 'not used')}</strong></span>
          <span>Why not Pro<strong>{String(brain.intelligence_lifecycle?.model_reason?.why_pro_not_needed || 'n/a')}</strong></span>
          <span>Self-promote<strong>false</strong></span>
        </div>
        <p className="cio-brain__muted">Routing candidates never edit model registries from this panel.</p>
      </Band>
      <Band title="What is not wired" testId="cio-brain-unwired">
        <List rows={brain.intelligence_lifecycle?.unwired_providers} empty="No declared gaps in this snapshot" />
      </Band>
      <Band title="Knowledge gaps" testId="cio-brain-knowledge-gaps">
        <List
          rows={brain.intelligence_lifecycle?.knowledge_gaps || ['NOT_CONFIGURED', 'UNAVAILABLE', 'STALE', 'UNRESOLVED_IDENTITY', 'POLICY_GAP', 'INSUFFICIENT_MODEL_SAMPLES', 'NO_OUTCOME_HISTORY']}
          empty="No declared knowledge gaps"
        />
        <p className="cio-brain__muted">Gaps are explicit. Missing providers do not crash this panel.</p>
      </Band>

      <Band title="System Health" state={serving.pin_match ? 'PIN MATCH' : 'PIN MISMATCH'} testId="cio-brain-system-health">
        <div className="cio-brain__source">
          <span>Loaded <strong>{serving.loaded_pin_sha || 'UNAVAILABLE'}</strong></span>
          <span>Current <strong>{serving.current_pin_sha || 'UNAVAILABLE'}</strong></span>
          <span>Process started <strong>{serving.process_started_at || 'UNAVAILABLE'}</strong></span>
          <span>Authority <strong>{brain.authority || 'READ_ONLY_ADVISORY'}</strong></span>
        </div>
      </Band>
    </div>
  )
}
