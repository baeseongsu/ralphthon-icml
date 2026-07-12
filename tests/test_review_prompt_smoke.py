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


class FakeTable:
    def __init__(self, *, columns):
        self.columns = columns
        self.rows = []

    def add_data(self, *values):
        self.rows.append(values)


class FakeRun:
    def __init__(self, owner):
        self.owner = owner
        self.id = "offline-smoke-run"
        self.dir = "/tmp/offline-run-smoke/files"
        self.summary = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def log(self, payload):
        self.owner.logged_payload = payload


class FakeWandb:
    Table = FakeTable

    def __init__(self):
        self.logged_payload = None
        self.init_kwargs = None

    def Settings(self, **kwargs):
        return kwargs

    def init(self, **kwargs):
        self.init_kwargs = kwargs
        return FakeRun(self)


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

    def test_ledger_appends_once_and_rejects_duplicate_candidate(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking")
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "experiments.jsonl"
            record = {
                "campaign_id": "smoke-001",
                "candidate_id": "baseline",
                "composite": 0.8,
            }

            tracking.append_record(ledger, record)
            with self.assertRaisesRegex(ValueError, "duplicate candidate_id"):
                tracking.append_record(ledger, record)

            self.assertEqual(
                len(ledger.read_text(encoding="utf-8").splitlines()),
                1,
            )

    def test_wandb_table_contains_review_but_no_human_scores(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking")
        fake = FakeWandb()
        with tempfile.TemporaryDirectory() as directory:
            run_id, _ = tracking.record_wandb_offline(
                wandb_module=fake,
                directory=Path(directory),
                entity="smoke-entity",
                project="review-prompt-smoke",
                campaign_id="smoke-001",
                candidate_id="baseline",
                config={"prompt_sha256": "sha256:" + "a" * 64},
                metrics={"objective/composite": 0.8},
                paper_id="paper-smoke-001",
                generated_review={
                    "summary": "complete generated review",
                    "scores": {"soundness": 3},
                },
                judge={
                    "scores": {"rubric_coverage": 5},
                    "rationale": "grounded",
                },
            )

        self.assertEqual(run_id, "offline-smoke-run")
        self.assertEqual(
            fake.init_kwargs["job_type"],
            "review-prompt-candidate",
        )
        payload = json.dumps(fake.logged_payload["reviews/all"].rows)
        self.assertIn("complete generated review", payload)
        self.assertNotIn("human_scores", payload)
        self.assertNotIn("pdf", payload.lower())


if __name__ == "__main__":
    unittest.main()
