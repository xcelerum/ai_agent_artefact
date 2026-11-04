"""First M2 RED increment: public agent flow, real graph and synthetic catalog."""

from copy import deepcopy
import csv
from decimal import Decimal
import inspect

import pytest
from langgraph.graph.state import CompiledStateGraph

from app.agent.catalog_agent import build_agent
from app.data.catalog import CATEGORY_FIELDS, PRODUCT_FIELDS, load_catalog
from app.domain.catalog import Catalog, serialize_product


class FakeIntentModel:
    """Supplies only untrusted extraction, never tool results or final answers."""

    def __init__(self, extraction):
        self.extraction = extraction
        self.calls = []

    def extract(self, *, history, message, schema):
        self.calls.append(deepcopy((history, message, schema)))
        return deepcopy(self.extraction)


@pytest.fixture
def catalog(tmp_path):
    categories = tmp_path / 'categories.csv'
    products = tmp_path / 'products.csv'
    with categories.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(CATEGORY_FIELDS)
        writer.writerows([(1, 'Test Guitars', ''), (2, 'Test Keys', ''),
                          (3, 'Test Winds', '')])
    rows = [
        (101, '1000.00', 'Aurora Nylon', 1, '', 3, 'active', '{"strings":"nylon"}', '2026-01-02'),
        (102, '999.99', 'Aurora Steel', 1, '', 3, 'active', '{"strings":"steel"}', '2026-01-02'),
        (103, '1000.01', 'Aurora Premium', 1, '', 3, 'active', '{"strings":"nylon"}', '2026-01-02'),
        (104, '900.00', 'Aurora Empty', 1, '', 0, 'active', '{"strings":"nylon"}', '2026-01-02'),
        (105, '950.00', 'Aurora Future', 1, '', 2, 'coming_soon', '{"strings":"nylon"}', '2026-01-02'),
        (106, '975.00', 'Aurora Retired', 1, '', 9, 'discontinued', '{"strings":"nylon"}', '2026-01-02'),
        (107, '800.00', 'Aurora Keys', 2, '', 2, 'active', '{"strings":"nylon"}', '2026-01-02'),
        (108, '850.00', 'Eclipse Nylon', 1, '', 2, 'active', '{"strings":"nylon"}', '2026-01-02'),
    ]
    with products.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(PRODUCT_FIELDS)
        writer.writerows(rows)
    return load_catalog(products, categories)


@pytest.fixture
def searches(monkeypatch):
    """Record effective arguments and results while delegating to M1 search."""
    original = Catalog.search
    calls = []

    def search(self, **kwargs):
        bound = inspect.signature(original).bind(self, **kwargs)
        bound.apply_defaults()
        arguments = dict(bound.arguments)
        del arguments['self']
        calls.append((arguments, None))
        result = original(self, **kwargs)
        calls[-1] = (arguments, result)
        return result

    monkeypatch.setattr(Catalog, 'search', search)
    return calls


def invoke(catalog, extraction, message='Show catalog products.'):
    model = FakeIntentModel(extraction)
    agent = build_agent(catalog=catalog, model=model)
    # The skeleton must compile a real graph, not substitute a fake final reply.
    assert isinstance(agent._graph, CompiledStateGraph)
    reply = agent.invoke(session_id='synthetic-session', message=message)
    assert len(model.calls) == 1
    assert model.calls[0][0] == []
    assert model.calls[0][1] == message
    return reply, model


def search_intent(**parameters):
    return {'schema_version': '2', 'disposition': 'execute', 'tasks': [
        {'id': 't1', 'intent': 'catalog_lookup', 'parameters': parameters}]}


def test_search_intent_routes_with_exact_validated_arguments(catalog, searches):
    """AGT-01: model extraction reaches real search with exact Decimal filters."""
    reply, model = invoke(catalog, search_intent(
        name='Aurora', category='Test Guitars', category_id=1,
        max_price='1000.00', specs={'strings': 'nylon'}),
        'Show Aurora nylon guitars at or below 1000.00.')
    assert len(searches) == 1
    arguments, results = searches[0]
    assert arguments == {
        'name': 'Aurora', 'category': 'Test Guitars', 'category_id': 1,
        'max_price': Decimal('1000.00'), 'specs': {'strings': 'nylon'},
        'purchasable_only': True,
    }
    assert type(arguments['max_price']) is Decimal
    assert [product.product_id for product in results] == [101]
    assert reply.status == 'ok'
    assert reply.products == [serialize_product(results[0])]
    schema = model.calls[0][2]
    assert schema['type'] == 'object'
    assert schema['additionalProperties'] is False
    assert set(schema['required']) == {'schema_version', 'disposition', 'tasks'}
    assert schema['properties']['schema_version']['const'] == '2'
    assert set(schema['properties']['tasks']['items']['properties']['intent']['enum']) == {
        'catalog_lookup', 'policy_question', 'order_status',
    }


