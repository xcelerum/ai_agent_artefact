"""Natural-language category filters through the real adapter and compiled graph."""

import csv
from dataclasses import replace
from decimal import Decimal

import pytest

from app.agent.catalog_agent import build_agent
from app.agent.groq_model import GroqIntentModel
from app.data.catalog import CATEGORY_FIELDS, PRODUCT_FIELDS, load_catalog
from test_agent import searches
from test_groq_model import client_response, generation_task, payload


@pytest.fixture
def category_catalog(tmp_path):
    categories, products = tmp_path / 'categories.csv', tmp_path / 'products.csv'
    with categories.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(CATEGORY_FIELDS)
        writer.writerows([(5, 'Violões', ''), (6, 'Synthetic Keys', '')])
    with products.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(PRODUCT_FIELDS)
        writer.writerows([
            (101, '1000.00', 'Aurora Nylon', 5, '', 3, 'active', '{"strings":"nylon"}', '2026-01-02'),
            (102, '999.99', 'Aurora Steel', 5, '', 2, 'active', '{"strings":"steel"}', '2026-01-02'),
            (103, '1000.01', 'Aurora Premium', 5, '', 3, 'active', '{}', '2026-01-02'),
            (104, '800.00', 'Aurora Empty', 5, '', 0, 'active', '{}', '2026-01-02'),
            (105, '900.00', 'Aurora Future', 5, '', 4, 'coming_soon', '{}', '2026-01-02'),
            (106, '777.00', 'Aurora Keys', 6, '', 2, 'active', '{}', '2026-01-02'),
        ])
    return load_catalog(products, categories)


def ask(catalog, parameters, question='Synthetic category request'):
    client = client_response(payload(generation_task(**parameters)))
    reply = build_agent(catalog=catalog, model=GroqIntentModel(client=client)).invoke(
        session_id='synthetic', message=question)
    return reply


@pytest.mark.parametrize('question,parameters,identifiers', [
    ('Olá! Vocês têm algum violão de até mil reais?',
     {'category': 'violão', 'max_price': '1000.00'}, [101, 102]),
    ('Vocês têm algum violão disponível, independentemente do preço?',
     {'name': 'violão', 'category': 'violão'}, [101, 102, 103]),
    ('Mostre produtos da categoria Violões, disponíveis por até R$ 1.000.',
     {'category': 'Violões', 'max_price': '1000.00'}, [101, 102]),
    ('Synthetic name-only singular', {'name': 'violão'}, [101, 102, 103]),
    ('Synthetic name-only plural', {'name': 'violões'}, [101, 102, 103]),
])
def test_natural_category_queries_resolve_to_catalog(category_catalog, searches, question, parameters, identifiers):
    reply = ask(category_catalog, parameters, question)
    assert reply.status == 'ok'
    assert [product['product_id'] for product in reply.products] == identifiers
    assert all(p['category_id'] == 5 and p['is_purchasable'] for p in reply.products)
    arguments = searches[0][0]
    assert arguments['name'] is None and arguments['category'] == 'Violões'
    assert arguments['purchasable_only'] is True
    if 'max_price' in parameters:
        assert arguments['max_price'] == Decimal('1000.00')
        assert arguments['max_price'].as_tuple().exponent == -2
    assert len(searches) == 1


@pytest.mark.parametrize('name', ['Aurora', 'Aurora Nylon', 'Violão Aurora Nylon', 'unknown brand'])
def test_named_product_and_brand_filters_are_preserved(category_catalog, searches, name):
    reply = ask(category_catalog, {'name': name})
    assert searches[0][0]['name'] == name
    assert searches[0][0]['category'] is None
    expected = category_catalog.search(name=name)
    assert [p['product_id'] for p in reply.products] == [p.product_id for p in expected]


def test_category_alias_preserves_specific_name_specs_price_and_availability(category_catalog, searches):
    reply = ask(category_catalog, {'category': 'violão', 'name': 'Aurora Nylon',
                                   'specs': [{'key': 'strings', 'value': 'nylon'}],
                                   'max_price': '1000.00', 'purchasable_only': False})
    assert [p['product_id'] for p in reply.products] == [101]
    assert searches[0][0] == dict(name='Aurora Nylon', category='Violões', category_id=None,
                                  max_price=Decimal('1000.00'), specs={'strings': 'nylon'},
                                  purchasable_only=False)


def test_exact_product_name_wins_over_generic_name_interpretation(category_catalog, searches):
    exact = replace(category_catalog.products[0], product_id=200, name='Violão')
    catalog = replace(category_catalog, products=(*category_catalog.products, exact))
    reply = ask(catalog, {'name': 'violão'})
    assert [p['product_id'] for p in reply.products] == [200]
    assert searches[0][0]['name'] == 'violão' and searches[0][0]['category'] is None


@pytest.mark.parametrize('condition', ['absent', 'ambiguous', 'conflicting_category', 'conflicting_id'])
def test_resolution_does_not_guess_or_override_other_filters(category_catalog, searches, condition):
    catalog = category_catalog
    parameters = {'name': 'violão'}
    if condition == 'absent':
        catalog = replace(catalog, categories=(replace(catalog.categories[0], name='Synthetic Strings'),
                                                catalog.categories[1]))
    if condition == 'ambiguous':
        catalog = replace(catalog, categories=(*catalog.categories, replace(catalog.categories[0], category_id=7)))
    if condition == 'conflicting_category': parameters['category'] = 'Synthetic Keys'
    if condition == 'conflicting_id': parameters['category_id'] = 6
    reply = ask(catalog, parameters)
    assert reply.status == 'no_matches'
    assert searches[0][0]['name'] == 'violão'
    assert searches[0][0]['category_id'] == parameters.get('category_id')


def test_alias_equivalent_operations_rejected_before_dispatch(category_catalog, searches):
    client = client_response(payload(generation_task('one', category='violão'),
                                     generation_task('two', category='Violões')))
    reply = build_agent(catalog=category_catalog, model=GroqIntentModel(client=client)).invoke(
        session_id='synthetic', message='Synthetic duplicate operations')
    assert reply.status == 'invalid_request' and searches == []
