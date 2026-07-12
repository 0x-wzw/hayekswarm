"""Task Lifecycle — state machine for inter-agent tasks."""

from __future__ import annotations
from .manifest import TaskState


TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.SUBMITTED:    {TaskState.NEGOTIATING, TaskState.REJECTED, TaskState.CANCELLED},
    TaskState.NEGOTIATING:  {TaskState.ACCEPTED, TaskState.REJECTED, TaskState.CANCELLED},
    TaskState.ACCEPTED:     {TaskState.RUNNING, TaskState.CANCELLED},
    TaskState.RUNNING:      {TaskState.STREAMING, TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.STREAMING:    {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.COMPLETED:    set(),  # Terminal
    TaskState.FAILED:       set(),  # Terminal
    TaskState.CANCELLED:    set(),  # Terminal
    TaskState.REJECTED:     set(),  # Terminal
}


def can_transition(current: TaskState, target: TaskState) -> bool:
    """Check if a task can transition from current state to target state."""
    return target in TRANSITIONS.get(current, set())


def transition(current: TaskState, target: TaskState) -> TaskState:
    """Attempt a state transition. Raises ValueError if invalid."""
    if not can_transition(current, target):
        raise ValueError(f"Invalid transition: {current.value} -> {target.value}")
    return target
