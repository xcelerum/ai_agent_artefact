"""Bounded policy continuity: real graph/services, mocked extraction only."""

import json
import pytest

from app.agent.catalog_agent import build_agent
from app.agent.conversation import Conversation
from app.agent.groq_model import GroqIntentModel
from app.agent.plans import plan_schema
from test_conversation import policy
from test_groq_model import client_response, generation_task
from test_store_policy import policy_pdf
from test_semantic_conversation import SemanticModel, request, semantic_task
from test_multi_intent import plan
from test_agent import catalog, searches


@pytest.mark.parametrize('category_id,message,expected', [
    (1, 'Quero conhecer violões de nylon e cancelar meu pedido.', 'Aurora Nylon'),
    (2, 'Estou procurando um teclado musical e também quero cancelar uma compra.', 'Aurora Keys'),
    (3, 'Quais acessórios vocês têm? Também gostaria de cancelar meu pedido.', 'Não encontrei'),
    (2, 'Cancele meu pedido e mostre teclados.', 'Aurora Keys'),
])
def test_mixed_cancellation_preserves_any_catalog_category_without_generic_error(
        catalog, policy, searches, category_id, message, expected):
    model = SemanticModel(plan(
        semantic_task('c', category_id=category_id),
        semantic_task('p', 'policy_question', topic='withdrawal', req=request(goal='guide'))))
    agent = build_agent(catalog=catalog, model=model, policy_service=policy)
    chat = Conversation(agent)
    text = chat.respond(message)
    assert expected in text
    assert text.count('Não posso executar cancelamentos') == 1 and 'atendimento' in text
    assert '7 dias' not in text and 'recebeu' not in text
    assert 'Não consegui confirmar essa informação' not in text
    assert len(searches) == 1 and searches[0][0]['category_id'] == category_id
    # Unsupported action remains a task outcome, not a missing-source failure.
    reply = agent.invoke(session_id='synthetic', message=message, semantic_mode=True)
    rejected = reply.task_outcomes[1]
    assert rejected.status == 'unsupported' and rejected.error_category == 'unsupported_action'
    assert not rejected.source_references and 'text' not in rejected.facts


@pytest.mark.parametrize('unshipped', [False, True])
@pytest.mark.parametrize('mixed', [False, True])
def test_requested_cancellation_is_acknowledged_despite_wrong_withdrawal_plan(
        catalog, policy, searches, monkeypatch, unshipped, mixed):
    from app.data.store_policy import LocalPolicyService
    calls = []
    original = LocalPolicyService.retrieve
    def retrieve(self, **kwargs):
        calls.append(kwargs['topic'])
        return original(self, **kwargs)
    monkeypatch.setattr(LocalPolicyService, 'retrieve', retrieve)
    tasks = [semantic_task('p', 'policy_question', topic='withdrawal', req=request(goal='guide'))]
    if mixed:
        tasks += [semantic_task('c', name='Aurora Nylon'),
                  semantic_task('pay', 'policy_question', topic='payments', req=request(goal='guide'))]
    chat = Conversation(build_agent(catalog=catalog, policy_service=policy,
                                   model=SemanticModel(plan(*tasks))))
    message = 'Quero cancelar um pedido' + (' que ainda não foi enviado.' if unshipped else '.')
    if mixed:
        message += ' Quanto custa Aurora Nylon e quais formas de pagamento existem?'
    text = chat.respond(message)
    assert 'Não posso executar cancelamentos' in text and 'atendimento' in text
    assert 'Não consegui confirmar essa informação' not in text
    assert '7 dias' not in text and 'recebeu' not in text
    assert calls == (['payments'] if mixed else [])
    assert len(searches) == int(mixed)
    if mixed:
        assert 'Aurora Nylon' in text and 'R$ 1.000,00' in text and 'PIX' in text


def test_negated_cancellation_does_not_block_general_withdrawal(catalog, policy):
    model = SemanticModel(plan(semantic_task('p', 'policy_question', topic='withdrawal', req=request(goal='guide'))))
    chat = Conversation(build_agent(catalog=catalog, model=model, policy_service=policy))
    text = chat.respond('Não quero cancelar um pedido. Quero conhecer a política de arrependimento online.')
    assert '7 dias' in text and 'Não posso executar cancelamentos' not in text


