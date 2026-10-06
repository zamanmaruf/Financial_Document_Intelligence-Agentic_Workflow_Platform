from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import LLMProviderName, Settings, VectorStoreName
from app.core.errors import ProviderError
from app.domain.models import EvaluationResult, GroundednessReport
from app.drift.monitor import DriftSnapshot
from app.evaluation import runner as runner_module
from app.evaluation.runner import EvaluationRunner
from app.providers.llm.base import LLMRequest, LLMResponse
from app.rag import service as rag_service
from app.rag.groundedness import check_groundedness
from app.services.container import Container
from tests.support import make_settings


def test_offline_evaluation_passes_quality_gate(settings: Settings) -> None:
    captured: list[DriftSnapshot] = []

    def inspect(c: Container) -> None:
        captured.append(c.drift.snapshot())

    result = EvaluationRunner(settings).run(inspect=inspect)
    assert result.is_mock
    assert result.gate_passed, result.gate_failures
    for category in ("classification", "extraction", "retrieval", "answers", "workflow"):
        assert category in result.metrics
    assert result.metrics["answers"]["unsupported_statement_rate"] == 0.0
    assert result.metrics["answers"]["correct_refusal_rate"] == 1.0
    assert captured and captured[0].counts["documents"] > 0


def test_unsupported_answer_sentences_are_listed_in_failures(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    invented = "The fund also charges a 2.00% performance fee."

    def with_invented_sentence(answer: str, evidence: list[str]) -> GroundednessReport:
        return check_groundedness(f"{answer} {invented}", evidence)

    monkeypatch.setattr(rag_service, "check_groundedness", with_invented_sentence)
    result = EvaluationRunner(settings).run()
    flagged = [
        f for f in result.metrics["failures"]["answers"] if f["issue"] == "unsupported_sentences"
    ]
    assert result.metrics["answers"]["groundedness"] < 1.0
    assert flagged and all(any(invented in s for s in f["sentences"]) for f in flagged)


def test_evaluation_is_deterministic(settings: Settings) -> None:
    a = EvaluationRunner(settings).run()
    b = EvaluationRunner(settings).run()
    for category in ("classification", "extraction", "retrieval", "answers", "workflow"):
        assert a.metrics[category] == b.metrics[category]


def test_report_describes_the_sandbox_it_ran_in(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, vector_store=VectorStoreName.CHROMA)
    result = EvaluationRunner(settings, run_name="offline-check").run()
    assert result.config["run_name"] == "offline-check"
    assert result.config["vector_store"] == "memory"  # the evaluation always uses a fresh store
    assert result.config["rag_engine"] == "native"
    assert result.metrics["retrieval"]["engine"] == "native"
    assert set(result.metrics["timing"]) == {
        "retrieval_latency_ms_mean",
        "retrieval_latency_ms_p95",
    }


class _RecordingJudge:
    """Stands in for a second provider; answers judge prompts only."""

    def __init__(self, fail: bool = False) -> None:
        self.contexts: list[str] = []
        self.fail = fail

    @property
    def provider_name(self) -> str:
        return "azure_openai"

    @property
    def model_name(self) -> str:
        return "gpt-judge"

    @property
    def is_mock(self) -> bool:
        return False

    def generate(self, request: LLMRequest) -> LLMResponse:
        assert request.prompt_name == "validation.groundedness_judge"
        self.contexts.append(str(request.variables["context"]))
        if self.fail:
            raise ProviderError("azure_openai call failed: RateLimitError")
        return LLMResponse(
            text='{"score": 0.5, "verdict": "unsupported", "rationale": "One figure is missing."}',
            provider=self.provider_name,
            model_name=self.model_name,
        )


def _judged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, judge: _RecordingJudge
) -> EvaluationResult:
    built: list[Settings] = []

    def fake_build(settings: Settings, registry: object) -> _RecordingJudge:
        built.append(settings)
        return judge

    monkeypatch.setattr(runner_module, "build_llm_provider", fake_build)
    settings = make_settings(
        tmp_path, eval_use_llm_judge=True, eval_judge_provider=LLMProviderName.AZURE_OPENAI
    )
    result = EvaluationRunner(settings).run()
    assert [s.llm_provider for s in built] == [LLMProviderName.AZURE_OPENAI]
    return result


def test_judge_uses_the_other_provider_and_sees_full_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    judge = _RecordingJudge()
    result = _judged(tmp_path, monkeypatch, judge)
    answers = result.metrics["answers"]
    assert result.config["llm_judge_model"] == "azure_openai:gpt-judge"
    assert result.config["llm_model"] == "mock-deterministic-v1"  # answers still come from mock
    assert answers["llm_judge_cases"] == len(judge.contexts) > 0
    assert answers["llm_judge_groundedness"] == 0.5 and answers["llm_judge_errors"] == 0
    assert all(ctx.startswith("[chunk_id=chk_") for ctx in judge.contexts)
    # cited snippets are at most one sentence (<= 300 chars); the judge gets whole chunks
    assert max(len(block) for ctx in judge.contexts for block in ctx.split("\n\n")) > 300
    flagged = [f for f in result.metrics["failures"]["answers"] if f["issue"] == "judge_flagged"]
    assert flagged and flagged[0]["rationale"] == "One figure is missing."


def test_judge_failures_are_counted_not_scored_as_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    judge = _RecordingJudge(fail=True)
    answers = _judged(tmp_path, monkeypatch, judge).metrics["answers"]
    retries = make_settings(tmp_path).llm_max_retries
    assert answers["llm_judge_errors"] > 0
    assert len(judge.contexts) == answers["llm_judge_errors"] * (retries + 1)
    assert answers["llm_judge_cases"] == 0
    assert "llm_judge_groundedness" not in answers


def test_judge_defaults_to_the_answer_model(settings: Settings) -> None:
    settings = settings.model_copy(update={"eval_use_llm_judge": True})
    result = EvaluationRunner(settings).run()
    assert result.config["llm_judge_model"] == "mock:mock-deterministic-v1"
    assert result.metrics["answers"]["llm_judge_cases"] > 0
