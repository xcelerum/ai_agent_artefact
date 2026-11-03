# Cycle 2A — targeted overall-status correction

## Contract and scope

Only response aggregation changed in production. Cardinality/integrity errors
still take precedence. Single-task status mapping remains unchanged (`error` maps
to `tool_error`). For multiple tasks:

1. Errors, unavailable services, authorization blocks or other non-success statuses
   retain `partial_failure` when at least one valid result exists, otherwise `failed`.
2. Valid evidence requiring clarification yields `clarification`.
3. Otherwise valid evidence requiring staff review yields `review_required`.
4. Successful results yield `ok`, or `no_matches` when every task has no matches.

Clarification takes precedence over review because missing facts must be obtained
first. Both are valid evidence outcomes, not execution failures. Per-task statuses,
ordered outcomes, products and factual rendering are unchanged. Graph topology,
model contracts, promotion calculations and PDF extraction were not changed.

## Commands and genuine RED

All pytest commands below used this exact prefix:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider'
```

Before modifying production, added two compiled-graph regression cases and twelve
supplementary aggregation precedence cases to `tests/test_cycle2a.py`.

```sh
uv run --locked python -m pytest -q tests/test_cycle2a.py -k 'not_failures or overall_status_precedence' --tb=short
```

Exit 1: **7 failed, 7 passed, 11 deselected, 13 warnings in 4.07s**.
Relevant actual failures:

```text
assert 'partial_failure' == 'clarification'
assert 'partial_failure' == 'review_required'
assert 'failed' == 'clarification'
assert 'failed' == 'partial_failure'
```

Both real compiled-graph cases failed on overall status. Supplementary failures
also reproduced review-plus-clarification and valid-assessment-plus-error/service
unavailability classification. No import/collection errors or missing dependencies.

## GREEN and intentional assertion migration

Changed only `aggregate()` in `app/agent/responses.py`: count clarification/review
as valid outcomes and apply explicit precedence after failure classification.
Updated the existing combined pricing/policy assertion from `partial_failure` to
`review_required`, preserving all factual, ordering, fan-in and safety assertions.

```sh
uv run --locked python -m pytest -q tests/test_cycle2a.py --tb=short
```

Exit 0: **25 passed, 13 warnings in 7.13s**.

First full run reported **1 failed, 185 passed, 13 warnings, 76 subtests passed
in 22.10s**. The only failure was the original-source smoke's obsolete assertion:

```text
tests/test_cycle2a_private.py:65
AssertionError: 'clarification' != 'partial_failure'
```

That invocation ran pytest followed by `git diff --check`; its shell exit was 0
from the latter command, not evidence of a passing pytest run. Updated only the
obsolete smoke expectation to `clarification`; no other smoke assertions changed.

Final full command, executed standalone:

```sh
uv run --locked python -m pytest -q
```

Exit 0: **186 passed, 13 warnings, 76 subtests passed in 16.48s**.
No failures/skips. Warnings remain LangSmith's existing asyncio deprecations.
`git diff --check` separately exited 0 with no output.

## Files touched by this correction

- `app/agent/responses.py`: aggregation classification only.
- `tests/test_cycle2a.py`: 14 new parameterized cases and one intentional expectation migration.
- `tests/test_cycle2a_private.py`: one intentional expectation migration.
- `tests/evidence/m2-cycle2a-status-fix.md`: this evidence.

Other existing Cycle 2A work remains uncommitted and unchanged by this correction.
No dependencies, historical evidence, graph topology or unrelated tests changed.
No staging, commit, push, PR or merge was performed. Stop for review.
