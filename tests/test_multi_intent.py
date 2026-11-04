"""Cycle 1 contracts: public invocation, real Send branches and domain services."""

import builtins
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event, Lock

import pytest
from langgraph.graph.state import CompiledStateGraph

import app.agent.catalog_agent as implementation
from app.domain.catalog import Catalog
from test_agent import catalog, FakeIntentModel  # Reuse public synthetic fixture.


def task(identifier='t1', intent='catalog_lookup', **parameters):
    return {'id': identifier, 'intent': intent, 'parameters': parameters}


def plan(*tasks, disposition='execute'):
    return {'schema_version': '2', 'disposition': disposition, 'tasks': list(tasks)}


class SyntheticPolicy:
    def __init__(self, label='DEMO'):
        self.label = label
        self.calls = []
        self.lock = Lock()

    def lookup(self, *, topic):
        with self.lock:
            self.calls.append(topic)
        return implementation.PolicyEvidence(
            text=f'SYNTHETIC {self.label}: evidence for {topic}',
            source_references=(f'synthetic://{self.label}/{topic}',),
        )


def observe(monkeypatch):
    """Capture real graph node entry/exit and Pregel supersteps, not final mocks."""
    events = []
    lock = Lock()
    for name in ('prepare_turn', 'interpret_intents', 'validate_plan', 'dispatch_tasks',
                 'catalog_worker', 'policy_worker', 'order_worker',
                 'aggregate_results', 'render_response'):
        original = getattr(implementation.CatalogAgent, '_' + name, None)
        if original is None:  # Old GREEN has no such nodes; outcome assertions must fail.
            continue

        def wrapped(self, state, config, _fn=original, _name=name):
            identity = state['task'].task_id if 'task' in state else None
            if _name.endswith('_worker'):
                assert set(state) == {'task'}  # No customer/session/raw plan in worker input.
            step = config['metadata']['langgraph_step']
            with lock:
                events.append(('start', _name, identity, step))
            result = _fn(self, state)
            with lock:
                events.append(('end', _name, identity, step))
            return result

        monkeypatch.setattr(implementation.CatalogAgent, '_' + name, wrapped)
    return events


def starts(events, name):
    return [event for event in events if event[:2] == ('start', name)]


def invoke(catalog, extraction, **kwargs):
    model = FakeIntentModel(extraction)
    agent = implementation.build_agent(catalog=catalog, model=model, **kwargs)
    assert isinstance(agent._graph, CompiledStateGraph)
    reply = agent.invoke(session_id='untrusted-session', message='Synthetic combined question')
    assert len(model.calls) == 1
    assert model.calls[0][0] == []
    assert isinstance(reply, implementation.AgentReply)
    return reply, model, agent


@pytest.mark.parametrize('intents', [
    ('catalog_lookup',), ('policy_question',), ('order_status',),
    ('catalog_lookup', 'policy_question'),
    ('catalog_lookup', 'policy_question', 'order_status'),
])
def test_dispatches_only_requested_domains(catalog, monkeypatch, intents):
    events = observe(monkeypatch)
    policy = SyntheticPolicy()
    parameters = {'catalog_lookup': {'name': 'Aurora Nylon'},
                  'policy_question': {'topic': 'withdrawal'},
                  'order_status': {'order_reference': 'DEMO-123'}}
    tasks = [task(f't{i}', intent, **parameters[intent]) for i, intent in enumerate(intents)]
    reply, _, _ = invoke(catalog, plan(*tasks), policy_service=policy)
    assert len(reply.task_outcomes) == len(tasks)
    mapping = {'catalog_lookup': 'catalog_worker', 'policy_question': 'policy_worker',
               'order_status': 'order_worker'}
    for intent, node in mapping.items():
        assert len(starts(events, node)) == intents.count(intent)
    assert len(starts(events, 'aggregate_results')) == 1
    assert len(starts(events, 'render_response')) == 1
    assert [outcome.task_id for outcome in reply.task_outcomes] == [t['id'] for t in tasks]
    if 'order_status' in intents:
        outcome = reply.task_outcomes[intents.index('order_status')]
        assert outcome.status == 'authorization_required'
        assert outcome.facts == {} and outcome.source_references == ()
        assert 'DEMO-123' not in reply.text
    if 'catalog_lookup' in intents:
        assert reply.products[0]['price_brl'] == '1000.00'
    if 'policy_question' in intents:
        assert policy.calls == ['withdrawal']
        outcome = reply.task_outcomes[intents.index('policy_question')]
        assert outcome.facts['text'] == 'SYNTHETIC DEMO: evidence for withdrawal'
        assert outcome.source_references == ('synthetic://DEMO/withdrawal',)
        assert outcome.source_references[0] in reply.text
    if len(intents) == 3:
        assert reply.status == 'partial_failure'
        assert [o.domain for o in reply.task_outcomes] == ['catalog', 'policy', 'order']


