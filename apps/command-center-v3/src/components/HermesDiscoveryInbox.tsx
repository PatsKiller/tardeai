import { useMemo, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { WL, numStyle } from '../lib/watchlistCardTokens'

// Hermes Discovery Inbox — operator triage surface for discovery candidates
// (sources / research topics / watch directives / tickers) staged by the
// discovery pipeline. Follows the LOCKED v4 card design system: calm neutral
// surfaces, signal-only color (teal = actionable, amber = needs-validation,
// red = blocked/risk), one tinted element per card, mono numerals.
//
// Everything here is ADVISORY ONLY — approvals feed staging tables, never
// trades, never execution, never Bucket-1 scalp promotion.
//
// API contract (Stage-2, may land after this UI — degrade gracefully):
//   GET  /api/v2/hermes/discovery-inbox?type=&status=&domain=&limit=
//   GET  /api/v2/hermes/discovery-scorecard
//   POST /api/v2/hermes/discovery-inbox/{id}/{action}

const ADVISORY_FOOTER = 'Advisory only. No trade. No execution. No Bucket-1 scalp promotion.'
const MATURITY_LINE = 'Discovery automation ON · Autonomous promotion OFF · Learning: collecting evidence'

interface Candidate {
  id: number | string
  candidate_type: string
  label: string
  summary: string
  status: string
  source_domain: string | null
  source_url: string | null
  seed_symbols: unknown
  extracted_symbols: unknown
  evidence_json: unknown
  score_json: { total?: number; parts?: unknown } | string | null
  risk_flags_json: unknown
  duplicate_cluster_id: number | string | null
  recommended_action: string | null
  safe_action_level: string | null
  seen_count: number | null
  first_seen_at: string | null
  last_seen_at: string | null
  operator_decision: string | null
  // URDL meta_json contract fields — hoisted by the list endpoint; fall back
  // to meta_json itself when talking to an older backend (metaField below).
  meta_json?: unknown
  research_domain?: string | null
  domain_risk_level?: string | null
  subject_json?: unknown
  advisory_label?: string | null
  required_review_label?: string | null
  llm_review_json?: unknown
  domain_promotion_paths?: unknown
}
interface InboxData { candidates?: Candidate[]; stats?: Record<string, unknown> }

// ── tolerant parsing helpers (contract fields are *_json — shape may drift) ──

function parseMaybeJson(v: unknown): unknown {
  if (typeof v !== 'string') return v
  const t = v.trim()
  if (!t) return null
  if (t.startsWith('{') || t.startsWith('[')) { try { return JSON.parse(t) } catch { return v } }
  return v
}

function asStringList(v: unknown): string[] {
  const p = parseMaybeJson(v)
  if (p == null) return []
  if (Array.isArray(p)) return p.map(x => (typeof x === 'string' ? x : (x as any)?.symbol ?? (x as any)?.label ?? '')).map(String).filter(Boolean)
  if (typeof p === 'string') return p.split(/[,\s]+/).filter(Boolean)
  if (typeof p === 'object') return Object.keys(p as object)
  return []
}

function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url.slice(0, 40) }
}

interface EvidenceLink { label: string; url?: string }
function evidenceLinks(c: Candidate): EvidenceLink[] {
  const out: EvidenceLink[] = []
  const seen = new Set<string>()
  const push = (l: EvidenceLink) => {
    const k = `${l.label}|${l.url ?? ''}`
    if (!seen.has(k)) { seen.add(k); out.push(l) }
  }
  if (c.source_url) push({ label: c.source_domain || hostOf(c.source_url), url: c.source_url })
  const ev = parseMaybeJson(c.evidence_json)
  let items: unknown[] = []
  if (Array.isArray(ev)) items = ev
  else if (ev && typeof ev === 'object') {
    const o = ev as Record<string, unknown>
    items = Array.isArray(o.items) ? o.items : Array.isArray(o.refs) ? o.refs : Array.isArray(o.links) ? o.links : Object.values(o)
  } else if (typeof ev === 'string' && ev) items = [ev]
  for (const e of items) {
    if (typeof e === 'string') {
      if (e.startsWith('http')) push({ label: hostOf(e), url: e })
      else push({ label: e.slice(0, 90) })
    } else if (e && typeof e === 'object') {
      const o = e as Record<string, unknown>
      const url = typeof o.url === 'string' ? o.url : typeof o.link === 'string' ? o.link : typeof o.href === 'string' ? o.href : undefined
      const label = o.title ?? o.label ?? o.note ?? o.source ?? o.reason ?? (url ? hostOf(url) : null)
      if (label != null) push({ label: String(label).slice(0, 90), url })
    }
  }
  return out
}

