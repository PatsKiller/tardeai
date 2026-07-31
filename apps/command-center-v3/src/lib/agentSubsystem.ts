/** Canonical agent product-area pills (matches scripts/agent_runtime/agents/base.py AgentSubsystem). */
export type AgentSubsystem = 'FLEET' | 'HERMES' | 'OPENCLAW' | 'SYSTEM'

export const SUBSYSTEM_LABELS: Record<AgentSubsystem, string> = {
  FLEET: 'Fleet',
  HERMES: 'Hermes',
  OPENCLAW: 'OpenClaw',
  SYSTEM: 'System',
}

export function normalizeSubsystem(raw: string | null | undefined): AgentSubsystem {
  const up = String(raw || 'FLEET').toUpperCase()
  if (up === 'HERMES' || up === 'OPENCLAW' || up === 'SYSTEM' || up === 'FLEET') return up
  // Legacy maturity strings
  if (up.includes('HERMES')) return 'HERMES'
  if (up.includes('OPENCLAW') || up === 'OPENCLAW_RUNTIME_INVENTORY') return 'OPENCLAW'
  if (up.includes('SYSTEM') || up === 'PROPOSAL_REVIEW' || up === 'AGENT_RUNTIME_MVL' || up === 'AGENT_RUNTIME') {
    return up.includes('SYSTEM') ? 'SYSTEM' : 'FLEET'
  }
  return 'FLEET'
}

export function subsystemChipTone(subsystem: AgentSubsystem): 'blue' | 'green' | 'amber' | 'slate' {
  switch (subsystem) {
    case 'HERMES': return 'green'
    case 'OPENCLAW': return 'amber'
    case 'SYSTEM': return 'slate'
    default: return 'blue'
  }
}

/** FLEET agent ids that share a name with OpenClaw personas / TradeAI advisory SOULs. */
export const FLEET_NAME_COLLISION_IDS = new Set(['aegis', 'alex', 'steph', 'maria'])

/** FLEET critics that may have a matching OpenClaw conversational persona (same id, different runtime). */
export const FLEET_IDS_WITH_OPENCLAW_PERSONA = new Set([
  'aegis', 'alex', 'steph', 'maria', 'iris', 'sentinel', 'darwin', 'concierge', 'risk_agent',
])

/** OpenClaw-only personas (gateway chat, not a FLEET dispatch target). */
export const OPENCLAW_ONLY_PERSONA_IDS = new Set(['main'])

export function fleetHasOpenClawPersona(agentId: string, registeredIds?: Set<string> | null): boolean {
  if (registeredIds) return registeredIds.has(agentId)
  return FLEET_IDS_WITH_OPENCLAW_PERSONA.has(agentId)
}

export function openClawPersonaLabel(agentId: string): string {
  return agentId === 'risk_agent' ? 'Guardian Risk' : agentId.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

/** Subsystem OPENCLAW = concierge FLEET bridge only; other agents use the persona badge instead. */
export function subsystemExplainer(subsystem: AgentSubsystem, agentId: string): string {
  if (subsystem === 'OPENCLAW') {
    return 'FLEET subsystem: governed OpenClaw operator bridge (concierge). Distinct from conversational OpenClaw personas.'
  }
  if (FLEET_IDS_WITH_OPENCLAW_PERSONA.has(agentId)) {
    return 'FLEET critic subsystem. May also have a separate OpenClaw chat persona — see OpenClaw persona column.'
  }
  return SUBSYSTEM_LABELS[subsystem]
}

export function fleetNameCollisionNote(agentId: string): string | null {
  if (!FLEET_NAME_COLLISION_IDS.has(agentId)) return null
  const name = agentId.replace('_', ' ')
  return `Distinct from the OpenClaw conversational persona and TradeAI advisory SOUL named "${name}" — no shared runtime, config, or memory.`
}

export function openClawCollisionNote(agentId: string): string | null {
  if (!FLEET_NAME_COLLISION_IDS.has(agentId)) return null
  const label = agentId === 'risk_agent' ? 'Guardian Risk' : agentId.charAt(0).toUpperCase() + agentId.slice(1)
  return `This OpenClaw persona is separate from the governed FLEET critic "${label} (${agentId})" on Agents → Runtime. Different role, no shared dispatch or memory.`
}