def test_same_worker_multiple_send_and_related_product_grouping(catalog, monkeypatch):
    events = observe(monkeypatch)
    reply, model, agent = invoke(catalog, plan(task('first', name='Aurora Nylon'),
                                         task('second', name='Aurora Steel')))
    assert reply.status == 'ok'
    assert [p['product_id'] for p in reply.products] == [101, 102]
    assert len(starts(events, 'catalog_worker')) == 2
    assert len({e[3] for e in starts(events, 'catalog_worker')}) == 1
    assert len(starts(events, 'aggregate_results')) == 1
    assert [o.position for o in reply.task_outcomes] == [0, 1]
    # A related availability+price question is represented by ONE extraction task.
    model.extraction = plan(task(name='Aurora Nylon'))
    before = len(starts(events, 'catalog_worker'))
    answer = agent.invoke(session_id='same', message='Is Aurora Nylon available and how much is it?')
    assert len(starts(events, 'catalog_worker')) == before + 1
    assert len(answer.task_outcomes) == 1
    assert answer.products[0]['is_purchasable'] is True
    assert answer.products[0]['price_brl'] == '1000.00'
    schema = model.calls[0][2]
    assert schema['properties']['tasks']['maxItems'] == 4


@pytest.mark.parametrize('first', ['a', 'b'])
def test_parallel_superstep_barrier_and_deterministic_fanin(catalog, monkeypatch, first):
    events = observe(monkeypatch)
    original = getattr(implementation.CatalogAgent, '_policy_worker', None)
    gate, first_finished = Barrier(2), Event()
    completion = []

    def ordered_worker(self, state, config):
        identifier = state['task'].task_id
        gate.wait(timeout=5)  # Sequential calls cannot pass this barrier.
        if identifier != first:
            assert first_finished.wait(5)
        result = original(self, state, config)
        completion.append(identifier)
        if identifier == first:
            first_finished.set()
        return result

    monkeypatch.setattr(implementation.CatalogAgent, '_policy_worker', ordered_worker, raising=False)
    reply, _, _ = invoke(catalog, plan(task('a', 'policy_question', topic='withdrawal'),
                                     task('b', 'policy_question', topic='warranty'),
                                     task('c', name='Aurora Nylon')),
                         policy_service=SyntheticPolicy())
    assert completion == [first, 'b' if first == 'a' else 'a']
    assert reply.status == 'ok'
    assert [r.task_id for r in reply.task_outcomes] == ['a', 'b', 'c']
    worker_entries = [e for e in events if e[0] == 'start' and e[1].endswith('_worker')]
    assert len(worker_entries) == 3 and len({e[3] for e in worker_entries}) == 1
    assert len(starts(events, 'aggregate_results')) == len(starts(events, 'render_response')) == 1
    aggregate_index = events.index(starts(events, 'aggregate_results')[0])
    assert all(events.index(e) < aggregate_index for e in events
               if e[0] == 'end' and e[1].endswith('_worker'))
    assert reply.text.index('withdrawal') < reply.text.index('warranty') < reply.text.index('Aurora Nylon')


