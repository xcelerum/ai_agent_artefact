# Risk Register — Empório da Música AI Assistant

**Review date:** November 3, 2026  
**Scope:** Artefact AI Engineer technical-challenge prototype.

Risk priorities are qualitative engineering judgments, not measured probabilities or claims of production safety.

## Controls and Residual Risks

| ID | Priority | Failure scenario | Implemented control / evidence | Residual risk |
|---|---|---|---|---|
| AUTH-01 | Critical | Unauthorized disclosure of another customer's order | Private order lookups are denied without trusted identity and ownership verification; authorization tests exist | Authentication and authorized order access are not implemented |
| PRIV-01 | Critical | Publication of private customer data or credentials | `data/private/` and `.env` are ignored; synthetic fixtures and Git audits are used | Ignore rules alone do not guarantee safety; staged files and history require final review |
| INJ-01 | High | Customer input attempts to override instructions or manipulate prices | Structured extraction, Python validation and catalog-grounded prices; live Yamaha C40/C70 scenarios preserved real prices | Broader prompt-injection resistance remains unverified |
| MONEY-01 | High | Incorrect discounts or unauthorized price adjustments | Decimal-based monetary calculations, catalog rules and automated tests | Source snapshots may be stale; negotiation requests can be omitted |
| POLICY-01 | High | Incomplete or misleading policy guidance | Section-level retrieval with citations and no automatic approvals | Relevant sections can still lead to incomplete answers, including missing warranty context |
| SOURCE-01 | High | Inconsistent contact information in store documentation | Source-grounded retrieval and avoidance of unsupported claims | Conflicting WhatsApp information in the supplied manual remains unresolved |
| ORCH-01 | High | Secondary customer intent is dropped | Bounded task plans, validation and multi-intent regression tests | A live price/PIX/negotiation request omitted the negotiation question |
| CLAR-01 | Medium | Unnecessary clarification despite sufficient information | Structured semantic interpretation and validated context | A defect-related request produced a redundant clarification |
| CONT-01 | Medium | Follow-up cannot resolve the assistant's previous offer | Safe denial and clarification responses | A live follow-up asking for rules and contacts received an incomplete answer |
| STATE-01 | High | Purchase A facts contaminate purchase B | Current-turn transaction facts are isolated; focused and live two-purchase tests passed | Ambiguous references across transactions are not comprehensively resolved |
| PROV-01 | High | Hosted model fails with HTTP 400, HTTP 429 or timeout | Sanitized diagnostics and safe technical fallback | The cause of intermittent `json_validate_failed` remains unconfirmed; provider availability is external |
| FRESH-01 | Medium | Snapshot data presented as real-time inventory | Catalog-based values and qualified availability wording | No live inventory or freshness guarantee |
| SCOPE-01 | Medium | Assistant promises unavailable transactions or human handoff | No cancellation/refund execution and explicit operational limits | Human-service guidance is not a connected ticketing workflow |
| REPRO-01 | High | Public repository cannot be reproduced by an evaluator | Python version pinning, `uv.lock`, CLI and synthetic tests | Real-data CLI requires local challenge sources and a Groq API key |
| EVAL-01 | Medium | Automated tests are overstated as general semantic accuracy | Mocked tests, controlled retrieval evaluation and human-led live conversations | The exploratory paraphrase evaluation produced one PASS and three PARTIAL outcomes |

## Evaluation Evidence

### Automated tests

The latest reported regression run before publication included:

- **353 passed tests**
- **76 passed subtests**
- **13 third-party deprecation warnings**
- Exit code 0

These figures describe a specific observed run. Tests must be repeated against the final submitted revision.

### Retrieval evaluation

A controlled synthetic benchmark contained 12 scenarios, including eight positive retrieval queries.

| Metric | Observed result |
|---|---:|
| Macro Recall@8 | 1.00 |
| Micro Recall@8 | 1.00 |
| Irrelevant sections | 0 |

These measurements assess section-level retrieval under controlled conditions. They are not measurements of live end-to-end answer accuracy.

### Exploratory semantic evaluation

Four previously untested formulations produced:

- One PASS: authoritative price preserved despite a false managerial claim.
- Three PARTIAL outcomes: incomplete warranty guidance, omitted negotiation intent and redundant clarification.

These are qualitative results, not a statistically representative model-quality estimate.

## Out-of-Scope Capabilities

The prototype does not implement production identity verification, authenticated private-order access, transactional cancellations or refunds, legal eligibility adjudication, live inventory synchronization, connected customer-service ticketing or guaranteed hosted-model availability.

## Release Requirements

Before publication:

- Confirm that no credentials or original private datasets appear in the Git index or history.
- Verify README commands, dependencies and file references.
- Publish three to five genuine customer conversations.
- Identify the actual model used in live evaluations.
- Re-run tests against the final revision.
- Preserve unresolved risks rather than claiming complete safety or accuracy.

**Assessment:** The prototype demonstrates bounded agent orchestration, deterministic business controls and observed safety behaviors, with material residual risks in semantic completeness, customer-service continuity and external-provider reliability.