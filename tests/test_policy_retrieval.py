"""Small Portuguese section-level evaluation, real PDF index and compiled graph."""

from dataclasses import dataclass
import json
import re

import pytest

from app.agent.catalog_agent import build_agent
from app.data.store_policy import LocalPolicyService
from test_agent import catalog, FakeIntentModel
from test_multi_intent import plan, task
from test_store_policy import policy_pdf, case_context


@dataclass(frozen=True)
class Case:
    query: str
    topic: str
    expected: frozenset[str]
    classification: str | None = None
    source: str = 'normal'


CASES = [
    Case('Desisti da compra pela internet, quero devolver.', 'returns', frozenset({'4.1', '4.4'})),
    Case('Comprei online e quero voltar atrás. Como faço?', 'troca_online', frozenset({'4.1', '4.4'})),
    Case('Chegou quebrado e nem liga. Posso trocar?', 'returns', frozenset({'4.2', '4.4'})),
    Case('Não gostei da cor, posso pegar outra?', 'returns', frozenset({'4.3', '4.4'})),
    Case('Me arrependi da compra online; e se estiver com defeito?', 'withdrawal', frozenset({'4.1', '4.2', '4.4'})),
    Case('Qual o frete e posso parcelar?', 'shipping', frozenset({'5.1', '3', '3.1'})),
    Case('Quanto tempo leva para chegar e quanto custa a entrega?', 'shipping', frozenset({'5.1', '5.2'})),
    Case('Dá para pagar com PIX?', 'payment_methods', frozenset({'3'})),
    Case('Como funciona isso?', 'situation', frozenset(), 'clarification_required'),
    Case('Vocês fazem seguro de carro?', 'insurance', frozenset(), 'insufficient_evidence'),
    Case('Quais as regras da garantia?', 'warranty', frozenset(), 'insufficient_evidence', 'missing'),
    Case('Qual o horário da loja?', 'hours', frozenset(), 'technical_error', 'broken'),
]


@pytest.fixture
def evaluation_services(policy_pdf, tmp_path):
    pages = [
        ['2. Hours', 'SYNTHETIC horario: atendimento ficticio.',
         '3. Payment methods', 'SYNTHETIC pagamento por PIX e cartao.',
         '3.1 Installments', 'SYNTHETIC parcelamento depende de confirmacao.', 'Page 37'],
        ['4. Returns', '4.1 Withdrawal', 'SYNTHETIC arrependimento: compra online, 7 dias do recebimento.',
         '4.2 Defect', 'SYNTHETIC produto com defeito ou quebrado exige analise.',
         '4.3 Preference', 'SYNTHETIC troca por preferencia ou outra cor exige analise.',
         '4.4 Exceptions', 'SYNTHETIC excecoes exigem revisao humana.',
         '5. Shipping', '5.1 Freight', 'SYNTHETIC custo do frete depende do destino.',
         '5.2 Delivery times', 'SYNTHETIC prazo de entrega depende do destino.',
         '5.3 Tracking', 'SYNTHETIC rastreamento somente em canal autorizado.', 'Page 38'],
        ['8. Warranty', '8.3 Exclusions', 'SYNTHETIC exclusoes isoladas nao comprovam garantia.', 'Page 39'],
    ]
    service = LocalPolicyService.from_pdf(policy_pdf(pages))
    broken = tmp_path / 'malformed.pdf'
    broken.write_bytes(b'not a PDF - SYNTHETIC_INTERNAL_MARKER')
    return {'normal': service, 'missing': service, 'broken': LocalPolicyService.from_pdf(broken)}


def run_case(catalog, service, case):
    model = FakeIntentModel(plan(task(intent='policy_question', topic=case.topic)))
    reply = build_agent(catalog=catalog, model=model, policy_service=service).invoke(
        session_id='synthetic', message=case.query)
    outcome = reply.task_outcomes[0]
    sections = {re.search(r':section/([^:]+):', ref).group(1) for ref in outcome.source_references}
    classification = outcome.facts.get('retrieval_status') or (
        'clarification_required' if outcome.status == 'clarification' else
        'ok' if outcome.status in ('ok', 'review_required') else outcome.error_category)
    return reply, sections, classification


@pytest.mark.parametrize('case', CASES, ids=[f'pt-{i+1:02}' for i in range(len(CASES))])
def test_portuguese_retrieval_evaluation(catalog, evaluation_services, case):
    reply, sections, classification = run_case(catalog, evaluation_services[case.source], case)
    assert case.expected <= sections
    assert sections <= case.expected  # This controlled fixture has no additional relevant sections.
    if case.classification:
        assert classification == case.classification
        assert not sections
    else:
        assert classification in ('ok', 'clarification_required')
    assert len(reply.task_outcomes[0].source_references) <= 8
    assert 'SYNTHETIC_INTERNAL_MARKER' not in reply.text
    assert 'does not exist' not in reply.text


@pytest.mark.parametrize('topic,query,expected', [
    ('withdrawal', 'Se eu me arrepender e quiser devolver?', {'4.1', '4.4'}),
    ('defect', 'Quero devolver o produto.', {'4.2', '4.4'}),
    ('preference', 'Quero trocar o produto.', {'4.3', '4.4'}),
    ('returns', 'Desisti da compra e quero devolver.', {'4.1', '4.4'}),
    ('unknown', 'O produto chegou quebrado.', {'4.2', '4.4'}),
    ('withdrawal', 'Quero devolver e o produto tem defeito.', {'4.1', '4.2', '4.4'}),
    ('shipping', 'Qual o frete e posso parcelar?', {'5.1', '3', '3.1'}),
    ('payments', 'Qual o frete e posso parcelar?', {'5.1', '3', '3.1'}),
])
def test_semantic_topic_precedence_preserves_multiple_subjects(
        evaluation_services, topic, query, expected):
    evidence = evaluation_services['normal'].retrieve(topic=topic, query=query)
    sections = {re.search(r':section/([^:]+):', ref).group(1)
                for ref in evidence.source_references}
    assert sections == expected


