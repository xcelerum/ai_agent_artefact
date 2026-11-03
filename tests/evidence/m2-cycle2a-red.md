# M2 Cycle 2A — genuine RED

Baseline branch feat/agent-m2, HEAD e1978e9; prior commits/evidence preserved.
Original baseline: 114 passed, 13 warnings, 76 subtests passed in 2.74s, exit 0.

The user explicitly approved only pypdf==6.21.4. `uv add --python 3.14.10
'pypdf==6.21.4'` installed one package after an approved retry for sandbox DNS.
Python 3.14.10 and pypdf 6.21.4 import; local original PDFs extract text (policy
8 pages; challenge 3 pages). No original passages were printed/committed or sent
to a hosted model. `uv audit --locked` exited 0 after approved network retry:
no known vulnerabilities/adverse statuses in 45 packages; audit is experimental.

The SDD source/rule table preceded test and production behavior. Synthetic CSV/PDF
tests were written against importable interfaces whose new behavior raises explicit
NotImplementedError. No provider or missing import was used to manufacture RED.

Exact command:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run --locked python -m pytest -q tests/test_promotions.py tests/test_store_policy.py tests/test_cycle2a.py --tb=line
```

Exit **1**, actual summary:

```text
48 failed, 6 passed, 13 warnings in 1.78s
```

Relevant actual failures:

```text
NotImplementedError: Cycle 2A RED: promotion ingestion
app/data/promotions.py:9
NotImplementedError: Cycle 2A RED: local PDF policy extraction
app/data/store_policy.py:7
```

There were no collection/import failures. Synthetic PDFs were generated through
the approved installed pypdf, not mocked page strings. The six already passing
cases are invalid-policy-context rejection in the existing validator. Many later
pricing/integration assertions are not yet reached; RED is not independent proof
that each downstream assertion has failed.

Coverage plan: promotion history/active flags, IDs/references/conflicts, percentages,
malformed CSVs and sanitized diagnostics; exact cent rounding/PIX/non-stacking;
actual local PDF extraction, section/physical/printed-page provenance, source failure,
topic matching, missing context, window comparison, exceptions and hostile data;
compiled catalog+policy fan-out, source-backed pricing and safe partial failures.
All public fixtures are invented; original-source smoke is separate.

Existing regression command after dependency setup and before GREEN:

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run --locked python -m pytest -q tests/test_catalog.py tests/test_agent.py tests/test_multi_intent.py
```

Its observed result is recorded in the subsequent GREEN evidence. The 13 warnings
are the existing LangSmith asyncio.iscoroutinefunction deprecations. No historical
evidence, M1 source, staging, commit, push, PR or merge was changed/performed.

## Additional observed edge-case RED within Cycle 2A

After the initial 54-case GREEN, three new regressions were written before their
respective corrections: exception-only/heading-only withdrawal evidence, negated
PIX-rate text, and conflicting withdrawal-versus-defect customer statements.
These are a separate iterative RED, not attributed to the first 48-failure run.

```sh
UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run --locked python -m pytest -q tests/test_store_policy.py tests/test_cycle2a.py -k 'exception_only_or_heading_only or negated_pix or ambiguous_case_reason' --tb=short
```

Exit 1: `3 failed, 25 deselected, 13 warnings in 3.13s`.
Actual failures: exception-only lookup returned PolicyEvidence instead of None;
negated rate returned PixRules instead of None; ambiguous case returned
review_required instead of clarification. All assertions used synthetic data and
actual PDF extraction; the ambiguity case used the real compiled graph. The
heading-only subassertion followed the first failure and was not reached at RED.
