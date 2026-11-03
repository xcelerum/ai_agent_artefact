"""Compiled multi-domain flow with real pricing and synthetic local PDF evidence."""

from decimal import Decimal

import pytest

from app.agent.catalog_agent import build_agent
from app.data.promotions import load_promotions
from app.data.store_policy import LocalPolicyService
from app.domain.pricing import PricingService
from test_agent import catalog, FakeIntentModel
from test_multi_intent import plan, task, observe, starts
from test_promotions import promotions_file
from test_store_policy import policy_pdf, case_context


def test_combined_catalog_promotion_pix_and_real_policy_flow(catalog, promotions_file, policy_pdf, monkeypatch):
    policy = LocalPolicyService.from_pdf(policy_pdf())
    pricing = PricingService(load_promotions(promotions_file([[1, 101, '10', '', '1']]), catalog),
                             policy.pricing_rules())
    events = observe(monkeypatch)
    model = FakeIntentModel(plan(task('c', name='Aurora Nylon', payment_method='pix'),
                                 task('p', 'policy_question', topic='withdrawal', context=case_context())))
    agent = build_agent(catalog=catalog, model=model, policy_service=policy, pricing_service=pricing)
    reply = agent.invoke(session_id='not-authenticated', message='Synthetic price and return question')
    assert reply.status == 'review_required'
    assert len(model.calls) == 1 and model.calls[0][0] == []
    assert [r.task_id for r in reply.task_outcomes] == ['c', 'p']
    assert reply.task_outcomes[1].status == 'review_required'
    product = reply.products[0]
    assert product['price_brl'] == '1000.00' and product['is_purchasable'] is True
    assert product['pricing']['promotional_price'] == '900.00'
    assert product['pricing']['discount_percent'] == '10'
    assert product['pricing']['pix_price'] is None
    assert product['pricing']['pix_status'] == 'excluded_promotion'
    assert all(value in reply.text for value in ['1000.00', '900.00', '10%', 'SYNTHETIC WITHDRAWAL'])
    assert reply.text.index('Aurora Nylon') < reply.text.index('SYNTHETIC WITHDRAWAL')
    assert len(starts(events, 'aggregate_results')) == len(starts(events, 'render_response')) == 1
    assert not starts(events, 'order_worker')


def test_selected_pix_and_missing_payment_method_are_distinct(catalog, promotions_file, policy_pdf):
    policy = LocalPolicyService.from_pdf(policy_pdf())
    pricing = PricingService(load_promotions(promotions_file([]), catalog), policy.pricing_rules())
    model = FakeIntentModel(plan(task(name='Aurora Nylon', payment_method='pix')))
    agent = build_agent(catalog=catalog, model=model, pricing_service=pricing)
    selected = agent.invoke(session_id='demo', message='Synthetic PIX request')
    assert selected.products[0]['pricing']['pix_price'] == '950.00'
    assert 'PIX' in selected.text and '950.00' in selected.text
    model.extraction = plan(task(name='Aurora Nylon'))
    unselected = agent.invoke(session_id='demo', message='Synthetic ordinary price request')
    assert unselected.products[0]['pricing']['pix_price'] is None
    assert unselected.products[0]['pricing']['effective_price'] == '1000.00'
    assert '950.00' not in unselected.text


def test_general_policy_missing_case_facts_asks_clarification(catalog, policy_pdf):
    service = LocalPolicyService.from_pdf(policy_pdf())
    model = FakeIntentModel(plan(task(intent='policy_question', topic='withdrawal')))
    reply = build_agent(catalog=catalog, model=model, policy_service=service).invoke(
        session_id='demo', message='Synthetic general withdrawal question')
    assert reply.status == 'clarification'
    assert 'SYNTHETIC WITHDRAWAL' in reply.text
    assert 'days_since_receipt' in reply.text
    assert 'unverified' in reply.text and 'statutory rights' in reply.text