@pytest.mark.parametrize('topic', ['withdrawal', 'returns'])
@pytest.mark.parametrize('with_catalog', [False, True])
def test_unshipped_fact_blocks_adversarial_post_receipt_plan(
        catalog, policy, searches, monkeypatch, topic, with_catalog):
    from app.data.store_policy import LocalPolicyService
    calls = []
    original = LocalPolicyService.retrieve
    def retrieve(self, **kwargs):
        calls.append(kwargs['topic'])
        return original(self, **kwargs)
    monkeypatch.setattr(LocalPolicyService, 'retrieve', retrieve)
    tasks = [semantic_task('p', 'policy_question', topic=topic,
                           req=request(goal='guide', situation='individual'))]
    if with_catalog:
        tasks.append(semantic_task('c', name='Aurora Nylon'))
    model = SemanticModel(plan(*tasks))
    chat = Conversation(build_agent(catalog=catalog, model=model, policy_service=policy))
    message = 'Quero cancelar um pedido que ainda não foi enviado.'
    if with_catalog:
        message += ' Também quero saber o preço do Aurora Nylon.'
    text = chat.respond(message)
    assert 'atendimento' in text
    assert '7 dias' not in text and 'recebeu' not in text and 'reembolso aprovado' not in text
    assert calls == []  # No retrieval or post-receipt assessment was dispatched.
    assert len(searches) == int(with_catalog)
    if with_catalog:
        assert 'Aurora Nylon' in text and 'R$ 1.000,00' in text


def test_received_order_still_gets_legitimate_withdrawal_guidance(catalog, policy):
    model = SemanticModel(plan(semantic_task('p', 'policy_question', topic='withdrawal',
        req=request(goal='guide', situation='individual'),
        context={'purchase_channel': 'online', 'days_since_receipt': 1})))
    chat = Conversation(build_agent(catalog=catalog, model=model, policy_service=policy))
    text = chat.respond('Recebi ontem minha compra online e quero devolver por arrependimento.')
    assert '7 dias' in text and 'p. 4' in text


def test_followup_preserves_semantic_topic_and_new_customer_facts(catalog, policy):
    model = SemanticModel(plan(semantic_task('p', 'policy_question',
        req=request(goal='guide', situation='individual'), topic='withdrawal',
        context={'purchase_channel': 'online', 'reason': 'withdrawal'})))
    chat = Conversation(build_agent(catalog=catalog, model=model, policy_service=policy))
    chat.respond('Comprei um violão pela internet, mas mudei de ideia. Posso mandar de volta?')
    model.extraction = plan(semantic_task('p', 'policy_question',
        req=request(goal='guide', situation='individual'), topic='withdrawal',
        context={'days_since_receipt': 1}))
    text = chat.respond('Recebi o instrumento ontem e acho que não quero mais ficar com ele. Como funciona?')
    assert '7 dias' in text and 'p. 4' in text
    assert 'Há quantos dias' not in text and 'internet ou na loja' in text
    assert model.calls[-1][0][0]['policy_topic'] == 'withdrawal'
    assert chat.policy_facts['days_since_receipt']['value'] == 1
    assert 'purchase_channel' not in chat.policy_facts


def test_transaction_claims_do_not_survive_a_turn_but_references_do(catalog, policy, monkeypatch):
    from app.data.store_policy import LocalPolicyService
    contexts = []
    original = LocalPolicyService.retrieve
    def retrieve(self, **kwargs):
        contexts.append(dict(kwargs.get('context') or {}))
        return original(self, **kwargs)
    monkeypatch.setattr(LocalPolicyService, 'retrieve', retrieve)
    model = SemanticModel(plan(semantic_task('p', 'policy_question', topic='withdrawal',
                                            req=request(goal='guide', situation='individual'))))
    chat = Conversation(build_agent(catalog=catalog, model=model, policy_service=policy))
    chat._candidates = (101, 107)  # Validated synthetic catalog IDs, unrelated product memory.
    chat.respond('Comprei pela internet e recebi há cinco dias.')
    assert contexts[-1]['purchase_channel'] == 'online'
    assert contexts[-1]['days_since_receipt'] == 5
    chat.respond('Agora quero falar sobre o pedido do meu pai, que ainda não foi enviado.')
    assert chat.policy_facts == {}
    assert chat.candidate_product_ids == (101, 107)
    text = chat.respond('Como funciona o arrependimento no meu caso?')
    assert contexts[-1] == {}
    assert 'internet ou na loja' in text
    assert model.calls[-1][0][0]['policy_topic'] == 'withdrawal'
    chat.reset()
    assert chat.policy_facts == {} and chat.candidate_product_ids == ()


