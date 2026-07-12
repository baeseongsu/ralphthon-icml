from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "auto-research" / "scripts"
SCORING = SCRIPTS / "review_prompt_scoring.py"
ASSETS = ROOT / "skills" / "auto-research" / "assets" / "review-optimization"
REVIEW_SCHEMA = ASSETS / "generated-review.schema.json"
JUDGE_SCHEMA = ASSETS / "judge.schema.json"


def load_module(path: Path, name: str):
    scripts_directory = str(path.parent)
    if scripts_directory not in sys.path:
        sys.path.insert(0, scripts_directory)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generated_review(**score_overrides: int | float) -> dict[str, object]:
    scores: dict[str, int | float] = {
        "soundness": 3,
        "presentation": 3,
        "significance": 3,
        "originality": 3,
        "overall_recommendation": 4,
        "confidence": 4,
    }
    scores.update(score_overrides)
    return {
        "summary": "A grounded summary.",
        "strengths": ["A supported strength."],
        "weaknesses": ["A supported weakness."],
        "questions": ["A decision-relevant question?"],
        "limitations": "A bounded limitation.",
        "ethical_concerns": "No material concerns identified.",
        "evidence_trace": ["Section 3 supports the assessment."],
        "scores": scores,
        "score_rationales": {
            dimension: f"Evidence-based rationale for {dimension}."
            for dimension in scores
        },
    }


def judge_result(**score_overrides: int | float) -> dict[str, object]:
    scores: dict[str, int | float] = {
        "rubric_coverage": 5,
        "evidence_grounding": 5,
        "major_issue_detection": 5,
        "score_rationale_consistency": 5,
        "specificity_actionability": 5,
        "summary_faithfulness": 5,
        "hallucination_avoidance": 5,
        "question_quality": 5,
        "limitations_ethics": 5,
    }
    scores.update(score_overrides)
    return {"scores": scores, "rationale": "The review is well supported."}


def paper_record(
    *,
    paper_id: str,
    review: dict[str, object],
    judge: dict[str, object],
    metrics: dict[str, object],
    reviewer_seconds: float,
    judge_seconds: float,
    total_seconds: float,
    reviewer_attempts: int = 1,
    judge_attempts: int = 1,
) -> dict[str, object]:
    return {
        "paper_id": paper_id,
        "generated_review": review,
        "judge": judge,
        "metrics": metrics,
        "timing": {
            "reviewer_seconds": reviewer_seconds,
            "judge_seconds": judge_seconds,
            "total_seconds": total_seconds,
        },
        "usage": {
            "reviewer": {"input_tokens": 100, "output_tokens": 20},
            "judge": {"input_tokens": 80, "output_tokens": 10},
        },
        "attempts": {
            "reviewer": reviewer_attempts,
            "judge": judge_attempts,
        },
        "failure": None,
    }


