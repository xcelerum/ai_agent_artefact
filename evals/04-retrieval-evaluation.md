# Policy Retrieval Evaluation — Controlled Section-Level Benchmark

**Execution date:** November 3, 2026  
**Reproducible test:** `tests/test_policy_retrieval.py::test_evaluation_metrics`  
**Command:**

```bash
uv run --locked python -m pytest tests/test_policy_retrieval.py::test_evaluation_metrics -s -q
```

**Observed execution:** `1 passed, 13 warnings in 0.79s`. The warnings concern a LangSmith deprecation under Python 3.14; they are not test failures.

## Scope and methodology

The evaluation used **a synthetic PDF**, the project's local section-retrieval implementation, and a **mocked semantic model** supplying controlled policy topics. It isolates whether expected sections are recovered and whether missing/invalid evidence is handled conservatively. It does **not** measure end-to-end real-model intent accuracy or answer faithfulness.

The dataset contains **12 test cases**:
- **8 positive cases** with nonempty relevance labels, containing **17 relevant-section occurrences** across the queries.
- **4 control cases** with empty expected section sets: clarification required (1), insufficient evidence (2), and technical error (1).

## Observed metrics

| Metric | Value | Denominator or interpretation |
| --- | ---: | --- |
| Macro Recall@8 | **1.00 / 100%** | Mean of per-query recall on the 8 positive cases |
| Micro Recall@8 | **1.00 / 100%** | 17 expected-section occurrences recovered out of 17 |
| Irrelevant sections | **0** | No extra sections outside the expected sets in this fixture |
| Positive expected/found set matches | **8/8** | Derived from printed expected/found lists |
| Control cases with no retrieved sections | **4/4** | Includes one modeled PDF-processing failure |

**Definitions:**

`Recall@8(q) = |expected(q) ∩ found(q)| / |expected(q)|`

`Macro Recall@8 = mean(Recall@8(q))`, over the 8 positive queries.

`Micro Recall@8 = Σ|expected(q) ∩ found(q)| / Σ|expected(q)| = 17/17 = 1.00`

`Irrelevant sections = Σ|found(q) − expected(q)| = 0`

The four cases with empty expected sets are evaluated for classification and absence of returned sections, **not** included in recall denominators. The section cap is eight; this benchmark does not establish ranking quality over a large corpus.

## Case-group classification

| Cases | Count | Observed outcome |
| --- | ---: | --- |
| Withdrawal, exchange, defect or related policies | 5 | `clarification_required`, expected sections retrieved |
| Shipping, delivery or payment guidance | 3 | `ok`, expected sections retrieved |
| Ambiguous query with no sufficient topic | 1 | `clarification_required`, no sections |
| Unsupported or uncovered policy query | 2 | `insufficient_evidence`, no sections |
| Invalid policy PDF | 1 | `technical_error`, no sections |

## Interpretation and residual risk

The benchmark supports a **narrow, reproducible claim**: all expected policy sections were returned, and no irrelevant sections appeared, in these 12 controlled cases. It does **not** prove 100% real-world retrieval precision or overall answer accuracy.

Residual risks include incorrect Groq topic extraction, unexpected wording, changing manuals, ambiguous/contradictory policies, incorrect final rendering or citation page labels, PDF parsing edge cases and provider rate limiting. A larger independently labeled dataset and live end-to-end evaluations would be required for broader claims.

**Evidence source:** retain the executable pytest test as the source of truth; the metrics above reproduce the output observed on November 3, 2026.
