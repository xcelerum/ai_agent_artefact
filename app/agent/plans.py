"""Version 2 schema and independent application validation; no tool-name dispatch."""

from decimal import Decimal
import json
import re
import unicodedata

from app.agent.contracts import Intent, ValidatedTask
from app.domain.catalog import Catalog
from app.domain.policy_rules import context_schema, validate_context
from app.agent.semantics import request_schema, validate_request, HINTS


def _catalog_schema() -> dict:
    text = {'type': ['string', 'null'], 'minLength': 1, 'maxLength': 200}
    search_parameters = {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'name': dict(text), 'category': dict(text),
            'category_id': {'type': ['integer', 'null'], 'minimum': 1},
            'max_price': {
                'type': ['string', 'null'], 'maxLength': 20,
                'pattern': r'^[0-9]+(?:\.[0-9]{1,2})?$',
            },
            'specs': {
                'type': ['object', 'null'], 'maxProperties': 20,
                'propertyNames': {'minLength': 1, 'maxLength': 200},
                'additionalProperties': {'type': 'string', 'minLength': 1, 'maxLength': 200},
            },
            'purchasable_only': {'type': 'boolean', 'default': True},
            'payment_method': {'enum': ['pix', 'credit_card', 'cash']},
        },
    }
    return search_parameters


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _decode_plan(raw: object) -> dict:
    if type(raw) is str:
        if len(raw.encode('utf-8')) > 16 * 1024:
            raise ValueError('Extraction too large')
        raw = json.loads(raw, object_pairs_hook=_unique_object)
    if type(raw) is not dict:
        raise ValueError('Expected intent object')
    # Also bounds adapter-decoded objects and rejects non-JSON values/nonfinite floats.
    if len(json.dumps(raw, allow_nan=False, ensure_ascii=True).encode('utf-8')) > 16 * 1024:
        raise ValueError('Extraction too large')
    return raw


