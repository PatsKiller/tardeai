/** R24 display contracts. Live rows are CONTROL_PLANE_API_V1_BASELINE data.items.
 *  ControlPlane@v1.0.0 field names remain vocabulary for labeled FIXTURE tests.
 *  Pages render these records. They must not infer, score, or promote. */

import type {
  AuditCapabilityClaim,
  LearningEvidenceStatus,
  MaturityDimension,
} from '../../../control-plane/contractV1'

export const LEARNING_KINDS = [
  'decision',
  'checkpoint',
  'outcome',
  'lesson',
  'hypothesis',
  'experiment',
  'specialist_performance',
  'model_performance',
  'routing_candidate',
] as const

export type LearningKind = (typeof LEARNING_KINDS)[number]

/** Operator labels for the nine required learning kinds. Keys are payload.kind. */
export const LEARNING_KIND_LABELS: Record<LearningKind, string> = {
  decision: 'Decisions',
  checkpoint: 'Checkpoints',
  outcome: 'Outcomes',
  lesson: 'Lessons',
  hypothesis: 'Hypotheses',
  experiment: 'Experiments',
  specialist_performance: 'Specialist performance',
  model_performance: 'Model performance',
  routing_candidate: 'Routing candidates',
}

export interface LearningPayload {
  auto_promotions: number
  items: LearningEvidenceStatus[]
}

export interface MaturityPayload {
  overall_is_not_a_certification: boolean
  limiting_dimension: string
  dimensions: MaturityDimension[]
}

export interface AuditPayload {
  readiness: string
  claims: AuditCapabilityClaim[]
  known_gaps: unknown[]
}

/** Independent maturity fields rendered from each data.items row (live)
 *  or FIXTURE payload.dimensions. Never computed client-side. */
export const MATURITY_RENDER_FIELDS = [
  'dimension',
  'score',
  'evidence_class',
  'proof_refs',
  'limiting_factor',
  'next_proof',
] as const

/**
 * Audit page sections required by R24. Filled only from data.items /
 * extras.known_gaps / item.reproduction_command. No marketing copy.
 * Labeled FIXTURE may still carry payload.claims + payload.known_gaps.
 */
export const AUDIT_SECTIONS = [
  { id: 'architecture', label: 'Architecture' },
  { id: 'authority', label: 'Authority' },
  { id: 'runtime', label: 'Runtime' },
  { id: 'stores', label: 'Stores' },
  { id: 'agent_roster', label: 'Agent roster' },
  { id: 'research_routes', label: 'Research routes' },
  { id: 'model_routes', label: 'Model routes' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'known_gaps', label: 'Known gaps' },
  { id: 'reproduction_commands', label: 'Reproduction commands' },
] as const

export type AuditSectionId = (typeof AUDIT_SECTIONS)[number]['id']

const SECTION_ID_SET = new Set<string>(AUDIT_SECTIONS.map(s => s.id))

/** Optional claim tags the payload may use to place a row in a section.
 *  Does not inspect claim text. Does not infer architecture from wording. */
export function claimSectionIds(claim: AuditCapabilityClaim | Record<string, unknown>): string[] {
  const extra = claim as AuditCapabilityClaim & Record<string, unknown>
  const out: string[] = []
  for (const key of ['section', 'area', 'topic', 'facet'] as const) {
    const value = extra[key]
    if (typeof value === 'string' && value.trim()) out.push(normalizeSectionId(value))
  }
  if (Array.isArray(extra.sections)) {
    for (const value of extra.sections) {
      if (typeof value === 'string' && value.trim()) out.push(normalizeSectionId(value))
    }
  }
  return out.filter(id => SECTION_ID_SET.has(id))
}

function normalizeSectionId(raw: string): string {
  return raw.trim().toLowerCase().replace(/\s+/g, '_')
}

export function isLearningKind(value: string): value is LearningKind {
  return (LEARNING_KINDS as readonly string[]).includes(value)
}
