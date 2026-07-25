export type PacketValidationSelection = {
  source: string | null
  family: string | null
  ticket: Record<string, any>
  validation: Record<string, any>
  deterministic: string
  quality: string
}

const FAMILY_ORDER = ['swing', 'long_term', 'bearish', 'options', 'no_trade'] as const
const VALIDATION_SEVERITY: Record<string, number> = { FAIL: 3, REVIEW_REQUIRED: 2, PASS: 1, NOT_RUN: 0 }
const QUALITY_SEVERITY: Record<string, number> = { QUARANTINED: 3, RESEARCH_ONLY: 2, ADMITTED: 1, UNASSESSED: 0 }

function normalize(value: any, fallback: string): string {
  return String(value || fallback).trim().toUpperCase()
}

function candidates(packet: any): PacketValidationSelection[] {
  const out: PacketValidationSelection[] = []
  const current = packet?.current_actionable_plan
  if (current?.ticket_validation && typeof current.ticket_validation === 'object') {
    const validation = current.ticket_validation
    out.push({
      source: 'current_actionable_plan',
      family: current.family || current.structure_family || null,
      ticket: current,
      validation,
      deterministic: normalize(validation.state, 'NOT_RUN'),
      quality: normalize(validation.quality_admission?.state, 'UNASSESSED'),
    })
  }

  const families = packet?.plan_families || {}
  for (const familyKey of FAMILY_ORDER) {
    const family = families[familyKey] || {}
    if (family.ticket_validation && typeof family.ticket_validation === 'object') {
      const validation = family.ticket_validation
      out.push({
        source: `plan_families.${familyKey}`,
        family: familyKey.toUpperCase(),
        ticket: family,
        validation,
        deterministic: normalize(validation.state, 'NOT_RUN'),
        quality: normalize(validation.quality_admission?.state, 'UNASSESSED'),
      })
    }
    for (const [index, structure] of (family.structures || []).entries()) {
      if (!structure?.ticket_validation || typeof structure.ticket_validation !== 'object') continue
      const validation = structure.ticket_validation
      out.push({
        source: `plan_families.${familyKey}.structures[${index}]`,
        family: familyKey.toUpperCase(),
        ticket: structure,
        validation,
        deterministic: normalize(validation.state, 'NOT_RUN'),
        quality: normalize(validation.quality_admission?.state, 'UNASSESSED'),
      })
    }
  }
  return out
}

export function selectPacketValidation(packet: any): PacketValidationSelection {
  const found = candidates(packet)
  if (!found.length) {
    return {
      source: null,
      family: null,
      ticket: {},
      validation: {},
      deterministic: 'NOT_RUN',
      quality: 'UNASSESSED',
    }
  }
  const current = found.find(item => item.source === 'current_actionable_plan')
  if (current) return current
  return [...found].sort((left, right) => {
    const validationDelta = (VALIDATION_SEVERITY[right.deterministic] || 0) - (VALIDATION_SEVERITY[left.deterministic] || 0)
    if (validationDelta) return validationDelta
    return (QUALITY_SEVERITY[right.quality] || 0) - (QUALITY_SEVERITY[left.quality] || 0)
  })[0]
}
