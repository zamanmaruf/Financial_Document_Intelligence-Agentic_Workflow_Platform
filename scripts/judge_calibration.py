"""Check that the LLM groundedness judge catches broken answers, next to the lexical check.

    python scripts/judge_calibration.py --output reports/judge_calibration.json

Answers every answerable question in ``evals/datasets/answers.jsonl`` with the configured answer
model, then scores the original answer and three corrupted copies (a changed number, a negated
claim, an appended unsupported sentence) with the judge (``DOCINTEL_EVAL_JUDGE_PROVIDER`` or the
answer model) and with the deterministic lexical check. Uses the providers configured in the
environment; with mock providers the judge is the deterministic mock and the run is offline.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import Settings, VectorStoreName  # noqa: E402
from app.core.errors import DocIntelError  # noqa: E402
from app.evaluation.judge_calibration import PERTURBATIONS  # noqa: E402
from app.evaluation.runner import JUDGE_FLAG_BELOW, EvaluationRunner  # noqa: E402
from app.observability.logging import configure_logging  # noqa: E402
from app.rag.groundedness import check_groundedness  # noqa: E402
from app.services.container import build_container  # noqa: E402


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    judged = [r["judge_score"] for r in rows if r["judge_score"] is not None]
    lexical = [r["lexical_score"] for r in rows]
    return {
        "n": len(rows),
        "judge_errors": len(rows) - len(judged),
        "judge_mean": round(mean(judged), 4) if judged else None,
        "judge_flag_rate": round(sum(s < JUDGE_FLAG_BELOW for s in judged) / len(judged), 4)
        if judged
        else None,
        "lexical_mean": round(mean(lexical), 4) if lexical else None,
        "lexical_flag_rate": round(sum(s < 1.0 for s in lexical) / len(lexical), 4)
        if lexical
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings()
    configure_logging("WARNING", json_logs=False)

    cases = [
        json.loads(line)
        for line in (settings.evals_dir / "datasets" / "answers.jsonl").read_text().splitlines()
        if line.strip()
    ]
    cases = [c for c in cases if c["answerable"]]
    runner = EvaluationRunner(settings)
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="docintel-judge-cal-") as tmp:
        c = build_container(
            settings.model_copy(
                update={
                    "data_dir": Path(tmp),
                    "database_url": None,
                    "vector_store": VectorStoreName.MEMORY,
                }
            )
        )
        try:
            doc_ids: dict[str, str] = {}
            for name in sorted({case["target_file"] for case in cases}):
                data = (settings.sample_data_dir / "pdfs" / name).read_bytes()
                doc_id = c.ingestion.upload(name, "application/pdf", data).document.document_id
                c.workflow.process(doc_id)
                doc_ids[name] = doc_id
            judge = runner.judge_gateway(c)
            judge_model = f"{judge.provider.provider_name}:{judge.provider.model_name}"
            for case in cases:
                scope = doc_ids[case["target_file"]] if case["scope"] == "document" else None
                try:
                    answer = c.rag.ask(case["question"], document_id=scope)
                except DocIntelError as exc:
                    print(f"{case['id']}: answer failed ({exc.error_type}), skipped")
                    continue
                if answer.refused:
                    print(f"{case['id']}: refused, skipped")
                    continue
                evidence = "\n".join(
                    runner.chunk_text(c, cit.document_id, cit.chunk_id) or cit.text_snippet
                    for cit in answer.citations
                )
                variants: dict[str, str | None] = {"original": answer.answer}
                for name, perturb in PERTURBATIONS.items():
                    variants[name] = perturb(answer.answer, evidence)
                for variant, text in variants.items():
                    if text is None:
                        continue
                    verdict = runner.judge_answer(
                        c, judge, answer.model_copy(update={"answer": text})
                    )
                    rows.append(
                        {
                            "id": case["id"],
                            "variant": variant,
                            "answer": text,
                            "judge_score": verdict.score if verdict else None,
                            "judge_verdict": verdict.verdict if verdict else None,
                            "judge_rationale": verdict.rationale if verdict else None,
                            "lexical_score": check_groundedness(text, [evidence]).score,
                        }
                    )
            answer_model = c.llm.model_name
        finally:
            c.close()

    summary = {
        variant: _summary([r for r in rows if r["variant"] == variant])
        for variant in ["original", *PERTURBATIONS]
    }
    report = {
        "answer_model": answer_model,
        "judge_model": judge_model,
        "flag_below": JUDGE_FLAG_BELOW,
        "summary": summary,
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"answers={answer_model}  judge={judge_model}")
    for variant, s in summary.items():
        print(
            f"  {variant:18} n={s['n']:2}  judge flagged={s['judge_flag_rate']}  "
            f"mean={s['judge_mean']}  errors={s['judge_errors']}  "
            f"lexical flagged={s['lexical_flag_rate']}  mean={s['lexical_mean']}"
        )
    print(f"report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
