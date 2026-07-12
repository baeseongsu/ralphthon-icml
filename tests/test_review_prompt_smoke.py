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


if __name__ == "__main__":
    unittest.main()
