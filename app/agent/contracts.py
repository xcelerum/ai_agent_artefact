"""Small contracts for untrusted planning and trusted per-task execution."""

from dataclasses import dataclass, field
from enum import StrEnum
import operator
from typing import Annotated, Protocol, TypedDict


class Intent(StrEnum):
    CATALOG = 'catalog_lookup'
    POLICY = 'policy_question'
    ORDER = 'order_status'


class StructuredIntentModel(Protocol):
    def extract(self, *, history: list, message: str, schema: dict) -> object: ...


@dataclass(frozen=True)
class ValidatedTask:
    task_id: str
    position: int
    intent: Intent
    validated_parameters: dict


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    position: int
    domain: str
    status: str
    facts: dict
    source_references: tuple[str, ...]
    error_category: str | None = None


@dataclass(frozen=True)
class PolicyEvidence:
    """Trusted configured-service evidence; test sources are explicitly synthetic."""
    text: str
    source_references: tuple[str, ...]


class PolicyLookup(Protocol):
    def lookup(self, *, topic: str) -> PolicyEvidence | None: ...


@dataclass(frozen=True)
class AgentReply:
    status: str
    text: str
    products: list[dict[str, object]]
    task_outcomes: list[TaskResult] = field(default_factory=list)


class WorkerState(TypedDict):
    # No message, session, raw plan, other tasks or domain dependencies.
    task: ValidatedTask


class GraphState(TypedDict, total=False):
    session_id: str                 # Caller input; identifier, never authentication.
    message: str                    # Caller input; untrusted text.
    raw_plan: object                # Interpret node; untrusted adapter output.
    validated_plan: tuple[ValidatedTask, ...]  # Validate node; fresh application values.
    task_results: Annotated[list[TaskResult], operator.add]  # Workers; append-only per turn.
    ordered_results: list[TaskResult]  # Aggregate node; cardinality-checked and sorted.
    routing_outcome: str            # Prepare/interpret/validate/aggregate; application-only.
    final_reply: AgentReply         # Render node only; public return value.
