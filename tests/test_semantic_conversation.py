"""Customer-visible capability evaluation; semantic plans are untrusted fixtures."""

import pytest

from app.agent.catalog_agent import build_agent
from app.agent.conversation import Conversation
from test_agent import FakeIntentModel
from test_conversation import conversation, policy
from test_conversation_behavior import five_catalog
from test_multi_intent import plan, task
from test_store_policy import policy_pdf


def request(**changes):
    return dict(goal='discover', response='answer', reference='new', positions=[],
                anchor=None, budget='keep', situation='general', **changes) if not changes else {
                    **request(), **changes}


def semantic_task(identifier='c', intent='catalog_lookup', req=None, **parameters):
    return {**task(identifier, intent, **parameters), 'request': req or request()}


class SemanticModel(FakeIntentModel):
    semantic_mode = True


def chat_with(catalog, policy=None):
    model = SemanticModel(plan(semantic_task()))
    chat = Conversation(build_agent(catalog=catalog, model=model, policy_service=policy))
    chat.respond('Mostre opções de violões para começar.')
    return chat, model


@pytest.mark.parametrize('question', [
    'Pensando em alguém que nunca tocou, qual desses você escolheria?',
    'Qual desses faz mais sentido para um iniciante?',
    'Entre aqueles cinco, o que recomenda?',
    'Se eu estiver dando meus primeiros passos, em qual opção focaria?',
])
def test_contextual_recommendations_have_same_grounded_capability(five_catalog, question):
    chat, model = chat_with(five_catalog)
    ids = chat.candidate_product_ids
    model.extraction = plan(semantic_task(req=request(goal='evaluate', response='recommend', reference='candidates')))
    text = chat.respond(question)
    assert 'menor preço' in text and 'R$ 500,00' in text
    assert 'não comprova' in text and text.count('?') == 1
    assert chat.candidate_product_ids == ids
    assert len(model.calls) == 2  # Semantic interpretation, not a phrase shortcut.


def test_semantic_ordinal_reference_and_price_difference(five_catalog):
    chat, model = chat_with(five_catalog)
    model.extraction = plan(semantic_task(req=request(reference='candidates', positions=[2])))
    selected = chat.respond('Gostei da opção número dois, conta mais.')
    assert 'Estudo B' in selected and 'Estudo A' not in selected
    model.extraction = plan(semantic_task(req=request(goal='evaluate', response='compare', reference='candidates', positions=[1,2])))
    text = chat.respond('O segundo justifica pagar a diferença em relação ao primeiro?')
    assert 'diferença' in text.lower() and 'R$ 100,00' in text
    assert 'Estudo C' not in text


def test_cheaper_similar_alternative_uses_local_baseline_and_attributes(five_catalog):
    chat, model = chat_with(five_catalog)
    model.extraction = plan(semantic_task(req=request(reference='candidates', positions=[2])))
    chat.respond('A segunda opção me interessou.')
    model.extraction = plan(semantic_task(req=request(goal='refine', reference='selected', budget='below_reference')))
    text = chat.respond('Tem algo semelhante, só que mais barato?')
    assert 'Estudo A' in text and 'Estudo C' in text
    assert 'Estudo B' not in text and 'Estudo D' not in text
    assert 'menor' in text and 'tabela' in text


def test_budget_change_keeps_previous_verified_filters(five_catalog):
    chat, model = chat_with(five_catalog)
    model.extraction = plan(semantic_task(category_id=5, specs={'strings':'nylon'}, max_price='800.00'))
    chat.respond('Quero nylon até oitocentos.')
    model.extraction = plan(semantic_task(req=request(goal='refine', reference='previous_search', budget='replace'), max_price='550.00'))
    text = chat.respond('Na verdade, meu limite agora é quinhentos e cinquenta.')
    assert 'Estudo A' in text and 'Estudo C' in text
    assert 'Estudo B' not in text
    assert chat.search_filters['category_id'] == 5
    assert chat.search_filters['specs'] == {'strings':'nylon'}


def test_category_explanation_does_not_claim_unsupported_store_quality(five_catalog):
    chat, model = chat_with(five_catalog)
    model.extraction = plan(semantic_task(req=request(goal='learn', response='explain')))
    text = chat.respond('Me explica o que devo observar nas cordas de um violão.')
    assert 'nylon' in text and 'característica' in text
    assert 'não comprova' in text
    assert not text.startswith('Estas são as opções')


