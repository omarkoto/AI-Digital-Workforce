"""Task — the unit of assignment and the unit of permission.

Every Task pins the exact definition versions that governed it (D9/I4). Pinning
is what lets the record answer "what were this agent's instructions at the
time?" long after the definition has moved on.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from adw.domain.ids import new_id
from adw.domain.states import TaskState
from adw.models.base import Base, CreatedAtMixin, TenantScopedMixin, UpdatedAtMixin

MAX_ATTEMPTS = 4
"""D11 permits three rework loops, so a task can reach a fourth attempt.

The budget itself is counted from the append-only rework rows, which are the
single authority. This column mirrors them so the current attempt is readable
without a join.
"""


class Task(Base, TenantScopedMixin, CreatedAtMixin, UpdatedAtMixin):
    """One assignment within an execution."""

    __tablename__ = "task"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence"),
        CheckConstraint(
            f"attempt_no BETWEEN 1 AND {MAX_ATTEMPTS}",
            name="attempt_no_within_rework_limit",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    execution_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("execution.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    """Position in the plan. Ordinal and tenant-local, so D26 does not apply."""

    agent_definition_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_definition_version.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """Pinned at creation. ``RESTRICT`` because a pinned version must survive as
    long as anything references it."""

    state: Mapped[TaskState] = mapped_column(
        SqlEnum(
            TaskState,
            name="task_state",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
            length=32,
        ),
        default=TaskState.PLANNED,
        nullable=False,
        index=True,
    )

    attempt_no: Mapped[int] = mapped_column(default=1, nullable=False)
    """Which attempt this task is on. Maintained by the rework controller."""

    skill_pins: Mapped[list[TaskSkillPin]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )


class TaskSkillPin(Base, TenantScopedMixin, CreatedAtMixin):
    """One pinned skill version for one task.

    A separate table rather than an array column so the pin is a real foreign
    key: the database refuses to drop a skill version that an execution relied
    on.
    """

    __tablename__ = "task_skill_pin"
    __table_args__ = (UniqueConstraint("task_id", "skill_version_id"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=new_id)
    task_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("skill_version.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    task: Mapped[Task] = relationship(back_populates="skill_pins")
