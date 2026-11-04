# Validation summary — high-fidelity synthetic demo

**Generated against the supplied challenge ZIP**, with structural and referential assertions. This report contains no original customer records.

| Table | Original rows | Synthetic rows | Same headers |
|---|---:|---:|---|
| `categories.csv` | 9 | 9 | Yes |
| `customers.csv` | 50 | 50 | Yes |
| `order_items.csv` | 22 | 22 | Yes |
| `orders.csv` | 20 | 20 | Yes |
| `products.csv` | 65 | 65 | Yes |
| `promotions.csv` | 25 | 25 | Yes |

## Preserved behavior

- All nine music-instrument categories and all 65 model names and technical specifications.
- Product IDs, category IDs, promotion IDs and foreign-key mappings.
- All 25 promotion records, active/inactive flags and discount percentages.
- Order/customer/order-item references, state values and record counts; customer identities and contact fields have been replaced with fictional placeholders.
- Eight-page document structure with numbered sections and the same core thresholds: PIX 5%; promotion non-cumulative; withdrawal 7 days; defect exchanges 30 days; legal warranty 90 days; delivery/working hours and installment conditions.

## Changes

- Product prices adjusted down 0.25% and some stock values changed by at most one unit. Product descriptions identified as synthetic.
- Customer names, phones and emails replaced, with `example.invalid` domains; order tracking codes and free-text notes replaced. Source customer ID relationships and duplicate-email relationships remain valid for tests.
- Store address and contacts fictionalized; policy text independently paraphrased while keeping relevant numbered rules.

## Tests performed against application code from supplied workspace snapshot

- `load_catalog` 9 categories / 65 products: PASS.
- `load_promotions` 25 records: PASS.
- `LocalPolicyService.from_pdf` 8 pages / 29 fragments, extraction successful: PASS.
- `LocalPolicyService.pricing_rules` PIX 5% and non-cumulativity references: PASS.
- Retrieval evidence for hours, contact, payment, withdrawal, returns, defect, preference, shipping, promotions, warranty and privacy: PASS (some topics correctly require clarification when context is absent).
- Structural data, schema, referential integrity and fictional-identity assertions: PASS.

**Not performed:** Groq-backed end-to-end live conversations, fresh installation on the recipient's Codespaces, or GitHub clone test. These still need to be checked. The package is a faithful *test fixture*, not the original dataset or a claim of production correctness.
