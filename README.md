# Empório da Música — deterministic catalog

Artefact AI Engineer challenge: build a Python customer-support prototype for a
fictional music-instrument store. **Milestone 1 implements only the deterministic
catalog foundation**, not a complete customer-support agent.

## Implemented

- Typed UTF-8 CSV loading for products and categories, with `Decimal` money,
  ISO dates, validated statuses, unique IDs and category references.
- All-or-nothing validation: malformed data raises `CatalogDataError` without raw
  cell contents. Empty descriptions and `{}` specs are allowed.
- Combined name, category/name or ID, inclusive maximum table price, and spec
  filters. Text matching ignores case/accents and trims surrounding whitespace;
  names/categories use substrings, spec values use exact normalized matches.
- Spec keys are normalized too. Unsupported keys and duplicate normalized query
  keys raise `ValueError`; duplicate normalized source keys are invalid data.
  Supported keys come from every product in the loaded snapshot. A supported
  filter with no matches returns an empty tuple; missing specs are not invented.
- Purchasable means `status == "active"` **and** `stock_quantity > 0`.
  Informational searches can include unavailable listings explicitly.
- Explicit JSON-safe serialization: decimal prices and dates become strings,
  statuses become enum values, and immutable specs become copied dictionaries.

This is a **catalog snapshot, not live stock**. Positive stock alone never makes
coming-soon or discontinued products purchasable. No matches means no matching
listing in the supplied snapshot, not a store-wide availability claim.

## Architecture

`app/data/catalog.py` reads explicitly supplied paths, validates CSV/JSON values
and relationships, and creates immutable catalog records. It reads no customer or
order files. `app/domain/catalog.py` contains the dataclasses, availability rule,
search logic and `serialize_product`. Business logic has no LLM dependency.
Construct untrusted input through `load_catalog`, not directly through dataclasses.

The following is a Python API usage example requiring local product/category CSV
files. It is not yet a runnable customer-support demo after cloning. Public
synthetic fixtures and a runnable demo interface are planned.

```python
from decimal import Decimal
from pathlib import Path
from app.data.catalog import load_catalog
from app.domain.catalog import serialize_product

catalog = load_catalog(Path("products.csv"), Path("categories.csv"))
products = catalog.search(category="violoes", max_price=Decimal("1000"),
                          specs={"strings": "nylon"})
json_safe_products = [serialize_product(product) for product in products]
```

## Setup and tests

Use Python **3.14.10**, uv, and default GitHub Codespaces. No Poetry or custom
Dev Container is required. Runtime code uses only the standard library; pytest is
an existing locked development dependency. On a fresh checkout, provision it with:

```sh
uv sync --locked --python 3.14.10
uv run --locked python -m pytest -q
```

The suite can also run without pytest through the standard-library runner:

```sh
.venv/bin/python -B -m unittest discover -s tests -p 'test_*.py' -v
```

Synthetic tests generate invented records in temporary directories and clean up
afterward. No originals are needed for those tests. The optional smoke test reads
only `data/private/desafio_tecnico_ai_eng - products.csv` and the corresponding
`desafio_tecnico_ai_eng - categories.csv`. With both originals present it validates
65 products, 9 categories, 61 purchasable products and availability edge cases;
otherwise it skips. Originals remain local and ignored; do not publish them.

Final verification on 2026-11-02 with Python 3.14.10:

- Existing environment: `uv run --locked python -m pytest -q` reported
  **22 passed, 76 subtests passed in 0.10s**, exit 0, including the private smoke test.
- Public-only temporary copy: `uv sync --locked --python 3.14.10` succeeded, then
  the same pytest command reported **21 passed, 1 skipped, 76 subtests passed in
  0.12s**, exit 0. Only public code, tests and dependency configuration were copied;
  the private smoke test skipped as expected. No original data were copied.

Local verification used the existing environment with uv offline and synchronization
disabled. The isolated copy received its own environment and locked development
dependencies. See [tests/README.md](tests/README.md) for commands and test behaviors.

## Requirements and Verification

Functions below are methods of `CatalogTests` in `tests/test_catalog.py`.
Availability cases use synthetic equivalents of the original snapshot edge cases;
`test_private_snapshot_smoke` additionally checks snapshot counts and invariants.

| Requirement ID | Behavior | Test function(s) | Verified status |
|---|---|---|---|
| CAT-01 | Nylon violões at or below R$1,000; only matching available items | `test_search_combines_filters_and_includes_price_boundary`; `test_search_filters_exclude_independent_active_distractors`; `test_status_and_stock_are_independent` | PASS — isolated domain filters and availability |
| CAT-02 | Active product with zero stock is not purchasable | `test_status_and_stock_are_independent` | PASS |
| CAT-03 | Coming-soon product with positive stock is not purchasable | `test_status_and_stock_are_independent` | PASS |
| CAT-04 | Discontinued product with positive stock is not purchasable | `test_status_and_stock_are_independent` | PASS |
| CAT-05 | Category with no listed products returns no results, without asserting store-wide absence | `test_search_combines_filters_and_includes_price_boundary` | PASS — empty domain result; customer-facing wording NOT IMPLEMENTED |
| CAT-06 | Missing technical specs are not invented; unsupported filters are explicit errors | `test_optional_description_and_unknown_spec_are_not_invented`; `test_missing_requested_specification_excludes_active_product`; `test_search_combines_filters_and_includes_price_boundary`; `test_supported_specification_can_have_no_matches` | PASS — domain behavior |