function riskFlags(c: Candidate): string[] {
  const p = parseMaybeJson(c.risk_flags_json)
  if (p == null) return []
  if (Array.isArray(p)) return p.map(f => (typeof f === 'string' ? f : (f as any)?.flag ?? (f as any)?.label ?? JSON.stringify(f))).map(String).filter(Boolean)
  if (typeof p === 'string') return p ? [p] : []
  if (typeof p === 'object') return Object.entries(p as Record<string, unknown>).filter(([, v]) => !!v).map(([k]) => k)
  return []
}

// ── URDL meta_json contract helpers (research_domain / domain_risk_level /
//    subject_json / advisory_label / required_review_label / llm_review_json) ──

function metaField(c: Candidate, key: string): unknown {
  const direct = (c as unknown as Record<string, unknown>)[key]
  if (direct != null) return parseMaybeJson(direct)
  const m = parseMaybeJson(c.meta_json)
  if (m && typeof m === 'object' && !Array.isArray(m)) return parseMaybeJson((m as Record<string, unknown>)[key])
  return null
}

function metaStr(c: Candidate, key: string): string {
  const v = metaField(c, key)
  return typeof v === 'string' ? v : v != null && typeof v !== 'object' ? String(v) : ''
}

function metaObj(c: Candidate, key: string): Record<string, unknown> | null {
  const v = metaField(c, key)
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null
}

// risk levels whose domain chip renders amber (professional-review adjacent)
const AMBER_RISK_LEVELS = new Set(['tax', 'legal', 'planning', 'medical'])

const LLM_SCORE_KEYS: [string, string][] = [
  ['relevance_score', 'relevance'], ['source_quality_score', 'source quality'],
  ['novelty_score', 'novelty'], ['risk_score', 'risk'],
  ['hallucination_risk', 'hallucination risk'], ['duplicate_risk', 'duplicate risk'],
  ['confidence', 'confidence'],
]

function llmScoresTip(r: Record<string, unknown>): string {
  const lines = LLM_SCORE_KEYS
    .filter(([k]) => r[k] != null && Number.isFinite(Number(r[k])))
    .map(([k, label]) => `${label}: ${Number(r[k]).toFixed(2)}`)
  if (r.legal_tax_sensitive) lines.push('legal/tax sensitive')
  if (r.needs_professional_review) lines.push('needs professional review')
  return lines.join('\n') || 'llm review scores unavailable'
}

function scoreOf(c: Candidate): { total: number | null; parts: [string, string][] } {
  const s = parseMaybeJson(c.score_json) as { total?: unknown; parts?: unknown } | null
  if (!s || typeof s !== 'object') return { total: null, parts: [] }
  const total = Number((s as any).total)
  const rawParts = parseMaybeJson((s as any).parts)
  const parts: [string, string][] = []
  if (rawParts && typeof rawParts === 'object' && !Array.isArray(rawParts)) {
    for (const [k, v] of Object.entries(rawParts as Record<string, unknown>)) parts.push([k.replace(/_/g, ' '), String(v)])
  } else if (Array.isArray(rawParts)) {
    for (const p of rawParts) {
      if (p && typeof p === 'object') parts.push([String((p as any).name ?? (p as any).label ?? '?').replace(/_/g, ' '), String((p as any).value ?? (p as any).score ?? '')])
    }
  }
  return { total: Number.isFinite(total) ? total : null, parts }
}

