import type { AgentLifecycle, AgentRuntimeDefinition } from './agentRuntimeMonitoring'
import type { AgentOperationsEntry } from './agentRuntimeOperations'

export interface CatalogRowLite {
  agentId: string
  displayName?: string
  role?: string
  lifecycle?: AgentLifecycle
  enabled?: boolean
  retrievalRequired?: boolean
  deadlineSeconds?: number
}

/** Prefer live operations + maturity overview; static catalog is narrative fallback only. */
export function mergeAgentDefinition(
  staticDef: AgentRuntimeDefinition,
  ops?: AgentOperationsEntry | null,
  catalogRow?: CatalogRowLite | null,
): AgentRuntimeDefinition {
  const merged: AgentRuntimeDefinition = { ...staticDef }

  if (catalogRow) {
    if (catalogRow.displayName) merged.displayName = catalogRow.displayName
    if (catalogRow.role) merged.role = catalogRow.role
    if (catalogRow.lifecycle) merged.lifecycle = catalogRow.lifecycle
    if (catalogRow.enabled != null) merged.enabled = catalogRow.enabled
    if (catalogRow.retrievalRequired != null) merged.retrievalRequired = catalogRow.retrievalRequired
    if (catalogRow.deadlineSeconds != null) {
      merged.budget = { ...merged.budget, deadlineSeconds: catalogRow.deadlineSeconds }
    }
  }

  if (!ops) return merged

  if (ops.display_name) merged.displayName = ops.display_name
  if (ops.role) merged.role = ops.role
  if (ops.lifecycle) merged.lifecycle = ops.lifecycle as AgentLifecycle
  merged.enabled = ops.enabled
  if (ops.owner) merged.owner = ops.owner
  if (ops.retrieval_required != null) merged.retrievalRequired = ops.retrieval_required
  if (ops.allowed_tools?.length) merged.allowedTools = [...ops.allowed_tools]
  if (ops.denied_tools?.length) merged.deniedTools = [...ops.denied_tools]
  if (ops.reviewer_agent_id) merged.reviewer = ops.reviewer_agent_id
  if (ops.scorer_agent_id) merged.scorer = ops.scorer_agent_id
  if (ops.trigger_description) merged.trigger = ops.trigger_description
  if (ops.allowed_outputs?.length) merged.artifact = ops.allowed_outputs.join(', ')
  if (ops.budget) {
    merged.budget = {
      maxModelCalls: ops.budget.max_model_calls,
      maxToolCalls: ops.budget.max_tool_calls,
      maxCostUsd: ops.budget.max_cost_usd,
      deadlineSeconds: ops.budget.deadline_seconds,
    }
  }
  return merged
}
