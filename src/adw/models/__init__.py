"""SQLAlchemy models.

Importing this package registers every model on ``Base.metadata``, which is what
``migrations/env.py`` targets. A model that is not imported here is invisible to
autogenerate and to the schema tests.
"""

from adw.models.base import Base
from adw.models.definition import (
    AgentDefinition,
    AgentDefinitionVersion,
    Skill,
    SkillVersion,
)
from adw.models.execution import Execution
from adw.models.task import MAX_REWORK_ATTEMPTS, Task, TaskSkillPin
from adw.models.tenant import Tenant

__all__ = [
    "MAX_REWORK_ATTEMPTS",
    "AgentDefinition",
    "AgentDefinitionVersion",
    "Base",
    "Execution",
    "Skill",
    "SkillVersion",
    "Task",
    "TaskSkillPin",
    "Tenant",
]

TENANT_SCOPED_TABLES = frozenset({"tenant", "execution", "task", "task_skill_pin"})
"""Tables that must carry row-level security.

``tenant`` is included although it has no ``tenant_id``: its policy compares
``id`` instead, so a tenant reads its own row and cannot enumerate the others.
"""

PLATFORM_SCOPED_TABLES = frozenset(
    {"agent_definition", "agent_definition_version", "skill", "skill_version"}
)
"""Definition tables. Platform-curated, no tenant data, outside tenant scope per D30."""