def test_catalog_facts_preserve_identity_price_and_availability(catalog, searches):
    """AGT-02: renderer uses actual catalog facts, including unavailable listings."""
    reply, _ = invoke(catalog, search_intent(category_id=1, purchasable_only=False))
    assert len(searches) == 1
    assert searches[0][0]['purchasable_only'] is False
    assert reply.status == 'ok'
    assert reply.products == [serialize_product(p) for p in catalog.products if p.category_id == 1]
    assert [(p['product_id'], p['name'], p['price_brl'], p['is_purchasable'])
            for p in reply.products] == [
        (101, 'Aurora Nylon', '1000.00', True),
        (102, 'Aurora Steel', '999.99', True),
        (103, 'Aurora Premium', '1000.01', True),
        (104, 'Aurora Empty', '900.00', False),
        (105, 'Aurora Future', '950.00', False),
        (106, 'Aurora Retired', '975.00', False),
        (108, 'Eclipse Nylon', '850.00', True),
    ]
    assert 'snapshot' in reply.text.casefold()
    for product in reply.products:
        assert product['name'] in reply.text
        assert product['price_brl'] in reply.text


@pytest.mark.parametrize('field,value', [
    ('response', 'FABRICATED_PRODUCT_999 costs 0.01 and is available'),
    ('results', [{'product_id': 999, 'price_brl': '0.01', 'is_purchasable': True}]),
], ids=['fabricated-prose', 'forged-results'])
def test_fabricated_model_facts_cannot_reach_customer(catalog, searches, field, value):
    """AGT-02/05: extra model facts invalidate extraction before any search."""
    extraction = search_intent(category_id=1)
    extraction[field] = value
    reply, _ = invoke(catalog, extraction)
    assert reply.status == 'invalid_request'
    assert reply.products == []
    assert searches == []
    assert 'FABRICATED_PRODUCT_999' not in reply.text
    assert '0.01' not in reply.text
    assert '999' not in reply.text


def test_empty_search_is_truthful_and_snapshot_scoped(catalog, searches):
    """AGT-03: actual empty result is not a store-wide inventory assertion."""
    reply, _ = invoke(catalog, search_intent(category_id=3))
    assert len(searches) == 1
    assert searches[0][1] == ()
    assert reply.status == 'no_matches'
    assert reply.products == []
    assert reply.text == 'No matching listings were found in this catalog snapshot.'


@pytest.mark.parametrize('parameters', [
    {'max_price': 1000.0}, {'max_price': 1000}, {'max_price': '-1'},
    {'max_price': 'NaN'}, {'max_price': 'Infinity'}, {'max_price': '1e3'},
    {'max_price': '1.001'}, {'category_id': True}, {'category_id': '1'},
    {'purchasable_only': 'false'}, {'purchasable_only': None}, {'name': ''},
    {'specs': []}, {'specs': {'strings': 6}}, {'stock_quantity': 3},
    {'specs': {'strings': 'nylon', ' STRÍNGS ': 'steel'}},
], ids=['float-money', 'integer-money', 'negative-money', 'nan-money',
        'infinite-money', 'exponent-money', 'subcent-money', 'boolean-id',
        'string-id', 'string-boolean', 'null-boolean', 'blank-name',
        'list-specs', 'numeric-spec', 'unknown-parameter', 'duplicate-normalized-spec'])
def test_invalid_arguments_never_execute_search(catalog, searches, parameters):
    """AGT-05: strict application validation runs before real catalog search."""
    reply, _ = invoke(catalog, search_intent(**parameters))
    assert reply.status == 'invalid_request'
    assert reply.products == []
    assert isinstance(reply.text, str) and reply.text
    assert searches == []


@pytest.mark.parametrize('extraction', [
    {'schema_version': '2', 'disposition': 'execute', 'tasks': [{'id': 't1', 'intent': 'execute_shell', 'parameters': {}}]},
    {'schema_version': '2', 'disposition': 'execute', 'tasks': [{'id': 't1', 'intent': 'catalog_lookup', 'parameters': []}]},
    {'schema_version': '2', 'disposition': 'execute', 'tasks': [{'id': 't1', 'intent': 'catalog_lookup'}]},
    [{'schema_version': '2', 'disposition': 'execute', 'tasks': []}],
], ids=['unknown-intent', 'invalid-parameters', 'missing-parameters', 'multiple-intents'])
def test_malformed_intents_never_execute_search(catalog, searches, extraction):
    """AGT-01/05: no unknown intent or malformed structure can force a search."""
    reply, _ = invoke(catalog, extraction)
    assert reply.status == 'invalid_request'
    assert reply.products == []
    assert searches == []


@pytest.mark.parametrize('intent,message,text', [
    ('clarification', 'That one, please.',
     'Please clarify the product or search criteria you want.'),
    ('unsupported', 'What is your returns policy?',
     'Supported requests include catalog products, configured policy evidence, '
     'and safe order-support guidance. Private order details require trusted authorization.'),
])
def test_fallback_intents_never_execute_search(catalog, searches, intent, message, text):
    """AGT-01/05: application renders explicit fallbacks without catalog access."""
    reply, _ = invoke(catalog, {'schema_version': '2', 'disposition': intent, 'tasks': []}, message)
    assert reply.status == intent
    assert reply.products == []
    assert reply.text == text
    assert searches == []
