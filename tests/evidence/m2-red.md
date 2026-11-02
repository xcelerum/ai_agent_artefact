# M2 — first genuine RED increment

Observed on 2026-11-02 in GitHub Codespaces, Python 3.14.10, uv 0.13.6.
No GREEN behavior, provider adapter, commit, push or PR was implemented/created.
Historical untracked materials and M1 source/tests were preserved.

## Files in this increment

- `pyproject.toml`: only new direct runtime dependency is `langgraph==1.2.19`.
- `uv.lock`: uv-resolved dependency graph; existing Python constraint preserved.
- `tests/test_agent.py`: tests written before the interface skeleton.
- `app/agent/catalog_agent.py`: importable interface and real graph wiring only;
  all three nodes raise NotImplementedError. Existing empty __init__.py preserved.
- `docs/M2.md`: corrected LangGraph attribution and recorded observed status.
- `tests/evidence/m2-red.md`: this evidence record.

`.python-version` remains `3.14.10`. M1 catalog modules and test_catalog.py have
no diff. README changes predate this increment; README was not edited here.

## Dependency setup and security gate

Exact installation command:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_PYTHON_DOWNLOADS=never uv add --python 3.14.10 'langgraph==1.2.19'
```

The sandbox attempt exited 2 with DNS failure fetching the public PyPI index.
The same command was retried with approved network escalation and exited 0:

```text
Resolved 45 packages in 535ms
Prepared 37 packages in 329ms
Installed 37 packages in 501ms
```

uv warned that hardlinks were unavailable and fell back to copying files. This
was not an installation failure. No unrelated or provider SDK was added directly.

Exact audit command:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_PYTHON_DOWNLOADS=never uv audit --locked --output-format json
```

The sandbox attempt exited 2 because api.osv.dev DNS resolution failed. The same
command with approved network escalation exited 0 and returned:

```json
{
  "schema": {"version": "preview"},
  "summary": {
    "audited_packages": 44,
    "vulnerabilities": 0,
    "adverse_statuses": 0
  },
  "vulnerabilities": [],
  "adverse_statuses": []
}
```

uv reported that audit and its JSON schema are experimental. The service was OSV
(`https://api.osv.dev/v1/querybatch`). Zero reported vulnerabilities is a dated
database result, not a guarantee that packages are vulnerability-free.

Resolved runtime tree reviewed using this exact command, exit 0:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never uv tree --locked --no-dev
```

The resolved LangGraph, checkpoint, prebuilt, SDK, core, Pydantic and xxhash versions
match the reviewed candidates. They exceed the fixed versions documented for the
specific historical deserialization, URL routing and Pydantic validation advisories
in docs/M2.md. OSV reported no findings for the resolved graph. No material
compatibility/security blocker was observed for this local RED increment.
SDK and LangSmith remain transitive dependencies; remote deployments, tracing,
checkpoints, caches and untrusted object deserialization are not used by the skeleton.
Native-code and supply-chain risks remain; no source-code security audit, live-model
evaluation, exhaustive platform test or production security claim is made.

Installed environment inventory, observed via importlib.metadata (not inferred
from candidate versions):

```text
annotated-types==0.8.0
anyio==4.16.0
certifi==2026.10.23
charset-normalizer==3.5.2
distro==1.9.0
h11==0.16.0
httpcore==1.0.9
httpcore2==2.16.0
httpx==0.28.1
httpx2==2.16.0
idna==3.20
iniconfig==2.3.1
jsonpatch==1.40
jsonpointer==3.7
langchain-core==1.7.4
langchain-protocol==0.0.20
langgraph==1.2.19
langgraph-checkpoint==4.3.1
langgraph-prebuilt==1.1.1
langgraph-sdk==0.4.11
langsmith==0.14.17
orjson==3.13.0
ormsgpack==1.13.0
packaging==26.3
pluggy==1.7.0
pydantic==2.14.2
pydantic_core==2.50.2
Pygments==2.21.0
pytest==9.2.0
PyYAML==6.0.3
requests==2.34.2
requests-toolbelt==1.0.0
sniffio==1.3.1
tenacity==9.2.1
truststore==0.10.5
typing-inspection==0.4.4
typing_extensions==4.16.0
urllib3==2.8.0
uuid_utils==0.19.0
websockets==17.4
xxhash==4.0.2
zstandard==0.25.0
```

The lock/audit includes platform-conditional packages in addition to the installed
Linux environment. Audit counts and installed inventory counts are different scopes.

## Import and StateGraph compatibility probe

Exact command, exit 0 (local code, no remote script):

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 uv run --locked python - <<'PY'
import sys
from importlib.metadata import version, distributions
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
import langchain_core, pydantic, xxhash, ormsgpack, orjson
assert sys.version_info[:3] == (3, 14, 10)
builder = StateGraph(dict)
builder.add_node('probe', lambda state: {'verified': True})
builder.add_edge(START, 'probe')
builder.add_edge('probe', END)
graph = builder.compile()
assert isinstance(graph, CompiledStateGraph)
assert graph.invoke({}) == {'verified': True}
print('Python', sys.version.split()[0])
print('Imports and StateGraph compile/invoke: PASS')
for dist in sorted(distributions(), key=lambda d: d.metadata['Name'].lower()):
 print(dist.metadata['Name'] + '==' + dist.version)
PY
```

