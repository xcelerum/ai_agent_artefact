# Policy Retrieval: Architecture Decision and Evaluation

**Project:** Empório da Música — AI customer-support agent  
**Decision:** Section-based retrieval with query-aware topic routing and bounded lexical fallback  
**Evaluation date:** November 3, 2026  
**Scope:** Store-policy PDF retrieval. Product/catalog retrieval is handled separately through structured CSV queries.

## 1. The problem and constraints

The assistant must answer questions about an eight-page store-policy manual, including withdrawal, exchanges, defects, warranties, shipping, and payment conditions. Customers may use informal Portuguese, paraphrases, or mention several policy subjects at once. The solution must preserve source attribution, avoid unsupported policy claims, and leave case-specific eligibility decisions subject to validation and human review.

The wider agent uses a hosted LLM (Groq, `openai/gpt-oss-20b`) to extract structured intentions, then validates the resulting plan in Python and dispatches bounded tasks through LangGraph. Commercial calculations and authorization controls remain deterministic. **The LLM is not the authority for prices, policy deadlines, eligibility, or access to orders.**

## 2. Alternatives considered

| Option | Benefits | Costs / limitations | Decision |
| --- | --- | --- | --- |
| Fixed topic-to-section mapping only | Fast, explainable, precise source references | Fragile with paraphrases, overlapping topics, and out-of-vocabulary expressions | Improved rather than retained alone |
| Section index + topic routing + bounded lexical fallback | Local, deterministic, auditable, no embedding service; supports multiple topics and source references | Semantic paraphrases and negation remain imperfect | **Selected for this small, structured manual** |
| Dense embeddings + vector index (e.g., FAISS) | Potentially better semantic recall for diverse phrasing and larger/unstructured corpora | Additional embedding model, indexing, evaluation and operational complexity; vector similarity alone cannot guarantee relevance or correctness | Deferred pending a demonstrated retrieval gap |
| Sparse–dense hybrid (e.g., BM25 + embeddings, optionally fused with RRF) | Combines exact-term and semantic matches | Greater implementation and evaluation scope | Potential future improvement, not claimed as implemented |

**Rationale.** The manual is short, organized in numbered sections, and frequently requires exact policy provenance rather than approximate semantic similarity. A bounded section-level search gives direct section/page citations and makes failures easier to inspect. It avoids creating a separate embedding pipeline solely for eight pages. This is a proportional engineering choice, **not a claim that lexical retrieval outperforms embeddings in general**. FAISS is a vector search library, not a requirement for Retrieval-Augmented Generation.

The use of a smaller hosted LLM further supports keeping retrieval and business constraints in local, deterministic Python: the model extracts intent but is not expected to memorize the manual or perform financial calculations. This architectural separation limits what a model interpretation error can directly change. It does **not** eliminate incorrect intent extraction, retrieval false negatives, or unsupported prose.

### Expected operational advantages (engineering hypotheses)

The decision favors lower operational cost and more controllable failure modes **for this particular eight-page, sectioned manual**. These are reasoned, directional expectations, not empirical superiority claims:

| Dimension | Expected advantage and mechanism | Evidence status / important caveat |
| --- | --- | --- |
| **Operating cost** | Local lexical scoring and topic routing avoid a separate embedding service, embedding-index lifecycle and potentially extra network requests. This makes the retrieval layer inexpensive to operate at this scale. | **Expected lower retrieval-layer overhead; not cost-benchmarked.** A local embedding model could also avoid API charges, and up-front embedding costs may be negligible for eight pages. |
| **Exposure and privacy** | Original PDF passages remain in the local retrieval process rather than being forwarded to a third-party embedding service. | **True for the implemented retrieval path.** If a future answer-generation stage sends retrieved passages to the hosted LLM, this data-flow claim must be updated. |
| **Traceability and debugging** | Deterministic section IDs, physical/printed pages, explicit topic aliases and bounded lexical scores make individual selections easy to inspect and reproduce. | **Architectural property verified by implementation/tests**, not evidence that it achieves better recall than dense retrieval. Vector search can also preserve provenance via metadata. |
| **Control of failure modes** | Fixed source boundaries, one fallback pass, explicit evidence limits and fail-closed categories reduce the opportunity for unsupported, uncontrolled tool behavior or fabricated policy *sources*. | **Narrower and easier-to-audit failure surface**, not a claim of universally lower overall error rates. Unseen paraphrases and negation can produce false negatives. |
| **Fit for a smaller LLM** | The hosted LLM only interprets a request; source selection, monetary rules and authorization checks run in local Python. This reduces tasks delegated to probabilistic generation. | **Architectural risk-reduction argument, not an A/B-tested model-accuracy improvement.** Schema-conformant but semantically wrong plans remain possible. |
| **Latency and maintainability** | An in-process index for a short document can avoid extra network hops and service dependencies. | **Plausible, not measured.** Cold extraction, Python processing and actual API latency must be measured independently before reporting speedups. |

