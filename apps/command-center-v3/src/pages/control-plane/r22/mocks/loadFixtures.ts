/** FIXTURE/MOCK copies of ControlPlane@v1.0.0 envelopes — not production data.
 *
 * Allowed for Agent Office DETAIL and Workflow Trace GRAPH/lineage until R21.1.
 * Forbidden as list-view live data. List views consume CONTROL_PLANE_API_V1_BASELINE
 * GET /api/v3/control-plane/agents and /workflows.
 * Field semantics must match `fixtures/control_plane/v1.0.0/{agents,workflows}.json`.
 * Banner must say FIXTURE/MOCK — not production data. */

import type {
  AgentRuntimeStatus,
  ControlPlaneEnvelope,
  WorkflowTrace,
} from '../../../control-plane/contractV1'
import agentsJson from './agents.json'
import workflowsJson from './workflows.json'

export type AgentsPagePayload = {
  on_current_runtime: boolean
  agents: AgentRuntimeStatus[]
}

export type WorkflowsPagePayload = {
  traces: WorkflowTrace[]
}

export const AGENTS_ENVELOPE = agentsJson as ControlPlaneEnvelope<AgentsPagePayload>
export const WORKFLOWS_ENVELOPE = workflowsJson as ControlPlaneEnvelope<WorkflowsPagePayload>

export const FIXTURE_SOURCE = 'fixtures/control_plane/v1.0.0'
export const FIXTURE_MOCK_LABEL = 'FIXTURE/MOCK — not production data'