def test_dissatisfaction_gets_one_specific_refinement_question(five_catalog):
    chat, model = chat_with(five_catalog)
    model.extraction = plan(semantic_task(req=request(goal='refine', response='clarify', reference='previous_search')))
    text = chat.respond('Nenhum me agradou, vamos tentar por outro caminho.')
    assert text.count('?') == 1 and 'mudar' in text and 'preço' in text


def test_semantic_multi_intent_preserves_policy_and_catalog(five_catalog, policy):
    chat, model = chat_with(five_catalog, policy)
    model.extraction = plan(semantic_task(req=request(goal='evaluate', response='compare', reference='candidates')),
                            semantic_task('p', 'policy_question', req=request(goal='guide', situation='hypothetical'), topic='withdrawal'))
    text = chat.respond('Ajuda a escolher entre eles e me diz como seria devolver uma compra online.')
    assert 'menor preço' in text and '7 dias' in text and 'seção 4.1' in text


def test_missing_reference_and_unsupported_action_are_specific(five_catalog):
    model = SemanticModel(plan(semantic_task(req=request(reference='selected'))))
    chat = Conversation(build_agent(catalog=five_catalog, model=model))
    text = chat.respond('Quanto custa esse?')
    assert 'qual' in text.lower() and 'produto' in text.lower()
    model.extraction = {**plan(disposition='unsupported'), 'response_hint':'unsupported_action'}
    text = chat.respond('Consegue efetuar o cancelamento e devolver o dinheiro?')
    assert 'não' in text.lower() and ('cancel' in text.lower() or 'transa' in text.lower())


@pytest.mark.parametrize('field,value', [('reference','/private/orders.csv'),('positions',[True]),('positions',[999]),('goal','execute_shell')])
def test_untrusted_semantic_metadata_cannot_dispatch(five_catalog, field, value):
    model = SemanticModel(plan(semantic_task(req=request(**{field:value}))))
    chat = Conversation(build_agent(catalog=five_catalog, model=model))
    text = chat.respond('Synthetic malicious extraction')
    assert 'validar' in text or 'técnica' in text
    assert 'Estudo A' not in text


def test_semantic_sdk_payload_excludes_all_local_context_records(five_catalog):
    import json
    from app.agent.groq_model import GroqIntentModel
    from test_groq_model import client_response, generation_task, payload
    raw = generation_task()
    raw['request'] = request(goal='evaluate', response='recommend', reference='candidates')
    client = client_response(payload(raw))
    chat = Conversation(build_agent(catalog=five_catalog, model=GroqIntentModel(client=client, semantic_mode=True)))
    chat._candidates = tuple(p.product_id for p in five_catalog.products)
    text = chat.respond('Qual desses faz mais sentido para um iniciante?')
    sent = json.dumps(client.chat.completions.create.call_args.kwargs)
    assert all(p.name not in sent for p in five_catalog.products)
    assert 'price_brl' not in sent and 'stock_quantity' not in sent and 'source_references' not in sent
    assert 'candidate_list_available=yes' in sent
    assert 'menor preço' in text


def test_named_subject_gets_an_objective_price_difference(five_catalog):
    from dataclasses import replace
    changed = replace(five_catalog, products=tuple(replace(p, name='Yamaha Demo') if p.product_id == 202 else p
                                                  for p in five_catalog.products))
    chat, model = chat_with(changed)
    model.extraction = plan(semantic_task(req=request(goal='evaluate', response='compare', reference='candidates', anchor='Yamaha'), name='Yamaha'))
    text = chat.respond('Esse Yamaha vale a diferença de preço?')
    assert 'Yamaha Demo custa R$ 100,00 a mais' in text
    assert 'não comprova' in text


def test_refinement_merges_attributes_without_dropping_previous_constraints(five_catalog):
    from dataclasses import replace
    changed = replace(five_catalog, products=tuple(replace(p, specs={**p.specs, 'body_material':'maple'}) for p in five_catalog.products))
    chat, model = chat_with(changed)
    model.extraction = plan(semantic_task(specs={'strings':'nylon'}))
    chat.respond('Quero nylon.')
    model.extraction = plan(semantic_task(req=request(goal='refine', reference='previous_search'), specs={'body_material':'maple'}))
    chat.respond('E com corpo de maple?')
    assert chat.search_filters['specs'] == {'strings':'nylon','body_material':'maple'}


def test_semantic_position_is_resolved_even_with_selected_reference(five_catalog):
    chat, model = chat_with(five_catalog)
    model.extraction = plan(semantic_task(req=request(reference='selected', positions=[2])))
    text = chat.respond('Quero saber mais da segunda opção.')
    assert 'Estudo B' in text and 'Estudo A' not in text


