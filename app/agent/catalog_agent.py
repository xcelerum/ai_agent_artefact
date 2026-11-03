"""Bounded multi-intent StateGraph; application code owns execution and facts."""

from dataclasses import dataclass, field
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from app.agent.contracts import (
    AgentReply, GraphState, Intent, PolicyEvidence, PolicyLookup,
    StructuredIntentModel, WorkerState,
)
from app.agent.plans import plan_schema, validate_plan
from app.agent.responses import aggregate, fixed_reply, render_reply
from app.agent.workers import catalog_lookup, order_authorization_gate, policy_lookup
from app.domain.catalog import Catalog
from app.domain.pricing import PricingService


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

    def invoke(self, *, session_id: str, message: str) -> AgentReply:
        try:
            state = self._graph.invoke({'session_id': session_id, 'message': message},
                                       config={'recursion_limit': 12, 'max_concurrency': 4})
            reply = state['final_reply']
            if not isinstance(reply, AgentReply):
                raise ValueError('Missing application reply')
            return reply
        except Exception:
            return fixed_reply('tool_error')

    def _prepare_turn(self, state: GraphState) -> dict:
        valid = (type(state['session_id']) is str and bool(state['session_id'].strip())
                 and len(state['session_id']) <= 200 and type(state['message']) is str
                 and bool(state['message'].strip()) and len(state['message']) <= 4000)
        return {'raw_plan': None, 'validated_plan': (), 'task_results': [], 'ordered_results': [],
                'routing_outcome': 'pending' if valid else 'invalid_request'}

    def _interpret_intents(self, state: GraphState) -> dict:
        if state['routing_outcome'] != 'pending':
            return {}
        try:
            return {'raw_plan': self.model.extract(history=[], message=state['message'], schema=plan_schema())}
        except Exception:
            return {'routing_outcome': 'model_error'}

    def _validate_plan(self, state: GraphState) -> dict:
        if state['routing_outcome'] != 'pending':
            return {}
        try:
            disposition, tasks = validate_plan(state['raw_plan'], self.catalog)
            return {'validated_plan': tasks, 'routing_outcome': disposition}
        except (ValueError, TypeError, RecursionError, OverflowError):
            return {'validated_plan': (), 'routing_outcome': 'invalid_request'}

    def _route_plan(self, state: GraphState) -> Literal['dispatch_tasks', 'render_response']:
        return 'dispatch_tasks' if state['routing_outcome'] == 'execute' else 'render_response'

    def _dispatch_tasks(self, state: GraphState) -> dict:
        # The conditional edge below performs scheduling, never business execution.
        return {}

    def _send_tasks(self, state: GraphState) -> list[Send]:
        nodes = {Intent.CATALOG: 'catalog_worker', Intent.POLICY: 'policy_worker', Intent.ORDER: 'order_worker'}
        return [Send(nodes[task.intent], {'task': task}) for task in state['validated_plan']]

    def _catalog_worker(self, state: WorkerState) -> dict:
        return {'task_results': [catalog_lookup(state['task'], self.catalog, self.pricing_service)]}

    def _policy_worker(self, state: WorkerState) -> dict:
        return {'task_results': [policy_lookup(state['task'], self.policy_service)]}

    def _order_worker(self, state: WorkerState) -> dict:
        return {'task_results': [order_authorization_gate(state['task'])]}

    def _aggregate_results(self, state: GraphState) -> dict:
        status, ordered = aggregate(state['validated_plan'], state['task_results'])
        return {'routing_outcome': status, 'ordered_results': ordered}

    def _render_response(self, state: GraphState) -> dict:
        return {'final_reply': render_reply(state['routing_outcome'], state['ordered_results'])}


def build_agent(*, catalog: Catalog, model: StructuredIntentModel,
                policy_service: PolicyLookup | None = None,
                pricing_service: PricingService | None = None) -> CatalogAgent:
    return CatalogAgent(catalog=catalog, model=model, policy_service=policy_service,
                        pricing_service=pricing_service)
