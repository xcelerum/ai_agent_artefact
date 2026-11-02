# M2 Cycle 1 — multi-intent RED

Baseline: branch feat/agent-m2, HEAD 03567da (separate first GREEN), ancestor RED
a26e46e preserved. No tracked/staged changes before this cycle; historical untracked
files untouched. Existing complete suite observed: exit 0, `49 passed, 13 warnings,
76 subtests passed in 1.44s`.

SDD amendment and tests were written before changing production code. Existing
test_agent.py migrates extraction envelopes and the schema assertion to version 2;
all commercial facts, availability, empty-result, invalid-input and fallback
assertions remain. No v1 router is retained. The new public reply gains task_outcomes
and build_agent gains optional policy_service. Historical evidence is unchanged.

All pytest runs used this exact environment prefix:

```sh
export UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider'
```

Commands (prefix applied inline during execution):

| Command | Exit | Actual result |
|---|---:|---|
| uv run --locked python -m pytest -q | 0 | 49 passed, 13 warnings, 76 subtests passed in 1.44s (baseline) |
| uv run --locked python -m pytest -q tests/test_multi_intent.py --tb=line | 1 | 50 failed, 13 warnings in 1.52s |
| uv run --locked python -m pytest -q tests/test_agent.py --tb=line | 1 | 5 failed, 22 passed, 13 warnings in 1.39s |

Representative actual failure output:

```text
TypeError: build_agent() got an unexpected keyword argument 'policy_service'
AssertionError: assert 'invalid_request' == 'ok'
AttributeError: 'AgentReply' object has no attribute 'task_outcomes'
AssertionError: assert 'invalid_request' == 'partial_failure'
AssertionError: assert 'invalid_request' == 'authorization_required'
AssertionError: assert 'invalid_request' == 'aggregation_error'
```

The migrated tests also reported `assert 0 == 1` for actual search counts and
invalid_request instead of clarification/unsupported. Those failures demonstrate
that the old implementation does not understand v2; valid v2 requests do not yet
execute real search. The absent keyword/reply field are new functional interface
gaps, not dependency, syntax, import or test-collection failures. Some downstream
assertions remain unreached at RED, which is not independent failure evidence for
every planned invariant.

Before implementation, the same-worker test was clarified to reuse its existing
agent and inspect the schema actually passed to the adapter, without changing
acceptance assertions. The focused suite was rerun with `--tb=no`, exit 1:
`50 failed, 13 warnings in 1.62s`. Production code was still unchanged.

New tests cover requested domains/worker counts, same-worker Send dispatch,
semantic product grouping representation, four-task bounds, invalid plans,
fallback paths, synthetic policy evidence/unavailability, order denial without CSV
reads, corrupt fan-in results, partial failure, repeated turns and instance/mutation
isolation. Two completion-order cases use a Barrier and Event plus graph-node
superstep observations to require real concurrent execution and single fan-in.
No actual LLM semantics or real policy retrieval is claimed.

Warnings are the same 13 LangSmith asyncio.iscoroutinefunction deprecations.
No package or lockfile changes, private CSV access, commits or remote writes.
