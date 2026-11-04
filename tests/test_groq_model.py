"""Hosted extraction mocked at the SDK boundary; real graph and synthetic catalog."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from groq import APIConnectionError, APITimeoutError, RateLimitError, AuthenticationError

from app.agent.catalog_agent import build_agent
from app.agent.groq_model import GroqIntentModel, ModelExtractionError
from app.agent.plans import plan_schema
from app.domain.policy_rules import context_schema
from test_agent import catalog, searches
from test_multi_intent import SyntheticPolicy


def generation_task(identifier='c', intent='catalog_lookup', **overrides):
    fields = {
        'catalog_lookup': dict(name=None, category=None, category_id=None, max_price=None,
                               specs=None, purchasable_only=True, payment_method=None),
        'policy_question': dict(topic='withdrawal', context={key: None for key in context_schema()['properties']}),
        'order_status': dict(order_reference=None),
    }
    return {'id': identifier, 'intent': intent, 'parameters': {**fields[intent], **overrides}}


def payload(*tasks, disposition='execute'):
    return {'schema_version': '2', 'disposition': disposition, 'tasks': list(tasks)}


def client_response(value, *, finish='stop', refusal=None):
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=finish, message=SimpleNamespace(
            content=value if isinstance(value, str) else json.dumps(value), refusal=refusal))])
    return client


def test_groq_multi_intent_uses_minimal_payload_and_real_graph(catalog, searches):
    client = client_response(payload(
        generation_task(name='Aurora Nylon', max_price='1000.00', specs=[{'key': 'strings', 'value': 'nylon'}]),
        generation_task('p', 'policy_question', topic='hours'),
        generation_task('o', 'order_status', order_reference='SYNTHETIC-1')))
    reply = build_agent(catalog=catalog, model=GroqIntentModel(client=client),
                        policy_service=SyntheticPolicy()).invoke(
                            session_id='DO_NOT_TRANSMIT_SESSION',
                            message='Tem Aurora Nylon até R$ 1.000,00, com cordas nylon? Qual o horário e meu pedido?')
    assert [r.status for r in reply.task_outcomes] == ['ok', 'ok', 'authorization_required']
    assert reply.products[0]['name'] == 'Aurora Nylon'
    assert reply.products[0]['price_brl'] == '1000.00'
    assert searches[0][0]['max_price'].as_tuple().exponent == -2
    assert searches[0][0]['specs'] == {'strings': 'nylon'}
    request = client.chat.completions.create.call_args.kwargs
    assert client.chat.completions.create.call_count == 1
    assert request['model'] == 'openai/gpt-oss-20b'
    assert request['response_format']['json_schema']['strict'] is True
    assert [m['role'] for m in request['messages']] == ['system', 'user']
    assert 'DO_NOT_TRANSMIT_SESSION' not in json.dumps(request)
    assert 'price_brl' not in json.dumps(request) and 'stock_quantity' not in json.dumps(request)
    assert 'SYNTHETIC DEMO' not in json.dumps(request)
    assert 'tools' not in request


def test_generation_schema_is_closed_without_application_conditionals():
    client = client_response(payload(disposition='clarification'))
    adapter = GroqIntentModel(client=client)
    extracted = adapter.extract(history=['PRIVATE_HISTORY'], message='E aquele?', schema=plan_schema())
    assert extracted == payload(disposition='clarification')
    sent = client.chat.completions.create.call_args.kwargs
    assert 'PRIVATE_HISTORY' not in json.dumps(sent)
    def visit(value):
        if isinstance(value, dict):
            assert not set(value) & {'allOf', 'if', 'then', 'else', 'default'}
            if value.get('type') == 'object':
                assert value['additionalProperties'] is False
                assert set(value['required']) == set(value['properties'])
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(sent['response_format']['json_schema']['schema'])


@pytest.mark.parametrize('kind', ['float_money', 'unknown_field', 'forged_price', 'too_many',
                                 'duplicate_specs', 'duplicate_json_key', 'invalid_type', 'empty',
                                 'missing_field', 'wrong_intent', 'malformed', 'fallback_with_tasks'])
def test_invalid_hosted_output_never_executes_catalog(catalog, searches, kind):
    value = payload(generation_task(name='Aurora Nylon'))
    params = value['tasks'][0]['parameters']
    if kind == 'float_money': params['max_price'] = 1000.0
    if kind == 'unknown_field': params['operation'] = 'execute_arbitrary_code'
    if kind == 'forged_price': params['price_brl'] = '0.01'
    if kind == 'too_many': value['tasks'] *= 5
    if kind == 'duplicate_specs': params['specs'] = [{'key': 'strings', 'value': 'nylon'}] * 2
    if kind == 'duplicate_json_key': value = '{"schema_version":"2","schema_version":"2","disposition":"execute","tasks":[]}'
    if kind == 'invalid_type': params['purchasable_only'] = 'true'
    if kind == 'empty': value['tasks'] = []
    if kind == 'missing_field': del params['name']
    if kind == 'wrong_intent': value['tasks'][0]['intent'] = 'catalog_worker'
    if kind == 'malformed': value = 'not JSON'
    if kind == 'fallback_with_tasks': value['disposition'] = 'unsupported'
    client = client_response(value)
    reply = build_agent(catalog=catalog, model=GroqIntentModel(client=client)).invoke(
        session_id='test', message='Synthetic')
    assert reply.status in ('invalid_request', 'model_error')
    assert searches == [] and reply.products == []
    assert 'execute_arbitrary_code' not in reply.text and '0.01' not in reply.text


@pytest.mark.parametrize('finish,refusal', [('length', None), ('stop', 'Cannot comply')])
def test_truncation_and_refusal_do_not_dispatch(catalog, searches, finish, refusal):
    client = client_response(payload(generation_task()), finish=finish, refusal=refusal)
    reply = build_agent(catalog=catalog, model=GroqIntentModel(client=client)).invoke(
        session_id='test', message='Synthetic')
    assert reply.status == 'model_error' and searches == []


@pytest.mark.parametrize('failure', ['connection', 'timeout', 'rate_limit', 'authentication'])
def test_api_failures_are_sanitized_without_retry_or_dispatch(catalog, searches, failure):
    request = httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions')
    response = httpx.Response(429 if failure == 'rate_limit' else 401, request=request)
    error = {'connection': APIConnectionError(request=request, message='SECRET_MARKER'),
             'timeout': APITimeoutError(request=request),
             'rate_limit': RateLimitError('SECRET_MARKER', response=response, body=None),
             'authentication': AuthenticationError('SECRET_MARKER', response=response, body=None)}[failure]
    client = client_response({})
    client.chat.completions.create.side_effect = error
    model = GroqIntentModel(client=client)
    with pytest.raises(ModelExtractionError) as captured:
        model.extract(history=[], message='Synthetic', schema=plan_schema())
    assert 'SECRET_MARKER' not in str(captured.value)
    reply = build_agent(catalog=catalog, model=model).invoke(session_id='test', message='Synthetic')
    assert reply.status == 'model_error' and searches == []
    assert 'SECRET_MARKER' not in reply.text


@pytest.mark.parametrize('disposition', ['clarification', 'unsupported'])
def test_hosted_fallbacks_never_dispatch(catalog, searches, disposition):
    client = client_response(payload(disposition=disposition))
    reply = build_agent(catalog=catalog, model=GroqIntentModel(client=client)).invoke(
        session_id='test', message='Synthetic')
    assert reply.status == disposition and searches == []


def test_default_client_has_bounded_timeout_no_retries_and_safe_missing_key(monkeypatch):
    import app.agent.groq_model as module
    constructor = Mock()
    monkeypatch.setattr(module, 'Groq', constructor)
    monkeypatch.setenv('GROQ_API_KEY', 'SYNTHETIC_KEY')
    model = GroqIntentModel()
    assert model.client is constructor.return_value
    assert constructor.call_args.kwargs == {'timeout': 20.0, 'max_retries': 0}
    constructor.side_effect = RuntimeError('SECRET_MARKER')
    with pytest.raises(ModelExtractionError, match='unavailable'):
        GroqIntentModel()


def test_one_question_command_uses_local_catalog_without_exporting_sources(catalog, tmp_path, monkeypatch, capsys):
    from contextlib import nullcontext
    import app.ask as command
    client = client_response(payload(generation_task(name='Aurora Nylon')))
    monkeypatch.setattr(command, 'Groq', lambda **kwargs: nullcontext(client))
    monkeypatch.setenv('LANGSMITH_TRACING', 'true')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'true')
    args = ['--products', str(tmp_path / 'products.csv'),
            '--categories', str(tmp_path / 'categories.csv'), 'Vocês têm Aurora Nylon?']
    assert command.main(args) == 0
    assert '1000.00' in capsys.readouterr().out
    request = client.chat.completions.create.call_args.kwargs
    assert str(tmp_path) not in json.dumps(request)
    import os
    assert os.environ['LANGSMITH_TRACING'] == 'false'
    client.chat.completions.create.side_effect = RuntimeError('SECRET_MARKER')
    assert command.main(args) == 1
    output = capsys.readouterr().out
    assert 'SECRET_MARKER' not in output and 'model_error' in output
