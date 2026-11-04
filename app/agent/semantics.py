"""Closed conversational objectives and local reference binding; never model IDs."""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext
import re


GOALS = ('discover', 'evaluate', 'learn', 'refine', 'guide', 'alternatives')
RESPONSES = ('answer', 'compare', 'recommend', 'explain', 'clarify')
REFERENCES = ('new', 'selected', 'candidates', 'previous_search')
BUDGETS = ('keep', 'replace', 'remove', 'below_reference', 'cheaper')
SITUATIONS = ('general', 'individual', 'hypothetical')
HINTS = ('reference', 'criteria', 'budget', 'unsupported_action', 'outside_capability')


def request_schema():
    return {'type': 'object', 'additionalProperties': False,
            'required': ['goal', 'response', 'reference', 'positions', 'anchor', 'budget', 'situation'],
            'properties': {
                'goal': {'type': 'string', 'enum': list(GOALS)},
                'response': {'type': 'string', 'enum': list(RESPONSES)},
                'budget': {'type': 'string', 'enum': list(BUDGETS)},
                'reference': {'type': 'string', 'enum': list(REFERENCES)},
                'positions': {'type': 'array', 'items': {'type': 'integer'}, 'maxItems': 5},
                'anchor': {'type': ['string', 'null'], 'maxLength': 200},
                'situation': {'type': 'string', 'enum': list(SITUATIONS)},
            }}


def validate_request(value):
    if value is None:
        return None
    schema = request_schema()
    if type(value) is not dict or set(value) != set(schema['required']):
        raise ValueError('Invalid conversational request')
    for key, choices in (('goal', GOALS), ('response', RESPONSES), ('reference', REFERENCES),
                         ('budget', BUDGETS), ('situation', SITUATIONS)):
        if type(value[key]) is not str or value[key] not in choices:
            raise ValueError('Invalid conversational enum')
    positions = value['positions']
    if (type(positions) is not list or len(positions) > 5
            or any(type(p) is not int or not 1 <= p <= 5 for p in positions)
            or len(set(positions)) != len(positions)):
        raise ValueError('Invalid reference positions')
    if positions and value['reference'] not in ('candidates', 'selected'):
        raise ValueError('Positions require candidate reference')
    anchor = value['anchor']
    if anchor is not None and (type(anchor) is not str or not anchor.strip() or len(anchor) > 200):
        raise ValueError('Invalid reference text')
    copied = deepcopy(value)
    if positions:
        copied['reference'] = 'candidates'
    if copied['budget'] == 'cheaper':
        copied['budget'] = 'below_reference'
    return copied


class NeedClarification(ValueError):
    def __init__(self, code='reference'):
        self.code = code
        super().__init__('Unresolved conversational reference')


def wire_parameters(parameters):
    return {k: str(v) if isinstance(v, Decimal) else deepcopy(v)
            for k, v in parameters.items() if v is not None}


