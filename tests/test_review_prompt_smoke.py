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
    scripts_directory = str(path.parent)
    if scripts_directory not in sys.path:
        sys.path.insert(0, scripts_directory)
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
        self.assertEqual(
            set(fixture["generated_review"]["score_rationales"]),
            set(fixture["generated_review"]["scores"]),
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

    def test_runtime_schema_rejects_sensitive_unknown_fields(self) -> None:
        scoring = load_module(SCORING, "review_prompt_scoring")
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fixture["generated_review"]["raw_human_review"] = "private review"

        with self.assertRaisesRegex(ValueError, "generated_review"):
            scoring.validate_smoke_fixture(fixture)

    def test_runtime_schema_rejects_out_of_range_confidence(self) -> None:
        scoring = load_module(SCORING, "review_prompt_scoring")
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fixture["generated_review"]["scores"]["confidence"] = 6

        with self.assertRaisesRegex(ValueError, "confidence"):
            scoring.validate_smoke_fixture(fixture)

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
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
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
                generated_review=fixture["generated_review"],
                judge=fixture["judge"],
            )

        self.assertEqual(run_id, "offline-smoke-run")
        self.assertEqual(
            fake.init_kwargs["job_type"],
            "review-prompt-candidate",
        )
        payload = json.dumps(fake.logged_payload["reviews/all"].rows)
        self.assertIn("bounded synthetic optimization problem", payload)
        self.assertNotIn("human_scores", payload)
        self.assertNotIn("pdf", payload.lower())

    def test_wandb_rejects_sensitive_payload_before_init(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking")
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fixture["generated_review"]["raw_human_review"] = "private"
        fake = FakeWandb()

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "generated_review"):
                tracking.record_wandb_offline(
                    wandb_module=fake,
                    directory=Path(directory),
                    entity="smoke-entity",
                    project="review-prompt-smoke",
                    campaign_id="smoke-001",
                    candidate_id="baseline",
                    config={"prompt_sha256": "sha256:" + "a" * 64},
                    metrics={"objective/composite": 0.8},
                    paper_id="paper-smoke-001",
                    generated_review=fixture["generated_review"],
                    judge=fixture["judge"],
                )

        self.assertIsNone(fake.init_kwargs)

    def test_wandb_rejects_config_and_metrics_outside_allowlist(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking")
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cases = (
            (
                {"prompt_sha256": "sha256:" + "a" * 64, "api_key": "secret"},
                {"objective/composite": 0.8},
                "config",
            ),
            (
                {"prompt_sha256": "sha256:" + "a" * 64},
                {"objective/composite": 0.8, "raw_human_score": 4},
                "metrics",
            ),
        )

        for config, metrics, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                fake = FakeWandb()
                with self.assertRaisesRegex(ValueError, expected):
                    tracking.record_wandb_offline(
                        wandb_module=fake,
                        directory=Path(directory),
                        entity="smoke-entity",
                        project="review-prompt-smoke",
                        campaign_id="smoke-001",
                        candidate_id="baseline",
                        config=config,
                        metrics=metrics,
                        paper_id="paper-smoke-001",
                        generated_review=fixture["generated_review"],
                        judge=fixture["judge"],
                    )
                self.assertIsNone(fake.init_kwargs)

    def test_cli_writes_recomputable_evidence_with_wandb_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--fixture",
                    str(FIXTURE),
                    "--prompt",
                    str(PROMPT),
                    "--output-dir",
                    str(output),
                    "--campaign-id",
                    "smoke-001",
                    "--candidate-id",
                    "baseline",
                    "--wandb-mode",
                    "disabled",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            metrics = json.loads(
                (output / "metrics.json").read_text(encoding="utf-8")
            )
            self.assertIn("composite", metrics)
            self.assertEqual(
                len(
                    (output / "experiments.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ),
                1,
            )
            self.assertTrue((output / "generated-review.json").is_file())
            self.assertTrue((output / "judge.json").is_file())
            self.assertTrue((output / "reflection.md").is_file())

    def test_cli_rejects_sensitive_fixture_before_writing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
            fixture["generated_review"]["raw_human_review"] = "private"
            fixture_path = root / "malicious.json"
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            output = root / "run"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--fixture",
                    str(fixture_path),
                    "--prompt",
                    str(PROMPT),
                    "--output-dir",
                    str(output),
                    "--campaign-id",
                    "smoke-sensitive",
                    "--candidate-id",
                    "baseline",
                    "--wandb-mode",
                    "disabled",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("generated_review", completed.stderr)
            self.assertFalse(output.exists())

    def test_cli_duplicate_rerun_preserves_existing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "run"
            base_command = [
                sys.executable,
                str(RUNNER),
                "--prompt",
                str(PROMPT),
                "--output-dir",
                str(output),
                "--campaign-id",
                "smoke-duplicate",
                "--candidate-id",
                "baseline",
                "--wandb-mode",
                "disabled",
            ]
            first = subprocess.run(
                [*base_command, "--fixture", str(FIXTURE)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            review_before = (output / "generated-review.json").read_bytes()
            ledger_before = (output / "experiments.jsonl").read_bytes()

            changed = json.loads(FIXTURE.read_text(encoding="utf-8"))
            changed["generated_review"]["summary"] = "MUTATED REVIEW"
            changed_fixture = root / "changed-fixture.json"
            changed_fixture.write_text(json.dumps(changed), encoding="utf-8")
            second = subprocess.run(
                [*base_command, "--fixture", str(changed_fixture)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(
                (output / "generated-review.json").read_bytes(),
                review_before,
            )
            self.assertEqual(
                (output / "experiments.jsonl").read_bytes(),
                ledger_before,
            )


if __name__ == "__main__":
    unittest.main()
