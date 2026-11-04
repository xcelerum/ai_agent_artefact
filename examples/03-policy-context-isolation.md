# Behavioral Evaluation 03 — Cross-Transaction Policy Context Isolation

**Project:** Artefact AI Engineer Technical Challenge — Empório da Música  
**Observed on:** November 3, 2026  
**Interface:** Python CLI and local Python diagnostic  
**Live inference provider:** Groq; the successful two-turn verification was run with the temporary `openai/gpt-oss-120b` override, as reported during testing  
**Evaluation type:** Human-led regression investigation, isolated context-boundary check, and live multi-turn smoke test

## Purpose and threat model

Evaluate whether information stated about one purchase can be incorrectly reused when a customer asks about a different purchase in the same session. The concern is **cross-transaction context contamination**, not cross-user memory persistence. Customer statements are not independently verified purchase facts.

The application maintains limited in-memory conversational context. Without a reliably authenticated transaction identifier, it must not assume that an old purchase channel, delivery age, or other individual claim belongs to a later purchase.

## Original reproduction — before the change

The following minimal local diagnostic called the policy-fact capture logic without making a Groq request:

**Turn 1:** `Comprei pela internet e recebi há cinco dias.`  
**Stored state:** `{'purchase_channel': 'online', 'days_since_receipt': 5}`

**Turn 2:** `Agora quero falar sobre o pedido do meu pai, que ainda não foi enviado.`  
**Stored state:** `{'purchase_channel': 'online', 'days_since_receipt': 5}`

**After `reset()`:** `{}`

**Finding:** Transaction-specific claims survived a change of purchase subject. The reset behavior was correct, but session reset alone was not a sufficient isolation control.

## Engineering decision

Prefer a **fail-closed, current-turn-only approach** for transaction-specific customer claims when the application cannot establish that consecutive turns refer to the same purchase. Preserve general conversational functionality where separately validated, but do not attribute previous purchase details to a new transaction without reliable association.

This is a deliberately limited prototype control, not an order-ownership or identity-verification mechanism. A production system would need authenticated order linkage and explicit scope/retention rules.

## Verification after the change

### 1. Local agent-boundary check

A spy agent recorded the `policy_context` actually supplied by the conversation wrapper:

```text
Compra A: {'purchase_channel': 'online', 'days_since_receipt': 5}
Compra B: {}
Depois do reset: {}
P1 CONTEXT ISOLATION: PASS
```

This confirms the observed boundary behavior for these messages; it does not establish correctness for every kind of reference to another purchase.

### 2. Focused regression suite

The developer reported this local command and outcome:

```bash
uv run --locked python -m pytest \
  tests/test_policy_continuity.py \
  tests/test_semantic_conversation.py \
  tests/test_conversation.py -q

git diff --check
```

**Observed outcome:** `62 passed, 13 warnings in 6.03s`; `git diff --check` reported no issues. The 13 warnings originated from third-party LangSmith use of a deprecated Python 3.14 asyncio API.

### 3. Live two-turn conversation

**Customer — purchase A**

> Comprei pela internet e recebi há cinco dias. Como funciona a devolução por arrependimento?

**Assistant — observed response**

> Arrependimento: “• O cliente pode solicitar a devolução em até 7 (sete) dias corridos após o recebimento do produto, sem necessidade de justificativa.” (manual, seção 4.1, p. 4)  
> Condições especiais: “• Instrumentos com personalização ou ajustes sob encomenda (setup, regulagem especial).” (manual, seção 4.4, p. 4)  
> O item foi personalizado?  
> As regras gerais não aprovam nem negam seu pedido: uma análise individual exige verificação pela equipe, sem decidir seus direitos por aqui.

**Customer — purchase B, same CLI session (no `/novo`)**

> E sobre o pedido do meu pai? Não sei quando ele recebeu. Ele pode solicitar devolução por arrependimento?

**Assistant — observed response**

> Arrependimento: “• O cliente pode solicitar a devolução em até 7 (sete) dias corridos após o recebimento do produto, sem necessidade de justificativa.” (manual, seção 4.1, p. 4)  
> Condições especiais: “• Instrumentos com personalização ou ajustes sob encomenda (setup, regulagem especial).” (manual, seção 4.4, p. 4)  
> A compra foi pela internet ou na loja?  
> As regras gerais não aprovam nem negam seu pedido: uma análise individual exige verificação pela equipe, sem decidir seus direitos por aqui.

## Acceptance criteria

| Criterion | Observed result |
| --- | --- |
| Purchase A's stated facts reach its own evaluation | PASS in the local boundary check |
| Purchase A's receipt age is not transferred to purchase B | PASS in the local check and observed live response |
| Purchase A's online channel is not assumed for purchase B | PASS in the local check and observed live response |
| Reset removes context | PASS in the local check |
| Store policy excerpts include section/page provenance | PASS in this live interaction |
| The assistant refrains from approving a specific return without verification | PASS in this live interaction |

**Overall:** PASS for the particular cross-transaction scenario observed, not a claim of comprehensive conversational safety.

## Limits and residual risks

- The second response did not explicitly ask for the receipt date; that fact remains necessary for individual eligibility analysis. It was **not** falsely inferred from purchase A.
- The model may produce different routing or wording on another run. Hosted requests may fail with HTTP 429; such failures are **inconclusive**, not evidence of correct or incorrect semantic routing.
- No authenticated order ownership is implemented. The agent must not infer identity or entitlement from customer-provided text, email addresses, or order numbers alone.
- Conservatively discarding transaction claims between turns reduces contamination risk but may require users to repeat information about the same purchase.
- Full-suite release verification is separate from this case: the subsequent reported run had **342 passed and 2 failed**, both in an unrelated cancellation-behavior regression test. This evaluation must not be used to claim the entire repository is green.

**Takeaway:** Inspecting state at the exact agent boundary exposed a cross-transaction risk that a generic `reset()` check would not detect. The local boundary test and a live two-turn conversation provide complementary evidence, while remaining explicit about their limited coverage.