Relevant output:

```text
Python 3.14.10
Imports and StateGraph compile/invoke: PASS
```

The inventory above is the rest of this command's output. This verifies the local
imports and basic graph compile/invoke, not every framework feature or platform.

## Test cases and intended missing behavior

The seven test functions expand to 27 cases. They use invented CSV fixtures loaded
by real load_catalog and a fake StructuredIntentModel returning only untrusted
extraction objects. The public build_agent/invoke flow enters a CompiledStateGraph.
The search spy records attempted calls before delegating to real Catalog.search,
so a domain ValueError cannot conceal an attempted search in zero-call assertions.

| Test name | Cases | Requirement | Expected behavior still missing |
|---|---:|---|---|
| test_search_intent_routes_with_exact_validated_arguments | 1 | AGT-01 | Extract once with the closed schema and original message; real search with exact combined filters, Decimal price and default purchasable flag; correct product returned. |
| test_catalog_facts_preserve_identity_price_and_availability | 1 | AGT-02 | Real informational results preserve exact names, IDs, prices, status/stock and availability; text labels snapshot facts. |
| test_fabricated_model_facts_cannot_reach_customer | 2 | AGT-02/05 | Reject fabricated-prose and forged-results envelope fields; no search or model-authored commercial output. |
| test_empty_search_is_truthful_and_snapshot_scoped | 1 | AGT-03 | Real empty tuple yields no_matches and exact snapshot-scoped sentence. |
| test_invalid_arguments_never_execute_search | 16 | AGT-05 | Reject invalid types/money/specs before search, with invalid_request and empty products. |
| test_malformed_intents_never_execute_search | 4 | AGT-01/05 | Unknown intent, invalid/missing parameters and list/multiple-intent structures cannot execute search. |
| test_fallback_intents_never_execute_search | 2 | AGT-01/05 | Clarification/unsupported yield their specified fixed templates, empty products and zero catalog calls. |

Invalid argument case IDs: float-money, integer-money, negative-money, nan-money,
infinite-money, exponent-money, subcent-money, boolean-id, string-id,
string-boolean, null-boolean, blank-name, list-specs, numeric-spec,
unknown-parameter, duplicate-normalized-spec.

All 27 failures are expected because the first graph node has no behavior.
They are **NotImplementedError failures**, not missing-dependency/import/syntax
or collection errors. The application-level routing/rendering assertions are
present but not yet reached. This does not establish that each downstream boundary
has independently failed an assertion, nor that the eventual tests are exhaustive.

## Actual RED commands and relevant failure output

Exact focused command, exit 1:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run --locked python -m pytest -q tests/test_agent.py --tb=short
```

Representative actual failure excerpt (repeated stack frames and transient task
IDs omitted; no private records, session trace dumps or secrets retained):

```text
___________ test_search_intent_routes_with_exact_validated_arguments ___________
tests/test_agent.py:92: in test_search_intent_routes_with_exact_validated_arguments
    reply, model = invoke(catalog, search_intent(
tests/test_agent.py:79: in invoke
    reply = agent.invoke(session_id='synthetic-session', message=message)
app/agent/catalog_agent.py:48: in invoke
    return self._graph.invoke({'session_id': session_id, 'message': message})
app/agent/catalog_agent.py:29: in _interpret
    raise NotImplementedError('M2 RED: structured intent interpretation is not implemented')
E   NotImplementedError: M2 RED: structured intent interpretation is not implemented
27 failed, 13 warnings in 3.77s
```

The full suite was then run to confirm M1 remains intact alongside RED, exit 1:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run --locked python -m pytest -q --tb=line
```

Actual summary:

```text
27 failed, 22 passed, 13 warnings, 76 subtests passed in 1.22s
```

Every M2 failure was the same NotImplementedError at the interpret node.

## Existing M1 regression result

Exact command after installation, before adding RED tests, exit 0:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run --locked python -m pytest -q tests/test_catalog.py
```

Actual output summary:

```text
22 passed, 13 warnings, 76 subtests passed in 0.09s
```

The 13 warnings in M1 and RED runs came from LangSmith's deprecated use of
asyncio.iscoroutinefunction, scheduled for removal in Python 3.16. They did not
prevent Python 3.14 execution. The optional local private snapshot smoke test ran;
no records were exposed. The full-suite run above also kept all M1 tests passing.

## Stop point and remaining work

The smallest proposed GREEN is to replace the three node stubs: extract once
through the injected adapter; strictly validate/map intents and invoke real search;
render safe fixed fallbacks/errors and serialized catalog facts. Keep existing
graph wiring and public interface, with no provider, generic ToolNode or second router.
The skeleton's AgentState/return conversion will need completing as part of GREEN.

No functional intent extraction, validation, catalog routing, rendering or session
history is implemented. All planned M2 cases beyond this increment remain open,
including full session isolation, model/tool failures, raw JSON duplicate handling,
size limits and adversarial/live-model evaluations. Schema shape does not establish
semantic interpretation accuracy. Stop here for human review; no GREEN or M3.