def test_evaluation_without_new_filters_defaults_to_local_candidates(five_catalog):
    chat, model = chat_with(five_catalog)
    model.extraction = plan(semantic_task(req=request(goal='evaluate', response='compare')))
    text = chat.respond('Queria entender melhor as opções apresentadas.')
    assert all(p.name in text for p in five_catalog.products)


def test_replace_budget_without_new_family_keeps_existing_search(five_catalog):
    chat, model = chat_with(five_catalog)
    model.extraction = plan(semantic_task(category_id=5, specs={'strings':'nylon'}, max_price='800.00'))
    chat.respond('Quero nylon até oitocentos.')
    model.extraction = plan(semantic_task(req=request(budget='replace'), max_price='520.00'))
    chat.respond('Agora meu teto é 520 reais.')
    assert chat.search_filters['specs'] == {'strings':'nylon'}


def test_hypothetical_context_does_not_become_an_actual_customer_claim(five_catalog, policy):
    chat, model = chat_with(five_catalog, policy)
    model.extraction = plan(semantic_task('p', 'policy_question',
        req=request(goal='guide', situation='hypothetical'), topic='defect', context={'reason':'defect'}))
    text = chat.respond('Se o instrumento chegar quebrado, como seria?')
    assert 'Se o produto vier com defeito' in text
    assert chat.policy_facts.get('reason') is None


def test_semantic_transport_keeps_supported_part_when_global_label_says_clarify(five_catalog):
    from app.agent.groq_model import GroqIntentModel
    from test_groq_model import client_response, generation_task
    raw = generation_task()
    raw['request'] = request(goal='evaluate', response='recommend', reference='candidates')
    client = client_response({'schema_version':'2','disposition':'clarification','tasks':[raw], 'response_hint':'criteria'})
    chat = Conversation(build_agent(catalog=five_catalog, model=GroqIntentModel(client=client, semantic_mode=True)))
    chat._candidates = tuple(p.product_id for p in five_catalog.products)
    text = chat.respond('Qual opção combina com alguém que está dando os primeiros passos?')
    assert 'menor preço' in text and 'não comprova' in text


def test_explaining_known_model_differences_uses_local_comparison(five_catalog):
    chat, model = chat_with(five_catalog)
    model.extraction = plan(semantic_task(req=request(goal='learn', response='explain', reference='candidates')))
    text = chat.respond('Não entendi as diferenças entre esses modelos.')
    assert 'diferença' in text and 'R$ 300,00' in text


def test_unresolved_product_reference_keeps_independent_verified_policy(five_catalog, policy):
    model = SemanticModel(plan(semantic_task(req=request(reference='selected')),
        semantic_task('p','policy_question',req=request(goal='guide'),topic='withdrawal')))
    chat = Conversation(build_agent(catalog=five_catalog,model=model,policy_service=policy))
    text = chat.respond('Quanto custa esse e como funciona a devolução online?')
    assert '7 dias' in text and 'qual produto' in text.lower()
    assert 'Estudo A' not in text


def test_anchor_entity_words_bind_to_validated_local_subject(five_catalog):
    from dataclasses import replace
    changed=replace(five_catalog,products=tuple(replace(p,name='Yamaha Demo') if p.product_id==202 else p for p in five_catalog.products))
    chat, model=chat_with(changed)
    model.extraction=plan(semantic_task(req=request(goal='evaluate',response='compare',anchor='Esse Yamaha')))
    text=chat.respond('Esse Yamaha vale a diferença de preço?')
    assert 'Yamaha Demo custa R$ 100,00 a mais' in text


def test_contextual_explanation_without_new_subject_uses_candidates(five_catalog):
    chat, model=chat_with(five_catalog)
    model.extraction=plan(semantic_task(req=request(goal='learn',response='explain',reference='candidates')))
    text=chat.respond('Não entendi as diferenças entre esses modelos.')
    assert 'diferença' in text and 'R$ 300,00' in text


def test_hypothetical_wording_is_not_overridden_by_individual_model_tag(five_catalog,policy):
    chat, model=chat_with(five_catalog,policy)
    model.extraction=plan(semantic_task('p','policy_question',req=request(goal='guide',situation='individual'),topic='defect',context={'reason':'defect'}))
    text=chat.respond('Se o produto chegar quebrado, o que muda?')
    assert 'Se o produto vier com defeito' in text and text.count('?') == 0
    assert chat.policy_facts.get('reason') is None
