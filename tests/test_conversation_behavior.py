"""Observed three-turn comparison and two-turn policy regressions."""

import csv
from dataclasses import replace
from decimal import Decimal

import pytest

from app.agent.catalog_agent import build_agent
from app.agent.conversation import Conversation
from app.data.catalog import CATEGORY_FIELDS, PRODUCT_FIELDS, load_catalog
from app.data.store_policy import LocalPolicyService
from test_agent import catalog
from test_conversation import conversation, policy
from test_multi_intent import plan, task
from test_store_policy import policy_pdf


@pytest.fixture
def five_catalog(tmp_path):
    categories, products = tmp_path / 'categories.csv', tmp_path / 'products.csv'
    with categories.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream); writer.writerow(CATEGORY_FIELDS); writer.writerow([5, 'Violões', ''])
    with products.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream); writer.writerow(PRODUCT_FIELDS)
        for i, price in enumerate(('500.00', '600.00', '550.00', '800.00', '700.00')):
            writer.writerow([201+i, price, f'Estudo {chr(65+i)}', 5, '', 3, 'active',
                             '{"strings":"nylon"}', '2026-01-02'])
    return load_catalog(products, categories)


def test_three_turn_comparison_keeps_five_candidates_and_no_model_facts(five_catalog):
    chat, model = conversation(five_catalog, plan(task()))
    chat.respond('Estou procurando um violão de nylon para começar.')
    initial = tuple(p.product_id for p in five_catalog.products)
    model.extraction = plan(task(payment_method='pix'))
    selected = chat.respond('E o segundo, quanto fica no PIX?')
    assert 'Estudo B' in selected and 'R$ 570,00' in selected
    model.extraction = plan(disposition='clarification')
    compared = chat.respond('Entre esses cinco violões, qual você recomendaria para alguém que está começando? Por quê?')
    assert all(p.name in compared for p in five_catalog.products)
    assert chat.candidate_product_ids == initial and chat.product_ids == (202,)
    assert 'R$ 500,00' in compared and 'nylon' in compared
    assert 'orçamento' in compared.lower() and compared.count('?') == 1
    assert 'não comprova' in compared.lower()
    assert len(model.calls) == 2  # Known candidate comparison is local; no source facts sent to a model.


def test_comparison_reloads_prices_and_reset_clears_candidates(five_catalog):
    chat, _ = conversation(five_catalog, plan(task()))
    chat.respond('Mostre cinco opções.')
    updated = replace(five_catalog, products=(replace(five_catalog.products[0], price_brl=Decimal('900.00')),
                                             *five_catalog.products[1:]))
    chat.agent = replace(chat.agent, catalog=updated)
    text = chat.respond('Compare esses cinco para um iniciante.')
    assert 'R$ 900,00' in text and 'R$ 500,00' not in text
    assert 'menor preço' in text and 'Estudo C' in text
    chat.reset()
    assert chat.candidate_product_ids == () and chat.product_ids == ()


def test_new_search_replaces_candidates(five_catalog):
    chat, model = conversation(five_catalog, plan(task()))
    chat.respond('Mostre as opções.')
    model.extraction = plan(task(name='Estudo C'))
    chat.respond('Quero ver Estudo C.')
    assert chat.candidate_product_ids == (203,)


def test_two_turn_policy_reuses_online_claim_and_distinguishes_hypothetical(catalog, policy):
    chat, model = conversation(catalog, plan(task(intent='policy_question', topic='withdrawal')), policy)
    first = chat.respond('Comprei pela internet e quero voltar atrás. Como faço?')
    assert '7 dias' in first
    assert 'internet ou na loja' not in first
    assert first.count('?') <= 1
    assert chat.policy_facts['purchase_channel'] == {'value': 'online', 'provenance': 'customer_statement'}
    model.extraction = plan(task(intent='policy_question', topic='withdrawal'))
    second = chat.respond('Me arrependi da compra online; e se o produto vier com defeito?')
    assert 'Se o produto vier com defeito' in second
    assert 'Arrependimento' in second
    assert 'internet ou na loja' not in second and second.count('?') <= 1
    assert chat.policy_facts['reason']['value'] == 'withdrawal'
    assert 'Você relatou um defeito' not in second
    assert 'seção 4.1' in second and 'seção 4.2' in second and 'p. 4' in second


def test_actual_defect_is_a_customer_claim_not_a_hypothetical(catalog, policy):
    chat, _ = conversation(catalog, plan(task(intent='policy_question', topic='defect')), policy)
    text = chat.respond('Comprei online e o produto veio com defeito.')
    assert 'Você relatou um defeito' in text
    assert chat.policy_facts['reason'] == {'value': 'defect', 'provenance': 'customer_statement'}
    assert 'Se o produto vier com defeito' not in text
    chat.reset()
    assert chat.policy_facts == {}