invalid_plans = [
    {}, plan(), {**plan(task()), 'schema_version': 2},
    {**plan(task()), 'schema_version': '1'}, {**plan(task()), 'disposition': 'run'},
    {**plan(task()), 'response': 'FORGED facts'},
    plan(*[task(f't{i}', name=str(i)) for i in range(5)]),
    plan(task('same', name='a'), task('same', name='b')),
    plan(task('a', name='Aurora'), task('b', name=' AURÓRA ')),
    plan(task('a', max_price='1000.0'), task('b', max_price='1000.00')),
    plan(task(intent='shell')), plan(task('bad id')),
    plan({'id': 'a', 'intent': 'catalog_lookup'}),
    plan(task(intent='catalog_lookup', max_price=1000.0)),
    plan(task(intent='catalog_lookup', max_price='1e3')),
    plan(task(intent='catalog_lookup', specs={'unknown': 'value'})),
    plan(task(intent='catalog_lookup', stock_quantity=99)),
    plan(task(intent='policy_question')), plan(task(intent='policy_question', topic=1)),
    plan(task(intent='policy_question', topic='x', path='/private/policies.pdf')),
    plan(task(intent='order_status', customer_id='forged')),
    plan(task(intent='order_status', order_reference=123)),
    plan(task(), disposition='clarification'), plan(task(), disposition='unsupported'),
    {**plan(task()), 'tasks': 'not-a-list'},
    plan(task(intent='policy_question', topic='x' * 201)),
    '{"schema_version":"2","schema_version":"2","disposition":"execute","tasks":[]}',
    '{"schema_version":"2","disposition":"execute","tasks":[{"id":"a","intent":"catalog_lookup","parameters":{"name":"a","name":"b"}}]}',
    'x' * (16 * 1024 + 1),
]


@pytest.mark.parametrize('extraction', invalid_plans, ids=[f'invalid-{i}' for i in range(len(invalid_plans))])
def test_invalid_plan_has_no_business_dispatch(catalog, monkeypatch, extraction):
    events = observe(monkeypatch)
    reply, _, _ = invoke(catalog, extraction)
    assert reply.status == 'invalid_request'
    assert reply.products == []
    assert reply.task_outcomes == []
    assert not any(e[0] == 'start' and e[1].endswith('_worker') for e in events)
    assert starts(events, 'dispatch_tasks') == []
    assert starts(events, 'aggregate_results') == []
    assert len(starts(events, 'render_response')) == 1
    assert 'FORGED' not in reply.text


@pytest.mark.parametrize('disposition', ['clarification', 'unsupported'])
def test_zero_task_fallback_uses_conditional_path(catalog, monkeypatch, disposition):
    events = observe(monkeypatch)
    reply, _, _ = invoke(catalog, plan(disposition=disposition))
    assert reply.status == disposition and reply.products == [] and reply.task_outcomes == []
    assert not starts(events, 'dispatch_tasks') and not starts(events, 'aggregate_results')
    assert len(starts(events, 'render_response')) == 1


def test_policy_unavailable_retains_independent_catalog_facts(catalog):
    reply, _, _ = invoke(catalog, plan(task(name='Aurora Nylon'),
                                     task('p', 'policy_question', topic='withdrawal')))
    assert reply.status == 'partial_failure'
    assert reply.products[0]['price_brl'] == '1000.00'
    assert reply.task_outcomes[1].status == 'policy_unavailable'
    assert reply.task_outcomes[1].facts == {} and reply.task_outcomes[1].source_references == ()
    assert 'could not be confirmed' in reply.text


@pytest.mark.parametrize('evidence', [None, 'not evidence'])
def test_policy_missing_or_malformed_evidence_never_invents_rules(catalog, evidence):
    class MissingPolicy:
        def lookup(self, *, topic):
            return evidence
    reply, _, _ = invoke(catalog, plan(task(intent='policy_question', topic='withdrawal')),
                         policy_service=MissingPolicy())
    assert reply.status == 'policy_unavailable'
    assert reply.task_outcomes[0].facts == {} and reply.task_outcomes[0].source_references == ()
    assert 'not evidence' not in reply.text


