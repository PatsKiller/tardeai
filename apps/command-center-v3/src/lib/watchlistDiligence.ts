import type { WatchlistDiligence } from '../components/EntryDeskDiligenceStrip'

export function hasAgentMaturity(d?: WatchlistDiligence | null): boolean {
  if (!d) return false
  return !!(d.maria || d.steph || d.risk || d.synthesisStatus || d.synthesis)
}

export function isActionable(d?: WatchlistDiligence | null): boolean {
  return d?.actionable === true
}

export function diligenceFromWatchlistItem(it: Record<string, unknown>): WatchlistDiligence {
  const unresolved = Array.isArray(it.unresolved) ? (it.unresolved as string[]) : []
  const conflicts = Array.isArray(it.conflicts) ? (it.conflicts as string[]) : []
  return {
    analysisStage: (it.analysis_stage as string) ?? null,
    maria: (it.maria_status as string) ?? null,
    steph: (it.steph_status as string) ?? null,
    risk: (it.risk_status as string) ?? null,
    tax: (it.tax_status as string) ?? null,
    synthesis: (it.synthesis_recommendation as string) ?? null,
    researchCard: (it.latest_recommendation as string) ?? (it.research_card_rec as string) ?? null,
    synthesisStatus: (it.final_synthesis_status as string) ?? null,
    grokRec: (it.grok_recommendation as string) ?? null,
    chatgptRec: (it.chatgpt_recommendation as string) ?? null,
    decisionSafety: (it.decision_safety as string) ?? null,
    modelsAgree: it.models_agree == null ? null : !!it.models_agree,
    actionable: it.decision_actionable != null ? !!it.decision_actionable
      : it.synthesis_actionable != null ? !!it.synthesis_actionable : null,
    entryPlannedAt: (it.entry_planned_at as string) ?? null,
    catalyst: (it.catalyst_headline as string) ?? (it.catalyst_type as string) ?? null,
    entryModel: (it.entry_model as string) ?? null,
    narrativeSnip: (it.synthesis_narrative_snip as string) ?? (typeof it.synthesis_narrative === 'string' ? String(it.synthesis_narrative).slice(0, 280) : null),
    conflictsSnip: (it.synthesis_conflicts_snip as string) ?? (conflicts.length ? conflicts.slice(0, 2).join('; ').slice(0, 200) : null),
    unresolved: unresolved.length ? unresolved.slice(0, 3) : null,
    dataIDoubt: (it.synthesis_data_i_doubt as string) ?? null,
  }
}

export function cioBlocksEntry(d?: WatchlistDiligence | null): boolean {
  const cio = String(d?.synthesis ?? '').toUpperCase()
  return ['AVOID', 'IGNORE', 'SELL', 'REBALANCE_TRIM'].includes(cio)
}