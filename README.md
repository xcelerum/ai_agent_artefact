# Empório da Música — AI Customer Support Agent

Python prototype for the **Artefact AI Engineer technical challenge**. The assistant
answers questions in Brazilian Portuguese about musical instruments, prices,
promotions and store policies. It does **not** execute customer transactions.

> **Important — evaluation provenance.** Development and the five documented live
> conversations used the **original challenge CSVs and policy PDF**, retained
> locally and not redistributed. The public `demo/data/` contains **adapted,
> sanitized inputs** preserving schemas, relationships, catalog taxonomy and
> principal business rules. Customer information, selected values and policy
> wording were changed. **Original-data results must not be attributed to the
> public demo**, which received less exploratory testing before submission.

## Quickstart

**Requirements:** Python **3.14.10**, [`uv`](https://docs.astral.sh/uv/) and,
for live conversations, a **Groq API key** and internet access.

```bash
uv sync --locked --python 3.14.10
uv run --locked python -m pytest -q
```

Automated tests use synthetic fixtures and mocked model interactions. They do
**not** require a Groq key or the original files; an optional original-data
smoke test is skipped when its sources are unavailable.

For a live chat, configure `GROQ_API_KEY` securely and run:

```bash
uv run --locked python -m app.chat \
  --products demo/data/products.csv \
  --categories demo/data/categories.csv \
  --promotions demo/data/promotions.csv \
  --policy-pdf demo/data/store_policy.pdf
```

Use `/novo` to reset the session and `/sair` to exit. The demo provides adapted
catalog, promotion and policy sources. Additional fictional customer/order
CSV files preserve input relationships but **are not used for private order
lookups**. The CLI also accepts authorized local original-source paths.

Direct dependencies: `langgraph==1.2.19`, `groq==1.7.0`, `pypdf==6.21.4`;
development dependency: `pytest>=9.2.0`. `uv.lock` records the resolved
versions. Docker, Poetry and a custom Dev Container are not required.

## Architecture and technical decisions

**Design:** a **hybrid, grounded agentic workflow**: probabilistic semantic
planning by an LLM, deterministic business execution in Python, and
source-grounded retrieval. Here, *hybrid* refers to **LLM + rules**, **not**
to hybrid BM25/vector search.

```text
Customer message
  -> Groq: structured intent plan (JSON Schema v2)
  -> Python: validate plan and bind catalog references
  -> LangGraph StateGraph: route and fan out tasks
       |-- Catalog worker: CSV records + Decimal pricing/PIX
       |-- Policy worker: local PDF sections + citations
       `-- Order boundary: deny private or transactional actions
  -> Aggregate worker results in task order
  -> Deterministic, customer-facing Portuguese renderer
```

| Choice | Rationale and trade-off |
| --- | --- |
| **Python** | Simple integration with typed data, model APIs, deterministic domain services and tests. |
| **LangGraph `StateGraph`** | Explicit state, conditional routing and `Send`-based fan-out for multiple intents; more complexity than a linear workflow, but clearer execution boundaries. |
| **Groq / `openai/gpt-oss-20b`** | Default model for semantic extraction with strict Structured Outputs. Some manual runs used a temporary `openai/gpt-oss-120b` override; **no controlled comparative benchmark** was run. |
| **JSON Schema + Python validation** | The model proposes up to four tasks; Python checks types, arguments and supported operations before dispatch. Valid JSON does not guarantee semantic correctness. |
| **Local tools and `Decimal`** | Catalog values and pricing are calculated from source data, not invented by the model. Eligible PIX payments receive 5% off table price; active promotions do not stack with PIX. |
| **Deterministic renderer** | Restricts final responses to retrieved facts and approved operations, at the cost of less flexible phrasing and occasional incomplete answers. |

### Retrieval: why not embeddings or vector RAG?

The supplied manual is **small, numbered and structurally organized**. The
implementation extracts sections from the PDF with `pypdf` through a bounded
subprocess, retaining section, PDF-page and printed-page references.

The model selects a policy topic; Python retrieves its **allowlisted sections**
and applies a **bounded lexical fallback** when evidence is missing. Evidence is
limited to eight references / 8,000 characters and cited in the response.

We deliberately avoided FAISS/pgvector and embedding infrastructure: section
retrieval is easier to inspect, reproduce and audit for this manual. This is
**grounded retrieval**, not vector RAG or a BM25/embedding ensemble. Its
limitations include weaker handling of unfamiliar paraphrases and the fact that
correct evidence can still produce an incomplete response.

### Prompts, state and safety boundaries

Active `SYSTEM_PROMPT` and `SEMANTIC_PROMPT` definitions are in
`app/agent/groq_model.py`. They define the store's **informal but professional**
persona, instruments-only scope and structured intent extraction.

The LLM receives the customer message and limited context flags, **not** the
entire catalog, policy document, order records or full chat history. Python
validates the plan and controls facts, calculations and authorization.

Conversation memory is bounded and in-process (selected products, search
refinements and policy topic). Purchase statements are unverified; no trusted
identity, authenticated order access or persistent checkpoint is implemented.
The assistant cannot cancel orders, issue refunds or mutate transactions.
Prices and stock reflect a **local snapshot**, not real-time inventory.

## Evaluation and observed limitations

**Original challenge data.** Five recorded conversations in [`examples/`](examples/)
cover product discovery, mixed intents, transaction-context isolation, defect
advice and an adversarial price-change attempt. In the observed injection test,
the assistant did not follow a fake managerial instruction to price the Yamaha
C40 at **R$ 1** and retained the original **R$ 599.90**. This is a successful
**single scenario**, not a claim of universal injection resistance.

**Automated and retrieval evidence.** The last reported regression run had
**353 passing tests and 76 passing subtests** (the submitted commit must be
retested). A **controlled synthetic** retrieval benchmark reported Macro/Micro
Recall@8 of **1.00**; these figures do **not** measure live end-to-end accuracy.
See [`evals/04-retrieval-evaluation.md`](evals/04-retrieval-evaluation.md) and
[`evals/retrieval-design.md`](evals/retrieval-design.md).

**Public demo — separate, limited live evaluation:**

| Scenario | Observed outcome |
| --- | --- |
| Yamaha C40: catalog + PIX | **Partial:** correct product/table price, PIX amount omitted. |
| Ohana CK-20: promotion + PIX stacking | **Pass:** promotional price and non-stacking rule preserved. |
| Online withdrawal after five days | **Pass with caveat:** seven-day rule cited; no automatic approval. |
| Yamaha C40: price + cancellation | **Pass after retry:** first Groq HTTP 429; second returned the price and denied cancellation. |

The public demo **was not** subjected to the full original-data test set.
Other exploratory runs observed Groq HTTP **400** (`json_validate_failed`),
secondary-intent omissions and redundant clarifications. Hosted inference also
depends on provider availability and quota. This is **not production-ready**;
see [`docs/RISK_REGISTER.md`](docs/RISK_REGISTER.md) for residual risks.

## Scope, future work and use of AI

**Implemented:** catalog lookup/comparison; source-based prices, promotions and
PIX; cited policy guidance; bounded multi-intent handling; safe refusal of
unsupported private operations.

**Not implemented:** authenticated order lookup, cancellations/refunds,
real-time inventory, human-service ticketing, durable storage or case-specific
legal adjudication.

**With more time:** independently labeled semantic evaluations, improved
secondary-intent coverage, context-sensitive clarification, better isolation of
search filters, broader terminology handling beyond targeted
`violão/violões/nylon` cases, fuller policy answers and greater provider
resilience.

### AI-assisted development: SDD and TDD

The project used **Specification-Driven Development (SDD)** and
**Test-Driven Development (TDD)** practices pragmatically. Requirements,
contracts, acceptance criteria, regression tests and observed failures guided
incremental development within the challenge deadline.

**I directed the workflow, reviewed AI-generated code, executed and interpreted
automated and live tests, investigated failures, and made architecture, scope
and technical trade-off decisions.** OpenAI **Codex** assisted implementation,
test generation and debugging; **ChatGPT** supported requirements analysis,
architecture discussions, evaluation design and documentation. AI assistance
accelerated delivery but did not replace human verification or accountability.

**Repository map:** `app/agent/` (graph, LLM adapter, contracts and renderer),
`app/data/` (CSV/PDF ingestion), `app/domain/` (catalog and pricing services),
`app/chat.py` (CLI), `tests/` (regressions), `examples/` and `evals/` (evidence),
`demo/` (adapted public inputs).