def test_policy_sentences_join_pdf_lines_without_truncation(catalog, policy_pdf):
    sentence = 'Compras online permitem solicitar devolucao em 7 dias do recebimento, ' + 'conforme as condicoes descritas no manual e sujeitas a verificacao ' * 4 + 'pela equipe.'
    cut = sentence.rfind(' ', 0, 100)
    service = LocalPolicyService.from_pdf(policy_pdf([
        ['4. Returns', '4.1 Withdrawal', sentence[:cut], sentence[cut+1:],
         '4.4 Exceptions', 'As excecoes precisam de analise.', 'Page 4']]))
    chat, _ = conversation(catalog, plan(task(intent='policy_question', topic='withdrawal')), service)
    text = chat.respond('Qual é a política de arrependimento?')
    assert '…' not in text and '...' not in text
    assert sentence in text
    assert text.count('?') == 0


def test_transaction_claims_require_current_turn_information(catalog, policy):
    chat, model = conversation(catalog, plan(task(intent='policy_question', topic='withdrawal')), policy)
    first = chat.respond('Comprei pela internet e recebi há 3 dias. Quero voltar atrás.')
    assert 'Há quantos dias' not in first
    model.extraction = plan(task(intent='policy_question', topic='withdrawal'))
    second = chat.respond('E no meu caso, posso devolver?')
    assert 'internet ou na loja' in second
    assert chat.policy_facts == {}
    assert second.count('?') <= 1


def test_additional_explicit_conditions_are_customer_claims(catalog, policy):
    chat, _ = conversation(catalog, plan(task(intent='policy_question', topic='withdrawal')), policy)
    chat.respond('Comprei online, não usei o produto e tenho a embalagem original. Tenho o comprovante.')
    for key in ('unused', 'original_packaging', 'proof_of_purchase'):
        assert chat.policy_facts[key] == {'value': True, 'provenance': 'customer_statement'}


def test_exact_aqueles_recommendation_uses_retained_candidates(five_catalog, monkeypatch):
    import json
    from app.agent.portuguese import MESSAGES
    chat, model = conversation(five_catalog, plan(task()))
    routes = []
    original = type(chat.agent).invoke
    def invoke(self, **kwargs):
        routes.append({'comparison': kwargs.get('compare_products', False),
                       'scope_count': len(kwargs.get('selected_product_ids', ()))})
        return original(self, **kwargs)
    monkeypatch.setattr(type(chat.agent), 'invoke', invoke)
    chat.respond('Oi! Estou procurando um violão de nylon para começar.')
    candidates = chat.candidate_product_ids
    model.extraction = plan(task(payment_method='pix'))
    chat.respond('E o segundo, quanto fica no PIX?')
    # Reproduce the observed unsupported extraction when the comparison route is missed.
    model.extraction = plan(disposition='unsupported')
    text = chat.respond('Entre aqueles cinco modelos que você mostrou, qual recomenda para um iniciante? Explique as diferenças.')
    print(json.dumps({'candidate_count': len(chat.candidate_product_ids),
                      'selected_second': chat.product_ids == (202,),
                      'last_route': routes[-1], 'model_calls': len(model.calls),
                      'unsupported_fallback': text == MESSAGES['unsupported']}))
    assert all(product.name in text for product in five_catalog.products)
    assert chat.candidate_product_ids == candidates and chat.product_ids == (202,)
    assert routes[-1] == {'comparison': True, 'scope_count': 5}
    assert len(model.calls) == 2 and text.count('?') == 1
    assert 'nylon' in text and 'não comprova' in text and 'orçamento' in text


@pytest.mark.parametrize('message', ['Cancele meu pedido.', 'Cancela meu pedido.',
                                    'Reembolse o pagamento.', 'Estorne meu pagamento.',
                                    'Entre aqueles cinco modelos, recomende um e faça o reembolso agora.'])
def test_transaction_denial_wins_over_recommendation(five_catalog, message):
    chat, model = conversation(five_catalog, plan(task()))
    chat.respond('Mostre cinco opções.')
    candidates = chat.candidate_product_ids
    calls = len(model.calls)
    text = chat.respond(message)
    assert 'Não consigo cancelar pedidos nem emitir reembolsos' in text
    assert 'Estas são as opções' not in text
    assert chat.candidate_product_ids == candidates
    assert len(model.calls) == calls
