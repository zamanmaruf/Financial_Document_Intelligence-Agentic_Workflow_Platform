/**
 * Published evaluation results, copied from the README ("Real-model results", round 3) and
 * dated. Update together with the README when the evaluation is re-run.
 */
export const RESULTS_MEASURED_ON = "3 October 2026";

export const RESULTS = {
  documents: 30,
  models: ["Claude Haiku 4.5 (AWS Bedrock)", "GPT-4.1 mini (Azure OpenAI)"],
  headline: [
    {
      value: "100%",
      label: "documents identified correctly",
      detail: "Classification accuracy on 30 synthetic test documents, both live models.",
    },
    {
      value: "99.5%",
      label: "of extracted values correct",
      detail: "Normalised field match with Claude Haiku 4.5 (98.9% with GPT-4.1 mini).",
    },
    {
      value: "0",
      label: "invented values",
      detail: "Hallucinated-field rate was 0.00 for both models.",
    },
    {
      value: "100%",
      label: "of answers cite real evidence",
      detail: "Citation correctness and groundedness were 1.00 for both models.",
    },
  ],
} as const;
