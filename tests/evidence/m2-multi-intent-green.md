# M2 Cycle 1 — multi-intent GREEN

Branch: feat/agent-m2. Baseline first GREEN 03567da and RED a26e46e remain in history.
See m2-multi-intent-red.md for the genuine pre-implementation RED: 50 new cases
failed; 5 migrated cases failed and 22 passed. No historical evidence was rewritten.
Tests/specification preceded production changes. No assertions were weakened to
obtain GREEN. The v2 envelope/schema migration preserves all prior behavioral
assertions for catalog facts, Decimal propagation, stock/status, invalid inputs,
empty results and non-executing fallbacks; v1 extraction is no longer accepted.

## Actual verification

Each pytest command below used this exact inline environment prefix:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider'
```

| Command after the prefix | Exit | Actual summary |
|---|---:|---|
| uv run --locked python -m pytest -q tests/test_multi_intent.py tests/test_agent.py --tb=short | 0 | 77 passed, 13 warnings in 2.10s |
| uv run --locked python -m pytest -q tests/test_multi_intent.py | 0 | 50 passed, 13 warnings in 4.12s |
| uv run --locked python -m pytest -q tests/test_catalog.py | 0 | 22 passed, 13 warnings, 76 subtests passed in 0.14s |
| uv run --locked python -m pytest -q | 0 | 99 passed, 13 warnings, 76 subtests passed in 2.49s |
| git diff --check (no prefix needed) | 0 | No output |

The 13 warnings are the existing LangSmith deprecation of
asyncio.iscoroutinefunction, scheduled for removal in Python 3.16. Python/dependencies
were not changed or synchronized. No new security audit was performed.
The optional local M1 private snapshot smoke ran without printing records.

Preservation command, exit 0, no output:

```sh
git diff --exit-code 03567da -- app/domain/catalog.py app/data/catalog.py tests/test_catalog.py pyproject.toml uv.lock .python-version tests/evidence/m2-red.md tests/evidence/m2-green.md
```

## Real graph evidence

Tests instrument bound node entry/exit through the public agent invoke call,
observing config.metadata.langgraph_step. They do not substitute a final answer.
Send workers receive exactly one validated task and no parent/session/raw-plan data.

- Requested-domain cases cover catalog-only, policy-only, order-only, catalog+policy
  and three domains; worker entry counts equal requested tasks exactly. Aggregate
  and render each execute once.
- Two catalog tasks use distinct filters and invoke the real catalog twice in one
  worker superstep, preserving exact prices. Related price/availability questions
  represented by one task execute one search; no live semantic classifier is tested.
- The parallel test runs both controlled orders, a→b and b→a, for two policy tasks
  plus a catalog task. A Barrier(2) requires the two policy worker calls to overlap;
  an Event forces their return order. A sequential implementation would time out.
  Both cases assert three worker entries in one superstep, all worker exits before
  aggregate entry, and exactly one aggregate/render. Reply outcomes and sections
  remain a,b,c in both cases. Synchronization is test-only.
- List concatenation preserves all branch results. Fan-in fault injection through
  actual worker nodes tests missing, duplicate, wrong-position and unknown-ID
  results. Each yields aggregation_error and a categorized outcome for the planned
  task, with no unverified product facts rendered.
- Invalid-plan and zero-task disposition cases assert no dispatch, worker or fan-in
  execution and one render. Invalid plans include schema/version/types, task count,
  task IDs, normalized duplicate operations, unknown intents/fields, domain
  parameters, JSON duplicate keys and payload bounds.
- A failing catalog task retains an independent successful catalog task and returns
  partial_failure without exception text. Missing policy sources preserve valid
  catalog information and explicitly return policy_unavailable.
- The order test guards both builtins.open and Path.open for CSV access after
  synthetic catalog ingestion. It observes zero CSV reads; the order route returns
  authorization_required without disclosing the supplied reference or session ID.
- Instance/turn tests interleave distinct models, catalogs and policy services;
  mutate reply facts; then exercise empty, valid and invalid subsequent turns.
  No previous plan/results/facts leak, and history remains empty.

## Implementation and ownership

Modified app/agent/catalog_agent.py builds prepare_turn → interpret_intents →
validate_plan, conditional dispatch/fallback, Send fan-out, three workers, checked
aggregation and deterministic rendering. Four cohesive modules were added:

- contracts.py: intent enum, validated task/result, policy protocol/evidence,
  parent/worker state and public reply.
- plans.py: actual v2 schema, reused strict catalog validation, full-plan validation
  and normalized duplicate-operation rejection.
- workers.py: real catalog lookup, configured policy evidence boundary, unconditional
  order authorization denial. No private order lookup service exists.
- responses.py: checked fan-in, per-task/overall statuses, ordered factual sections.

CatalogAgent owns bound model/catalog/policy dependencies per instance. No mutable
global buffers, history, cache or checkpointer. Every invoke initializes fresh turn
state; each Send contains its own application-created ValidatedTask. Workers return
new result lists; operator.add concatenates without overwriting parallel writes.
Aggregate validates cardinality and sorts by original position. Returned products
and outcome facts are copied separately, preserving catalog/mutation isolation.

Production size: 529 physical Python lines across five nonempty modules; net +278
relative to the 251-line first GREEN. Four new files contain 416 lines; the revised
orchestrator contains 113. This includes reused validators/rendering and blank lines;
tests, documentation and generated files are excluded.

## Completion limits and stop

Catalog is functional with real M1 filtering, exact money and snapshot semantics.
Policy routing/protocol is functional, but evidence in tests is explicitly synthetic;
there is no production document retrieval. Missing evidence is unavailable. Order
routing is functional only as an authorization-required safe handoff; no identity,
tracking or private lookup is available. Session/reference values never authenticate.

Original PDFs were inspected locally at stream level without exposing content.
No PDF reader/text utility was available, so full text extraction was NOT VERIFIED;
no original policy rule is claimed or implemented. Customer/order CSVs were unread
by this cycle; M1's optional smoke reads only existing product/category files.

Remaining risks: schema validity cannot prove model classification/grouping accuracy;
adapters must preserve/reject duplicate JSON keys before decoding; injected policy
services must support concurrent lookup; no timeout/cancellation or persistence is
implemented. Outputs are plain text/data and require safe rendering by a future UI.
Unknown dependency vulnerabilities, production source security and broader
adversarial/end-to-end behavior remain outside this verification.

Cycle 2 requires separate authorization for history/session lifecycle, original
policy sources, deeper commercial rules and extended failure/business tests. No
provider SDK, live model, RAG, promotions, authentication, transactions, deployment
or M3 was added. No packages, branch, commits, push, PR or merge were created.
Stop for human code review.