def bind_request(task, *, catalog, selected, candidates, previous, message):
    """Map symbolic references to validated local IDs/filters, without a model call."""
    from app.agent.contracts import Intent
    from app.agent.plans import _parameters, _normalized_key
    if task.request is None or task.intent != Intent.CATALOG:
        return task
    request = deepcopy(task.request)
    reference = request['reference']
    independent_explanation = (request['goal'] == 'learn' and request['response'] == 'explain'
                               and reference == 'new')
    current = {k: v for k, v in task.validated_parameters.items() if k in task.supplied_parameters}
    if request['goal'] == 'evaluate' and candidates:
        # Contextual evaluation must not acquire an unstated family from model guesses.
        for key in ('name', 'category'):
            if current.get(key) and _normalized_key(current[key]) not in _normalized_key(message):
                current.pop(key)
        name = current.get('name')
        if name and any(_normalized_key(name) in _normalized_key(p.name)
                        for p in catalog.products if p.product_id in candidates):
            request['anchor'] = request['anchor'] or name
            current.pop('name')
    new_identity = any(current.get(k) for k in ('name', 'category', 'category_id', 'specs'))
    # Operation-level defaults apply only when no fresh identity/filter was supplied.
    if reference == 'new' and not new_identity and not independent_explanation:
        if (request['goal'] == 'evaluate' or request['response'] in ('compare', 'recommend', 'explain')) and candidates:
            reference = 'candidates'
        elif previous and (request['goal'] == 'refine' or request['budget'] == 'replace'):
            reference = 'previous_search'
        elif request['goal'] == 'alternatives':
            reference = 'selected'
    request['reference'] = reference
    params = deepcopy(previous) if reference == 'previous_search' else {}
    params.update(current)
    if reference == 'previous_search' and current.get('specs'):
        specs = dict(previous.get('specs') or {})
        for key, value in current['specs'].items():
            specs = {k: v for k, v in specs.items() if _normalized_key(k) != _normalized_key(key)}
            specs[key] = value
        params['specs'] = specs
    if request['budget'] == 'keep' and 'max_price' not in current and previous.get('max_price') is not None:
        params['max_price'] = previous['max_price']
    if request['budget'] == 'remove':
        if current.get('max_price') is not None:
            raise ValueError('Conflicting budget request')
        params.pop('max_price', None)
    if request['budget'] == 'replace' and current.get('max_price') is None:
        raise NeedClarification('budget')
    ids = ()
    if reference == 'selected':
        ids = selected or (candidates if len(candidates) == 1 else ())
    elif reference == 'candidates':
        ids = candidates
        if request['positions']:
            if any(p > len(candidates) for p in request['positions']):
                raise NeedClarification()
            ids = tuple(candidates[p-1] for p in request['positions'])
    elif reference == 'previous_search' and not previous:
        raise NeedClarification('criteria')
    records = {p.product_id: p for p in catalog.products}
    if reference in ('selected', 'candidates') and not ids:
        raise NeedClarification()
    anchor = request['anchor']
    focus = selected[0] if len(selected) == 1 and (selected[0] in ids or reference == 'previous_search') else None
    if anchor and not independent_explanation:
        normalized = _normalized_key(anchor)
        if normalized not in _normalized_key(message):
            raise NeedClarification()
        words = set(re.findall(r'\w+', normalized))
        scores = {identifier: len(words & set(re.findall(r'\w+', _normalized_key(records[identifier].name))))
                  for identifier in (ids or candidates)}
        best = max(scores.values(), default=0)
        matches = tuple(identifier for identifier, score in scores.items() if best and score == best)
        if not matches:
            raise NeedClarification()
        if request['response'] not in ('compare', 'recommend'):
            ids = matches
        elif len(matches) > 1 and not (selected and set(selected) <= set(matches)):
            raise NeedClarification()
        if len(matches) == 1:
            focus = matches[0]
        if request['response'] in ('compare', 'recommend', 'explain') and reference == 'new':
            reference = 'candidates'
            request['reference'] = reference
            ids = candidates
        # A subject reference must not restrict a comparison to its own name.
        if current.get('name') and request['response'] in ('compare', 'recommend', 'explain'):
            params.pop('name', None)
    if request['response'] in ('compare', 'recommend', 'explain') and request['goal'] == 'evaluate' and reference == 'selected':
        ids = candidates
    if request['response'] == 'compare' and len(ids) < 2:
        raise NeedClarification('comparison')
    if reference == 'selected' and request['response'] not in ('compare', 'recommend') and len(ids) != 1:
        raise NeedClarification()
    alternative_to = None
    if request['budget'] == 'below_reference' or request['goal'] == 'alternatives':
        baseline = selected or (ids if len(ids) == 1 else ())
        if len(baseline) != 1:
            raise NeedClarification()
        base = records[baseline[0]]
        alternative_to = base.product_id
        with localcontext() as context:
            context.prec = max(28, len(base.price_brl.as_tuple().digits)+4)
            ceiling = max(Decimal('0'), base.price_brl - Decimal('0.01'))
        if request['budget'] == 'below_reference':
            params['max_price'] = min(Decimal(str(params['max_price'])), ceiling) if params.get('max_price') is not None else ceiling
        if params.get('category_id') not in (None, base.category_id):
            raise NeedClarification('criteria')
        params['category_id'] = base.category_id
        params.pop('name', None)
        specs = dict(params.get('specs') or {})
        if 'strings' in base.specs:
            specs.setdefault('strings', base.specs['strings'])
        params['specs'] = specs
        ids = ()
    # Revalidate every inherited/derived filter through the same application contract.
    validated = _parameters(Intent.CATALOG, wire_parameters(params), catalog)
    return replace(task, request=request, validated_parameters=validated, product_ids=ids,
                   alternative_to=alternative_to, focus_product_id=focus)
