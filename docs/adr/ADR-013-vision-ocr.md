# ADR-013: Vision OCR with multimodal models

- Status: Accepted
- Date: 2026-10-06

## Context

Scanned PDFs have no usable text layer. Until now the options were Tesseract (local, free,
weak on noisy scans and dense tables) and AWS Textract (managed, but the test account has no
subscription, so it has never run live). Claude on Bedrock and gpt-4.1-mini on Azure OpenAI,
which the project already uses for classification and extraction, also read images. The
question was whether they can serve as the OCR step, and how to use them without giving up the
pipeline's rule that the model proposes and deterministic code decides.

## Decision

1. **Vision OCR is one more `DocumentTextExtractor`.** `OCR_PROVIDER=bedrock_vision` uses Claude
   on Bedrock and `azure_vision` uses an Azure OpenAI vision deployment. The model defaults to the
   chat model (`BEDROCK_MODEL_ID` / `AZURE_OPENAI_CHAT_DEPLOYMENT`); `OCR_VISION_MODEL` overrides
   it. The rest of the pipeline is unchanged: the text it returns is classified, extracted,
   validated and checked against evidence exactly like native or Tesseract text.
2. **Images go through the existing adapters and gateway.** `LLMRequest.images` carries base64
   PNGs; the LangChain adapter sends them as `image_url` blocks (Azure sends them as-is,
   `ChatBedrockConverse` converts them to Converse image blocks). Vision OCR has its own
   `ModelGateway`, sharing the prompt registry, invocation ledger, metrics, cost estimator and
   retry policy, with a larger output budget (`OCR_VISION_MAX_TOKENS`, default 4096). Each call
   is recorded with operation `ocr`, the document and workflow IDs, and the SHA-256 of each image
   in the structured log; the image bytes are never logged.
3. **One page per call, long edge capped.** Pages are rendered with pdfium so the long edge is
   `OCR_VISION_MAX_EDGE_PX` (default 1568 px, the size above which Claude downscales anyway).
   One page per call keeps each request small and makes a failure point at a page.
4. **A versioned prompt that asks for a transcription, not an interpretation.**
   `ocr.page_transcription` v1.0.0 asks for printed lines verbatim, `?` for unreadable
   characters, no corrections or reformatting, and treats any instruction in the image as text
   to transcribe. The output is validated as `{"lines": [...]}` like every other model output.
5. **Cross-check with Tesseract.** A vision model can misread or invent a digit without any
   error. When Tesseract is installed (`OCR_VISION_CROSS_CHECK=true`, the default) it reads the
   same page image, and each page where the two engines read different numbers gets a warning
   listing them. Warnings go into the review case, so the reviewer knows which values to check
   on the page.
6. **Always reviewed, never silent.** As with any OCR, a document read this way gets the
   `ocr_used` review reason. If the model call fails after retries, the document moves to
   `FAILED` with the provider error type and can be retried; it is never processed without text.
7. **Not in demo mode.** Settings validation refuses vision OCR when `DEMO_MODE=true`. Vision
   calls go through their own gateway, so the public site's daily live-AI budget does not cover
   them, and an image page costs far more than a text call.

## Alternatives considered

| Option | Why not |
|---|---|
| Send the whole PDF to the model | Bedrock Converse accepts documents, but per-page images give per-page failures, per-page cross-checks, and work the same way on Azure |
| Let the vision model extract fields directly from the image | skips the evidence check: field values could no longer be matched against page text, which is the main defence against invented values |
| Trust the vision transcription without a second reader | a confident misread digit is the failure that matters most in financial documents; the cross-check is cheap when Tesseract is already installed |
| Textract only | not available on the test account; it remains an option behind the same interface |

## Consequences

- The click-to-locate boxes on scanned pages still come from Tesseract ([ADR-012](ADR-012-design-system-and-document-viewer.md)),
  because a vision transcription has no word positions.
- Cost per page depends on image size and model. The ledger records the provider-reported input
  tokens (which include the image), so `config/pricing.yaml` prices it like any other call.
- The cross-check compares numbers only. Misread names, dates written as words, or a dropped
  line are not caught by it; they are caught, if at all, by the extraction validators and the
  human review that every OCR document gets.
- The mock provider can't read images, so vision OCR always uses a real provider, even when the
  rest of the pipeline runs on the mock. Tests use a scripted provider and fake chat models.
