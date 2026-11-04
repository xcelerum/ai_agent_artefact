"""Small contracts for untrusted planning and trusted per-task execution."""

from dataclasses import dataclass, field
from enum import StrEnum
import operator
import json
import logging
import os
from typing import Annotated, Protocol, TypedDict

from app.domain.policy_rules import PolicyAssessment

POLICY_TOPICS = ('hours', 'contacts', 'payments', 'withdrawal', 'returns', 'defect',
                 'preference', 'shipping', 'promotions', 'warranty', 'privacy')


def diagnostic(stage: str, exc: BaseException | None = None, **metadata) -> None:
    """Opt-in diagnostics: never exception messages, tracebacks or customer values."""
    if os.environ.get('ARTEFACT_DEBUG') != '1':
        return
    try:
        allowed = {'http_status', 'semantic_mode', 'task_count', 'selected_count', 'candidate_count',
                   'has_name', 'has_category', 'has_max_price', 'spec_count', 'response_complete',
                   'refusal_present', 'input_valid'}
        safe = {key: value for key, value in metadata.items()
                if key in allowed and type(value) in (int, bool)}
        status = getattr(exc, 'status_code', None)
        if type(status) is int:
            safe['http_status'] = status
        # The SDK retains provider detail in body. Emit only fixed, recognized labels.
        # Never serialize the body, message, failed generation or unknown values.
        body = getattr(exc, 'body', None)
        if stage == 'groq.request' and type(body) is dict:
            error = body.get('error', body)
            if type(error) is dict:
                labels = {'type': {'invalid_request_error', 'rate_limit_error', 'server_error'},
                          'code': {'json_validate_failed', 'tool_use_failed',
                                   'context_length_exceeded', 'rate_limit_exceeded'}}
                for key, known in labels.items():
                    value = error.get(key)
                    if value is not None:
                        safe['provider_' + key] = value if type(value) is str and value in known else 'unrecognized'
        codes = {'catalog_error', 'invalid_parameters', 'pricing_unavailable', 'no_matches'}
        if metadata.get('result_code') in codes:
            safe['result_code'] = metadata['result_code']
        logging.getLogger('artefact.diagnostics').warning(
            'stage=%s exception_type=%s metadata=%s', stage,
            type(exc).__name__ if exc is not None else 'none', json.dumps(safe, sort_keys=True))
    except Exception:
        pass  # Diagnostic handlers must not change application behavior.


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
    query: str | None = None  # Application-attached untrusted utterance; policy worker only.
    product_ids: tuple[int, ...] = ()  # Application-validated conversational selection, never model output.
    request: dict | None = None
    supplied_parameters: tuple[str, ...] = ()
    alternative_to: int | None = None
    focus_product_id: int | None = None
    clarification: str | None = None


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
    """Configured-service evidence, separate from a conservative case assessment."""
    text: str
    source_references: tuple[str, ...]
    assessment: PolicyAssessment | None = None
    retrieval_status: str = 'ok'
    fallback_used: bool = False


class PolicyLookup(Protocol):
    """Legacy lookup; query-aware services may also expose retrieve(topic, query, context).

    retrieve returns classified PolicyEvidence, including safe evidence-free outcomes.
    """
    def lookup(self, *, topic: str, context: dict | None = None) -> PolicyEvidence | None: ...


@dataclass(frozen=True)
class AgentReply:
    status: str
    text: str
    products: list[dict[str, object]]
    task_outcomes: list[TaskResult] = field(default_factory=list)
    clarification: str | None = None


class WorkerState(TypedDict):
    # No message, session, raw plan, other tasks or domain dependencies.
    task: ValidatedTask


class GraphState(TypedDict, total=False):
    candidate_product_ids: tuple[int, ...]
    previous_filters: dict
    semantic_mode: bool
    clarification: str | None
    compare_products: bool  # Narrow application-owned comparison of validated candidates.
    policy_context: dict  # Typed customer statements; never verified eligibility.
    policy_topic: str | None  # Last supported topic only; no source text or history.
    selected_product_ids: tuple[int, ...]  # Application reference scope; validated anew each turn.
    session_id: str                 # Caller input; identifier, never authentication.
    message: str                    # Caller input; untrusted text.
    raw_plan: object                # Interpret node; untrusted adapter output.
    validated_plan: tuple[ValidatedTask, ...]  # Validate node; fresh application values.
    task_results: Annotated[list[TaskResult], operator.add]  # Workers; append-only per turn.
    ordered_results: list[TaskResult]  # Aggregate node; cardinality-checked and sorted.
    routing_outcome: str            # Prepare/interpret/validate/aggregate; application-only.
    final_reply: AgentReply         # Render node only; public return value.
