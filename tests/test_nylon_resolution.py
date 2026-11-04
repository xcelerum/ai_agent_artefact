"""Confirmed nylon extraction regression; synthetic sources, real compiled graph."""

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
def nylon_catalog(tmp_path):
    categories, products = tmp_path / 'categories.csv', tmp_path / 'products.csv'
    with categories.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream); writer.writerow(CATEGORY_FIELDS)
        writer.writerow((5, 'Violões', ''))
    with products.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream); writer.writerow(PRODUCT_FIELDS)
        writer.writerows([
            (1, '599.90', 'Luar Nylon', 5, '', 2, 'active', '{"strings":"nylon"}', '2026-01-02'),
            (2, '429.90', 'Estrela Nylon', 5, '', 2, 'active', '{"strings":"nylon"}', '2026-01-02'),
            (3, '400.00', 'Luar Steel', 5, '', 2, 'active', '{"strings":"steel"}', '2026-01-02'),
            (4, '600.01', 'Luar Premium', 5, '', 2, 'active', '{"strings":"nylon"}', '2026-01-02'),
            (5, '300.00', 'Luar Empty', 5, '', 0, 'active', '{"strings":"nylon"}', '2026-01-02'),
            (6, '350.00', 'Luar Future', 5, '', 2, 'coming_soon', '{"strings":"nylon"}', '2026-01-02'),
        ])
    return load_catalog(products, categories)


def ask(catalog, parameters, question='Queria um violão de nylon que custasse no máximo 600 reais.'):
    client = client_response(payload(generation_task(**parameters)))
    return build_agent(catalog=catalog, model=GroqIntentModel(client=client)).invoke(
        session_id='synthetic', message=question)


@pytest.mark.parametrize('parameters', [
    {'name': 'violão de nylon', 'category': 'violão de nylon', 'specs': [{'key': 'material', 'value': 'nylon'}]},
    {'name': 'violão de nylon', 'category': 'violão de nylon', 'specs': None},
    {'name': 'violão de nylon', 'category': 'violão', 'specs': [{'key': 'strings', 'value': 'nylon'}]},
    {'category': 'Violões', 'specs': [{'key': 'strings', 'value': 'nylon'}]},
])
def test_natural_and_explicit_nylon_queries_match_same_real_results(nylon_catalog, searches, parameters):
    reply = ask(nylon_catalog, {**parameters, 'max_price': '600.00'})
    assert reply.status == 'ok'
    assert [p['product_id'] for p in reply.products] == [1, 2]
    assert [p['price_brl'] for p in reply.products] == ['599.90', '429.90']
    assert len(searches) == 1
    args = searches[0][0]
    assert args['category'] == 'Violões' and args['name'] is None
    assert args['specs'] == {'strings': 'nylon'}
    assert args['max_price'] == Decimal('600.00') and args['max_price'].as_tuple().exponent == -2
    assert args['purchasable_only'] is True


def test_genuine_steel_filter_is_not_changed_to_nylon(nylon_catalog, searches):
    reply = ask(nylon_catalog, {'category': 'Violões', 'specs': [{'key': 'strings', 'value': 'steel'}],
                               'max_price': '600.00'}, 'Synthetic explicit steel request')
    assert [p['product_id'] for p in reply.products] == [3]
    assert searches[0][0]['specs'] == {'strings': 'steel'}


def test_conflicting_string_constraint_is_rejected_not_discarded(nylon_catalog, searches):
    reply = ask(nylon_catalog, {'category': 'violão de nylon',
                               'specs': [{'key': 'strings', 'value': 'steel'}]})
    assert reply.status == 'invalid_request' and searches == []


def test_specific_product_name_is_preserved(nylon_catalog, searches):
    reply = ask(nylon_catalog, {'name': 'Luar Nylon', 'category': 'violão de nylon', 'max_price': '600.00'})
    assert [p['product_id'] for p in reply.products] == [1]
    assert searches[0][0]['name'] == 'Luar Nylon'


def test_literal_compound_product_name_is_not_reinterpreted(nylon_catalog, searches):
    product = replace(nylon_catalog.products[0], name='Violão de nylon')
    catalog = replace(nylon_catalog, products=(product, *nylon_catalog.products[1:]))
    reply = ask(catalog, {'name': 'violão de nylon', 'max_price': '600.00'})
    assert [p['product_id'] for p in reply.products] == [1]
    assert searches[0][0]['name'] == 'violão de nylon' and searches[0][0]['specs'] is None


def test_unknown_spec_alias_is_still_rejected(nylon_catalog, searches):
    reply = ask(nylon_catalog, {'category': 'violão de nylon', 'specs': [{'key': 'arbitrary_key', 'value': 'nylon'}]})
    assert reply.status == 'invalid_request' and searches == []


def test_no_string_evidence_cannot_become_a_broad_search(nylon_catalog, searches):
    catalog = replace(nylon_catalog, products=tuple(replace(p, specs={}) for p in nylon_catalog.products))
    reply = ask(catalog, {'category': 'violão de nylon', 'max_price': '600.00'})
    assert reply.products == [] and searches == [] and reply.status == 'invalid_request'
