# M2 Cycle 2A — GREEN, integration and source verification

Session continued across 2026-11-02/03. Baseline feat/agent-m2 at e1978e9; earlier
commits/evidence preserved. No commit, stage, push, PR, merge or Cycle 2B work.

## Dependency and source verification

The user explicitly approved pypdf==6.21.4 without extras. Exact command:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_PYTHON_DOWNLOADS=never uv add --python 3.14.10 'pypdf==6.21.4'
```

Sandbox attempt exited 2 with DNS failure; approved escalated retry exited 0:
`Resolved 46 packages in 401ms`; `Installed 1 package in 20ms`; pypdf==6.21.4.
uv fell back from hardlinks to copying; installation succeeded. No unrelated
package/version was added or upgraded. The lock diff adds only pypdf and its root
requirement; Python remains 3.14.10.

`UV_CACHE_DIR=/tmp/artefact-uv-cache UV_PYTHON_DOWNLOADS=never uv audit --locked`
initially exited 2 on sandbox OSV DNS. Approved retry exited 0:

```text
Resolved 46 packages in 1ms
Found no known vulnerabilities and no adverse project statuses in 45 packages
```

Audit is experimental and database-dependent, not a security guarantee. Prior
research/advisory sources are in docs/M2.md. Import probe printed Python 3.14.10
and pypdf 6.21.4; actual original PDF extraction succeeded (challenge 3 pages,
manual 8 pages). No original passage was emitted or sent to a hosted model.

Actual promotion structural checks: exact five-column UTF-8 source, 25 rows, flags
0/1, 4 active rows on 4 products, no duplicate IDs/orphan references/conflicting
active rows; 3 products have multiple history rows. Catalog: 65 products/9 categories.
No promotion start/end fields exist. Only summarized rule facts and metadata are
documented; original rows, campaign descriptions and PDF passages are not fixtures.

## RED to GREEN chronology

See m2-cycle2a-red.md for the first real execution before behavior implementation:
48 failed, 6 passed, exit 1. Failures were explicit NotImplementedError ingestion/
extraction stubs, not missing packages/imports. Six malformed context cases already
passed under the strict old validator. Downstream assertions were not independently
reached at that first RED. Existing regressions after dependency setup, before GREEN:
114 passed, 13 warnings, 76 subtests passed in 2.62s, exit 0.

The initial implementation then passed all 54 new cases in 9.92s, exit 0. Three
further safety tests were written and observed RED before their corrections:
3 failed, 25 deselected, 13 warnings in 3.13s. Corrections require primary topic
body evidence, reject the tested negated PIX-rate text, and clarify conflicting
withdrawal/defect claims. Focused recheck: 3 passed, 25 deselected, 13 warnings in
3.41s, exit 0. No assertions were weakened.

An ensuing policy regression run reported **1 failed, 16 passed, 13 warnings in
18.51s**, exit 1: promotions evidence required §6.1 but the fixture correctly supplied
§6.2 rules. The code's primary section was corrected to §6.2, retaining §6.1 as
supplementary campaign evidence. Tests were unchanged. Final policy/full runs pass.

## Exact test commands and observed results

All pytest commands used this exact inline environment prefix:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider'
```

| Command after prefix | Exit | Actual summary |
|---|---:|---|
| uv run --locked python -m pytest -q tests/test_catalog.py tests/test_agent.py tests/test_multi_intent.py | 0 | 114 passed, 13 warnings, 76 subtests passed in 2.62s (before GREEN) |
| uv run --locked python -m pytest -q tests/test_promotions.py tests/test_store_policy.py tests/test_cycle2a.py --tb=short | 0 | 54 passed, 13 warnings in 9.92s (initial GREEN) |
| uv run --locked python -m pytest -q tests/test_cycle2a_private.py --tb=short | 0 | 1 passed, 13 warnings in 2.04s (initial original-source smoke) |
| uv run --locked python -m pytest -q tests/test_store_policy.py tests/test_cycle2a.py -k 'exception_only_or_heading_only or negated_pix or ambiguous_case_reason' --tb=short | 0 | 3 passed, 25 deselected, 13 warnings in 3.41s |
| uv run --locked python -m pytest -q tests/test_promotions.py | 0 | 29 passed, 13 warnings in 4.35s |
| uv run --locked python -m pytest -q tests/test_cycle2a.py tests/test_cycle2a_private.py | 0 | 12 passed, 13 warnings in 11.02s |
| uv run --locked python -m pytest -q tests/test_agent.py tests/test_multi_intent.py | 0 | 92 passed, 13 warnings in 9.09s |
| uv run --locked python -m pytest -q tests/test_store_policy.py | 0 | 17 passed, 13 warnings in 13.57s (after primary-section correction) |
| uv run --locked python -m pytest -q | 0 | 172 passed, 13 warnings, 76 subtests passed in 18.84s |

