# Milestone 1 test verification

`test_catalog.py` contains 22 test methods using invented CSV rows created in
self-cleaning temporary directories. Runtime code uses the standard library;
pytest is a locked development dependency. No original records are embedded here.

## Commands and final observed results

Verified on 2026-11-02 with Python **3.14.10**:

```sh
export UV_CACHE_DIR=/tmp/artefact-uv-cache UV_OFFLINE=1 UV_NO_SYNC=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider'
uv run --locked python -m pytest -q
```

Exit 0: **22 passed, 76 subtests passed in 0.10s**, zero skips. The existing local
private product/category snapshot was available, so its optional smoke test ran.
Subtests are parameterized cases within test methods, not independent test methods.

For a fresh public-only copy, use Python 3.14.10 and a separate virtual environment:

```sh
uv sync --locked --python 3.14.10
uv run --locked python -m pytest -q
```

This exact sequence was verified in a temporary directory containing only
`.python-version`, `pyproject.toml`, `uv.lock`, the two catalog modules and their
package initializers, and `tests/test_catalog.py`. Synchronization succeeded with
exit 0 and installed the locked development dependencies. Pytest then returned
exit 0: **21 passed, 1 skipped, 76 subtests passed in 0.12s**. The skip was
`test_private_snapshot_smoke`, because originals were absent. No original CSV,
PDF, ZIP, credentials or customer/order data were copied. Bytecode and pytest cache
writes were disabled; the isolated pytest run used uv offline after synchronization.

The standard-library alternative remains:

```sh
.venv/bin/python -B -m unittest discover -s tests -p 'test_*.py' -v
```

The counts above are from pytest, not a new execution of this alternative.

## Behavior-to-test mapping

All methods below belong to `CatalogTests`. CAT-01 through CAT-06 retain their
meanings in the root README; this table also covers supporting ingestion contracts.

| Behavior | Exact test methods |
|---|---|
| Typed loading and read-only specifications | `test_typed_snapshot_and_immutable_specs` |
| CAT-01 combined filters, price boundary; CAT-05 empty category result | `test_search_combines_filters_and_includes_price_boundary` |
| CAT-01 independent name, category/name or ID, price and material exclusion | `test_search_filters_exclude_independent_active_distractors` |
| CAT-02–CAT-04 availability status and stock | `test_status_and_stock_are_independent` |
| CAT-06 stored absence, missing active-product spec, supported filter with no matches | `test_optional_description_and_unknown_spec_are_not_invented`; `test_missing_requested_specification_excludes_active_product`; `test_supported_specification_can_have_no_matches` |
| Invalid product fields, orphan category references and sanitized errors | `test_invalid_product_fields_fail_without_raw_data`; `test_invalid_source_field_marker_is_not_exposed` |
| Duplicate primary keys, blank/invalid category IDs and names | `test_duplicate_primary_keys_and_invalid_categories` |
| Malformed quoted CSV in both tables; invalid category headers | `test_malformed_quoted_csv_is_rejected`; `test_invalid_category_csv_schemas_are_rejected` |
| Invalid product schema, row width and encoding; missing files and empty snapshot; BOM and reordered headers | `test_schema_row_width_and_encoding_errors`; `test_missing_file_and_empty_snapshot`; `test_bom_and_reordered_columns` |
| Invalid query types, values and unsupported keys | `test_invalid_search_inputs`; `test_search_combines_filters_and_includes_price_boundary` |
| Spec-key normalization and normalized duplicate rejection | `test_specification_keys_normalize_on_both_sides`; `test_duplicate_normalized_query_keys_are_rejected`; `test_duplicate_normalized_source_keys_are_rejected` |
| JSON-safe exact values and serialization mutation isolation | `test_product_serialization_is_json_safe_and_preserves_values` |
| Hostile text remains stored/searchable data | `test_untrusted_content_is_only_data` |
| Optional local original product/category counts and availability invariants | `test_private_snapshot_smoke` |

## Evidence limits

The optional smoke test reads only the local product/category CSVs under ignored
`data/private/` and skips when either is unavailable. It verifies 65 products,
9 categories and 61 purchasable listings without printing records. All other tests
run independently of original data. Catalog results describe a snapshot, not live
inventory. CAT-05 customer-facing wording is NOT IMPLEMENTED.

M1 has specification traceability and automated regression verification. The final
three strengthening tests passed the existing implementation immediately; they do
not demonstrate a historical RED phase. Earlier isolated-copy mutation checks
caught 10 selected deliberate defects, as recorded in the root README. These are
test-effectiveness checks, not proof of exhaustive mutation or 100% code coverage.
A complete historical RED–GREEN–REFACTOR cycle is **not independently established**.

Storing hostile content as data does not prove LLM prompt-injection resistance.
Authentication, LLM behavior and adversarial evaluations remain NOT IMPLEMENTED;
passing catalog tests provides no production-security or compliance certification.
