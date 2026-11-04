"""Eight conversational scenarios with real graph/services and synthetic data."""

from decimal import Decimal

import pytest

from app.agent.catalog_agent import build_agent
from app.agent.contracts import AgentReply, TaskResult
from app.agent.conversation import Conversation
from app.agent.portuguese import render_portuguese
from app.data.promotions import PromotionBook
from app.data.store_policy import LocalPolicyService
from app.domain.pricing import PricingService, PixRules
from test_agent import catalog, FakeIntentModel, searches
from test_multi_intent import plan, task
from test_store_policy import policy_pdf
from test_nylon_resolution import nylon_catalog


@pytest.fixture
def policy(policy_pdf):
    return LocalPolicyService.from_pdf(policy_pdf([
        ['3. Payment methods', 'O pagamento pode ser feito por PIX.',
         '4. Returns', '4.1 Withdrawal', 'Compras online permitem solicitar devolucao em 7 dias do recebimento.',
         '4.2 Defect', 'Produtos com defeito exigem avaliacao da equipe.',
         '4.3 Preference', 'Trocas por preferencia exigem avaliacao.',
         '4.4 Exceptions', 'Itens personalizados exigem analise especifica.', 'Page 4']]))


def conversation(catalog, extraction, policy=None):
    model = FakeIntentModel(extraction)
    pricing = PricingService(PromotionBook(()), PixRules(Decimal('5'), ('synthetic://pix',)))
    agent = build_agent(catalog=catalog, model=model, policy_service=policy, pricing_service=pricing)
    return Conversation(agent), model


def test_multi_intent_portuguese_is_concise_and_grounded(catalog, policy):
    chat, _ = conversation(catalog, plan(task('c', name='Aurora Nylon'),
                                       task('p', 'policy_question', topic='returns')), policy)
    text = chat.respond('Vocês têm Aurora Nylon e posso devolver?')
    assert 'Aurora Nylon' in text and 'R$ 1.000,00' in text
    assert '7 dias' in text and 'p. 4' in text
    assert 'source_references' not in text and 'Configured policy' not in text
    assert 'clarification' not in text and 'review_required' not in text
    assert len(text) < 1500


def test_ambiguity_does_not_choose_among_multiple_products(catalog, searches):
    chat, model = conversation(catalog, plan(task(name='Aurora', category_id=1)))
    chat.respond('Mostre os Aurora disponíveis.')
    count = len(searches)
    text = chat.respond('Quanto custa esse no PIX?')
    assert 'qual' in text.lower() and len(searches) == count
    assert len(model.calls) == 1


def test_multiturn_reference_uses_validated_catalog_id_and_real_pricing(catalog, searches):
    chat, model = conversation(catalog, plan(task(name='Aurora', category_id=1)))
    chat.respond('Mostre os modelos Aurora.')
    model.extraction = plan(task(payment_method='pix'))
    text = chat.respond('Gostei do segundo. Quanto fica no PIX?')
    assert 'Aurora Steel' in text and 'R$ 949,99' in text
    assert 'Aurora Nylon' not in text and 'Aurora Premium' not in text
    assert model.calls[-1][0] == [{'selected_product_available': True}]
    assert chat.product_ids == (102,)
    assert len(searches) == 2


def test_overlapping_policies_are_not_repeated_or_approved(catalog, policy):
    chat, _ = conversation(catalog, plan(task('a', 'policy_question', topic='withdrawal'),
                                       task('b', 'policy_question', topic='defect')), policy)
    text = chat.respond('Me arrependi da compra online; e se vier com defeito?')
    assert text.count('7 dias') == 1
    assert 'defeito' in text and 'equipe' in text
    assert 'aprovado' not in text.lower()


def test_constrained_nylon_conversation_keeps_real_filters(nylon_catalog):
    chat, _ = conversation(nylon_catalog, plan(task(name='violão de nylon', category='violão de nylon',
                                                  specs={'material': 'nylon'}, max_price='600.00')))
    text = chat.respond('Queria um violão de nylon que custasse no máximo 600 reais.')
    assert 'Luar Nylon' in text and 'Estrela Nylon' in text
    assert 'Luar Steel' not in text and 'Luar Premium' not in text and 'Luar Empty' not in text
    assert 'R$ 599,90' in text and 'R$ 429,90' in text and 'estoque' in text.lower()


