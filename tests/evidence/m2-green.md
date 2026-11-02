# M2 — first GREEN increment

Observed on 2026-11-02, branch `feat/agent-m2`, following RED commit `a26e46e`.
Existing tests and assertions were preserved; no packages, lockfile or M1 code changed.
No commit, push, PR, merge, live LLM integration or M3 work was performed.

## Commands and results

Focused acceptance command, exit **0**:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run --locked python -m pytest -q tests/test_agent.py
```

Actual summary: `27 passed, 13 warnings in 1.43s`.
All original RED cases now exercise the compiled LangGraph and real synthetic
catalog flow successfully, including the delegating search spy assertions.

Complete regression command, exit **0**:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run --locked python -m pytest -q
```

Actual summary: `49 passed, 13 warnings, 76 subtests passed in 1.35s`.
All 22 M1 test methods still pass, including the optional private snapshot smoke
test. No original records were printed or transmitted externally.

Both runs reported the existing LangSmith warning:

```text
DeprecationWarning: 'asyncio.iscoroutinefunction' is deprecated and slated for removal in Python 3.16; use inspect.iscoroutinefunction() instead
```

Supplemental one-off synthetic probe, exit **0**, executed with a local inline
Python program on standard input using:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 uv run --locked python -
```

The program loaded two invented CSV catalogs from temporary directories and used
two sequence-driven fake models. It interleaved calls with the same session ID,
mutated a returned price/spec and the adapter's schema, then checked subsequent
results, invalid/empty/fallback outcomes and call counts. A synthetic exception
marker was absent from model/catalog error replies. A raw JSON duplicate-key
intent was rejected with zero search calls. Actual output:

```text
PASS: instance ownership, fresh state/schema, reply mutation isolation, sanitized failures, duplicate JSON rejection
```

This probe is supplementary observed evidence, not a permanent regression test
or a claim of exhaustive concurrency/session/error coverage.

Preservation check, exit **0**:

```sh
git diff --exit-code -- tests/test_agent.py app/domain/catalog.py app/data/catalog.py pyproject.toml uv.lock .python-version
```

`git diff --check` also passed before the evidence/documentation updates.

## Principal implementation decisions

- Preserve START → interpret → validate_execute → render → END, with no alternate
  router, ToolNode, retry loop or second model call.
- Frozen CatalogAgent instances compile their own bound node methods. Model and
  catalog are instance dependencies, with no module-level mutable state.
- Each invoke supplies a fresh state dictionary. There is no checkpointer, cache,
  stored history or prior results; the adapter receives history=[] and a fresh
  schema. Returned product serialization copies specs, keeping reply mutation
  separate from catalog records and later replies.
- The schema describes a closed intent enum and conditional parameter shape.
  Application code independently validates envelope keys, parameter keys/types,
  strings, limits, booleans, positive IDs, exact monetary strings and spec filters.
  Raw JSON rejects duplicate keys; decoded spec objects reject normalized duplicates.
  The existing catalog remains the final supported-spec/domain validator.
- Only search_products maps to Catalog.search. Clarification and unsupported use
  fixed messages without searching. Decimal conversion uses source strings directly.
- Catalog results alone populate serialized product facts and plain-text rendering.
  Model facts/results/prose are rejected as unknown fields. AgentReply is returned,
  never graph state. Errors expose fixed text and empty products.

## Remaining scope and risks

AGT-01/02/03 and the tested AGT-05 invalid-input/fallback slice are GREEN with a fake
adapter. AGT-04 history/follow-ups/session lifecycle is not implemented. Structured
schema validity does not establish semantic correctness of model interpretation.
No provider, live AI demo, RAG, policies, promotions, orders or authentication exists.

Broader AGT-05 needs permanent tests for model/tool/unexpected failures, raw JSON,
resource limits and adversarial/source text. The one-off probe does not replace
those tests. Blocking adapter timeouts/cancellation are not implemented. Catalog
data remain a snapshot. Output is plain text/data; future UIs must render it safely.
Dependencies were neither changed nor re-audited here; previous audit evidence
retains its original limitations. Passing tests do not establish production security.

The next smallest increment is permanent boundary regressions for dependency
ownership, repeated invocations/stale facts and sanitized failures, before adding
AGT-04 history or selecting a provider. Stop for human review.