def test_new_policy_topic_overrides_previous_and_reset_clears_context(catalog, policy):
    model = SemanticModel(plan(semantic_task('p', 'policy_question',
        req=request(goal='guide'), topic='withdrawal')))
    chat = Conversation(build_agent(catalog=catalog, model=model, policy_service=policy))
    chat.respond('Quais as condições de arrependimento?')
    model.extraction = plan(semantic_task('p', 'policy_question',
        req=request(goal='guide'), topic='payments'))
    text = chat.respond('Agora quero saber como posso pagar.')
    assert 'PIX' in text and '7 dias' not in text
    chat.respond('Como funciona o pagamento?')
    assert model.calls[-1][0][0]['policy_topic'] == 'payments'
    chat.reset()  # The terminal's /novo command calls this existing method.
    model.extraction = {'schema_version': '2', 'disposition': 'clarification', 'tasks': []}
    text = chat.respond('Como funciona isso?')
    assert all('policy_topic' not in item for item in model.calls[-1][0])
    assert chat.policy_facts == {} and '7 dias' not in text


def test_unknown_topic_remains_ambiguous_but_specific_topic_is_authoritative(policy):
    assert policy.retrieve(topic='situation', query='Como funciona isso?').retrieval_status == 'clarification_required'
    evidence = policy.retrieve(topic='withdrawal', query='Como funciona isso?')
    assert evidence.text and any(':section/4.1:' in ref for ref in evidence.source_references)


def test_unshipped_cancellation_uses_existing_safe_handoff(catalog, policy, searches):
    client = client_response({'schema_version': '2', 'tasks': [],
                              'response_hint': 'unsupported_action'})
    chat = Conversation(build_agent(catalog=catalog,
        model=GroqIntentModel(client=client, semantic_mode=True), policy_service=policy))
    text = chat.respond('Quero cancelar um pedido que ainda não foi enviado.')
    assert 'Não posso executar cancelamentos' in text
    assert 'atendimento' in text and 'recebeu' not in text and '7 dias' not in text
    assert searches == []
    prompt = client.chat.completions.create.call_args.kwargs['messages'][0]['content']
    assert 'Before-shipment cancellation' in prompt
    assert 'not post-receipt withdrawal' in prompt


def test_groq_receives_only_allowlisted_policy_topic(catalog, policy):
    raw = generation_task('p', 'policy_question', topic='withdrawal')
    raw['request'] = request(goal='guide')
    client = client_response({'schema_version': '2', 'tasks': [raw], 'response_hint': None})
    chat = Conversation(build_agent(catalog=catalog,
        model=GroqIntentModel(client=client, semantic_mode=True), policy_service=policy))
    chat.respond('Quais as condições de arrependimento?')
    chat.respond('Como funciona?')
    sent = client.chat.completions.create.call_args.kwargs
    prompt = sent['messages'][0]['content']
    assert 'Previous validated policy topic: withdrawal' in prompt
    assert 'Quais as condições' not in json.dumps(sent)
    assert '7 dias' not in json.dumps(sent) and 'store-policy:' not in json.dumps(sent)
    model = GroqIntentModel(client=client, semantic_mode=True)
    model.extract(history=[{'policy_topic': 'PRIVATE_UNTRUSTED_TOPIC'}],
                  message='Como funciona?', schema=plan_schema())
    assert 'PRIVATE_UNTRUSTED_TOPIC' not in json.dumps(client.chat.completions.create.call_args.kwargs)