The primary technical claim is therefore **proportionality and control**, not "this retriever is more accurate/safer/cheaper than all vector RAG systems." A dense retriever might improve recall for unfamiliar paraphrases; that possibility remains a stated residual risk and a reason for future comparison if the document collection grows.


## 3. Implemented retrieval path

1. Extract PDF text locally with `pypdf` under bounded execution (`app/data/_pdf_worker.py`).
2. Index numbered policy sections and retain document identity, section ID, physical PDF page and printed page (`app/data/store_policy.py`).
3. Pass the original customer query locally to the policy retriever, along with validated policy context; preserve source text locally.
4. Route known policy topics, including multi-topic queries; rank relevant indexed sections using bounded normalized lexical overlap (`app/data/policy_matching.py`). **This is custom lexical ranking, not BM25; the implementation does not require a BM25 library.**
5. If primary required coverage is insufficient, perform **at most one** controlled fallback search. Deduplicate and bound the output to eight source references and 8,000 characters.
6. Return classified outcomes: supported evidence, clarification needed, insufficient evidence, or technical error. Preserve citations and do not silently treat extraction failures as nonexistent policies.
7. Apply deterministic rules and human-review requirements. The current customer-facing rendering is not claimed to be a fully implemented LLM-generated answer-grounding stage.

The product catalog follows a different path: validated structured queries over products, categories and promotions. Embedding search is not used for exact prices, inventory flags or discount calculations.

## 4. Retrieval evaluation: actual evidence

A focused test set contains **12 authored, synthetic Portuguese questions**: eight answerable cases with expected section IDs and four cases requiring a safely classified non-answer. Synthetic PDFs exercise the extraction and section-indexing code. These tests do **not** measure live LLM intent accuracy, nor do they use a held-out question set.

**Metric definition:** section Recall@8 = expected section IDs retrieved / expected section IDs, within at most eight retrieved source references. Macro recall averages the eight answerable cases; micro recall pools 17 expected section occurrences. The irrelevant-section count measures retrieved section IDs that were not expected in those test cases.

| Measure | Before | After |
| --- | ---: | ---: |
| Macro section Recall@8 | 0.75 | **1.00** |
| Micro section Recall@8 | 12/17 (0.706) | **17/17 (1.00)** |
| Irrelevant section selections | 10 | **0** |
| Withdrawal + defect section coverage | 2/3 | **3/3** |
| Shipping + installments section coverage | 1/3 | **3/3** |

The evaluation also verified that unsupported requests, missing evidence and malformed sources produce distinct safe outcomes. Regression testing followed RED → GREEN. The implementation report recorded **255 passing tests, 76 passing subtests**, and `git diff --check` passing at this checkpoint. See `tests/evidence/m2-policy-retrieval.md` and `tests/test_policy_retrieval.py` for reproducible test definitions and execution evidence.

**Interpretation:** this is 100% section recall **on the small authored evaluation set**, not universal retrieval accuracy. It does not prove that an answer is legally correct, factually faithful, natural in Portuguese, or safe for every customer situation. No measured comparison with a dense retriever exists.

## 5. Risk controls and residual limitations

- **Grounding and traceability:** every selected policy section retains provenance; the agent must not fabricate policy text or cite a missing source.
- **Bounded behavior:** one fallback pass, capped evidence volume, and no unbounded autonomous tool loop.
- **Policy/business controls:** the LLM does not authorize refunds, exchange eligibility or order access; the Python domain layer applies available rules and requests review when facts are unverified.
- **Failure classification:** missing support differs from document-processing errors; ambiguity should result in targeted clarification when possible.
- **Residual risks:** unseen paraphrases, negation, lexical mismatch, incorrect intent extraction, contradictory evidence and imperfect customer-facing synthesis. A retrieved passage is not itself proof of a correct final answer.

Possible next evaluation: a separate held-out paraphrase set, with retrieval Recall@k, irrelevant-evidence rate and answer-faithfulness assessment. Add dense retrieval only if these tests identify meaningful gaps and a controlled comparison demonstrates benefit.

## 6. Latency and operating cost: evidence status

**Not measured at this checkpoint.** Unit-test runtime and total suite duration are not API or retrieval latency benchmarks. The lower-cost / lower-latency discussion above is an engineering hypothesis, not a benchmark result. Do not claim p95/p99 latency, throughput or cost superiority from the tests above.

For an optional lightweight measurement, separately time (a) one-time PDF extraction/index building, (b) warm local retrieval, (c) hosted LLM request, and (d) end-to-end question processing. Report sample count, environment, p50, p95 and maximum; distinguish cold start and warm calls. With a small number of samples, **p99 is too unstable to be a useful headline metric**. If there is no time to collect trustworthy measurements, retain this explicit limitation.

## 7. Final decision

Retain the **local, section-based, query-aware and lexically assisted policy retriever** for this bounded challenge, with documented provenance, classified failures and measured section recall. Keep structured catalog queries and deterministic business rules separate. Prioritize an interactive Portuguese-language customer demonstration and end-to-end behavioral evaluation over adding an unvalidated vector index before submission.