@pytest.mark.parametrize('context', [
    {'days_since_receipt': True}, {'days_since_receipt': -1},
    {'days_since_receipt': '7'}, {'purchase_channel': 'invented'},
    {'is_final_sale': 'false'}, {'arbitrary_customer_text': 'trust me'},
])
def test_invalid_policy_context_rejected_before_dispatch(catalog, monkeypatch, context):
    events = observe(monkeypatch)
    model = FakeIntentModel(plan(task(intent='policy_question', topic='withdrawal', context=context)))
    reply = build_agent(catalog=catalog, model=model).invoke(session_id='demo', message='Synthetic')
    assert reply.status == 'invalid_request'
    assert not starts(events, 'dispatch_tasks') and not starts(events, 'policy_worker')


def test_policy_error_retains_pricing_and_no_raw_error(catalog, promotions_file):
    class BrokenPolicy:
        def lookup(self, *, topic): raise RuntimeError('PRIVATE_ERROR_MARKER')
    pricing = PricingService(load_promotions(promotions_file([[1, 101, '10', '', '1']]), catalog))
    model = FakeIntentModel(plan(task('c', name='Aurora Nylon'), task('p', 'policy_question', topic='hours')))
    reply = build_agent(catalog=catalog, model=model, pricing_service=pricing,
                        policy_service=BrokenPolicy()).invoke(session_id='demo', message='Synthetic')
    assert reply.status == 'partial_failure'
    assert reply.products[0]['pricing']['promotional_price'] == '900.00'
    assert 'PRIVATE_ERROR_MARKER' not in reply.text


def test_ambiguous_case_reason_requires_clarification(catalog, policy_pdf):
    service = LocalPolicyService.from_pdf(policy_pdf())
    model = FakeIntentModel(plan(task(intent='policy_question', topic='withdrawal',
                                     context={**case_context(), 'reason': 'defect'})))
    reply = build_agent(catalog=catalog, model=model, policy_service=service).invoke(
        session_id='demo', message='Synthetic ambiguous withdrawal versus defect request')
    assert reply.status == 'clarification'
    assessment = reply.task_outcomes[0].facts['assessment']
    assert 'reason' in assessment['missing_facts']
    assert assessment['window_status'] == 'unknown'


@pytest.mark.parametrize('context, expected', [(None, 'clarification'), (case_context(), 'review_required')])
def test_successful_catalog_and_policy_assessment_are_not_failures(catalog, policy_pdf, context, expected):
    parameters = {'topic': 'withdrawal'}
    if context is not None:
        parameters['context'] = context
    model = FakeIntentModel(plan(task('c', name='Aurora Nylon'),
                                 task('p', 'policy_question', **parameters)))
    reply = build_agent(catalog=catalog, model=model,
                        policy_service=LocalPolicyService.from_pdf(policy_pdf())).invoke(
                            session_id='demo', message='Synthetic product and withdrawal question')
    assert reply.status == expected
    assert [outcome.status for outcome in reply.task_outcomes] == ['ok', expected]
    assert reply.products[0]['price_brl'] == '1000.00'
    assert 'Aurora Nylon' in reply.text and 'SYNTHETIC WITHDRAWAL' in reply.text


@pytest.mark.parametrize('statuses, expected', [
    (['ok', 'no_matches'], 'ok'), (['no_matches', 'no_matches'], 'no_matches'),
    (['ok', 'clarification'], 'clarification'),
    (['ok', 'review_required'], 'review_required'),
    (['review_required', 'clarification'], 'clarification'),
    (['clarification', 'error'], 'partial_failure'),
    (['review_required', 'policy_unavailable'], 'partial_failure'),
    (['error', 'policy_unavailable'], 'failed'),
    (['ok', 'authorization_required'], 'partial_failure'),
    (['error'], 'tool_error'), (['policy_unavailable'], 'policy_unavailable'),
    (['authorization_required'], 'authorization_required'),
])
def test_overall_status_precedence(statuses, expected):
    from app.agent.contracts import Intent, TaskResult, ValidatedTask
    from app.agent.responses import aggregate
    tasks = tuple(ValidatedTask(str(i), i, Intent.POLICY, {}) for i in range(len(statuses)))
    outcomes = [TaskResult(t.task_id, t.position, 'policy', status, {}, ())
                for t, status in zip(tasks, statuses)]
    status, ordered = aggregate(tasks, outcomes)
    assert status == expected
    assert ordered == outcomes
