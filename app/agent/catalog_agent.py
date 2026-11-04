"""Bounded multi-intent StateGraph; application code owns execution and facts."""

from dataclasses import dataclass, field, replace
import re
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from app.agent.contracts import (
    AgentReply, GraphState, Intent, PolicyEvidence, PolicyLookup,
    StructuredIntentModel, WorkerState,
    diagnostic, TaskResult, POLICY_TOPICS,
)
from app.agent.plans import plan_schema, validate_plan
from app.agent.responses import aggregate, fixed_reply, render_reply
from app.agent.workers import catalog_lookup, order_authorization_gate, policy_lookup, result
from app.domain.catalog import Catalog
from app.domain.pricing import PricingService
from app.domain.policy_rules import validate_context
from app.agent.semantics import bind_request, NeedClarification, wire_parameters
from app.agent.plans import _decode_plan, _normalized_key


@dataclass(frozen=True)
class CatalogAgent:
    catalog: Catalog
    model: StructuredIntentModel
    policy_service: PolicyLookup | None = None
    pricing_service: PricingService | None = None
    _graph: CompiledStateGraph = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        builder = StateGraph(GraphState)
        for name in ('prepare_turn', 'interpret_intents', 'validate_plan', 'dispatch_tasks',
                     'catalog_worker', 'policy_worker', 'order_worker',
                     'aggregate_results', 'render_response'):
            builder.add_node(name, getattr(self, '_' + name))
        builder.add_edge(START, 'prepare_turn')
        builder.add_edge('prepare_turn', 'interpret_intents')
        builder.add_edge('interpret_intents', 'validate_plan')
        builder.add_conditional_edges('validate_plan', self._route_plan,
                                      ['dispatch_tasks', 'render_response'])
        builder.add_conditional_edges('dispatch_tasks', self._send_tasks,
                                      ['catalog_worker', 'policy_worker', 'order_worker'])
        # All Send tasks are one superstep. Each worker schedules this same fan-in,
        # which runs once at the next superstep after all current tasks finish.
        for worker in ('catalog_worker', 'policy_worker', 'order_worker'):
            builder.add_edge(worker, 'aggregate_results')
        builder.add_edge('aggregate_results', 'render_response')
        builder.add_edge('render_response', END)
        object.__setattr__(self, '_graph', builder.compile())

    def invoke(self, *, session_id: str, message: str, selected_product_ids: tuple[int, ...] = (),
               compare_products: bool = False, policy_context: dict | None = None,
               candidate_product_ids: tuple[int, ...] = (), previous_filters: dict | None = None,
               semantic_mode: bool = False, policy_topic: str | None = None) -> AgentReply:
        try:
            state = self._graph.invoke({'session_id': session_id, 'message': message,
                                        'selected_product_ids': selected_product_ids,
                                        'compare_products': compare_products,
                                        'candidate_product_ids': candidate_product_ids,
                                        'previous_filters': {} if previous_filters is None else previous_filters,
                                        'semantic_mode': semantic_mode,
                                        'policy_topic': policy_topic,
                                        'policy_context': {} if policy_context is None else policy_context},
                                       config={'recursion_limit': 12, 'max_concurrency': 4})
            reply = state['final_reply']
            if not isinstance(reply, AgentReply):
                raise ValueError('Missing application reply')
            return reply
        except Exception as exc:
            diagnostic('graph.invoke', exc)
            return fixed_reply('tool_error')

    def _prepare_turn(self, state: GraphState) -> dict:
        ids = state.get('selected_product_ids', ())
        candidates = state.get('candidate_product_ids', ())
        try:
            topic = state.get('policy_topic')
            if topic is not None and (type(topic) is not str or topic not in POLICY_TOPICS):
                raise ValueError('Invalid previous policy topic')
            claims = validate_context(state.get('policy_context', {}))
            previous = state.get('previous_filters', {})
            if type(previous) is not dict:
                raise ValueError('Invalid previous filters')
            if previous:
                _, prior_tasks = validate_plan({'schema_version': '2', 'disposition': 'execute', 'tasks': [
                    {'id': 'prior', 'intent': 'catalog_lookup', 'parameters': previous}]}, self.catalog)
                previous = wire_parameters(prior_tasks[0].validated_parameters)
        except (ValueError, TypeError) as exc:
            diagnostic('graph.input_context', exc)
            return {'raw_plan': None, 'validated_plan': (), 'task_results': [], 'ordered_results': [],
                    'routing_outcome': 'invalid_request'}
        known = {product.product_id for product in self.catalog.products}
        valid = (type(state['session_id']) is str and bool(state['session_id'].strip())
                 and len(state['session_id']) <= 200 and type(state['message']) is str
                 and bool(state['message'].strip()) and len(state['message']) <= 4000
                 and type(ids) is tuple and len(ids) <= 5
                 and all(type(identifier) is int and identifier in known for identifier in ids)
                 and len(set(ids)) == len(ids)
                 and type(candidates) is tuple and len(candidates) <= 5
                 and all(type(i) is int and i in known for i in candidates)
                 and len(set(candidates)) == len(candidates)
                 and type(state.get('semantic_mode', False)) is bool
                 and type(state.get('compare_products', False)) is bool
                 and (not state.get('compare_products') or len(ids) >= 2))
        if not valid:
            diagnostic('graph.input_validation', input_valid=False)
        return {'raw_plan': None, 'validated_plan': (), 'task_results': [], 'ordered_results': [],
                'policy_context': claims, 'previous_filters': previous, 'clarification': None,
                'routing_outcome': 'pending' if valid else 'invalid_request'}

    def _interpret_intents(self, state: GraphState) -> dict:
        if state['routing_outcome'] != 'pending':
            return {}
        if state.get('compare_products'):
            # The customer selected a known list; no LLM interpretation/data transfer is needed.
            return {'raw_plan': {'schema_version': '2', 'disposition': 'execute', 'tasks': [
                {'id': 'compare', 'intent': 'catalog_lookup', 'parameters': {'purchasable_only': False}}]}}
        try:
            history = [{'selected_product_available': True}] if len(state.get('selected_product_ids', ())) == 1 else []
            if state.get('semantic_mode'):
                history = [{'selected_product_available': len(state.get('selected_product_ids', ())) == 1,
                            'candidate_list_available': bool(state.get('candidate_product_ids')),
                            'previous_search_available': bool(state.get('previous_filters'))}]
            if state.get('policy_topic'):
                history = [{**(history[0] if history else {}), 'policy_topic': state['policy_topic']}]
            return {'raw_plan': self.model.extract(history=history, message=state['message'], schema=plan_schema())}
        except Exception as exc:
            diagnostic('graph.interpret', exc)
            return {'routing_outcome': 'model_error'}

    def _validate_plan(self, state: GraphState) -> dict:
        if state['routing_outcome'] != 'pending':
            return {}
        stage = 'graph.plan_validation'
        raw = state['raw_plan']
        task_count = len(raw['tasks']) if type(raw) is dict and type(raw.get('tasks')) is list else -1
        try:
            disposition, tasks = validate_plan(state['raw_plan'], self.catalog)
            hint = _decode_plan(state['raw_plan']).get('response_hint')
            bound, unresolved = [], []
            # An explicit shipment-state contradiction vetoes assessment, not routing.
            message = ' '.join(_normalized_key(state['message']).split())
            unshipped = re.search(r'\bnao\s+foi\s+enviad[oa]\b', message)
            # Veto an explicit action verb, independent of product filters or phrasing.
            cancellation = any(not re.search(r'\bnao(?:\s+\w+)?\s*$', message[:match.start()])
                               for match in re.finditer(r'\bcancel(?:ar|e|a)\b', message))
            if cancellation:
                # Renderer-only distinction; never accepted as a model response hint.
                hint = 'cancellation'
            for task in tasks:
                if ((unshipped or cancellation) and task.intent == Intent.POLICY
                        and task.validated_parameters['topic'] in ('withdrawal', 'returns')):
                    bound.append(replace(task, clarification='unsupported_action'))
                    unresolved.append(result(task, 'unsupported' if cancellation else 'policy_unavailable',
                                             error='unsupported_action'))
                    continue
                stage = 'graph.binding'
                try:
                    if task.request is not None:
                        task = bind_request(task, catalog=self.catalog,
                            selected=state.get('selected_product_ids', ()), candidates=state.get('candidate_product_ids', ()),
                            previous=state.get('previous_filters', {}), message=state['message'])
                    elif task.intent == Intent.CATALOG and not state.get('semantic_mode'):
                        task = replace(task, product_ids=state.get('selected_product_ids', ()))
                except NeedClarification as exc:
                    diagnostic(stage, exc, task_count=task_count,
                               selected_count=len(state.get('selected_product_ids', ())),
                               candidate_count=len(state.get('candidate_product_ids', ())))
                    task = replace(task, clarification=exc.code)
                    unresolved.append(result(task, 'clarification', facts={'clarification': exc.code}))
                bound.append(task)
            tasks = tuple(bound)
            if state.get('policy_context'):
                stage = 'graph.policy_context'
                tasks = tuple(replace(task, validated_parameters={**task.validated_parameters,
                    'context': validate_context(({**state['policy_context'],
                        **{k: v for k, v in task.validated_parameters.get('context', {}).items() if v is not None}})
                        if state.get('semantic_mode') else {**task.validated_parameters.get('context', {}),
                                                           **state['policy_context']})})
                    if task.intent == Intent.POLICY else task for task in tasks)
            all_unresolved = bool(tasks) and len(unresolved) == len(tasks)
            fallback = ('unsupported' if unresolved and all(r.status == 'unsupported' for r in unresolved) else
                        'policy_unavailable' if unresolved and all(r.status == 'policy_unavailable' for r in unresolved)
                        else 'clarification')
            return {'validated_plan': tasks, 'routing_outcome': fallback if all_unresolved else disposition,
                    'clarification': hint, 'task_results': unresolved,
                    'ordered_results': unresolved if all_unresolved else []}
        except NeedClarification as exc:
            diagnostic(stage, exc, task_count=task_count)
            return {'validated_plan': (), 'routing_outcome': 'clarification', 'clarification': exc.code}
        except (ValueError, TypeError, RecursionError, OverflowError) as exc:
            diagnostic(stage, exc, task_count=task_count)
            return {'validated_plan': (), 'routing_outcome': 'invalid_request'}

    def _route_plan(self, state: GraphState) -> Literal['dispatch_tasks', 'render_response']:
        return 'dispatch_tasks' if state['routing_outcome'] == 'execute' else 'render_response'

    def _dispatch_tasks(self, state: GraphState) -> dict:
        # The conditional edge below performs scheduling, never business execution.
        return {}

    def _send_tasks(self, state: GraphState) -> list[Send]:
        nodes = {Intent.CATALOG: 'catalog_worker', Intent.POLICY: 'policy_worker', Intent.ORDER: 'order_worker'}
        return [Send(nodes[task.intent], {'task': replace(task, query=state['message'])
                     if task.intent == Intent.POLICY else task}) for task in state['validated_plan'] if not task.clarification]

    def _catalog_worker(self, state: WorkerState) -> dict:
        outcome = catalog_lookup(state['task'], self.catalog, self.pricing_service)
        if isinstance(outcome, TaskResult) and outcome.status in ('error', 'no_matches'):
            parameters = state['task'].validated_parameters
            diagnostic('graph.catalog_result', result_code=outcome.error_category or outcome.status,
                       has_name=parameters.get('name') is not None,
                       has_category=parameters.get('category') is not None or parameters.get('category_id') is not None,
                       has_max_price=parameters.get('max_price') is not None,
                       spec_count=len(parameters.get('specs') or {}))
        return {'task_results': [outcome]}

    def _policy_worker(self, state: WorkerState) -> dict:
        return {'task_results': [policy_lookup(state['task'], self.policy_service)]}

    def _order_worker(self, state: WorkerState) -> dict:
        return {'task_results': [order_authorization_gate(state['task'])]}

    def _aggregate_results(self, state: GraphState) -> dict:
        status, ordered = aggregate(state['validated_plan'], state['task_results'])
        return {'routing_outcome': status, 'ordered_results': ordered}

    def _render_response(self, state: GraphState) -> dict:
        return {'final_reply': replace(render_reply(state['routing_outcome'], state['ordered_results']),
                                       clarification=state.get('clarification'))}


def build_agent(*, catalog: Catalog, model: StructuredIntentModel,
                policy_service: PolicyLookup | None = None,
                pricing_service: PricingService | None = None) -> CatalogAgent:
    return CatalogAgent(catalog=catalog, model=model, policy_service=policy_service,
                        pricing_service=pricing_service)
