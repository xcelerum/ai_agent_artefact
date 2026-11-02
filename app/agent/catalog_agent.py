"""Importable M2 RED skeleton: graph wiring only, no agent behavior."""

from dataclasses import dataclass
from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.domain.catalog import Catalog


class StructuredIntentModel(Protocol):
    def extract(self, *, history, message: str, schema) -> object: ...


@dataclass(frozen=True)
class AgentReply:
    status: str
    text: str
    products: list[dict[str, object]]


class AgentState(TypedDict):
    session_id: str
    message: str


def _interpret(state: AgentState):
    raise NotImplementedError('M2 RED: structured intent interpretation is not implemented')


def _validate_execute(state: AgentState):
    raise NotImplementedError('M2 RED: intent validation and catalog routing are not implemented')


def _render(state: AgentState):
    raise NotImplementedError('M2 RED: grounded rendering is not implemented')


@dataclass
class CatalogAgent:
    catalog: Catalog
    model: StructuredIntentModel
    _graph: CompiledStateGraph

    def invoke(self, *, session_id: str, message: str) -> AgentReply:
        # All execution stops in the first unimplemented node during this increment.
        return self._graph.invoke({'session_id': session_id, 'message': message})


def build_agent(*, catalog: Catalog, model: StructuredIntentModel) -> CatalogAgent:
    builder = StateGraph(AgentState)
    builder.add_node('interpret', _interpret)
    builder.add_node('validate_execute', _validate_execute)
    builder.add_node('render', _render)
    builder.add_edge(START, 'interpret')
    builder.add_edge('interpret', 'validate_execute')
    builder.add_edge('validate_execute', 'render')
    builder.add_edge('render', END)
    return CatalogAgent(catalog=catalog, model=model, _graph=builder.compile())