def _text(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 200:
        raise ValueError('Invalid search text')
    return value


def _normalized_key(key: str) -> str:
    # Match the catalog's accent/case/whitespace normalization before dispatch.
    return ''.join(c for c in unicodedata.normalize('NFD', key.casefold().strip())
                   if not unicodedata.combining(c))


def _catalog_parameters(parameters: dict) -> dict:
    allowed = {'name', 'category', 'category_id', 'max_price', 'specs', 'purchasable_only'}
    if not set(parameters) <= allowed:
        raise ValueError('Unknown search parameter')
    arguments = {key: parameters.get(key) for key in allowed - {'purchasable_only'}}
    arguments['purchasable_only'] = parameters.get('purchasable_only', True)
    for key in ('name', 'category'):
        if arguments[key] is not None:
            arguments[key] = _text(arguments[key])
    identifier = arguments['category_id']
    if identifier is not None and (type(identifier) is not int or identifier <= 0):
        raise ValueError('Invalid category ID')
    if type(arguments['purchasable_only']) is not bool:
        raise ValueError('Invalid purchasable flag')
    price = arguments['max_price']
    if price is not None:
        if (type(price) is not str or len(price) > 20
                or re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?', price) is None):
            raise ValueError('Invalid monetary string')
        arguments['max_price'] = Decimal(price)
    specs = arguments['specs']
    if specs is not None:
        if type(specs) is not dict or len(specs) > 20:
            raise ValueError('Invalid specification filters')
        seen = set()
        copied = {}
        for key, item in specs.items():
            normalized = _normalized_key(_text(key))
            if normalized in seen:
                raise ValueError('Duplicate normalized specification key')
            seen.add(normalized)
            copied[key] = _text(item)
        arguments['specs'] = copied
    return arguments


def plan_schema() -> dict:
    parameters = {
        Intent.CATALOG: _catalog_schema(),
        Intent.POLICY: {
            'type': 'object', 'additionalProperties': False, 'required': ['topic'],
            'properties': {'topic': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                           'context': context_schema()},
        },
        Intent.ORDER: {
            'type': 'object', 'additionalProperties': False,
            'properties': {'order_reference': {'type': ['string', 'null'], 'minLength': 1, 'maxLength': 200}},
        },
    }
    item = {
        'type': 'object', 'additionalProperties': False,
        'required': ['id', 'intent', 'parameters'],
        'properties': {
            'id': {'type': 'string', 'pattern': '^[A-Za-z][A-Za-z0-9_-]{0,31}$', 'maxLength': 32},
            'intent': {'type': 'string', 'enum': [intent.value for intent in Intent]},
            'parameters': {'type': 'object'},
            'request': {'anyOf': [request_schema(), {'type': 'null'}]},
        },
        'allOf': [
            {'if': {'properties': {'intent': {'const': intent.value}}},
             'then': {'properties': {'parameters': schema}}}
            for intent, schema in parameters.items()
        ],
    }
    return {
        'type': 'object', 'additionalProperties': False,
        'required': ['schema_version', 'disposition', 'tasks'],
        'properties': {
            'schema_version': {'const': '2'},
            'disposition': {'type': 'string', 'enum': ['execute', 'clarification', 'unsupported']},
            'tasks': {'type': 'array', 'maxItems': 4, 'items': item},
            'response_hint': {'enum': [*HINTS, None]},
        },
        'allOf': [{
            'if': {'properties': {'disposition': {'const': 'execute'}}},
            'then': {'properties': {'tasks': {'minItems': 1}}},
            'else': {'properties': {'tasks': {'maxItems': 0}}},
        }],
        'description': ('Group related availability and price questions into one catalog task. '
                        'Use separate tasks for independent domains or different filters. '
                        'Ask for clarification on ambiguity; do not guess missing criteria.'),
    }


def _resolve_category(arguments: dict, catalog: Catalog) -> dict:
    """Resolve confirmed Portuguese guitar phrases against actual catalog facts.

    No stemming, fuzzy name matching, invented IDs or fallback broad searches.
    Keep exact product names and conflicting explicit filters unchanged.
    """
    forms = {'violao', 'violoes'}
    matches = [category for category in catalog.categories
               if _normalized_key(category.name) in forms]
    if len(matches) != 1:
        return arguments
    category = matches[0]
    category_text = arguments['category']
    nylon_forms = {'violao de nylon', 'violao nylon', 'violoes de nylon', 'violoes nylon'}
    category_key = _normalized_key(category_text) if category_text is not None else None
    name = arguments['name']
    name_key = _normalized_key(name) if name is not None else None
    generic_name = (name_key in forms | nylon_forms
                    and not any(_normalized_key(product.name) == name_key
                                for product in catalog.products))
    compatible = (category_key is None or category_key in forms | nylon_forms)
    compatible = compatible and arguments['category_id'] in (None, category.category_id)
    if category_key in nylon_forms or (generic_name and name_key in nylon_forms and compatible):
        if not any(product.category_id == category.category_id
                   and any(_normalized_key(k) == 'strings' and _normalized_key(v) == 'nylon'
                           for k, v in product.specs.items()) for product in catalog.products):
            raise ValueError('Unconfirmed nylon specification')
        specs = dict(arguments['specs'] or {})
        supported = {_normalized_key(k) for product in catalog.products for k in product.specs}
        # Correct the observed unsupported key only within this explicit nylon phrase.
        for key in tuple(specs):
            if (_normalized_key(key) == 'material' and 'material' not in supported
                    and _normalized_key(specs[key]) == 'nylon'):
                del specs[key]
        strings = [value for key, value in specs.items() if _normalized_key(key) == 'strings']
        if any(_normalized_key(value) != 'nylon' for value in strings):
            raise ValueError('Conflicting string specification')
        if not strings:
            specs['strings'] = 'nylon'
        arguments['specs'] = specs
    if category_key in forms | nylon_forms:
        arguments['category'] = category.name
    if generic_name and compatible:
        arguments['name'] = None
        arguments['category'] = category.name
    return arguments


def _parameters(intent: Intent, parameters: object, catalog: Catalog) -> dict:
    if type(parameters) is not dict:
        raise ValueError('Expected parameter object')
    if intent == Intent.CATALOG:
        search_parameters = {key: value for key, value in parameters.items() if key != 'payment_method'}
        arguments = _catalog_parameters(search_parameters)
        if 'payment_method' in parameters:
            method = parameters['payment_method']
            if type(method) is not str or method not in ('pix', 'credit_card', 'cash'):
                raise ValueError('Invalid payment method')
            arguments['payment_method'] = method
        arguments = _resolve_category(arguments, catalog)
        supported = {_normalized_key(key) for p in catalog.products for key in p.specs}
        if any(_normalized_key(key) not in supported for key in arguments['specs'] or {}):
            raise ValueError('Unsupported specification key')
        return arguments
    if intent == Intent.POLICY:
        if 'topic' not in parameters or not set(parameters) <= {'topic', 'context'}:
            raise ValueError('Invalid policy parameters')
        arguments = {'topic': _text(parameters['topic'])}
        if 'context' in parameters:
            arguments['context'] = validate_context(parameters['context'])
        return arguments
    if not set(parameters) <= {'order_reference'}:
        raise ValueError('Invalid order parameters')
    reference = parameters.get('order_reference')
    return {'order_reference': None if reference is None else _text(reference)}


def _fingerprint(value):
    """Normalized effective operations: default/null fields and Decimal equality count."""
    if type(value) is dict:
        return tuple(sorted((_normalized_key(k), _fingerprint(v)) for k, v in value.items()))
    return _normalized_key(value) if type(value) is str else value


def validate_plan(raw: object, catalog: Catalog) -> tuple[str, tuple[ValidatedTask, ...]]:
    value = _decode_plan(raw)
    if (not {'schema_version', 'disposition', 'tasks'} <= set(value)
            or not set(value) <= {'schema_version', 'disposition', 'tasks', 'response_hint'}
            or value['schema_version'] != '2'):
        raise ValueError('Invalid plan envelope')
    hint = value.get('response_hint')
    if hint is not None and (type(hint) is not str or hint not in HINTS):
        raise ValueError('Invalid response hint')
    disposition = value['disposition']
    if type(disposition) is not str or disposition not in ('execute', 'clarification', 'unsupported'):
        raise ValueError('Invalid disposition')
    tasks = value['tasks']
    if type(tasks) is not list or len(tasks) > 4:
        raise ValueError('Invalid task list')
    if disposition != 'execute':
        if tasks:
            raise ValueError('Fallback must not execute tasks')
        return disposition, ()
    if not tasks:
        raise ValueError('Execute requires a task')
    accepted, identifiers, operations = [], set(), set()
    for position, task in enumerate(tasks):
        if (type(task) is not dict or not {'id', 'intent', 'parameters'} <= set(task)
                or not set(task) <= {'id', 'intent', 'parameters', 'request'}):
            raise ValueError('Invalid task structure')
        identifier = task['id']
        if (type(identifier) is not str or re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}', identifier) is None
                or identifier in identifiers or type(task['intent']) is not str):
            raise ValueError('Invalid task identity')
        intent = Intent(task['intent'])
        request = validate_request(task.get('request'))
        parameters = _parameters(intent, task['parameters'], catalog)
        effective_parameters = parameters
        if intent == Intent.CATALOG:
            # Missing/null/empty specs all impose no restriction. Preserve dispatch arguments.
            effective_parameters = {**parameters, 'specs': parameters['specs'] or None}
        operation = (intent, _fingerprint(effective_parameters),
                     json.dumps(request, sort_keys=True) if request is not None else None)
        if operation in operations:
            raise ValueError('Duplicate operation')
        identifiers.add(identifier)
        operations.add(operation)
        accepted.append(ValidatedTask(identifier, position, intent, parameters, request=request,
                                      supplied_parameters=tuple(task['parameters'])))
    return disposition, tuple(accepted)
