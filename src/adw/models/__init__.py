"""SQLAlchemy models.

Importing this package registers every model on ``Base.metadata``, which is what
``migrations/env.py`` targets. A model that is not imported here is invisible to
autogenerate and to the schema tests.
"""

from adw.models.action import Action, Evidence
from adw.models.anchor import ANCHOR_HEAD_ID, AnchorHead, AnchorRecord
from adw.models.artifact import (
    Artifact,
    ArtifactDefinition,
    ArtifactDefinitionVersion,
    ArtifactVersion,
)
from adw.models.audit import (
    EVENT_TIME_ANOMALY,
    PLATFORM_TENANT_ID,
    AuditChainHead,
    AuditChainRecord,
)
from adw.models.base import Base
from adw.models.cost import ActionCost, ExecutionBudget
from adw.models.definition import (
    AgentDefinition,
    AgentDefinitionVersion,
    DefinitionDeprecation,
    DefinitionKind,
    Skill,
    SkillVersion,
)
from adw.models.execution import Execution
from adw.models.gate import (
    ApprovalItem,
    GateDecision,
    GateDefinition,
    GateDefinitionVersion,
    ReworkAttempt,
)
from adw.models.queue import QUEUE_COLUMNS, DispatchJob, JobExecution
from adw.models.task import MAX_ATTEMPTS, Task, TaskSkillPin
from adw.models.tenant import Tenant

__all__ = [
    "ANCHOR_HEAD_ID",
    "EVENT_TIME_ANOMALY",
    "MAX_ATTEMPTS",
    "PLATFORM_TENANT_ID",
    "QUEUE_COLUMNS",
    "Action",
    "ActionCost",
    "AgentDefinition",
    "AgentDefinitionVersion",
    "AnchorHead",
    "AnchorRecord",
    "ApprovalItem",
    "Artifact",
    "ArtifactDefinition",
    "ArtifactDefinitionVersion",
    "ArtifactVersion",
    "AuditChainHead",
    "AuditChainRecord",
    "Base",
    "DefinitionDeprecation",
    "DefinitionKind",
    "DispatchJob",
    "Evidence",
    "Execution",
    "ExecutionBudget",
    "GateDecision",
    "GateDefinition",
    "GateDefinitionVersion",
    "JobExecution",
    "ReworkAttempt",
    "Skill",
    "SkillVersion",
    "Task",
    "TaskSkillPin",
    "Tenant",
]

TENANT_SCOPED_TABLES = frozenset(
    {
        "tenant",
        "execution",
        "task",
        "task_skill_pin",
        "chain_record",
        "chain_head",
        "action",
        "evidence",
        "artifact",
        "artifact_version",
        "gate_decision",
        "rework_attempt",
        "approval_item",
        "action_cost",
        "execution_budget",
    }
)
"""Tables that must carry row-level security.

``tenant`` is included although it has no ``tenant_id``: its policy compares
``id`` instead, so a tenant reads its own row and cannot enumerate the others.
"""

PLATFORM_SCOPED_TABLES = frozenset(
    {
        "agent_definition",
        "agent_definition_version",
        "skill",
        "skill_version",
        "artifact_definition",
        "artifact_definition_version",
        "gate_definition",
        "gate_definition_version",
        "definition_deprecation",
    }
)
"""Definition tables. Platform-curated, no tenant data, outside tenant scope per D30."""
