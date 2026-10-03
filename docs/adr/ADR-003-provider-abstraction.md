# ADR-003: Bedrock / Azure OpenAI provider abstraction

- Status: Accepted
- Date: 2026-09-30

## Context

The target enterprise uses AWS Bedrock (Anthropic Claude) as the primary model platform and Azure
OpenAI as a secondary one. The application must also run with no credentials at all (local/mock mode,
CI). Business logic must not import vendor SDKs.

## Decision

1. **Protocols, not base classes** (`typing.Protocol`):
   - `LLMProvider.generate(LLMRequest) -> LLMResponse`
   - `EmbeddingProvider.embed_documents / embed_query`
   - `VectorStore`, `DocumentTextExtractor` (OCR), `DocumentStore`, `MetricsRecorder`
2. **Implementations**:
   - `BedrockClaudeProvider`: `ChatBedrockConverse`; credentials via the standard AWS chain.
   - `AzureOpenAIProvider`: `AzureChatOpenAI`; endpoint, key and deployment from env (`SecretStr`).
   - `MockLLMProvider`: deterministic, rule-based handlers keyed by prompt name. **Clearly labelled**:
     every result carries `is_mock=true` and `model_name="mock-deterministic-v1"`.
   - Embeddings: Bedrock Titan, Azure OpenAI, or the local `HashingEmbeddingProvider` (lexical, not
     semantic; labelled `is_mock=true`).
3. **Single selection point**: `app/providers/factory.py` maps `DOCINTEL_*` settings to
   implementations. `app/services/container.py` wires everything; tests inject fakes via the same
   constructor arguments.
4. **Single call path**: all LLM calls go through `ModelGateway`, which owns prompt rendering,
   timeout, bounded retries, JSON extraction, Pydantic validation, repair re-prompts, cost estimation
   and invocation logging. Providers only translate request and response shapes.
5. **Structured variables for the mock**: `LLMRequest.variables` carries the variables the prompt was
   rendered from, so the mock reads structured inputs instead of re-parsing prompt text.

## Switching providers

```bash
# AWS Bedrock (credentials from env/profile/instance role)
DOCINTEL_LLM_PROVIDER=bedrock
DOCINTEL_BEDROCK_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0
DOCINTEL_EMBEDDING_PROVIDER=bedrock

# Azure OpenAI
DOCINTEL_LLM_PROVIDER=azure_openai
DOCINTEL_AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
DOCINTEL_AZURE_OPENAI_API_KEY=...          # or managed identity (roadmap)
DOCINTEL_AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o
```

## Consequences

- Business modules (`classification`, `extraction`, `rag`, `workflows`) have no vendor imports; the
  import graph can be checked with `grep -r "langchain_aws\|langchain_openai\|boto3" app/`, which
  only matches `app/providers/`.
- The real adapters are unit-tested with LangChain fake chat models and construct real SDK clients
  offline. **The Azure OpenAI adapter has since been verified live** (`gpt-4.1-mini`): the first
  real-provider run was the evaluation suite, as intended, and it surfaced four issues that the
  mock could not (see the README's "Real-model results"). The Bedrock adapter has not yet been run
  against a live endpoint.
- Prompts are shared across vendors. If vendor-specific prompt variants become necessary, the
  registry supports multiple versions per prompt name.
- Automatic cross-vendor failover is intentionally **not** implemented: switching vendor changes model
  behaviour and must be a deliberate, evaluated change (see roadmap).