class BatchScoringTest(unittest.TestCase):
    def test_generated_and_judge_scores_require_integers(self) -> None:
        scoring = load_module(SCORING, "review_prompt_scoring_integer_test")

        with self.assertRaisesRegex(ValueError, "integer"):
            scoring.validate_generated_review(generated_review(soundness=3.5))
        with self.assertRaisesRegex(ValueError, "integer"):
            scoring.validate_judge(judge_result(rubric_coverage=4.5))
        with self.assertRaisesRegex(ValueError, "integer"):
            scoring.validate_generated_review(generated_review(soundness=3.0))
        with self.assertRaisesRegex(ValueError, "integer"):
            scoring.validate_judge(judge_result(rubric_coverage=True))
        with self.assertRaisesRegex(ValueError, "integer"):
            scoring.score_candidate(
                human_scores={
                    "soundness": [3],
                    "presentation": [3],
                    "significance": [3],
                    "originality": [3],
                    "overall_recommendation": [4],
                },
                predicted_scores=generated_review(soundness=3.5)["scores"],
                judge_scores=judge_result()["scores"],
                penalties={
                    "hallucination": 0,
                    "schema_failure": 0,
                    "missing_evidence": 0,
                    "api_failure": 0,
                },
            )

        review_schema = json.loads(REVIEW_SCHEMA.read_text(encoding="utf-8"))
        judge_schema = json.loads(JUDGE_SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                value["type"]
                for value in review_schema["properties"]["scores"]["properties"].values()
            },
            {"integer"},
        )
        self.assertEqual(
            {
                value["type"]
                for value in judge_schema["properties"]["scores"]["properties"].values()
            },
            {"integer"},
        )

    def test_batch_aggregate_records_distributions_gaps_and_latency(self) -> None:
        scoring = load_module(SCORING, "review_prompt_scoring_aggregate_test")
        human_scores_1 = {
            "soundness": [3],
            "presentation": [3],
            "significance": [3],
            "originality": [3],
            "overall_recommendation": [4],
        }
        review_1 = generated_review()
        judge_1 = judge_result()
        metrics_1 = scoring.score_candidate(
            human_scores=human_scores_1,
            predicted_scores=review_1["scores"],
            judge_scores=judge_1["scores"],
            penalties={field: 0 for field in scoring.PENALTY_FIELDS},
        )

        human_scores_2 = {
            "soundness": [3],
            "presentation": [3],
            "significance": [2],
            "originality": [4],
            "overall_recommendation": [5],
        }
        review_2 = generated_review(
            soundness=4,
            presentation=2,
            significance=3,
            originality=4,
            overall_recommendation=4,
            confidence=3,
        )
        judge_2 = judge_result(
            **{dimension: 3 for dimension in scoring.JUDGE_DIMENSIONS}
        )
        metrics_2 = scoring.score_candidate(
            human_scores=human_scores_2,
            predicted_scores=review_2["scores"],
            judge_scores=judge_2["scores"],
            penalties={field: 0 for field in scoring.PENALTY_FIELDS},
        )

        result = scoring.aggregate_paper_records(
            [
                paper_record(
                    paper_id="paper-a",
                    review=review_1,
                    judge=judge_1,
                    metrics=metrics_1,
                    reviewer_seconds=10.0,
                    judge_seconds=5.0,
                    total_seconds=16.0,
                ),
                paper_record(
                    paper_id="paper-b",
                    review=review_2,
                    judge=judge_2,
                    metrics=metrics_2,
                    reviewer_seconds=20.0,
                    judge_seconds=15.0,
                    total_seconds=38.0,
                    reviewer_attempts=2,
                ),
            ]
        )

        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(result["completed_count"], 2)
        self.assertEqual(result["failure_count"], 0)
        self.assertEqual(
            result["predicted_distributions"]["soundness"]["counts"],
            {"1": 0, "2": 0, "3": 1, "4": 1},
        )
        self.assertEqual(
            result["reference_distributions"]["overall_recommendation"]["counts"],
            {"1": 0, "2": 0, "3": 0, "4": 1, "5": 1, "6": 0},
        )
        self.assertEqual(result["signed_gaps"]["soundness"], [0.0, 1.0])
        self.assertEqual(result["signed_gaps"]["presentation"], [0.0, -1.0])
        self.assertAlmostEqual(result["human_agreement"], 0.88)
        self.assertAlmostEqual(result["judge_quality"], 0.75)
        self.assertAlmostEqual(
            result["judge_dimension_scores"]["rubric_coverage"],
            4.0,
        )
        self.assertAlmostEqual(result["penalty"], 0.0)
        self.assertAlmostEqual(result["composite"], 0.815)
        self.assertAlmostEqual(
            result["human_dimension_agreement"]["soundness"],
            5.0 / 6.0,
        )
        self.assertEqual(result["timing"]["reviewer_seconds"]["total"], 30.0)
        self.assertEqual(result["timing"]["reviewer_seconds"]["p50"], 15.0)
        self.assertEqual(result["timing"]["reviewer_seconds"]["p95"], 19.5)
        self.assertEqual(result["usage"]["reviewer"]["input_tokens"], 200)
        self.assertEqual(result["attempts"]["total"], 5)
        self.assertEqual(result["attempts"]["retries"], 1)


if __name__ == "__main__":
    unittest.main()