def test_order_gate_never_reads_csv_or_treats_session_as_identity(catalog, monkeypatch):
    reads = []
    def guard(original):
        def open_file(path, *args, **kwargs):
            if str(path).endswith('.csv'):
                reads.append(str(path))
                raise AssertionError('Private lookup must not occur')
            return original(path, *args, **kwargs)
        return open_file
    monkeypatch.setattr(builtins, 'open', guard(builtins.open))
    monkeypatch.setattr(Path, 'open', guard(Path.open))
    reply, _, _ = invoke(catalog, plan(task(intent='order_status', order_reference='SYNTHETIC_PRIVATE_ID')))
    assert reads == []
    assert reply.status == 'authorization_required' and reply.products == []
    assert reply.task_outcomes[0].error_category == 'authorization_required'
    assert reply.task_outcomes[0].facts == {}
    assert 'SYNTHETIC_PRIVATE_ID' not in reply.text and 'untrusted-session' not in reply.text


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'wrong-position', 'unknown-id'])
def test_fanin_detects_corrupt_worker_cardinality(catalog, monkeypatch, fault):
    original = getattr(implementation.CatalogAgent, '_catalog_worker', None)
    def faulty(self, state):
        update = original(self, state)
        result = update['task_results'][0]
        if fault == 'missing':
            return {'task_results': []}
        if fault == 'duplicate':
            return {'task_results': [result, result]}
        return {'task_results': [replace(result, **({'position': 99} if fault == 'wrong-position' else {'task_id': 'unplanned'}))]}
    monkeypatch.setattr(implementation.CatalogAgent, '_catalog_worker', faulty, raising=False)
    reply, _, _ = invoke(catalog, plan(task(name='Aurora Nylon')))
    assert reply.status == 'aggregation_error'
    assert len(reply.task_outcomes) == 1
    assert reply.task_outcomes[0].status == 'error'
    assert reply.task_outcomes[0].error_category == 'aggregation_error'
    assert reply.products == []


def test_domain_failure_retains_other_success_and_sanitizes_errors(catalog, monkeypatch):
    original = Catalog.search
    def search(self, **kwargs):
        if kwargs['name'] == 'Fail':
            raise RuntimeError('SENSITIVE_EXCEPTION_MARKER')
        return original(self, **kwargs)
    monkeypatch.setattr(Catalog, 'search', search)
    reply, _, _ = invoke(catalog, plan(task('bad', name='Fail'), task('good', name='Aurora Nylon')))
    assert reply.status == 'partial_failure'
    assert [r.status for r in reply.task_outcomes] == ['error', 'ok']
    assert reply.products[0]['price_brl'] == '1000.00'
    assert 'SENSITIVE_EXCEPTION_MARKER' not in reply.text


def test_instance_and_turn_isolation_with_mutable_adapter_outputs(catalog):
    policy_a, policy_b = SyntheticPolicy('A'), SyntheticPolicy('B')
    model_a = FakeIntentModel(plan(task(), task('p', 'policy_question', topic='withdrawal')))
    model_b = FakeIntentModel(plan(task(name='Other'), task('p', 'policy_question', topic='warranty')))
    other = replace(catalog, products=(replace(catalog.products[0], name='Other', price_brl=catalog.products[1].price_brl),))
    a = implementation.build_agent(catalog=catalog, model=model_a, policy_service=policy_a)
    b = implementation.build_agent(catalog=other, model=model_b, policy_service=policy_b)
    one = a.invoke(session_id='same', message='Synthetic')
    two = b.invoke(session_id='same', message='Synthetic')
    assert one.products[0]['price_brl'] == '1000.00' and two.products[0]['price_brl'] == '999.99'
    assert policy_a.calls == ['withdrawal'] and policy_b.calls == ['warranty']
    one.products[0]['price_brl'] = 'forged'
    one.task_outcomes[0].facts['products'][0]['specs']['strings'] = 'forged'
    model_a.extraction = plan(task(category_id=3))
    empty = a.invoke(session_id='same', message='Empty')
    assert empty.status == 'no_matches' and empty.products == []
    assert len(empty.task_outcomes) == 1 and 'SYNTHETIC A' not in empty.text
    model_a.extraction = plan(task(name='Aurora Nylon'))
    again = a.invoke(session_id='same', message='Again')
    assert again.products[0]['price_brl'] == '1000.00'
    assert again.products[0]['specs'] == {'strings': 'nylon'}
    model_a.extraction = {'invalid': 'plan'}
    invalid = a.invoke(session_id='same', message='Invalid')
    assert invalid.status == 'invalid_request' and invalid.task_outcomes == [] and invalid.products == []
    assert all(call[0] == [] for call in model_a.calls + model_b.calls)


