"""Cardinality-checked fan-in and deterministic trusted-fact rendering."""

from collections import Counter
from copy import deepcopy
import json

from app.agent.contracts import AgentReply, TaskResult, ValidatedTask
from app.agent.workers import domain, result


def fixed_reply(status: str) -> AgentReply:
    messages = {
        'clarification': 'Please clarify the product or search criteria you want.',
        'unsupported': ('Supported requests include catalog products, configured policy evidence, '
                        'and safe order-support guidance. Private order details require trusted authorization.'),
        'invalid_request': 'The request could not be validated. Please check the search criteria.',
        'no_matches': 'No matching listings were found in this catalog snapshot.',
        'model_error': 'The request could not be interpreted. Please try again.',
        'tool_error': 'The request could not be completed. Please try again.',
        'aggregation_error': 'The task results could not be verified. Please try again.',
        'policy_unavailable': 'The policy information could not be confirmed from an available source.',
        'authorization_required': 'Order information requires trusted authorization. Please contact support.',
        'failed': 'The requested information could not be confirmed.',
    }
    return AgentReply(status, messages[status], [])


def aggregate(tasks: tuple[ValidatedTask, ...], results: list[TaskResult]) -> tuple[str, list[TaskResult]]:
    expected = {task.task_id for task in tasks}
    unknown = any(not isinstance(item, TaskResult) or item.task_id not in expected for item in results)
    counts = Counter(item.task_id for item in results if isinstance(item, TaskResult))
    by_id = {item.task_id: item for item in results if isinstance(item, TaskResult)}
    ordered, corrupt = [], False
    for task in tasks:
        item = by_id.get(task.task_id)
        if (unknown or counts[task.task_id] != 1 or item.position != task.position
                or item.domain != domain(task.intent)):
            item = result(task, 'error', error='aggregation_error')
            corrupt = True
        ordered.append(item)
    ordered.sort(key=lambda item: item.position)
    if corrupt:
        return 'aggregation_error', ordered
    successes = sum(item.status in ('ok', 'no_matches') for item in ordered)
    if len(ordered) == 1:
        status = 'tool_error' if ordered[0].status == 'error' else ordered[0].status
    elif successes == len(ordered):
        status = 'no_matches' if all(item.status == 'no_matches' for item in ordered) else 'ok'
    else:
        status = 'partial_failure' if successes else 'failed'
    return status, ordered


def _catalog_text(products: list[dict]) -> str:
    lines = ['Matching listings in this catalog snapshot (not live inventory):']
    for product in products:
        name = json.dumps(product['name'], ensure_ascii=False)
        specs = json.dumps(product['specs'], ensure_ascii=False, sort_keys=True)
        availability = 'purchasable' if product['is_purchasable'] else 'not purchasable'
        lines.append(
            f"Product {product['product_id']}: {name}; BRL {product['price_brl']}; "
            f"snapshot availability: {availability}; status: {product['status']}; "
            f"stock: {product['stock_quantity']}; category ID: {product['category_id']}; "
            f"specifications: {specs}"
        )
    return '\n'.join(lines)


def render_reply(status: str, outcomes: list[TaskResult]) -> AgentReply:
    if not outcomes:
        return fixed_reply(status)
    sections, products, seen = [], [], set()
    for outcome in outcomes:
        if outcome.status == 'ok' and outcome.domain == 'catalog':
            current = outcome.facts['products']
            text = _catalog_text(current)
            for product in current:
                if product['product_id'] not in seen:
                    seen.add(product['product_id'])
                    products.append(deepcopy(product))
        elif outcome.status == 'ok' and outcome.domain == 'policy':
            text = 'Configured policy evidence: ' + json.dumps(outcome.facts['text'], ensure_ascii=False)
            text += '\nSources: ' + ', '.join(json.dumps(ref) for ref in outcome.source_references)
        else:
            category = ('aggregation_error' if outcome.error_category == 'aggregation_error' else
                        'tool_error' if outcome.status == 'error' else outcome.status)
            text = fixed_reply(category).text
        if len(outcomes) > 1:
            text = f'{outcome.domain.capitalize()} [{outcome.task_id}]\n' + text
        sections.append(text)
    # Separate copies prevent callers from mutating catalog records or shared result lists.
    return AgentReply(status, '\n\n'.join(sections), products, deepcopy(outcomes))
