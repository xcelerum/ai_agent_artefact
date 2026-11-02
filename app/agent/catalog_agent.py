"""Structured intent interpretation with deterministic catalog routing and output.

The injected model supplies untrusted intent only. Each invocation runs fresh graph
state; conversation history and a live provider adapter are deliberately absent.
"""

from dataclasses import dataclass, field
from decimal import Decimal
import json
import re
from typing import Protocol, TypedDict
import unicodedata

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.domain.catalog import Catalog, Product, serialize_product


class StructuredIntentModel(Protocol):
    def extract(self, *, history: list, message: str, schema: dict) -> object: ...


@dataclass(frozen=True)
class AgentReply:
    status: str
    text: str
    products: list[dict[str, object]]


class AgentState(TypedDict, total=False):
    session_id: str
    message: str
    raw_intent: object
    status: str
    results: tuple[Product, ...]
    reply: AgentReply


def _intent_schema() -> dict:
    """Return a fresh closed schema so adapters cannot mutate another call's schema."""
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
        },
    }
    return {
        'type': 'object', 'additionalProperties': False,
        'required': ['intent', 'parameters'],
        'properties': {
            'intent': {'type': 'string', 'enum': ['search_products', 'clarification', 'unsupported']},
            'parameters': {'type': 'object'},
        },
        'allOf': [{
            'if': {'properties': {'intent': {'const': 'search_products'}}},
            'then': {'properties': {'parameters': search_parameters}},
            'else': {'properties': {'parameters': {'type': 'object', 'maxProperties': 0}}},
        }],
    }


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _decode_intent(raw: object) -> dict:
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


def _validated_intent(raw: object) -> tuple[str, dict]:
    value = _decode_intent(raw)
    if set(value) != {'intent', 'parameters'}:
        raise ValueError('Invalid envelope')
    intent = value['intent']
    if type(intent) is not str or intent not in ('search_products', 'clarification', 'unsupported'):
        raise ValueError('Invalid intent')
    parameters = value['parameters']
    if type(parameters) is not dict:
        raise ValueError('Expected parameters object')
    if intent != 'search_products':
        if parameters:
            raise ValueError('Fallback parameters must be empty')
        return intent, {}

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
    return intent, arguments


def _fixed_reply(status: str) -> AgentReply:
    messages = {
        'clarification': 'Please clarify the product or search criteria you want.',
        'unsupported': 'This assistant currently supports catalog product searches only.',
        'invalid_request': 'The request could not be validated. Please check the search criteria.',
        'no_matches': 'No matching listings were found in this catalog snapshot.',
        'model_error': 'The request could not be interpreted. Please try again.',
        'tool_error': 'The catalog search could not be completed. Please try again.',
    }
    return AgentReply(status, messages[status], [])


@dataclass(frozen=True)
class CatalogAgent:
    catalog: Catalog
    model: StructuredIntentModel
    _graph: CompiledStateGraph = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        builder = StateGraph(AgentState)
        builder.add_node('interpret', self._interpret)
        builder.add_node('validate_execute', self._validate_execute)
        builder.add_node('render', self._render)
        builder.add_edge(START, 'interpret')
        builder.add_edge('interpret', 'validate_execute')
        builder.add_edge('validate_execute', 'render')
        builder.add_edge('render', END)
        object.__setattr__(self, '_graph', builder.compile())

    def invoke(self, *, session_id: str, message: str) -> AgentReply:
        if (type(session_id) is not str or not session_id.strip()
                or type(message) is not str or not message.strip() or len(message) > 4000):
            return _fixed_reply('invalid_request')
        # No checkpoint, history or previous results are carried between calls.
        try:
            state = self._graph.invoke({'session_id': session_id, 'message': message})
            reply = state['reply']
            if not isinstance(reply, AgentReply):
                raise ValueError('Missing application reply')
            return reply
        except Exception:
            # Framework/unexpected failures must not expose state or exception text.
            return _fixed_reply('tool_error')

    def _interpret(self, state: AgentState) -> dict:
        try:
            raw = self.model.extract(history=[], message=state['message'], schema=_intent_schema())
            return {'raw_intent': raw}
        except Exception:
            return {'status': 'model_error'}

    def _validate_execute(self, state: AgentState) -> dict:
        if state.get('status') == 'model_error':
            return {}
        try:
            intent, arguments = _validated_intent(state['raw_intent'])
        except (ValueError, TypeError, RecursionError, OverflowError):
            return {'status': 'invalid_request', 'results': ()}
        if intent != 'search_products':
            return {'status': intent, 'results': ()}
        try:
            results = self.catalog.search(**arguments)
        except ValueError:
            return {'status': 'invalid_request', 'results': ()}
        except Exception:
            return {'status': 'tool_error', 'results': ()}
        return {'status': 'ok' if results else 'no_matches', 'results': results}

    def _render(self, state: AgentState) -> dict:
        if state['status'] != 'ok':
            return {'reply': _fixed_reply(state['status'])}
        try:
            products = [serialize_product(product) for product in state['results']]
            lines = ['Matching listings in this catalog snapshot (not live inventory):']
            for product in products:
                # JSON-quoted source strings are data, not markup or instructions.
                name = json.dumps(product['name'], ensure_ascii=False)
                specs = json.dumps(product['specs'], ensure_ascii=False, sort_keys=True)
                availability = 'purchasable' if product['is_purchasable'] else 'not purchasable'
                lines.append(
                    f"Product {product['product_id']}: {name}; BRL {product['price_brl']}; "
                    f"snapshot availability: {availability}; status: {product['status']}; "
                    f"stock: {product['stock_quantity']}; category ID: {product['category_id']}; "
                    f"specifications: {specs}"
                )
            # Plain text response; consumers must not interpret catalog strings as HTML.
            return {'reply': AgentReply('ok', '\n'.join(lines), products)}
        except Exception:
            return {'reply': _fixed_reply('tool_error')}


def build_agent(*, catalog: Catalog, model: StructuredIntentModel) -> CatalogAgent:
    return CatalogAgent(catalog=catalog, model=model)