def test_four_tasks_are_bounded_and_each_result_preserved(catalog):
    reply, _, _ = invoke(catalog, plan(task('a', name='Aurora Nylon'), task('b', name='Aurora Steel'),
                                     task('c', 'policy_question', topic='withdrawal'),
                                     task('d', 'order_status')), policy_service=SyntheticPolicy())
    assert len(reply.task_outcomes) == 4
    assert [o.position for o in reply.task_outcomes] == [0, 1, 2, 3]
    assert Counter(o.task_id for o in reply.task_outcomes) == Counter(['a', 'b', 'c', 'd'])
    assert reply.status == 'partial_failure'


def record_search_attempts(monkeypatch):
    """Observe exact arguments, including attempted calls that might raise."""
    original, calls, lock = Catalog.search, [], Lock()

    def search(self, **kwargs):
        with lock:
            calls.append(deepcopy(kwargs))
        return original(self, **kwargs)

    monkeypatch.setattr(Catalog, 'search', search)
    return calls


@pytest.mark.parametrize('spec_fields', [{}, {'specs': None}, {'specs': {}}],
                         ids=['omitted', 'null', 'empty'])
def test_effective_specs_single_task_preserves_arguments(catalog, monkeypatch, spec_fields):
    from decimal import Decimal

    calls = record_search_attempts(monkeypatch)
    reply, _, _ = invoke(catalog, plan(task(name='Aurora Nylon', max_price='1000.00', **spec_fields)))
    assert reply.status == 'ok'
    assert len(calls) == 1
    assert calls[0]['specs'] == spec_fields.get('specs')
    assert calls[0]['name'] == 'Aurora Nylon'
    assert type(calls[0]['max_price']) is Decimal
    assert calls[0]['max_price'] == Decimal('1000.00')
    assert [p['product_id'] for p in reply.products] == [101]
    assert reply.products[0]['price_brl'] == '1000.00'


@pytest.mark.parametrize('left', [{}, {'specs': None}, {'specs': {}}],
                         ids=['omitted', 'null', 'empty'])
@pytest.mark.parametrize('right', [{}, {'specs': None}, {'specs': {}}],
                         ids=['omitted', 'null', 'empty'])
def test_effective_specs_duplicates_rejected_before_dispatch(catalog, monkeypatch, left, right):
    events = observe(monkeypatch)
    calls = record_search_attempts(monkeypatch)
    reply, _, _ = invoke(catalog, plan(task('left', name='Aurora Nylon', **left),
                                     task('right', name='Aurora Nylon', **right)))
    assert reply.status == 'invalid_request'
    assert reply.products == [] and reply.task_outcomes == []
    assert calls == []
    assert starts(events, 'dispatch_tasks') == []
    assert not any(e[0] == 'start' and e[1].endswith('_worker') for e in events)
    assert len(starts(events, 'render_response')) == 1


@pytest.mark.parametrize('spec_fields', [{}, {'specs': None}, {'specs': {}}],
                         ids=['omitted', 'null', 'empty'])
def test_effective_specs_distinct_searches_still_dispatch(catalog, monkeypatch, spec_fields):
    events = observe(monkeypatch)
    calls = record_search_attempts(monkeypatch)
    reply, _, _ = invoke(catalog, plan(task('nylon', name='Aurora Nylon', **spec_fields),
                                     task('steel', name='Aurora Steel', **spec_fields)))
    assert reply.status == 'ok'
    assert [p['product_id'] for p in reply.products] == [101, 102]
    assert len(calls) == 2
    assert {call['name'] for call in calls} == {'Aurora Nylon', 'Aurora Steel'}
    assert all(call['specs'] == spec_fields.get('specs') for call in calls)
    assert len(starts(events, 'catalog_worker')) == 2
    assert len(starts(events, 'aggregate_results')) == 1