No skips/failures in the final full run. Count: 114 existing +29 promotion +17 policy
+11 new integration +1 optional original smoke =172. The existing M1 private smoke
also ran; without originals those two optional smoke tests skip. All 13 warnings
remain LangSmith's deprecated asyncio.iscoroutinefunction; no warning was hidden.

`git diff --check` exited 0 with no output before final documentation. Preservation
check exited 0, no output:

```sh
git diff --exit-code e1978e9 -- app/domain/catalog.py app/data/catalog.py tests/test_catalog.py tests/test_agent.py tests/test_multi_intent.py .python-version tests/evidence/m2-red.md tests/evidence/m2-green.md tests/evidence/m2-multi-intent-red.md tests/evidence/m2-multi-intent-green.md tests/evidence/m2-cycle1-fixes.md
```

## Functional evidence

- Promotions: strict atomic ingestion, history versus active state, duplicate IDs
  including normalized numeric IDs, reference errors and equal/different active
  conflicts. Invalid flags/percentages and malformed CSVs produce sanitized errors.
- Arithmetic: Decimal only, local precision, ROUND_HALF_UP at half-cent boundaries
  (0.05 with 10% ->0.05; 0.30 with 5% ->0.29), fractional percentages and original/
  discounted presentation. PIX is selected explicitly, never stacks and is disabled
  without recognized policy evidence. Campaign names cannot activate a row.
- Policies: actual pypdf extraction of synthetic PDFs, independent physical versus
  printed page markers, correct topic sections, malformed/missing/heading-only/
  exception-only/unmatched evidence, malicious instruction-like text as inert data,
  and missing/conflicting case facts. A window comparison is a customer claim,
  never eligibility approval or statutory-rights denial.
- Integration: real compiled graph, fake structured extractor, real catalog plus
  validated promotions and PDF evidence, ordered fan-in once, safe clarification/
  review outcomes, selected PIX versus absent method and independent success
  retained across a policy error. Existing order no-CSV-lookup tests still pass.

Original-source smoke is post-implementation verification, not falsely claimed
test-first evidence. It loads only products/categories/promotions and the manual,
disables external tracing, and asserts counts, rule/reference recognition and
non-stacking/stock invariants without printing any record or passage. Actual combined
graph returns 61 purchasable listings plus policy evidence with a fake extractor.
No real model or customer/order/order-item lookup runs.

## Boundaries and remaining limitations

Topology, Send, reducer, fan-in, per-instance services and fresh-turn state remain.
M1 production and all 114 existing tests are unchanged. V2 parameters only gain
optional payment_method and typed policy context; topic-only fake services stay
compatible when no context is supplied. Source text never becomes code or a model
instruction. References are document-digest/section/page IDs, not local paths.

Extraction is bounded in a local Linux subprocess and no extracted cache is saved.
The topic/PIX recognizer targets the supplied manual profile; it is not semantic
understanding of arbitrary policy documents or a complete adversarial-language
classifier. OCR/encrypted sources, individualized shipping/financing/manufacturer
eligibility, source refresh orchestration and broader legal adjudication are absent.
Store-policy statements are not independent statutory-law verification. No purchase,
refund, approval or legal denial executes. No live inventory guarantee is made.

No live provider, checkpointer/history, customer authentication, private order
tracking, HITL workflow, deployment or Cycle 2B was added. Historical/unrelated
files remain untouched. Ready for human code review; no commit/stage/push/PR/merge.