Ingestion regressions additionally cover malformed quoted CSVs in both tables
(`test_malformed_quoted_csv_is_rejected`), invalid category headers
(`test_invalid_category_csv_schemas_are_rejected`), blank category IDs
(`test_duplicate_primary_keys_and_invalid_categories`), and orphan category
references (`test_invalid_product_fields_fail_without_raw_data`, `category_id=999`).
`test_invalid_source_field_marker_is_not_exposed` places a synthetic sensitive
marker directly inside invalid price, status and JSON fields and verifies that
`CatalogDataError` messages omit it.

The three final strengthening tests passed immediately: **3 passed, 19 deselected,
8 subtests passed**. No production defect or RED phase was observed. Temporary
application copies detected **10/10 selected deliberate mutations**: omitted name,
category name/ID, price or material filters; weakened status/stock predicates;
fabricated empty-category matches; ignored missing specs; and raw-field error
leakage. An unmodified temporary-copy control passed all five selected test methods.
Mutation failures were assertion failures, not import/syntax errors; working files
were unchanged. These checks measure selected test effectiveness, not exhaustive
mutation coverage or historical test-first development.

The regressions passed against the existing implementation; no production-code
change was needed. M1 has specification traceability
and automated verification; a complete historical TDD cycle is **not independently
established**. These tests do not establish conversational or production security.

## Risks and evidence

| Risk | Control | Evidence | Status |
|---|---|---|---|
| Incorrect price or availability | Decimal; active status plus positive stock | Boundary/status tests and snapshot smoke | Tested for catalog scope |
| Ambiguous or malformed specs | Strict JSON and normalized-key duplicate checks | Synthetic regression tests | Tested |
| Publishing private inputs/secrets | Ignore rules; explicit proposed commit list | Git ignore/status checks; human review required | Local guard, not a leak guarantee |
| Prompt injection in source text | Text stored as data; no LLM invocation | Data-storage test only | LLM resistance not evaluated |
| Unauthorized order access | Planned: deny private order queries without verified identity; enforce ownership authorization inside the data-access tool | Future negative authorization tests | NOT IMPLEMENTED |

## Milestone 2 — specified, not implemented

M2 specifies a minimal conversational catalog agent: AGT-01 product interpretation
and validated intent routing; AGT-02 catalog-grounded facts; AGT-03 honest empty
results; AGT-04 isolated in-memory conversation history; AGT-05 safe tool execution
and sanitized failures. The first slice targets AGT-01–03 and invalid arguments
from AGT-05. RAG, policies, authentication, private orders and promotions are excluded.

The proposed LangGraph StateGraph has three nodes: interpret, validate/execute,
and deterministic render. An injected structured-output adapter extracts a closed
intent (`search_products`, `clarification`, or `unsupported`) and catalog-compatible
parameters. Python validates the extraction and selects the operation; factual
output comes exclusively from actual catalog results. Ambiguous and unsupported
requests receive fixed fallbacks. There is no second tool-calling router. Schema
validation does not guarantee semantically correct interpretation.
LangGraph adds complexity over a Python loop but supports future explicit retrieval
and human review workflows. See [the M2 specification](docs/M2.md) for acceptance
criteria, interfaces, trust boundaries, dependency/security sources and test cases.

Planned TDD uses an injected fake model with the real graph, CSV loader and catalog,
then verifies the intent contract, real catalog routing, exact argument propagation,
grounded facts, malformed-intent rejection, empty results and both fallback intents.
RED begins only after dependency approval and environment
preparation. **No M2 tests or agent functionality are implemented; dependency
installation and lockfile auditing await explicit approval.**

## Planned demo authentication — NOT IMPLEMENTED

After the conversational MVP is functional, demo mode will use credential-based
authentication for fictional accounts and exclusively synthetic customers/orders.
Application code will verify passwords and bind the authenticated identity to the
session; chat messages and LLM tool arguments must never change that identity.
Switching users will require logout and a new login, with no identity or
conversational history carried over between sessions. Logout must invalidate access.

Authentication and authorization will run in application code, never in the LLM.
Private order queries without a trusted identity will be denied; ownership checks
inside the data-access tool must block cross-customer access before returning
private information to the LLM. Demo credentials/accounts must only authorize
synthetic orders, never original Artefact customer/order data. This future demo
mechanism is **not production identity verification**.

Planned tests cover valid/invalid credentials, authorized/unauthorized order
lookups, identity spoofing through chat and LLM tool arguments, session isolation,
and access denial after logout. All mechanisms and tests in this section are
**PLANNED / NOT IMPLEMENTED**.

## Limitations and development disclosure

No LLM, LangGraph, RAG, order authorization, policy retrieval, promotions, PIX pricing,
installments or conversational CLI is implemented yet. Prices are table prices;
sub-cent source amounts are rejected without rounding. Specs support string values
only, with no aliases or unit conversion. There is no freshness guarantee,
production authentication, legal adjudication or compliance certification.
Full adversarial LLM evaluations belong to a future milestone.
Storing untrusted content as data does not establish LLM prompt-injection resistance.

AI-assisted development (OpenAI Codex) is used for implementation, tests and
review preparation. Human review and approval remain required before committing
or publishing; test results do not replace that review.
