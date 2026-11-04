# Public synthetic demo — faithful input contracts

These files are **synthetic derivatives for technical testing**, not the original challenge materials. They preserve the exact six CSV table names, headers, row counts, categorical taxonomy, product ID relationships, promotion active flags and discount percentages, product identities/models and product technical specifications. Prices have been adjusted downward by 0.25%, stock amounts by at most one item, descriptions labeled as fictional. Customer identities, contacts, order notes and tracking identifiers were substituted; IDs and foreign-key relationships are preserved.

The policy PDF has been **rewritten** (not copied) to preserve eight-page layout, numbered sections 1–10, operating hours, PIX rate, non-cumulative promotion rule, return/exchange/warranty thresholds and supporting rules. Contact details are non-operational. It is intentionally a synthetic version, not a republication of the source manual.

For a CLI demonstration, only `products.csv`, `categories.csv`, `promotions.csv` and `store_policy.pdf` are needed. `customers.csv`, `orders.csv`, and `order_items.csv` are included to preserve the original data contracts, but the prototype **does not implement authenticated order access**. Never enable order lookups from this data without authentication and ownership checks.

```bash
uv sync --locked --python 3.14.10
uv run --locked python -m pytest -q
uv run --locked python -m app.chat \
  --products demo/data/products.csv \
  --categories demo/data/categories.csv \
  --promotions demo/data/promotions.csv \
  --policy-pdf demo/data/store_policy.pdf
```

For the interactive CLI, set `GROQ_API_KEY` using a secure local environment setting; never commit credentials. Public test fixtures do not require a Groq key. The full live model output depends on the external provider and is not guaranteed by fixture validation.

**IMPORTANT:** If your repository already contains `demo/generate_demo_data.py`, exclude that prior experimental generator from the final release: it generates a different fixture and would otherwise overwrite these validated files if executed.