def test_unauthorized_order_inquiry_is_safe_portuguese_handoff(catalog):
    chat, _ = conversation(catalog, plan(task(intent='order_status', order_reference='SYNTHETIC')))
    text = chat.respond('Onde está meu pedido?')
    assert 'autenticação' in text.lower() and 'atendimento' in text.lower()
    assert 'authorization_required' not in text and 'SYNTHETIC' not in text


def test_complex_policy_paraphrase_reaches_local_evidence(catalog, policy):
    chat, _ = conversation(catalog, plan(task(intent='policy_question', topic='troca_online')), policy)
    text = chat.respond('Comprei pela internet e quero voltar atrás. Como faço?')
    assert '7 dias' in text and 'p. 4' in text
    assert 'recebeu' in text.lower() or 'recebimento' in text.lower()


def test_unsupported_cancellation_refund_action_never_dispatches(catalog, searches):
    chat, model = conversation(catalog, plan(task(intent='order_status')))
    text = chat.respond('Cancele meu pedido e faça o reembolso agora.')
    assert 'não' in text.lower() and 'reembolso' in text.lower()
    assert searches == [] and model.calls == []


@pytest.mark.parametrize('status,expected', [('clarification', 'qual'),
                                           ('policy_unavailable', 'confirmar'),
                                           ('tool_error', 'técnic')])
def test_failure_categories_are_distinct_in_portuguese(status, expected):
    text = render_portuguese(AgentReply(status, 'PRIVATE_INTERNAL_TEXT', []))
    assert expected in text.lower()
    assert 'PRIVATE_INTERNAL_TEXT' not in text and status not in text


def test_context_is_bounded_isolated_and_invalid_ids_rejected(catalog, searches):
    chat, model = conversation(catalog, plan(task(name='Aurora Nylon')))
    other, _ = conversation(catalog, plan(task(name='Aurora Steel')))
    for _ in range(8): chat.respond('Tem Aurora Nylon?')
    assert len(chat.turns) <= 6 and chat.product_ids == (101,) and other.product_ids == ()
    text = other.respond('E no PIX?')
    assert 'qual' in text.lower()
    prior = len(searches)
    reply = chat.agent.invoke(session_id='synthetic', message='E no PIX?', selected_product_ids=(999999,))
    assert reply.status == 'invalid_request' and len(searches) == prior
    chat.reset()
    assert chat.product_ids == () and chat.turns == ()


def test_groq_followup_gets_only_reference_flag_not_stored_catalog(catalog):
    import json
    from app.agent.groq_model import GroqIntentModel
    from test_groq_model import client_response, generation_task, payload
    client = client_response(payload(generation_task(name='Aurora Nylon')))
    pricing = PricingService(PromotionBook(()), PixRules(Decimal('5'), ('synthetic://pix',)))
    chat = Conversation(build_agent(catalog=catalog, model=GroqIntentModel(client=client), pricing_service=pricing))
    chat.respond('Tem Aurora Nylon?')
    client.chat.completions.create.return_value = client_response(
        payload(generation_task(payment_method='pix'))).chat.completions.create.return_value
    text = chat.respond('E no PIX?')
    request = client.chat.completions.create.call_args.kwargs
    assert 'R$ 950,00' in text
    assert 'previously selected' in request['messages'][0]['content']
    assert 'Aurora Nylon' not in json.dumps(request) and 'stock_quantity' not in json.dumps(request)
    assert request['messages'][1]['content'] == 'E no PIX?'


def test_interactive_terminal_prints_portuguese_and_supports_reset(catalog, tmp_path, monkeypatch, capsys):
    from contextlib import nullcontext
    import app.chat as command
    from test_groq_model import client_response, generation_task, payload
    client = client_response(payload(generation_task(name='Aurora Nylon')))
    monkeypatch.setattr(command, 'Groq', lambda **kwargs: nullcontext(client))
    messages = iter(['Tem Aurora Nylon?', '/novo', '/sair'])
    monkeypatch.setattr('builtins.input', lambda prompt: next(messages))
    assert command.main(['--products', str(tmp_path / 'products.csv'),
                         '--categories', str(tmp_path / 'categories.csv')]) == 0
    output = capsys.readouterr().out
    assert 'R$ 1.000,00' in output and 'nova conversa' in output and 'Até logo' in output
    assert 'Status:' not in output and 'price_brl' not in output
