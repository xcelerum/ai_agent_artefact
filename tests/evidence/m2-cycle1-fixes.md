# M2 Cycle 1 — targeted corrections F01, F03 and F04

Branch: feat/agent-m2; HEAD at start: 03567da. Existing uncommitted Cycle 1 work
was preserved. This file records the corrections separately from the unchanged
historical RED/GREEN evidence. No graph redesign or F02/F05/F06 implementation.

## F01: genuine RED before fingerprint correction

Permanent graph-level regressions were added before production changes:

- test_effective_specs_single_task_preserves_arguments (3 cases).
- test_effective_specs_duplicates_rejected_before_dispatch (9 ordered pairs).
- test_effective_specs_distinct_searches_still_dispatch (3 cases).

They use the real compiled graph and synthetic catalog. A delegating, thread-safe
search spy records attempts before executing real Catalog.search. Node events check
that duplicate plans cannot dispatch business workers. Omitted, null and empty
specs remain valid on their own; distinct product filters still execute independently.
The single-task cases assert exact Decimal conversion and unchanged specs arguments.

Exact RED command:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run --locked python -m pytest -q tests/test_multi_intent.py -k effective_specs --tb=short
```

Exit **1**, actual summary:

```text
4 failed, 11 passed, 50 deselected, 13 warnings in 1.53s
```

All four failures were behavioral assertion failures:

```text
test_effective_specs_duplicates_rejected_before_dispatch[omitted-empty]
test_effective_specs_duplicates_rejected_before_dispatch[null-empty]
test_effective_specs_duplicates_rejected_before_dispatch[empty-omitted]
test_effective_specs_duplicates_rejected_before_dispatch[empty-null]
E   AssertionError: assert 'ok' == 'invalid_request'
```

Pytest IDs combine the right/left parameter labels; the matrix covers all nine
ordered pairs. No import, collection or missing-dependency error caused RED.

The defect: omitted/null specs validate to None, while explicit empty specs stays
{}. M1 treats all three as no spec restriction, but their old fingerprints differ.
The correction canonicalizes only the catalog operation's comparison copy, using
None for an empty spec map. Validated/dispatch parameters remain unchanged.

## F03 and F04 scope

Unsupported wording now describes catalog products, configured policy evidence and
safe order-support guidance, without promising actual retrieval or authenticated
tracking. The exact-message assertion is intentionally updated; unsupported status,
empty products and zero-search assertions remain. README is updated to distinguish
functional catalog, synthetic-only policy service boundary, authorization-required
orders, installed LangGraph, real tests, and unimplemented demo/business capabilities.

## F03: exact-message RED

The new exact fallback expectation was written before changing the template.
Command:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run --locked python -m pytest -q tests/test_agent.py -k fallback_intents --tb=short
```

Exit **1**, actual summary:

```text
1 failed, 1 passed, 25 deselected, 13 warnings in 1.09s
```

The unsupported case failed at `assert reply.text == text`: the application still
returned “This assistant currently supports catalog product searches only.” The
clarification case passed. The new fixed message is:

```text
Supported requests include catalog products, configured policy evidence, and safe order-support guidance. Private order details require trusted authorization.
```

No unsupported-status, empty-products or zero-search assertion was changed.

## Observed GREEN and regression results

All commands below used this exact inline prefix, with synchronization, network
downloads, bytecode and pytest cache writes disabled:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider'
```

| Command after the prefix | Exit | Actual output summary |
|---|---:|---|
| uv run --locked python -m pytest -q tests/test_multi_intent.py -k effective_specs --tb=short | 0 | 15 passed, 50 deselected, 13 warnings in 1.50s |
| uv run --locked python -m pytest -q tests/test_multi_intent.py | 0 | 65 passed, 13 warnings in 5.90s |
| uv run --locked python -m pytest -q tests/test_agent.py | 0 | 27 passed, 13 warnings in 3.77s |
| uv run --locked python -m pytest -q | 0 | 114 passed, 13 warnings, 76 subtests passed in 6.13s |

No failures or skips occurred in the full suite. The focused deselections are
intentional `-k` filtering, not skipped tests. The warnings remain LangSmith's
deprecated asyncio.iscoroutinefunction usage; no warning suppression was added.
The full suite includes all 22 M1 methods; its optional local product/category
smoke test ran without printing records. No customer/order CSV was accessed.

`git diff --check` exited **0** with no output. This preservation command also
exited **0** with no output:

```sh
git diff --exit-code 03567da -- app/data/catalog.py app/domain/catalog.py tests/test_catalog.py pyproject.toml uv.lock .python-version tests/evidence/m2-red.md tests/evidence/m2-green.md
```

Starting hashes were recorded for all 64 nonignored tracked/untracked files before
edits. The final comparison found changes only to README.md, app/agent/plans.py,
app/agent/responses.py, tests/test_agent.py and tests/test_multi_intent.py. This new
evidence file is the only new file in this correction task. Thus the preexisting
graph, contracts, workers, docs/M2.md, Cycle 1 RED/GREEN evidence, dependencies and
historical untracked files are unchanged from the task's starting state.

## Scope and review gate

The fingerprint change uses a shallow comparison copy only for validated catalog
parameters. Empty specs canonicalize to None there; the original specs argument
(including {}) still reaches real search unchanged. No semantic search engine,
M1 modification or routing change was introduced. The existing graph's conditional
edges, Send dispatch, reducer, fan-in, worker isolation and factual renderer remain.
Only the unsupported message changes in rendering.

README now describes the actual versioned multi-intent graph, current automated
tests and installed langgraph==1.2.19. It distinguishes synthetic policy evidence
and order denial from unimplemented real retrieval/tracking, live extraction,
history/checkpointing, promotions and conversational CLI. Historical M1 verification
is labeled historical rather than presented as the current full-suite result.

F01, F03 and F04 are resolved within this scope. No behavioral assertions were
weakened, removed, skipped or rewritten beyond the authorized exact-message change.
F02 timeouts, F05 diagnostics and F06 broader regression improvements remain
untouched and deferred. No dependency was added/installed, no private data was
staged or exposed, and no commit, stage, push, PR or merge was performed. The index
was empty at the preservation check. Cycle 2 and live provider work did not begin.

Verdict: **READY FOR CYCLE 1 COMMIT, subject to human review and explicit commit
authorization**. The safe policy boundary/order handoff do not complete full M2;
known live-model, memory, real-policy, commercial-rule and operational limitations
remain as documented in the comprehensive review.
