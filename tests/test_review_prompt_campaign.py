from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "skills" / "auto-research" / "assets" / "review-optimization"
P0 = ASSETS / "smoke-prompt.md"
P1 = ASSETS / "smoke-prompt-calibration-v2.md"
SCRIPTS = ROOT / "skills" / "auto-research" / "scripts"
BATCH = SCRIPTS / "review_prompt_batch.py"
TRACKING = SCRIPTS / "review_prompt_tracking.py"
JUDGE_PROMPT = ASSETS / "judge-prompt.md"
REVIEW_SCHEMA = ASSETS / "generated-review.schema.json"
JUDGE_SCHEMA = ASSETS / "judge.schema.json"
SMOKE_FIXTURE = ASSETS / "smoke-fixture.json"


def load_module(path: Path, name: str):
    scripts_directory = str(path.parent)
    if scripts_directory not in sys.path:
        sys.path.insert(0, scripts_directory)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_manifest(path: Path, payload: dict[str, object]) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    value = {**payload, "manifest_sha256": hashlib.sha256(encoded).hexdigest()}
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class PromptCandidateContractTest(unittest.TestCase):
    def test_p1_preserves_p0_and_adds_one_calibration_module(self) -> None:
        baseline = P0.read_text(encoding="utf-8")
        candidate = P1.read_text(encoding="utf-8")

        self.assertTrue(candidate.startswith(baseline))
        addition = candidate[len(baseline) :]
        self.assertEqual(addition.count("## Evidence-to-ordinal calibration pass"), 1)
        normalized_addition = " ".join(addition.split())
        for required in (
            "strongest supporting evidence",
            "most decision-relevant deficiency",
            "material flaw affecting a central claim",
            "mostly solid",
            "only minor limitations",
            "not a mechanical average",
            "evaluator certainty",
            "section, table, figure, equation, or reported result",
        ):
            self.assertIn(required, normalized_addition)


class BatchCampaignContractTest(unittest.TestCase):
    def test_shared_configuration_hash_excludes_candidate_identity(self) -> None:
        batch = load_module(BATCH, "review_prompt_batch_config_test")
        common = {
            "sample_manifest_sha256": "a" * 64,
            "judge_prompt_sha256": "sha256:" + "b" * 64,
            "review_schema_sha256": "sha256:" + "c" * 64,
            "judge_schema_sha256": "sha256:" + "d" * 64,
            "reviewer_model": "gpt-5.4",
            "judge_model": "gpt-5.4",
            "max_attempts": 2,
            "workers": 2,
        }

        first = batch.shared_configuration_sha256(common)
        second = batch.shared_configuration_sha256(
            {**common, "candidate_id": "p9", "prompt_sha256": "sha256:" + "e" * 64}
        )

        self.assertEqual(first, second)
        self.assertNotEqual(
            first,
            batch.shared_configuration_sha256({**common, "workers": 3}),
        )

    def test_candidate_run_is_five_of_five_and_resumable(self) -> None:
        batch = load_module(BATCH, "review_prompt_batch_run_test")
        fixture = json.loads(SMOKE_FIXTURE.read_text(encoding="utf-8"))
        calls: list[str] = []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries: list[dict[str, object]] = []
            for index in range(5):
                paper_id = f"paper-sample-{index:02d}"
                pdf = root / f"source-{index:02d}.pdf"
                label = root / f"source-{index:02d}.json"
                pdf.write_bytes(b"%PDF-1.7 synthetic")
                label.write_text("{}", encoding="utf-8")
                entries.append(
                    {
                        "source_id": f"source-{index:02d}",
                        "paper_id": paper_id,
                        "split": "development",
                        "pdf_path": str(pdf),
                        "label_path": str(label),
                    }
                )
            sample = root / "sample-manifest.json"
            write_manifest(
                sample,
                {
                    "schema_version": "review-prompt-dataset-v1",
                    "selector_version": "score-marginal-greedy-v1",
                    "split": "development",
                    "seed": 20260713,
                    "source_manifest_sha256": "f" * 64,
                    "count": 5,
                    "score_marginals": {},
                    "entries": entries,
                },
            )

            def fake_runner(args):
                calls.append(args.paper_id)
                args.output_dir.mkdir(parents=True)
                metrics = batch.score_candidate(
                    human_scores=fixture["human_scores"],
                    predicted_scores=fixture["generated_review"]["scores"],
                    judge_scores=fixture["judge"]["scores"],
                    penalties=fixture["penalties"],
                )
                write_json(args.output_dir / "generated-review.json", fixture["generated_review"])
                write_json(args.output_dir / "judge.json", fixture["judge"])
                write_json(args.output_dir / "metrics.json", metrics)
                write_json(
                    args.output_dir / "provenance.json",
                    {
                        "reviewer_prompt_sha256": batch.sha256_file(args.reviewer_prompt),
                        "reviewer_usage": {"input_tokens": 10, "output_tokens": 5},
                        "judge_usage": {"input_tokens": 8, "output_tokens": 4},
                    },
                )
                write_json(
                    args.output_dir / "timing.json",
                    {"reviewer_seconds": 2.0, "judge_seconds": 1.0, "total_seconds": 3.5},
                )
                write_json(
                    args.output_dir / "attempts.json",
                    {
                        "max_attempts": 2,
                        "reviewer": {"attempt_count": 1, "retry_count": 0},
                        "judge": {"attempt_count": 1, "retry_count": 0},
                    },
                )
                write_json(
                    args.output_dir / "publish-bundle.json",
                    {
                        "schema_version": "review-prompt-publish-v1",
                        "paper_id": args.paper_id,
                        "generated_review": fixture["generated_review"],
                        "judge": fixture["judge"],
                    },
                )
                return {"paper_id": args.paper_id, **metrics}

            kwargs = {
                "sample_manifest_path": sample,
                "prompt_path": P0,
                "campaign_root": root / "campaign",
                "campaign_id": "n5-test",
                "candidate_id": "p0",
                "parent_candidate_id": "none",
                "judge_prompt_path": JUDGE_PROMPT,
                "review_schema_path": REVIEW_SCHEMA,
                "judge_schema_path": JUDGE_SCHEMA,
                "reviewer_model": "gpt-5.4",
                "judge_model": "gpt-5.4",
                "workers": 2,
                "max_attempts": 2,
                "paper_runner": fake_runner,
            }
            first = batch.run_candidate(**kwargs)
            second = batch.run_candidate(**kwargs)
            stored_config = json.loads(
                (root / "campaign" / "candidates" / "p0" / "candidate-config.json")
                .read_text(encoding="utf-8")
            )

        self.assertEqual(len(calls), 5)
        self.assertEqual(first["sample_count"], 5)
        self.assertEqual(first["completed_count"], 5)
        self.assertEqual(first["failure_count"], 0)
        self.assertEqual(first["aggregate_sha256"], second["aggregate_sha256"])
        self.assertEqual(first["shared_configuration_sha256"], second["shared_configuration_sha256"])
        self.assertEqual(stored_config["workers"], 2)
        tracking = load_module(TRACKING, "review_prompt_tracking_campaign_test")
        wandb_metrics = batch.wandb_metrics_from_aggregate(first)
        self.assertLessEqual(
            set(wandb_metrics),
            tracking.ALLOWED_WANDB_BATCH_METRIC_FIELDS,
        )
        self.assertEqual(wandb_metrics["ops/sample_count"], 5)
        self.assertEqual(wandb_metrics["ops/completed_count"], 5)


if __name__ == "__main__":
    unittest.main()
