"""Trade AI reflective-agent Minimum Viable Loop.

This package is shadow/lab only. It has no broker, order, approval, 2FA,
production-secret, or production-configuration authority.
"""

from .contracts import (
    AgentDefinition,
    Artifact,
    DeploymentState,
    Environment,
    Review,
    ReviewVerdict,
    RunStatus,
    ToolDecision,
    ToolPolicy,
    canonical_hash,
)
from .critics import CriticLane, CriticPanel, CriticReconciliation, CriticResult, reconcile_critics
from .knowledge import (
    EmbeddingProvenance,
    KnowledgeIndex,
    KnowledgeRecord,
    RetrievalBundle,
    RetrievalHit,
    WatchRetrievalContext,
)
from .runtime import MvlRuntime
from .sentinel import SentinelFinding, SentinelReport, finding_codes, inspect_population, inspect_ticket
from .sentinel_pipeline import (
    ReviewDecision,
    ScoreDecision,
    SentinelPipelineResult,
    SentinelShadowPipeline,
)
from .watch_artifact import WatchAdapterResult, WatchArtifact, WatchProvenance, adapt_watch_item

__all__ = [
    "AgentDefinition",
    "Artifact",
    "CriticLane",
    "CriticPanel",
    "CriticReconciliation",
    "CriticResult",
    "DeploymentState",
    "EmbeddingProvenance",
    "Environment",
    "KnowledgeIndex",
    "KnowledgeRecord",
    "MvlRuntime",
    "RetrievalBundle",
    "RetrievalHit",
    "Review",
    "ReviewDecision",
    "ReviewVerdict",
    "RunStatus",
    "ScoreDecision",
    "SentinelFinding",
    "SentinelPipelineResult",
    "SentinelReport",
    "SentinelShadowPipeline",
    "ToolDecision",
    "ToolPolicy",
    "WatchAdapterResult",
    "WatchArtifact",
    "WatchProvenance",
    "WatchRetrievalContext",
    "adapt_watch_item",
    "canonical_hash",
    "finding_codes",
    "inspect_population",
    "inspect_ticket",
    "reconcile_critics",
]