def test_evaluation_metrics(catalog, evaluation_services):
    rows, recalls, hits, expected_total, irrelevant = [], [], 0, 0, 0
    for case in CASES:
        _, found, classification = run_case(catalog, evaluation_services[case.source], case)
        if case.expected:
            hit = len(case.expected & found)
            recalls.append(hit / len(case.expected))
            hits += hit
            expected_total += len(case.expected)
            irrelevant += len(found - case.expected)
        rows.append({'expected': sorted(case.expected), 'found': sorted(found), 'classification': classification})
    print(json.dumps({'macro_recall_at_8': sum(recalls)/len(recalls),
                      'micro_recall_at_8': hits/expected_total,
                      'irrelevant_sections': irrelevant, 'cases': rows}, sort_keys=True))
    assert sum(recalls)/len(recalls) == 1.0
    assert irrelevant == 0


def test_policy_query_and_captured_facts_reach_retrieval_without_reasking(catalog, policy_pdf):
    service = LocalPolicyService.from_pdf(policy_pdf())
    model = FakeIntentModel(plan(task(intent='policy_question', topic='withdrawal', context=case_context(3))))
    reply = build_agent(catalog=catalog, model=model, policy_service=service).invoke(
        session_id='synthetic', message='Desisti da compra online recebida há três dias.')
    assessment = reply.task_outcomes[0].facts['assessment']
    assert 'days_since_receipt' not in assessment['missing_facts']
    assert assessment['customer_claims']['days_since_receipt'] == 3
    assert reply.status == 'review_required'


def test_fallback_is_single_bounded_pass_with_deduplicated_provenance(catalog, evaluation_services, monkeypatch):
    from dataclasses import replace
    service = evaluation_services['normal']
    service = replace(service, fragments=service.fragments + service.fragments)
    calls = []
    original = LocalPolicyService._fallback
    def fallback(self, allowed, required, query):
        calls.append(query)
        return original(self, allowed, required, query)
    monkeypatch.setattr(LocalPolicyService, '_fallback', fallback)
    case = CASES[5]
    reply, sections, _ = run_case(catalog, service, case)
    assert len(calls) == 1 and calls[0] == case.query
    outcome = reply.task_outcomes[0]
    assert outcome.facts['fallback_used'] is True
    assert sections == case.expected
    assert len(outcome.source_references) == len(set(outcome.source_references)) == 3
    assert all(':pdf-page/' in ref and ':printed-page/' in ref for ref in outcome.source_references)
    assert len(outcome.facts['text']) <= 8000


def test_oversized_required_section_fails_closed_after_one_fallback(evaluation_services, monkeypatch):
    from dataclasses import replace
    service = evaluation_services['normal']
    service = replace(service, fragments=tuple(replace(f, text=f.text + 'x' * 8000)
                                              if f.section == '3' else f for f in service.fragments))
    calls = []
    original = LocalPolicyService._fallback
    def fallback(self, allowed, required, query):
        calls.append(1)
        return original(self, allowed, required, query)
    monkeypatch.setattr(LocalPolicyService, '_fallback', fallback)
    evidence = service.retrieve(topic='payments', query='Posso pagar com PIX?')
    assert evidence.retrieval_status == 'insufficient_evidence'
    assert evidence.text == '' and evidence.source_references == ()
    assert calls == [1]


def test_extraction_error_and_service_error_are_technical_not_missing(catalog, evaluation_services):
    class BrokenService:
        def lookup(self, **kwargs):
            raise RuntimeError('PRIVATE_INTERNAL_MARKER')
    case = CASES[-1]
    for service in (evaluation_services['broken'], BrokenService()):
        reply, sections, classification = run_case(catalog, service, case)
        assert classification == 'technical_error'
        assert reply.task_outcomes[0].status == 'error'
        assert not sections and 'PRIVATE_INTERNAL_MARKER' not in reply.text


def test_original_query_is_application_owned_and_only_policy_worker_receives_it(catalog, evaluation_services, monkeypatch):
    import app.agent.catalog_agent as implementation
    observed = []
    for name in ('_catalog_worker', '_policy_worker', '_order_worker'):
        original = getattr(implementation.CatalogAgent, name)
        def wrapped(self, state, _original=original, _name=name):
            assert set(state) == {'task'}
            observed.append((_name, state['task'].query))
            return _original(self, state)
        monkeypatch.setattr(implementation.CatalogAgent, name, wrapped)
    query = 'Qual o frete e posso parcelar?'
    model = FakeIntentModel(plan(task('c', name='Aurora Nylon'),
                                 task('p', 'policy_question', topic='shipping'),
                                 task('o', 'order_status')))
    build_agent(catalog=catalog, model=model, policy_service=evaluation_services['normal']).invoke(
        session_id='synthetic', message=query)
    assert sorted(observed) == sorted([('_catalog_worker', None), ('_policy_worker', query), ('_order_worker', None)])


def test_legacy_topic_alias_remains_supported(evaluation_services):
    evidence = evaluation_services['normal'].lookup(topic='installments')
    assert evidence is not None
    assert any(':section/3.1:' in ref for ref in evidence.source_references)
