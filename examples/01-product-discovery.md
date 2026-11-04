# Agent Behavioral Evaluation

## Case 01 — A Simple Customer Question Returned No Products

**Date:** November 2, 2026  
**Scenario:** Product discovery — Empório da Música  
**Evaluation method:** Human-led exploratory testing with a live LLM, the compiled LangGraph workflow, and local challenge data

### Why I tested this

After connecting the language model to the existing LangGraph workflow and seeing the automated tests pass, I wanted to check whether the assistant could handle the way an actual customer would ask for help. I deliberately used everyday Portuguese instead of the catalog's field names or category labels.

My first question was:

> “Olá! Vocês têm algum violão de até mil reais?”  
> *(Hi! Do you have any acoustic guitars for up to R$1,000?)*

The agent returned `no_matches`.

That was a technically valid response status, but it raised a business concern: the agent might be telling a customer that suitable products did not exist when they actually did.

### How I investigated

I removed the price constraint:

> “Vocês têm algum violão disponível, independentemente do preço?”  
> *(Do you have any acoustic guitars available, regardless of price?)*

The agent again returned `no_matches`.

I then referred to the catalog category explicitly:

> “Mostre produtos da categoria Violões, disponíveis por até R$ 1.000.”  
> *(Show available products in the Violões category for up to R$1,000.)*

This time, the agent returned **12 products**.

The contrast suggested that neither the price ceiling nor the absence of inventory fully explained the earlier answers. Inspecting sanitized extraction diagnostics confirmed the issue:

- For the first question, the LLM produced `category="violão"`.
- For the second, it produced both `category="violão"` and a redundant `name="violão"` filter.
- The catalog used the plural category label **`Violões`**. Its existing accent-normalized substring matching did not equate the singular and plural terms; the extra name filter also excluded valid matches.

This was a **false negative in product discovery**, not evidence that the requested items were absent.

### Engineering decision

I chose to fix the confirmed mismatch without allowing the LLM to broaden searches arbitrarily or invent catalog categories.

The implementation introduced a **narrow, catalog-grounded resolution** for the observed `violão` / `violões` pair. It resolves only against an unambiguous category present in the loaded catalog and removes a generic, redundant name filter only when the conditions are satisfied.

The existing deterministic checks remain authoritative. In particular, specific product and brand searches, conflicting filters, price limits, specifications, availability constraints, and business rules are preserved.

This is deliberately a bounded correction, **not** a claim to solve all Portuguese morphology, synonyms, or ambiguous product references.

### Before-and-after behavior

| Customer request | Before | After |
| --- | --- | --- |
| Acoustic guitars up to R$1,000 (natural wording) | `no_matches` | `ok` — 12 products |
| Available acoustic guitars at any price (natural wording) | `no_matches` | `ok` — 33 products |
| Explicit `Violões` category up to R$1,000 | `ok` — 12 products | `ok` — 12 products |

### Verification

The issue was reproduced in focused regression tests before the fix (**RED: 6 failed, 10 passed**). After the change, **all 16 focused tests passed**. The full reported suite finished with **226 passed, 76 subtests passed, exit code 0**, and 13 pre-existing warnings.

The three customer questions were then retested using the **live Groq-backed model and compiled graph**, with the results shown above. The checks confirmed that returned items belonged to the requested category and met the applicable purchasability constraints.

These figures are the observed results of this evaluation, not a claim of general conversational accuracy.

### What this taught me

**Passing automated tests is necessary, but it does not guarantee a useful customer experience.** The original response was safe in the sense that it did not fabricate products or prices. Yet it was still wrong: it hid relevant products from a customer, potentially losing a sale.

This case reminded me to evaluate both sides of reliability:

- **Incorrect positives:** showing products or offers that do not qualify.
- **Incorrect negatives:** failing to show products that actually qualify.

Human-led exploratory conversations helped reveal a gap that the initial tests did not cover. Reproducing that gap, tracing it to the LLM-to-catalog boundary, and adding regression coverage made the correction explainable and verifiable.

### Limits and next evaluation steps

This case validates the specific observed category mismatch. It does **not** establish broad coverage for other singular/plural pairs, alternative names, typos, or conversational references such as “that Yamaha you mentioned.” Those require separate, representative tests and should be prioritized by observed customer impact.

The next behavioral evaluation should focus on multi-turn conversations, natural Portuguese responses, price and promotion consistency, policy-grounded answers, and safe handling of unsupported requests.

**Takeaway:** The strongest result of this test was not a larger test count; it was discovering a real customer-facing failure, fixing it at the appropriate boundary, and preserving deterministic business controls.