function ago(v: string | null | undefined): string {
  if (!v) return '—'
  const t = new Date(v).getTime()
  if (!Number.isFinite(t)) return '—'
  const h = (Date.now() - t) / 36e5
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m ago`
  if (h < 48) return `${Math.round(h)}h ago`
  return `${Math.round(h / 24)}d ago`
}

// ── status → state class (color = signal only) ──────────────────────────────

function stateOf(status: string | null | undefined): { word: string; color: string } {
  const s = String(status ?? '').toLowerCase()
  const word = (status || 'new').replace(/[_-]/g, ' ').toUpperCase()
  if (/(blocked|block|risk|fail)/.test(s)) return { word, color: WL.signal.red }
  if (/(approved|promot|staged|accept)/.test(s)) return { word, color: WL.signal.teal }
  if (/(reject|merged|duplicate|dismiss|archiv)/.test(s)) return { word, color: WL.text.dim }
  if (/(needs|pending|validat|review|stale|hold)/.test(s)) return { word, color: WL.signal.amber }
  return { word, color: WL.text.secondary } // new / discovered — neutral, no urgency invented
}

const TERMINAL_RE = /(approved|promot|staged|reject|blocked|merged|dismiss|archiv)/

// ── actions ──────────────────────────────────────────────────────────────────

interface ActionDef { slug: string; label: string; forTypes?: string[]; confirm?: boolean; danger?: boolean; requiresCluster?: boolean }
const ACTIONS: ActionDef[] = [
  { slug: 'approve-source', label: 'Approve source', forTypes: ['source', 'feed', 'rss', 'site', 'domain'] },
  { slug: 'approve-research-topic', label: 'Approve research topic', forTypes: ['research_topic', 'topic', 'theme'] },
  { slug: 'approve-watch-directive', label: 'Approve watch directive', forTypes: ['watch_directive', 'directive'] },
  { slug: 'stage-ticker', label: 'Stage ticker', forTypes: ['ticker', 'symbol', 'equity', 'etf'] },
  { slug: 'needs-more-data', label: 'Needs more data' },
  { slug: 'merge', label: 'Merge', requiresCluster: true },
  { slug: 'reject', label: 'Reject', confirm: true, danger: true },
  { slug: 'block', label: 'Block', confirm: true, danger: true },
]

function actionsFor(c: Candidate): ActionDef[] {
  const t = String(c.candidate_type ?? '').toLowerCase()
  const typed = ACTIONS.filter(a => a.forTypes && a.forTypes.some(ft => t === ft || t.includes(ft)))
  // unknown type: fall back to the backend's own recommendation if it names an approve action
  const approve = typed.length ? typed
    : ACTIONS.filter(a => a.forTypes && a.slug === String(c.recommended_action ?? '').toLowerCase().replace(/_/g, '-'))
  const generic = ACTIONS.filter(a => !a.forTypes && (!a.requiresCluster || c.duplicate_cluster_id != null))
  return [...approve, ...generic]
}

// ── shared styles ────────────────────────────────────────────────────────────

const moduleLabel: CSSProperties = {
  fontSize: 10, fontWeight: 700, letterSpacing: '.09em', textTransform: 'uppercase', color: WL.text.dim,
}
const filterCtl: CSSProperties = {
  fontSize: 11, color: WL.text.secondary, background: WL.surface.inset,
  border: `1px solid ${WL.surface.edge}`, borderRadius: 6, padding: '5px 8px', outline: 'none',
}
const chipStyle = (color: string): CSSProperties => ({
  fontSize: 9.5, fontWeight: 700, letterSpacing: '.05em', color,
  border: `1px solid ${color}55`, borderRadius: 4, padding: '1px 6px', whiteSpace: 'nowrap',
})

function textButton(color: string, disabled: boolean): CSSProperties {
  return {
    fontSize: 11, fontWeight: 700, color: disabled ? WL.text.dim : color,
    background: 'none', border: 'none', padding: 0, cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.55 : 1, whiteSpace: 'nowrap',
  }
}

// ── scorecard strip ──────────────────────────────────────────────────────────

function fmtRate(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n <= 1 ? `${(n * 100).toFixed(0)}%` : `${n.toFixed(0)}%`
}

function scorecardTiles(sc: Record<string, unknown> | null): { label: string; value: string }[] {
  if (!sc || typeof sc !== 'object') return []
  const tiles: { label: string; value: string }[] = []
  const byType = (sc.discovered_by_type ?? sc.by_type ?? sc.counts_by_type ?? sc.candidates_by_type) as Record<string, unknown> | undefined
  if (byType && typeof byType === 'object' && !Array.isArray(byType)) {
    for (const [k, v] of Object.entries(byType)) tiles.push({ label: k.replace(/_/g, ' '), value: String(v) })
  }
  const dup = sc.dup_rate ?? sc.duplicate_rate ?? sc.dedup_rate
  if (dup != null) tiles.push({ label: 'dup rate', value: fmtRate(dup) })
  const vfail = sc.validation_failure_rate ?? sc.validation_fail_rate ?? sc.failure_rate
  if (vfail != null) tiles.push({ label: 'validation fail', value: fmtRate(vfail) })
  if (tiles.length === 0) {
    for (const [k, v] of Object.entries(sc)) {
      if (typeof v === 'number' || typeof v === 'string') tiles.push({ label: k.replace(/_/g, ' '), value: String(v) })
      if (tiles.length >= 8) break
    }
  }
  return tiles.slice(0, 10)
}

// ── candidate card ───────────────────────────────────────────────────────────

interface AuditRow { id?: number | string; action?: string; actor?: string; notes?: string | null; created_at?: string | null }

function DiscoveryCard({ c, onDone }: { c: Candidate; onDone: () => void }) {
  const [evOpen, setEvOpen] = useState(false)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [actErr, setActErr] = useState<string | null>(null)
  const [decidedAs, setDecidedAs] = useState<string | null>(null)
  const [llmBusy, setLlmBusy] = useState(false)
  const [llmErr, setLlmErr] = useState<string | null>(null)
  const [localReview, setLocalReview] = useState<Record<string, unknown> | null>(null)
  const [auditOpen, setAuditOpen] = useState(false)
  const [auditRows, setAuditRows] = useState<AuditRow[] | null>(null)
  const [auditErr, setAuditErr] = useState<string | null>(null)

  const st = stateOf(decidedAs ? `${decidedAs}` : c.status)
  const { total, parts } = scoreOf(c)
  const flags = riskFlags(c)
  const links = evidenceLinks(c)
  const shownLinks = evOpen ? links : links.slice(0, 3)
  const seeds = asStringList(c.seed_symbols)
  const extracted = asStringList(c.extracted_symbols).filter(s => !seeds.includes(s))
  const typeLabel = String(c.candidate_type ?? 'candidate').replace(/[_-]/g, ' ').toUpperCase()
  const terminal = decidedAs != null || TERMINAL_RE.test(String(c.status ?? '').toLowerCase()) || !!c.operator_decision
  const scoreTip = parts.length ? parts.map(([k, v]) => `${k}: ${v}`).join('\n') : 'composite discovery score'
  const recSlug = String(c.recommended_action ?? '').toLowerCase().replace(/_/g, '-')

  // URDL enrichment (meta_json contract)
  const rDomain = metaStr(c, 'research_domain')
  const riskLevel = metaStr(c, 'domain_risk_level').toLowerCase()
  const requiredReview = metaStr(c, 'required_review_label')
  const subject = metaObj(c, 'subject_json')
  const subjectType = subject && typeof subject.subject_type === 'string' ? subject.subject_type : ''
  const recurrence = subject != null ? Number(subject.recurrence_count) : NaN
  const crossSource = subject != null ? Number(subject.cross_source_count) : NaN
  const review = localReview ?? metaObj(c, 'llm_review_json')
  const promoPaths = asStringList(c.domain_promotion_paths)
  const domainAmber = AMBER_RISK_LEVELS.has(riskLevel)

  const requestReview = async () => {
    if (llmBusy || busy != null) return
    setLlmBusy(true)
    setLlmErr(null)
    try {
      const r = await fetch(`/api/v2/hermes/discovery-inbox/${encodeURIComponent(String(c.id))}/request-llm-review`, { method: 'POST' })
      let j: any = null
      try { j = await r.json() } catch { /* non-JSON error body */ }
      if (r.status === 429) throw new Error(j?.reason || 'daily LLM review cap exhausted — try tomorrow')
      if (!r.ok || (j && j.ok === false)) throw new Error(j?.reason || j?.error || j?.detail || `HTTP ${r.status}`)
      if (j?.llm_review_json && typeof j.llm_review_json === 'object') setLocalReview(j.llm_review_json)
      setAuditRows(null) // review appends an audit row — refetch on next expand
      onDone()
    } catch (e: any) {
      setLlmErr(e?.message || 'LLM review failed')
    } finally {
      setLlmBusy(false)
    }
  }

  const toggleAudit = async () => {
    if (auditOpen) { setAuditOpen(false); return }
    setAuditOpen(true)
    if (auditRows != null) return
    setAuditErr(null)
    try {
      const r = await fetch(`/api/v2/hermes/discovery-inbox/${encodeURIComponent(String(c.id))}`)
      const j: any = await r.json().catch(() => null)
      if (!r.ok) throw new Error(j?.error || `HTTP ${r.status}`)
      setAuditRows(Array.isArray(j?.audit) ? j.audit : [])
    } catch (e: any) {
      setAuditErr(e?.message || 'audit trail unavailable')
    }
  }

  const doAction = async (a: ActionDef) => {
    if (busy || terminal) return
    if (a.confirm && confirming !== a.slug) { setConfirming(a.slug); window.setTimeout(() => setConfirming(cur => (cur === a.slug ? null : cur)), 5000); return }
    setConfirming(null)
    setBusy(a.slug)
    setActErr(null)
    try {
      const r = await fetch(`/api/v2/hermes/discovery-inbox/${encodeURIComponent(String(c.id))}/${a.slug}`, { method: 'POST' })
      let j: any = null
      try { j = await r.json() } catch { /* non-JSON error body */ }
      if (!r.ok || (j && j.ok === false)) throw new Error(j?.error || j?.detail || `HTTP ${r.status}`)
      setDecidedAs(a.slug.replace(/-/g, ' '))
      onDone()
    } catch (e: any) {
      setActErr(e?.message || 'action failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div style={{
      background: WL.surface.card,
      border: `1px solid ${WL.surface.edge}`,
      borderLeft: `3px solid ${st.color}`,
      borderRadius: WL.card.radius,
      boxShadow: WL.card.shadow,
      color: WL.text.primary,
      overflow: 'hidden',
      minWidth: 0,
    }}>
      {/* header — identity + state word + score */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '11px 18px 8px', minWidth: 0 }}>
        <span style={chipStyle(WL.text.muted)}>{typeLabel}</span>
        <span style={{ fontSize: 14, fontWeight: 800, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.label}>
          {c.label || '(unlabeled candidate)'}
        </span>
        <span style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: '.08em', color: st.color, flexShrink: 0 }}>{st.word}</span>
        <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'baseline', gap: 6, flexShrink: 0 }} title={scoreTip}>
          <span style={{ ...moduleLabel }}>score</span>
          <span style={{ ...numStyle, fontSize: 15, fontWeight: 800, color: WL.text.primary }}>{total != null ? total : '—'}</span>
        </span>
      </div>

      {/* why discovered */}
      {c.summary && (
        <div style={{ padding: '0 18px 8px', fontSize: 11.5, color: WL.text.secondary, lineHeight: 1.5 }}>{c.summary}</div>
      )}

      {/* professional-review label — rendered prominently on sensitive domains */}
      {requiredReview && (
        <div style={{
          margin: '0 18px 8px', padding: '6px 10px', fontSize: 11, fontWeight: 700,
          color: WL.signal.amber, border: `1px solid ${WL.signal.amber}55`,
          borderRadius: 6, lineHeight: 1.4,
        }}>
          ⚠ {requiredReview}
        </div>
      )}

      {/* LLM review summary — advisory triage verdict (tooltip = full scores) */}
      {review && (
        <div
          title={llmScoresTip(review)}
          style={{
            margin: '0 18px 8px', padding: '7px 10px', background: WL.surface.inset,
            border: `1px solid ${WL.surface.edge}`, borderRadius: 6,
          }}
        >
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 10 }}>
            <span style={moduleLabel}>llm review</span>
            <span style={{ fontSize: 11.5, fontWeight: 800, color: WL.text.primary }}>
              {String(review.recommended_action ?? '—').replace(/_/g, ' ')}
            </span>
            {Number.isFinite(Number(review.confidence)) && (
              <span style={{ fontSize: 10.5, color: WL.text.muted }}>
                conf <span style={numStyle}>{Number(review.confidence).toFixed(2)}</span>
              </span>
            )}
            <span style={{ fontSize: 10.5, color: WL.text.dim }}>
              lanes: {asStringList(review.lanes_used).join(' + ') || '—'}
            </span>
          </div>
          {typeof review.reasoning_summary === 'string' && review.reasoning_summary && (
            <div style={{
              marginTop: 3, fontSize: 11, color: WL.text.secondary, lineHeight: 1.45,
              display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
            }}>{review.reasoning_summary}</div>
          )}
        </div>
      )}

      {/* evidence + risk flags */}
      <div style={{ padding: '0 18px 8px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, fontSize: 11 }}>
        {rDomain && (
          <span
            style={chipStyle(domainAmber ? WL.signal.amber : WL.text.muted)}
            title={`research domain (risk level: ${riskLevel || 'unknown'})`}
          >
            {rDomain.replace(/_/g, ' ')}{riskLevel ? ` · ${riskLevel}` : ''}
          </span>
        )}
        {shownLinks.length > 0 && (
          <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', minWidth: 0 }}>
            <span style={moduleLabel}>evidence</span>
            {shownLinks.map((l, i) => l.url
              ? <a key={i} href={l.url} target="_blank" rel="noreferrer" className="wlc4-link" style={{ fontSize: 11 }}>{l.label} ↗</a>
              : <span key={i} style={{ color: WL.text.secondary }}>{l.label}</span>)}
            {links.length > 3 && (
              <button onClick={() => setEvOpen(v => !v)} style={textButton(WL.text.dim, false)}>
                {evOpen ? 'less ▴' : `+${links.length - 3} more ▾`}
              </button>
            )}
          </span>
        )}
        {flags.map(f => <span key={f} style={chipStyle(WL.signal.amber)} title="risk flag">{f.replace(/_/g, ' ')}</span>)}
      </div>

      {/* provenance line — mono numerals, dim */}
      <div style={{ padding: '0 18px 10px', display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 10.5, color: WL.text.dim }}>
        <span>seen <span style={{ ...numStyle, color: WL.text.muted }}>{c.seen_count ?? 1}×</span></span>
        <span>first <span style={{ ...numStyle, color: WL.text.muted }}>{ago(c.first_seen_at)}</span></span>
        <span>last <span style={{ ...numStyle, color: WL.text.muted }}>{ago(c.last_seen_at)}</span></span>
        {c.source_domain && <span>{c.source_domain}</span>}
        {seeds.length > 0 && <span>seeds: <span style={{ ...numStyle, color: WL.text.muted }}>{seeds.slice(0, 6).join(', ')}</span></span>}
        {extracted.length > 0 && <span>extracted: <span style={{ ...numStyle, color: WL.text.muted }}>{extracted.slice(0, 6).join(', ')}</span></span>}
        {c.duplicate_cluster_id != null && (
          <span style={{ color: WL.signal.amber }}>dup cluster #{String(c.duplicate_cluster_id)}</span>
        )}
        {c.safe_action_level && <span>safe level: {c.safe_action_level}</span>}
        {subjectType && <span>subject: {subjectType.replace(/_/g, ' ')}</span>}
        {Number.isFinite(recurrence) && (
          <span>recurrence <span style={{ ...numStyle, color: WL.text.muted }}>{recurrence}×</span></span>
        )}
        {Number.isFinite(crossSource) && (
          <span>cross-source <span style={{ ...numStyle, color: WL.text.muted }}>{crossSource}</span></span>
        )}
      </div>

      {/* promotion-path preview (from the domain registry) + audit expander */}
      <div style={{ padding: '0 18px 10px', fontSize: 10.5, color: WL.text.dim }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12 }}>
          {promoPaths.length > 0 && (
            <span title="promotion paths this domain allows — every one is operator-gated">
              promotes via: {promoPaths.map(p => p.replace(/_/g, ' ')).join(' · ')}
            </span>
          )}
          <button onClick={toggleAudit} style={textButton(WL.text.dim, false)}>
            {auditOpen ? 'audit trail ▴' : 'audit trail ▾'}
          </button>
        </div>
        {auditOpen && (
          <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 3 }}>
            {auditErr ? (
              <span style={{ color: WL.signal.amber }}>{auditErr}</span>
            ) : auditRows == null ? (
              <span>loading audit trail…</span>
            ) : auditRows.length === 0 ? (
              <span>no audit rows</span>
            ) : (
              auditRows.slice(0, 15).map((a, i) => (
                <div key={String(a.id ?? i)} style={{ display: 'flex', gap: 8, alignItems: 'baseline', minWidth: 0 }}>
                  <span style={{ ...numStyle, color: WL.text.dim, flexShrink: 0, width: 58 }}>{ago(a.created_at)}</span>
                  <span style={{ fontWeight: 700, color: WL.text.muted, flexShrink: 0 }}>
                    {String(a.action ?? '?').replace(/_/g, ' ').toLowerCase()}
                  </span>
                  <span style={{ flexShrink: 0 }}>{a.actor || 'system'}</span>
                  {a.notes && (
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }} title={a.notes}>
                      {a.notes}
                    </span>
                  )}
                </div>
              ))
            )}
            {auditRows != null && auditRows.length > 15 && (
              <span>+{auditRows.length - 15} older rows (see API detail)</span>
            )}
          </div>
        )}
      </div>

      {/* actions */}
      <div style={{ borderTop: `1px solid ${WL.surface.divider}`, padding: '9px 18px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 16 }}>
        {terminal ? (
          <span style={{ fontSize: 11, color: WL.text.dim }}>
            {decidedAs
              ? <>recorded: <b style={{ color: WL.text.secondary }}>{decidedAs}</b></>
              : <>decided{c.operator_decision ? <> — <b style={{ color: WL.text.secondary }}>{String(c.operator_decision).replace(/[_-]/g, ' ')}</b></> : null} · no further actions</>}
          </span>
        ) : (
          <>
            {actionsFor(c).map(a => {
              const isRec = recSlug === a.slug
              const color = a.danger ? WL.signal.red : WL.signal.teal
              const label = busy === a.slug ? `${a.label}…`
                : confirming === a.slug ? `Confirm ${a.label.toLowerCase()}?` : `${a.label} ▸`
              return (
                <button
                  key={a.slug}
                  onClick={() => doAction(a)}
                  disabled={busy != null || llmBusy}
                  title={isRec ? 'recommended by discovery scoring' : undefined}
                  style={{
                    ...textButton(a.danger ? (confirming === a.slug ? WL.signal.red : WL.text.dim) : color, busy != null || llmBusy),
                    ...(isRec ? { textDecoration: 'underline', textUnderlineOffset: 3 } : {}),
                    ...(confirming === a.slug ? { color: WL.signal.red } : {}),
                  }}
                >{label}</button>
              )
            })}
            {!review && (
              <button
                onClick={requestReview}
                disabled={busy != null || llmBusy}
                title="advisory-only LLM triage — never changes candidate status"
                style={textButton(WL.signal.teal, busy != null || llmBusy)}
              >{llmBusy ? 'Requesting LLM review…' : 'Request LLM review ▸'}</button>
            )}
          </>
        )}
        {(actErr || llmErr) && (
          <span style={{ fontSize: 10.5, color: WL.signal.red, marginLeft: 'auto' }}>{actErr || llmErr}</span>
        )}
      </div>

      {/* advisory footer — REQUIRED verbatim on every card */}
      <div style={{ padding: '6px 18px 9px', fontSize: 10, color: WL.text.dim, borderTop: `1px solid ${WL.surface.divider}` }}>
        {ADVISORY_FOOTER}
      </div>
    </div>
  )
}

// ── panel ────────────────────────────────────────────────────────────────────

const TYPE_OPTIONS = ['source', 'research_topic', 'watch_directive', 'ticker']
const STATUS_OPTIONS = ['new', 'pending_validation', 'needs_more_data', 'approved', 'staged', 'rejected', 'blocked', 'merged']
const RISK_LEVEL_OPTIONS = ['financial', 'tax', 'planning', 'legal', 'operational', 'general', 'variable', 'medical']
const SAFE_LEVEL_OPTIONS = ['OBSERVE_ONLY', 'RESEARCH_ONLY', 'OPERATOR_REVIEW_REQUIRED', 'AUTO_STAGE_INSIDE_RAILS', 'BLOCKED']

export default function HermesDiscoveryInbox() {
  const [typeF, setTypeF] = useState('')
  const [statusF, setStatusF] = useState('')
  const [domainInput, setDomainInput] = useState('')
  const [domainF, setDomainF] = useState('')
  const [minScore, setMinScore] = useState('')
  const [rDomainF, setRDomainF] = useState('')      // research_domain (server-side)
  const [riskF, setRiskF] = useState('')            // domain_risk_level (server-side)
  const [reviewedF, setReviewedF] = useState('')    // llm_reviewed '', 'true', 'false' (server-side)
  const [safeLevelF, setSafeLevelF] = useState('')  // safe_action_level (server-side)
  const [profOnly, setProfOnly] = useState(false)   // required_review_label present (client-side)

  const qs = useMemo(() => {
    const p = new URLSearchParams()
    if (typeF) p.set('type', typeF)
    if (statusF) p.set('status', statusF)
    if (domainF) p.set('domain', domainF)
    if (rDomainF) p.set('research_domain', rDomainF)
    if (riskF) p.set('risk_level', riskF)
    if (reviewedF) p.set('llm_reviewed', reviewedF)
    if (safeLevelF) p.set('safe_action_level', safeLevelF)
    p.set('limit', '100')
    return p.toString()
  }, [typeF, statusF, domainF, rDomainF, riskF, reviewedF, safeLevelF])

  const inbox = useApi<InboxData>(`/api/v2/hermes/discovery-inbox?${qs}`, 60_000)
  const scorecard = useApi<Record<string, unknown>>('/api/v2/hermes/discovery-scorecard', 120_000)

  const all = inbox.data?.candidates ?? []
  const min = Number(minScore)
  const candidates = all.filter(c => {
    if (Number.isFinite(min) && minScore !== '') {
      const t = scoreOf(c).total
      if (t == null || t < min) return false
    }
    if (profOnly && !metaStr(c, 'required_review_label')) return false
    return true
  })

  // union fixed options with whatever the live data actually uses
  const typeOptions = useMemo(() => [...new Set([...TYPE_OPTIONS, ...all.map(c => String(c.candidate_type ?? '')).filter(Boolean)])], [all])
  const statusOptions = useMemo(() => [...new Set([...STATUS_OPTIONS, ...all.map(c => String(c.status ?? '')).filter(Boolean)])], [all])
  const rDomainOptions = useMemo(
    () => [...new Set([...(rDomainF ? [rDomainF] : []), ...all.map(c => metaStr(c, 'research_domain')).filter(Boolean)])].sort(),
    [all, rDomainF])
  const riskOptions = useMemo(
    () => [...new Set([...RISK_LEVEL_OPTIONS, ...all.map(c => metaStr(c, 'domain_risk_level').toLowerCase()).filter(Boolean)])],
    [all])
  const safeLevelOptions = useMemo(
    () => [...new Set([...SAFE_LEVEL_OPTIONS, ...all.map(c => String(c.safe_action_level ?? '').toUpperCase()).filter(Boolean)])],
    [all])

  const tiles = scorecardTiles(scorecard.data)
  const maturityLine = typeof scorecard.data?.maturity_line === 'string' ? String(scorecard.data.maturity_line) : MATURITY_LINE
  const notDeployed = !!inbox.error && /404/.test(inbox.error) && !inbox.data
  const refetchAll = () => { inbox.refetch(); scorecard.refetch() }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* header row — title + filters */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ ...moduleLabel, fontSize: 11 }}>Discovery Inbox</span>
        <select value={typeF} onChange={e => setTypeF(e.target.value)} style={filterCtl} title="candidate type">
          <option value="">all types</option>
          {typeOptions.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
        </select>
        <select value={statusF} onChange={e => setStatusF(e.target.value)} style={filterCtl} title="status">
          <option value="">all statuses</option>
          {statusOptions.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
        </select>
        <input
          value={domainInput}
          onChange={e => setDomainInput(e.target.value)}
          onBlur={() => setDomainF(domainInput.trim())}
          onKeyDown={e => { if (e.key === 'Enter') setDomainF(domainInput.trim()) }}
          placeholder="source domain"
          style={{ ...filterCtl, width: 130 }}
        />
        <input
          value={minScore}
          onChange={e => setMinScore(e.target.value)}
          placeholder="min score"
          inputMode="numeric"
          style={{ ...filterCtl, width: 74, ...numStyle }}
          title="minimum composite score (client-side)"
        />
        <select value={rDomainF} onChange={e => setRDomainF(e.target.value)} style={filterCtl} title="research domain">
          <option value="">all domains</option>
          {rDomainOptions.map(d => <option key={d} value={d}>{d.replace(/_/g, ' ')}</option>)}
        </select>
        <select value={riskF} onChange={e => setRiskF(e.target.value)} style={filterCtl} title="domain risk level">
          <option value="">all risk levels</option>
          {riskOptions.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
        <select value={reviewedF} onChange={e => setReviewedF(e.target.value)} style={filterCtl} title="LLM review status">
          <option value="">llm: any</option>
          <option value="true">llm reviewed</option>
          <option value="false">not reviewed</option>
        </select>
        <select value={safeLevelF} onChange={e => setSafeLevelF(e.target.value)} style={filterCtl} title="safe action level">
          <option value="">all safe levels</option>
          {safeLevelOptions.map(l => <option key={l} value={l}>{l.replace(/_/g, ' ').toLowerCase()}</option>)}
        </select>
        <button
          onClick={() => setProfOnly(v => !v)}
          title="only candidates requiring professional review (tax / planning / legal / medical)"
          style={{
            ...filterCtl, cursor: 'pointer', fontWeight: 700,
            color: profOnly ? WL.signal.amber : WL.text.secondary,
            borderColor: profOnly ? `${WL.signal.amber}88` : WL.surface.edge,
          }}
        >{profOnly ? '⚠ prof review ✓' : '⚠ prof review'}</button>
        <span style={{ marginLeft: 'auto', fontSize: 10.5, color: WL.text.dim }}>
          <span style={numStyle}>{candidates.length}</span> of <span style={numStyle}>{all.length}</span> candidates
          {inbox.stale && <span style={{ color: WL.signal.amber, marginLeft: 8 }}>reconnecting…</span>}
        </span>
      </div>

      {/* scorecard strip */}
      {(tiles.length > 0 || scorecard.data != null) && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'stretch' }}>
          {tiles.map(t => (
            <div key={t.label} style={{
              background: WL.surface.card, border: `1px solid ${WL.surface.edge}`, borderRadius: 8,
              padding: '7px 12px', minWidth: 84,
            }}>
              <div style={{ ...numStyle, fontSize: 15, fontWeight: 800, color: WL.text.primary }}>{t.value}</div>
              <div style={{ ...moduleLabel, marginTop: 1 }}>{t.label}</div>
            </div>
          ))}
          <div style={{
            display: 'flex', alignItems: 'center', padding: '7px 12px',
            background: WL.surface.card, border: `1px solid ${WL.surface.edge}`, borderRadius: 8,
            fontSize: 10.5, color: WL.text.muted,
          }}>{maturityLine}</div>
        </div>
      )}
      {tiles.length === 0 && scorecard.data == null && (
        <div style={{ fontSize: 10.5, color: WL.text.dim }}>{maturityLine}</div>
      )}

      {/* body */}
      {notDeployed ? (
        <div style={{
          background: WL.surface.card, border: `1px solid ${WL.surface.edge}`, borderRadius: WL.card.radius,
          padding: '22px 20px', fontSize: 12, color: WL.text.secondary,
        }}>
          <div style={{ fontWeight: 700, color: WL.text.primary, marginBottom: 4 }}>Discovery API not deployed yet</div>
          The discovery-inbox endpoints (Stage 2) have not landed on this server. This panel will populate automatically once
          <code style={{ margin: '0 4px' }}>/api/v2/hermes/discovery-inbox</code> is live.
          <div style={{ marginTop: 10 }}>
            <button onClick={refetchAll} style={textButton(WL.signal.teal, false)}>Retry ▸</button>
          </div>
        </div>
      ) : inbox.loading && !inbox.data ? (
        <div style={{ fontSize: 11.5, color: WL.text.dim, padding: '18px 2px' }}>Loading discovery inbox…</div>
      ) : inbox.error && !inbox.data ? (
        <div style={{
          background: WL.surface.card, border: `1px solid ${WL.surface.edge}`, borderRadius: WL.card.radius,
          padding: '18px 20px', fontSize: 11.5, color: WL.text.secondary,
        }}>
          Discovery inbox unavailable — {inbox.error}.
          <button onClick={refetchAll} style={{ ...textButton(WL.signal.teal, false), marginLeft: 10 }}>Retry ▸</button>
        </div>
      ) : candidates.length === 0 ? (
        <div style={{ fontSize: 11.5, color: WL.text.dim, padding: '18px 2px' }}>
          No discovery candidates match the current filters.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {candidates.map(c => <DiscoveryCard key={String(c.id)} c={c} onDone={refetchAll} />)}
        </div>
      )}
    </div>
  )
}
