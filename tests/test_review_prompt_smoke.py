from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "skills" / "auto-research" / "assets" / "review-optimization"
SCRIPTS = ROOT / "skills" / "auto-research" / "scripts"
FIXTURE = ASSETS / "smoke-fixture.json"
PROMPT = ASSETS / "smoke-prompt.md"
RUNNER = SCRIPTS / "review_prompt_smoke.py"
SCORING = SCRIPTS / "review_prompt_scoring.py"
TRACKING = SCRIPTS / "review_prompt_tracking.py"
SCORE_RANGES = {
    "soundness": (1, 4),
    "presentation": (1, 4),
    "significance": (1, 4),
    "originality": (1, 4),
    "overall_recommendation": (1, 6),
}
JUDGE_DIMENSIONS = {
    "rubric_coverage",
    "evidence_grounding",
    "major_issue_detection",
    "score_rationale_consistency",
    "specificity_actionability",
    "summary_faithfulness",
    "hallucination_avoidance",
    "question_quality",
    "limitations_ethics",
}


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_human_scores() -> dict[str, list[int]]:
    return {
        "soundness": [2, 3, 4],
        "presentation": [3, 3, 4],
        "significance": [2, 3, 3],
        "originality": [3, 4, 4],
        "overall_recommendation": [3, 4, 5],
    }


class ReviewPromptSmokeTest(unittest.TestCase):
    def test_smoke_fixture_is_anonymized_and_complete(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

        self.assertEqual(fixture["paper_id"], "paper-smoke-001")
        self.assertEqual(set(fixture["human_scores"]), set(SCORE_RANGES))
        self.assertEqual(
            set(fixture["generated_review"]["scores"]),
            set(SCORE_RANGES) | {"confidence"},
        )
        self.assertEqual(set(fixture["judge"]["scores"]), JUDGE_DIMENSIONS)
        serialized = json.dumps(fixture).lower()
        for forbidden in (
            "author",
            "reviewer_id",
            "pdf_path",
            "raw_human_review",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_human_targets_use_arithmetic_mean(self) -> None:
        scoring = load_module(SCORING, "review_prompt_scoring")

        result = scoring.human_targets(valid_human_scores())

        self.assertEqual(result["soundness"], 3.0)
        self.assertAlmostEqual(result["presentation"], 10 / 3)
        self.assertEqual(result["overall_recommendation"], 4.0)

    def test_out_of_range_human_score_is_rejected(self) -> None:
        scoring = load_module(SCORING, "review_prompt_scoring")

        with self.assertRaisesRegex(ValueError, "soundness"):
            scoring.human_targets({**valid_human_scores(), "soundness": [0]})

    def test_composite_uses_equal_human_and_judge_weights(self) -> None:
        scoring = load_module(SCORING, "review_prompt_scoring")

        result = scoring.score_candidate(
            human_scores=valid_human_scores(),
            predicted_scores={
                "soundness": 3,
                "presentation": 3,
                "significance": 3,
                "originality": 4,
                "overall_recommendation": 4,
            },
            judge_scores={
                dimension: 5 for dimension in scoring.JUDGE_DIMENSIONS
            },
            penalties={field: 0 for field in scoring.PENALTY_FIELDS},
        )

        self.assertAlmostEqual(result["judge_quality"], 1.0)
        self.assertGreaterEqual(result["human_agreement"], 0.0)
        self.assertLessEqual(result["human_agreement"], 1.0)
        self.assertAlmostEqual(
            result["composite"],
            0.5 * result["human_agreement"]
            + 0.5 * result["judge_quality"],
        )


if __name__ == "__main__":
    unittest.main()
