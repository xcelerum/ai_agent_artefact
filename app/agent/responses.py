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
    # Assessment outcomes carry valid evidence; they are not tool failures.
    statuses = {item.status for item in ordered}
    nonfailures = {'ok', 'no_matches', 'clarification', 'review_required'}
    successes = sum(item.status in nonfailures for item in ordered)
    if len(ordered) == 1:
        status = 'tool_error' if ordered[0].status == 'error' else ordered[0].status
    elif successes != len(ordered):
        status = 'partial_failure' if successes else 'failed'
    elif 'clarification' in statuses:
        status = 'clarification'
    elif 'review_required' in statuses:
        status = 'review_required'
    else:
        status = 'no_matches' if statuses == {'no_matches'} else 'ok'
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
        pricing = product.get('pricing')
        if pricing:
            if pricing['promotion_applied']:
                lines.append(f"Original table price: BRL {pricing['table_price']}; promotional price: "
                             f"BRL {pricing['promotional_price']} ({pricing['discount_percent']}% discount).")
            if pricing['pix_price'] is not None:
                lines.append(f"Selected PIX price: BRL {pricing['pix_price']} (5% of table price off; not cumulative).")
            elif pricing['pix_status'] == 'excluded_promotion':
                lines.append('PIX discount does not apply to promotional products; no discount stacking.')
            elif pricing['pix_status'] == 'policy_unavailable':
                lines.append('The conditional PIX price could not be confirmed from policy evidence.')
            elif pricing['pix_status'] == 'unavailable_snapshot':
                lines.append('PIX and promotional purchase offers are unavailable for this snapshot listing.')
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
        elif outcome.status in ('ok', 'clarification', 'review_required') and outcome.domain == 'policy':
            text = 'Configured policy evidence: ' + json.dumps(outcome.facts['text'], ensure_ascii=False)
            text += '\nSources: ' + ', '.join(json.dumps(ref) for ref in outcome.source_references)
            assessment = outcome.facts.get('assessment')
            if assessment:
                text += '\n' + assessment['notice']
                if assessment['missing_facts']:
                    text += '\nPlease clarify: ' + ', '.join(assessment['missing_facts']) + '.'
                text += '\nCustomer-stated window: ' + assessment['window_status'] + '; staff review required.'
        else:
            category = ('aggregation_error' if outcome.error_category == 'aggregation_error' else
                        'tool_error' if outcome.status == 'error' else outcome.status)
            text = fixed_reply(category).text
        if len(outcomes) > 1:
            text = f'{outcome.domain.capitalize()} [{outcome.task_id}]\n' + text
        sections.append(text)
    # Separate copies prevent callers from mutating catalog records or shared result lists.
    return AgentReply(status, '\n\n'.join(sections), products, deepcopy(outcomes))
