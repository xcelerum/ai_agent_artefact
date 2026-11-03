"""Domain workers: catalog facts, configured policy evidence, and order denial."""

from copy import deepcopy
from dataclasses import asdict

from app.agent.contracts import Intent, PolicyEvidence, PolicyLookup, TaskResult, ValidatedTask
from app.domain.catalog import Catalog, serialize_product
from app.domain.policy_rules import PolicyAssessment
from app.domain.pricing import PricingService


def domain(intent: Intent) -> str:
    return {Intent.CATALOG: 'catalog', Intent.POLICY: 'policy', Intent.ORDER: 'order'}[intent]


def result(task: ValidatedTask, status: str, *, facts=None, references=(), error=None) -> TaskResult:
    return TaskResult(task.task_id, task.position, domain(task.intent), status,
                      {} if facts is None else facts, references, error)


def catalog_lookup(task: ValidatedTask, catalog: Catalog, pricing: PricingService | None = None) -> TaskResult:
    try:
        arguments = deepcopy(task.validated_parameters)
        payment_method = arguments.pop('payment_method', None)
        if payment_method is not None and pricing is None:
            return result(task, 'error', error='pricing_unavailable')
        products = []
        references = []
        for product in catalog.search(**arguments):
            serialized = serialize_product(product)
            references.append(f'catalog-snapshot:product/{product.product_id}')
            if pricing is not None:
                serialized['pricing'] = pricing.quote(product, payment_method)
                references.extend(serialized['pricing']['source_references'])
            products.append(serialized)
        return result(task, 'ok' if products else 'no_matches', facts={'products': products},
                      references=tuple(dict.fromkeys(references)))
    except ValueError:
        return result(task, 'error', error='invalid_parameters')
    except Exception:
        return result(task, 'error', error='catalog_error')


def policy_lookup(task: ValidatedTask, service: PolicyLookup | None) -> TaskResult:
    if service is None:
        return result(task, 'policy_unavailable', error='policy_unavailable')
    try:
        arguments = deepcopy(task.validated_parameters)
        evidence = service.lookup(**arguments)
        if (not isinstance(evidence, PolicyEvidence) or type(evidence.text) is not str
                or not evidence.text.strip() or len(evidence.text) > 8000
                or type(evidence.source_references) is not tuple
                or not 1 <= len(evidence.source_references) <= 8
                or any(type(ref) is not str or not ref.strip() or len(ref) > 500
                       for ref in evidence.source_references)):
            return result(task, 'policy_unavailable', error='policy_unavailable')
        facts, status = {'text': evidence.text}, 'ok'
        if evidence.assessment is not None:
            if not isinstance(evidence.assessment, PolicyAssessment):
                return result(task, 'policy_unavailable', error='policy_unavailable')
            facts['assessment'] = asdict(evidence.assessment)
            status = ('clarification' if evidence.assessment.decision == 'clarification_required'
                      else 'review_required')
        return result(task, status, facts=facts, references=tuple(evidence.source_references))
    except Exception:
        return result(task, 'error', error='policy_error')


def order_authorization_gate(task: ValidatedTask) -> TaskResult:
    # No authentication exists. No lookup dependency, filesystem access or invented status.
    return result(task, 'authorization_required', error='authorization_required')
