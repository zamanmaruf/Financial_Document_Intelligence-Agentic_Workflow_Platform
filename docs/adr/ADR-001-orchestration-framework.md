# ADR-001: AI orchestration framework choice

- Status: Accepted
- Date: 2026-09-30

## Context

The platform needs to call two chat-model vendors (AWS Bedrock/Claude, Azure OpenAI) and two embedding
vendors, render versioned prompts, split documents into chunks, and coordinate a multi-step document
workflow. The brief allowed exactly one orchestration framework (LangChain, LlamaIndex, LangGraph,
Semantic Kernel, ...) and asked for the choice to be justified.

Requirements that constrain the choice:

1. Financial-services workflows must be deterministic, enumerable and auditable (see ADR-004).
2. Business logic must not depend on vendor SDKs (see ADR-003).
3. CI must run offline without paid APIs.
4. The framework must not hide retries, prompts or state from our own logging and audit trail.

## Decision

Use **LangChain (`langchain-core` 0.3, `langchain-aws`, `langchain-openai`, `langchain-text-splitters`)
strictly as an integration layer**:

| LangChain component | Used for | Where |
|---|---|---|
| `ChatBedrockConverse` | Claude on Bedrock (Converse API) | `app/providers/llm/langchain_chat.py` |
| `AzureChatOpenAI` | Azure OpenAI chat deployments | same |
| `BedrockEmbeddings`, `AzureOpenAIEmbeddings` | cloud embeddings | `app/providers/embeddings/langchain_embeddings.py` |
| `PromptTemplate` | rendering versioned YAML prompts, variable validation | `app/prompts/registry.py` |
| `RecursiveCharacterTextSplitter` | page-aware chunking with start offsets | `app/retrieval/chunking.py` |
| `GenericFakeChatModel` | offline adapter tests | `tests/unit/test_providers.py` |

Workflow orchestration is **our own explicit state machine** (`app/workflows/`), not LangChain agents,
chains or LangGraph.

## Alternatives considered

- **LlamaIndex**: strong for RAG-centric apps, but its index/query-engine abstractions own retrieval,
  prompting and response synthesis. We need to control citation binding, groundedness checks and
  refusal logic ourselves, so most of LlamaIndex would be bypassed.
- **LangGraph**: a good fit for durable graph workflows with checkpoints. Our workflow is linear with a
  few branches; a ~70-line transition table is easier to audit than a graph runtime. LangGraph stays
  the natural upgrade if the workflow grows parallel branches or long-running human pauses (roadmap).
- **Semantic Kernel**: first-class Azure support, weaker Bedrock story in Python.
- **No framework (raw boto3 + openai SDKs)**: viable, but we would re-implement message normalization,
  usage-metadata mapping and fake models for tests.

## Consequences

- Vendor adapters are small (about 160 lines) and unit-tested with fake chat models.
- LangChain retries are disabled (`max_retries=0`, botocore `max_attempts=1`) so that retry and timeout
  policy lives in one place (`ModelGateway`) and is visible in logs and metrics.
- LangChain version churn is contained to three provider files and two utilities.
- We do not use LangChain's structured-output helpers; JSON parsing, Pydantic validation and bounded
  repair are done in `ModelGateway` so the behaviour is identical across vendors and the mock.
