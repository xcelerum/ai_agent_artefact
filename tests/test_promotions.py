"""Synthetic promotion/price contracts; real CSV ingestion and exact arithmetic."""

import csv
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from app.data.promotions import load_promotions, PromotionDataError
from app.domain.pricing import PricingService, PixRules
from test_agent import catalog


FIELDS = ['promotion_id', 'product_id', 'discount_percent', 'description', 'is_active']


@pytest.fixture
def promotions_file(tmp_path):
    def write(rows, fields=FIELDS):
        path = tmp_path / 'synthetic-promotions.csv'
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(fields)
            writer.writerows(rows)
        return path
    return write


def test_inactive_history_and_active_offer(catalog, promotions_file):
    book = load_promotions(promotions_file([
        [1, 101, '30', 'Invented expired-sounding campaign', '0'],
        [2, 101, '20', 'Invented future-sounding campaign', '0'],
        [3, 102, '12.5', 'Synthetic active offer', '1'],
    ]), catalog)
    pricing = PricingService(book)
    inactive = pricing.quote(catalog.products[0])
    assert inactive['table_price'] == inactive['effective_price'] == '1000.00'
    assert inactive['promotional_price'] is None and inactive['discount_percent'] is None
    active = pricing.quote(catalog.products[1])
    assert active['table_price'] == '999.99'
    assert active['promotional_price'] == active['effective_price'] == '874.99'
    assert active['discount_percent'] == '12.5' and active['promotion_id'] == 3
    assert not {'starts_at', 'ends_at', 'valid_until'} & active.keys()


@pytest.mark.parametrize('rows', [
    [[1, 101, '10', '', '1'], [2, 101, '20', '', '1']],
    [[1, 101, '10', '', '1'], [2, 101, '10', '', '1']],
    [[1, 999, '10', '', '1']],
    [[1, 101, '10', '', '0'], [1, 102, '20', '', '1']],
    [['001', 101, '10', '', '0'], [1, 102, '20', '', '1']],
    [[0, 101, '10', '', '1']], [['True', 101, '10', '', '1']],
    [[1, 101, '-1', '', '1']], [[1, 101, '0', '', '1']],
    [[1, 101, '100.01', '', '1']], [[1, 101, 'NaN', '', '1']],
    [[1, 101, 'Infinity', '', '1']], [[1, 101, '1e1', '', '1']],
    [[1, 101, '10%', '', '1']], [[1, 101, '10', '', 'true']],
    [[1, 101, '10', '', 'False']], [[1, 101, '10', '', '2']],
    [[1, 101, '10', '', '']],
], ids=[f'invalid-{i}' for i in range(18)])
def test_promotion_validation(catalog, promotions_file, rows):
    with pytest.raises(PromotionDataError) as caught:
        load_promotions(promotions_file(rows), catalog)
    assert 'Invented private marker' not in str(caught.value)


@pytest.mark.parametrize('raw', [
    'promotion_id,product_id,discount_percent,description,is_active\n1,"unterminated',
    'promotion_id,product_id,discount_percent,description,is_active\n1,101,10,missing',
    'promotion_id,product_id,discount_percent,description,is_active,extra\n',
    'promotion_id,product_id,discount_percent,description,is_active,is_active\n',
])
def test_malformed_promotion_sources_fail_safely(catalog, tmp_path, raw):
    path = tmp_path / 'private-path-marker.csv'
    path.write_text(raw, encoding='utf-8')
    with pytest.raises(PromotionDataError) as caught:
        load_promotions(path, catalog)
    assert str(path) not in str(caught.value)


def test_invalid_promotion_value_is_not_exposed(catalog, promotions_file):
    with pytest.raises(PromotionDataError) as caught:
        load_promotions(promotions_file([[1, 101, 'Invented private marker', '', '1']]), catalog)
    assert 'Invented private marker' not in str(caught.value)


@pytest.mark.parametrize('price,percent,expected', [('0.05', '10', '0.05'),
                                                 ('0.30', '5', '0.29'),
                                                 ('100.00', '12.5', '87.50')])
def test_exact_cent_rounding(catalog, promotions_file, price, percent, expected):
    product = replace(catalog.products[0], price_brl=Decimal(price))
    book = load_promotions(promotions_file([[1, 101, percent, '', '1']]), catalog)
    with localcontext() as context:
        context.prec = 3
        quote = PricingService(book).quote(product)
    assert quote['promotional_price'] == expected
    assert quote['table_price'] == price


def test_pix_conditions_and_no_stacking(catalog, promotions_file):
    rules = PixRules(Decimal('5'), ('synthetic-policy:PIX',))
    book = load_promotions(promotions_file([[1, 102, '10', '', '1']]), catalog)
    pricing = PricingService(book, rules)
    product, promoted = catalog.products[:2]
    absent = pricing.quote(product)
    assert absent['pix_price'] is None and absent['effective_price'] == '1000.00'
    pix = pricing.quote(product, payment_method='pix')
    assert pix['pix_price'] == pix['effective_price'] == '950.00'
    assert pix['pix_status'] == 'applied'
    stacked = pricing.quote(promoted, payment_method='pix')
    assert stacked['pix_price'] is None and stacked['pix_status'] == 'excluded_promotion'
    assert stacked['effective_price'] == '899.99'
    unverified = PricingService(book).quote(product, payment_method='pix')
    assert unverified['pix_price'] is None and unverified['pix_status'] == 'policy_unavailable'


def test_unavailable_product_and_campaign_names(catalog, promotions_file):
    book = load_promotions(promotions_file([
        [1, 104, '40', 'Campaign name cannot authorize purchase', '1'],
        [2, 101, '30', 'ACTIVE NOW is merely an inactive description', '0'],
    ]), catalog)
    pricing = PricingService(book, PixRules(Decimal('5'), ('synthetic-policy:PIX',)))
    for index in [3, 4, 5]:
        quote = pricing.quote(catalog.products[index], payment_method='pix')
        assert quote['is_purchasable'] is False
        assert quote['promotional_price'] is None and quote['pix_price'] is None
    assert pricing.quote(catalog.products[0])['promotion_applied'] is False
