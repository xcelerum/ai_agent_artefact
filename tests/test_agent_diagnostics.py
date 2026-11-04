"""Opt-in failure diagnostics without user/provider text or source records."""

import logging
from unittest.mock import Mock

import httpx
import pytest
from groq import RateLimitError

from app.agent.catalog_agent import build_agent
from app.agent.contracts import diagnostic, TaskResult
from app.agent.groq_model import GroqIntentModel, ModelExtractionError
from app.agent.plans import plan_schema
from test_agent import catalog, FakeIntentModel


def extraction(parameters=None, request=None):
    task = {'id':'t1','intent':'catalog_lookup','parameters':parameters or {}}
    if request is not None:
        task['request'] = request
    return {'schema_version':'2','disposition':'execute','tasks':[task]}


@pytest.mark.parametrize('enabled', [False, True])
def test_sdk_failure_diagnostics_are_opt_in_and_redacted(monkeypatch, caplog, enabled):
    monkeypatch.setenv('ARTEFACT_DEBUG', '1' if enabled else '0')
    caplog.set_level(logging.WARNING, logger='artefact.diagnostics')
    client = Mock()
    response = httpx.Response(429, request=httpx.Request('POST','https://api.groq.com',
                                                       headers={'Authorization':'Bearer SYNTHETIC_SECRET'}))
    client.chat.completions.create.side_effect = RateLimitError('PRIVATE_PROVIDER_BODY', response=response, body=None)
    with pytest.raises(ModelExtractionError, match='Model interpretation unavailable'):
        GroqIntentModel(client=client).extract(history=['PRIVATE_HISTORY'], message='PRIVATE_CUSTOMER_TEXT', schema=plan_schema())
    if enabled:
        assert 'stage=groq.request' in caplog.text and 'exception_type=RateLimitError' in caplog.text
        assert '"http_status": 429' in caplog.text
    else:
        assert caplog.text == ''
    assert all(value not in caplog.text for value in ('SYNTHETIC_SECRET','PRIVATE_PROVIDER_BODY','PRIVATE_HISTORY','PRIVATE_CUSTOMER_TEXT'))


def test_plan_validation_and_binding_have_separate_stages(catalog, monkeypatch, caplog):
    monkeypatch.setenv('ARTEFACT_DEBUG','1')
    caplog.set_level(logging.WARNING, logger='artefact.diagnostics')
    model = FakeIntentModel(extraction({'max_price':1.25}))
    agent = build_agent(catalog=catalog, model=model)
    assert agent.invoke(session_id='PRIVATE_SESSION', message='PRIVATE_MESSAGE').status == 'invalid_request'
    assert 'stage=graph.plan_validation' in caplog.text and 'exception_type=ValueError' in caplog.text
    caplog.clear()
    model.extraction = extraction(request={'goal':'discover','response':'answer','reference':'selected',
        'positions':[],'anchor':None,'budget':'keep','situation':'general'})
    assert agent.invoke(session_id='PRIVATE_SESSION', message='PRIVATE_MESSAGE').status == 'clarification'
    assert 'stage=graph.binding' in caplog.text and 'exception_type=NeedClarification' in caplog.text
    assert 'PRIVATE_SESSION' not in caplog.text and 'PRIVATE_MESSAGE' not in caplog.text


def test_catalog_failure_result_logs_category_without_changing_reply(catalog, monkeypatch, caplog):
    import app.agent.catalog_agent as module
    monkeypatch.setenv('ARTEFACT_DEBUG','1')
    caplog.set_level(logging.WARNING, logger='artefact.diagnostics')
    monkeypatch.setattr(module, 'catalog_lookup', lambda task, *args: TaskResult(
        task.task_id,task.position,'catalog','error',{},(), 'catalog_error'))
    agent = build_agent(catalog=catalog,model=FakeIntentModel(extraction({'name':'PRIVATE_PRODUCT_QUERY'})))
    reply = agent.invoke(session_id='PRIVATE_SESSION', message='PRIVATE_MESSAGE')
    assert reply.status == 'tool_error'
    assert 'stage=graph.catalog_result' in caplog.text and '"result_code": "catalog_error"' in caplog.text
    assert 'PRIVATE_PRODUCT_QUERY' not in caplog.text


def test_logging_handler_failure_cannot_escape(monkeypatch):
    monkeypatch.setenv('ARTEFACT_DEBUG','1')
    monkeypatch.setattr(logging.getLogger('artefact.diagnostics'), 'warning', Mock(side_effect=RuntimeError('PRIVATE')))
    diagnostic('test.stage', ValueError('PRIVATE'))
