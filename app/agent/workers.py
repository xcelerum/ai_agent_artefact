"""Domain workers: catalog facts, configured policy evidence, and order denial."""

from copy import deepcopy

from app.agent.contracts import Intent, PolicyEvidence, PolicyLookup, TaskResult, ValidatedTask
from app.domain.catalog import Catalog, serialize_product


def domain(intent: Intent) -> str:
    return {Intent.CATALOG: 'catalog', Intent.POLICY: 'policy', Intent.ORDER: 'order'}[intent]


def result(task: ValidatedTask, status: str, *, facts=None, references=(), error=None) -> TaskResult:
    return TaskResult(task.task_id, task.position, domain(task.intent), status,
                      {} if facts is None else facts, references, error)


def catalog_lookup(task: ValidatedTask, catalog: Catalog) -> TaskResult:
    try:
        products = [serialize_product(p) for p in catalog.search(**deepcopy(task.validated_parameters))]
        return result(task, 'ok' if products else 'no_matches', facts={'products': products},
                      references=tuple(f"catalog-snapshot:product/{p['product_id']}" for p in products))
    except ValueError:
        return result(task, 'error', error='invalid_parameters')
    except Exception:
        return result(task, 'error', error='catalog_error')


def policy_lookup(task: ValidatedTask, service: PolicyLookup | None) -> TaskResult:
    if service is None:
        return result(task, 'policy_unavailable', error='policy_unavailable')
    try:
        evidence = service.lookup(topic=task.validated_parameters['topic'])
        if (not isinstance(evidence, PolicyEvidence) or type(evidence.text) is not str
                or not evidence.text.strip() or len(evidence.text) > 8000
                or type(evidence.source_references) is not tuple
                or not 1 <= len(evidence.source_references) <= 8
                or any(type(ref) is not str or not ref.strip() or len(ref) > 500
                       for ref in evidence.source_references)):
            return result(task, 'policy_unavailable', error='policy_unavailable')
        return result(task, 'ok', facts={'text': evidence.text}, references=tuple(evidence.source_references))
    except Exception:
        return result(task, 'error', error='policy_error')


def order_authorization_gate(task: ValidatedTask) -> TaskResult:
    # No authentication exists. No lookup dependency, filesystem access or invented status.
    return result(task, 'authorization_required', error='authorization_required')
