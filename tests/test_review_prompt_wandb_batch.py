from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "auto-research" / "scripts"
TRACKING = SCRIPTS / "review_prompt_tracking.py"

SCORE_RANGES = {
    "soundness": (1, 4),
    "presentation": (1, 4),
    "significance": (1, 4),
    "originality": (1, 4),
    "overall_recommendation": (1, 6),
    "confidence": (1, 5),
}
REFERENCE_SCORE_RANGES = {
    dimension: bounds
    for dimension, bounds in SCORE_RANGES.items()
    if dimension != "confidence"
}
JUDGE_DIMENSIONS = (
    "rubric_coverage",
    "evidence_grounding",
    "major_issue_detection",
    "score_rationale_consistency",
    "specificity_actionability",
    "summary_faithfulness",
    "hallucination_avoidance",
    "question_quality",
    "limitations_ethics",
)
BATCH_CONFIG_FIELDS = frozenset(
    {
        "campaign_id",
        "candidate_id",
        "parent_candidate_id",
        "sample_manifest_sha256",
        "reviewer_prompt_sha256",
        "judge_prompt_sha256",
        "review_schema_sha256",
        "judge_schema_sha256",
        "reviewer_model",
        "judge_model",
        "codex_cli_version",
        "auth_mode",
        "source_git_sha",
        "target_source",
        "objective_human_weight",
        "objective_judge_weight",
        "objective_penalty_weight",
    }
)
BATCH_OPTIONAL_CONFIG_FIELDS = frozenset({"kept_git_sha"})
BATCH_METRIC_FIELDS = frozenset(
    {
        "objective/composite",
        "objective/human_agreement",
        "objective/judge_quality",
        "objective/penalty",
        *{
            f"agreement/{dimension}"
            for dimension in REFERENCE_SCORE_RANGES
        },
        *{
            f"distribution_agreement/{dimension}"
            for dimension in REFERENCE_SCORE_RANGES
        },
        *{f"judge/{dimension}" for dimension in JUDGE_DIMENSIONS},
        *{
            f"gap/{dimension}/{summary}"
            for dimension in REFERENCE_SCORE_RANGES
            for summary in ("mean", "p50")
        },
        *{
            f"timing/{role}/{summary}"
            for role in ("reviewer_seconds", "judge_seconds", "total_seconds")
            for summary in ("total", "mean", "p50", "p95", "min", "max")
        },
        "timing/wall_clock_seconds",
        *{
            f"usage/{role}_{field}"
            for role in ("reviewer", "judge")
            for field in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            )
        },
        "ops/sample_count",
        "ops/completed_count",
        "ops/failure_count",
        "ops/reviewer_attempts",
        "ops/judge_attempts",
        "ops/attempts_total",
        "ops/retries",
        "throughput/papers_per_hour",
    }
)


def load_module(path: Path, name: str):
    scripts_directory = str(path.parent)
    if scripts_directory not in sys.path:
        sys.path.insert(0, scripts_directory)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generated_review(index: int) -> dict[str, object]:
    scores = {
        dimension: minimum + index % (maximum - minimum + 1)
        for dimension, (minimum, maximum) in SCORE_RANGES.items()
    }
    return {
        "summary": f"Grounded candidate summary {index}.",
        "strengths": ["A supported strength."],
        "weaknesses": ["A bounded weakness."],
        "questions": ["A decision-relevant question?"],
        "limitations": "A concrete limitation.",
        "ethical_concerns": "No material concern identified.",
        "evidence_trace": ["Section 2 supports the assessment."],
        "scores": scores,
        "score_rationales": {
            dimension: "The cited evidence supports this ordinal score."
            for dimension in SCORE_RANGES
        },
    }


def judge_result(index: int) -> dict[str, object]:
    return {
        "scores": {
            dimension: 1 + index % 5 for dimension in JUDGE_DIMENSIONS
        },
        "rationale": f"The review is grounded and internally consistent {index}.",
    }


def publish_bundles() -> list[dict[str, object]]:
    return [
        {
            "schema_version": "review-prompt-publish-v1",
            "paper_id": f"paper-batch-{index:02d}",
            "generated_review": generated_review(index),
            "judge": judge_result(index),
        }
        for index in range(5)
    ]


def ordinal_distribution(
    values: list[int | float],
    minimum: int,
    maximum: int,
) -> dict[str, object]:
    counts = {
        str(score): sum(value == score for value in values)
        for score in range(minimum, maximum + 1)
    }
    return {
        "counts": counts,
        "frequencies": {
            score: count / len(values) for score, count in counts.items()
        },
        "sample_count": len(values),
    }


def predicted_distributions(
    bundles: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {
        dimension: ordinal_distribution(
            [
                bundle["generated_review"]["scores"][dimension]  # type: ignore[index]
                for bundle in bundles
            ],
            minimum,
            maximum,
        )
        for dimension, (minimum, maximum) in SCORE_RANGES.items()
    }


def reference_distributions() -> dict[str, dict[str, object]]:
    return {
        dimension: ordinal_distribution(
            [minimum + index % (maximum - minimum + 1) for index in range(5)],
            minimum,
            maximum,
        )
        for dimension, (minimum, maximum) in REFERENCE_SCORE_RANGES.items()
    }


def judge_distributions(
    bundles: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {
        dimension: ordinal_distribution(
            [bundle["judge"]["scores"][dimension] for bundle in bundles],  # type: ignore[index]
            1,
            5,
        )
        for dimension in JUDGE_DIMENSIONS
    }


def valid_config() -> dict[str, int | float | str]:
    return {
        "campaign_id": "n5-001",
        "candidate_id": "p0",
        "parent_candidate_id": "root",
        "sample_manifest_sha256": "sha256:" + "1" * 64,
        "reviewer_prompt_sha256": "sha256:" + "2" * 64,
        "judge_prompt_sha256": "sha256:" + "3" * 64,
        "review_schema_sha256": "sha256:" + "4" * 64,
        "judge_schema_sha256": "sha256:" + "5" * 64,
        "reviewer_model": "gpt-5.4",
        "judge_model": "gpt-5.4",
        "codex_cli_version": "codex-cli 0.test",
        "auth_mode": "chatgpt",
        "source_git_sha": "a" * 40,
        "target_source": "pseudo_label",
        "objective_human_weight": 0.5,
        "objective_judge_weight": 0.5,
        "objective_penalty_weight": 0.25,
    }


def valid_metrics() -> dict[str, int | float]:
    return {
        "objective/composite": 0.8,
        "objective/human_agreement": 0.75,
        "objective/judge_quality": 0.85,
        "objective/penalty": 0.0,
        "agreement/soundness": 0.8,
        "distribution_agreement/soundness": 0.75,
        "judge/rubric_coverage": 4.0,
        "gap/soundness/mean": 0.1,
        "gap/soundness/p50": 0.0,
        "timing/reviewer_seconds/total": 150.0,
        "timing/reviewer_seconds/p95": 12.0,
        "timing/wall_clock_seconds": 300.0,
        "usage/reviewer_input_tokens": 1500,
        "usage/judge_output_tokens": 300,
        "ops/sample_count": 5,
        "ops/completed_count": 5,
        "ops/failure_count": 0,
        "ops/attempts_total": 10,
        "ops/retries": 0,
        "throughput/papers_per_hour": 180.0,
    }


class FakeTable:
    def __init__(self, *, columns):
        self.columns = list(columns)
        self.rows: list[tuple[object, ...]] = []

    def add_data(self, *values):
        self.rows.append(values)


class FakeRun:
    def __init__(self, owner):
        self.owner = owner
        self.id = "offline-batch-run"
        self.dir = "/tmp/offline-run-batch/files"
        self.summary: dict[str, object] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def log(self, payload):
        self.owner.log_calls.append(payload)


class FakeWandb:
    Table = FakeTable

    def __init__(self):
        self.init_calls: list[dict[str, object]] = []
        self.settings_calls: list[dict[str, object]] = []
        self.log_calls: list[dict[str, object]] = []

    def Settings(self, **kwargs):
        self.settings_calls.append(kwargs)
        return kwargs

    def init(self, **kwargs):
        self.init_calls.append(kwargs)
        return FakeRun(self)


class WandbBatchTest(unittest.TestCase):
    def call_batch(self, tracking, fake, directory: str, **overrides):
        bundles = overrides.pop("publish_bundles", publish_bundles())
        arguments = {
            "wandb_module": fake,
            "directory": Path(directory),
            "entity": "seongsubae",
            "project": "review-prompt-smoke",
            "campaign_id": "n5-001",
            "candidate_id": "p0",
            "config": valid_config(),
            "metrics": valid_metrics(),
            "publish_bundles": bundles,
            "predicted_distributions": predicted_distributions(bundles),
            "reference_distributions": reference_distributions(),
            "judge_distributions": judge_distributions(bundles),
            "forbidden_terms": ["private-forum-id", "Secret Paper Title"],
        }
        arguments.update(overrides)
        return tracking.record_wandb_batch_offline(**arguments)

    def test_logs_one_validated_candidate_run_with_exact_batch_tables(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking_batch_success")
        fake = FakeWandb()

        with tempfile.TemporaryDirectory() as directory:
            run_id, run_directory = self.call_batch(
                tracking,
                fake,
                directory,
            )

        self.assertEqual(run_id, "offline-batch-run")
        self.assertEqual(
            run_directory,
            str(Path("/tmp/offline-run-batch").resolve()),
        )
        self.assertEqual(len(fake.init_calls), 1)
        self.assertEqual(len(fake.log_calls), 1)
        self.assertEqual(fake.init_calls[0]["mode"], "offline")
        self.assertEqual(
            fake.init_calls[0]["job_type"],
            "review-prompt-candidate",
        )
        self.assertEqual(fake.init_calls[0]["group"], "n5-001")
        self.assertEqual(fake.init_calls[0]["name"], "p0")
        self.assertEqual(
            fake.settings_calls,
            [
                {
                    "console": "off",
                    "disable_code": True,
                    "disable_git": True,
                    "disable_job_creation": True,
                    "x_disable_machine_info": True,
                    "x_disable_meta": True,
                    "x_disable_stats": True,
                    "x_save_requirements": False,
                    "save_code": False,
                }
            ],
        )

        payload = fake.log_calls[0]
        table_keys = {
            key for key, value in payload.items() if isinstance(value, FakeTable)
        }
        self.assertEqual(
            table_keys,
            {"reviews/all", "score_distributions", "judge_distributions"},
        )
        reviews = payload["reviews/all"]
        self.assertEqual(
            reviews.columns,
            ["paper_id", "generated_review_json", "judge_json"],
        )
        self.assertEqual(len(reviews.rows), 5)
        self.assertEqual(len({row[0] for row in reviews.rows}), 5)

        scores = payload["score_distributions"]
        self.assertEqual(
            scores.columns,
            ["kind", "dimension", "score", "count", "frequency", "sample_count"],
        )
        self.assertEqual(len(scores.rows), 49)
        self.assertEqual(
            sum(row[0] == "predicted" for row in scores.rows),
            27,
        )
        self.assertEqual(
            sum(row[0] == "reference" for row in scores.rows),
            22,
        )
        self.assertNotIn("paper_id", scores.columns)

        judges = payload["judge_distributions"]
        self.assertEqual(
            judges.columns,
            ["dimension", "score", "count", "frequency", "sample_count"],
        )
        self.assertEqual(len(judges.rows), 45)
        self.assertNotIn("paper_id", judges.columns)
        self.assertEqual(payload["objective/composite"], 0.8)

    def test_rejects_any_batch_size_other_than_five_before_init(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking_batch_size")

        for count in (4, 6):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as parent:
                fake = FakeWandb()
                output = Path(parent) / "wandb"
                bundles = publish_bundles()
                if count == 4:
                    bundles = bundles[:-1]
                else:
                    extra = dict(bundles[-1])
                    extra["paper_id"] = "paper-batch-extra"
                    bundles.append(extra)

                with self.assertRaisesRegex(ValueError, "exactly 5"):
                    self.call_batch(
                        tracking,
                        fake,
                        str(output),
                        publish_bundles=bundles,
                    )

                self.assertEqual(fake.init_calls, [])
                self.assertFalse(output.exists())

    def test_rejects_invalid_publish_bundle_contract_before_init(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking_bundle_contract")
        cases: list[tuple[str, list[dict[str, object]], str]] = []

        duplicate = publish_bundles()
        duplicate[1]["paper_id"] = duplicate[0]["paper_id"]
        cases.append(("duplicate", duplicate, "duplicate paper_id"))

        original_id = publish_bundles()
        original_id[0]["paper_id"] = "forum12345"
        cases.append(("original id", original_id, "pseudonymous"))

        unexpected_field = publish_bundles()
        unexpected_field[0]["source_id"] = "private-source"
        cases.append(("unexpected field", unexpected_field, "keys do not match schema"))

        wrong_version = publish_bundles()
        wrong_version[0]["schema_version"] = "review-prompt-publish-v0"
        cases.append(("wrong version", wrong_version, "schema_version"))

        bad_review = publish_bundles()
        bad_review[0]["generated_review"] = {
            **bad_review[0]["generated_review"],  # type: ignore[arg-type]
            "raw_human_review": "private reference prose",
        }
        cases.append(("bad review", bad_review, "generated_review"))

        bad_judge = publish_bundles()
        bad_judge[0]["judge"] = {
            **bad_judge[0]["judge"],  # type: ignore[arg-type]
            "reference_review": "private reference prose",
        }
        cases.append(("bad judge", bad_judge, "judge"))

        for label, bundles, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as parent:
                fake = FakeWandb()
                output = Path(parent) / "wandb"

                with self.assertRaisesRegex(ValueError, expected):
                    self.call_batch(
                        tracking,
                        fake,
                        str(output),
                        publish_bundles=bundles,
                    )

                self.assertEqual(fake.settings_calls, [])
                self.assertEqual(fake.init_calls, [])
                self.assertFalse(output.exists())

    def test_batch_allowlists_are_exact_and_separate_from_legacy_fields(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking_batch_allowlists")

        self.assertEqual(
            tracking.REQUIRED_WANDB_BATCH_CONFIG_FIELDS,
            BATCH_CONFIG_FIELDS,
        )
        self.assertEqual(
            tracking.OPTIONAL_WANDB_BATCH_CONFIG_FIELDS,
            BATCH_OPTIONAL_CONFIG_FIELDS,
        )
        self.assertEqual(
            tracking.ALLOWED_WANDB_BATCH_CONFIG_FIELDS,
            BATCH_CONFIG_FIELDS | BATCH_OPTIONAL_CONFIG_FIELDS,
        )
        self.assertEqual(
            tracking.ALLOWED_WANDB_BATCH_METRIC_FIELDS,
            BATCH_METRIC_FIELDS,
        )
        self.assertNotIn(
            "pdf_sha256",
            tracking.REQUIRED_WANDB_BATCH_CONFIG_FIELDS
            | tracking.OPTIONAL_WANDB_BATCH_CONFIG_FIELDS,
        )
        self.assertNotIn(
            "human_review_sha256",
            tracking.REQUIRED_WANDB_BATCH_CONFIG_FIELDS
            | tracking.OPTIONAL_WANDB_BATCH_CONFIG_FIELDS,
        )

    def test_rejects_invalid_batch_config_and_identity_before_init(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking_batch_config")
        base = valid_config()
        cases: list[tuple[str, dict[str, object], dict[str, object], str]] = []

        missing = dict(base)
        del missing["sample_manifest_sha256"]
        cases.append(("missing", missing, {}, "config keys do not match schema"))

        legacy_hash = {**base, "pdf_sha256": "sha256:" + "9" * 64}
        cases.append(("legacy hash", legacy_hash, {}, "config keys do not match schema"))

        campaign_mismatch = {**base, "campaign_id": "n5-other"}
        cases.append(("campaign mismatch", campaign_mismatch, {}, "campaign_id mismatch"))

        candidate_mismatch = {**base, "candidate_id": "p1"}
        cases.append(("candidate mismatch", candidate_mismatch, {}, "candidate_id mismatch"))

        nonfinite = {**base, "objective_human_weight": float("nan")}
        cases.append(("nonfinite", nonfinite, {}, "finite scalar"))

        nonscalar = {**base, "reviewer_model": ["gpt-5.4"]}
        cases.append(("nonscalar", nonscalar, {}, "finite scalar"))

        invalid_hash = {**base, "source_git_sha": "not-a-git-sha"}
        cases.append(("invalid hash", invalid_hash, {}, "source_git_sha"))

        for label, config, extra_arguments, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as parent:
                fake = FakeWandb()
                output = Path(parent) / "wandb"
                with self.assertRaisesRegex(ValueError, expected):
                    self.call_batch(
                        tracking,
                        fake,
                        str(output),
                        config=config,
                        **extra_arguments,
                    )
                self.assertEqual(fake.init_calls, [])
                self.assertFalse(output.exists())

    def test_rejects_non_allowlisted_or_nonfinite_batch_metrics_before_init(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking_batch_metrics")
        cases: list[tuple[str, dict[str, object], str]] = [
            (
                "reference labels",
                {**valid_metrics(), "reference/soundness": 4},
                "outside the allowlist",
            ),
            (
                "nonfinite",
                {**valid_metrics(), "objective/composite": float("inf")},
                "finite number",
            ),
            (
                "nonnumeric",
                {**valid_metrics(), "ops/sample_count": "5"},
                "finite number",
            ),
            (
                "boolean",
                {**valid_metrics(), "ops/failure_count": False},
                "finite number",
            ),
        ]

        for label, metrics, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as parent:
                fake = FakeWandb()
                output = Path(parent) / "wandb"
                with self.assertRaisesRegex(ValueError, expected):
                    self.call_batch(
                        tracking,
                        fake,
                        str(output),
                        metrics=metrics,
                    )
                self.assertEqual(fake.init_calls, [])
                self.assertFalse(output.exists())

    def test_rejects_invalid_distribution_schema_or_arithmetic_before_init(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking_distributions")
        bundles = publish_bundles()
        predicted = predicted_distributions(bundles)
        reference = reference_distributions()
        judges = judge_distributions(bundles)
        cases: list[tuple[str, dict[str, object], str]] = []

        missing_dimension = json.loads(json.dumps(predicted))
        del missing_dimension["confidence"]
        cases.append(
            (
                "missing dimension",
                {"predicted_distributions": missing_dimension},
                "predicted_distributions dimensions",
            )
        )

        wrong_sample_count = json.loads(json.dumps(reference))
        wrong_sample_count["soundness"]["sample_count"] = 4
        cases.append(
            (
                "wrong sample count",
                {"reference_distributions": wrong_sample_count},
                "sample_count must be 5",
            )
        )

        bad_count_sum = json.loads(json.dumps(judges))
        bad_count_sum["rubric_coverage"]["counts"]["1"] += 1
        cases.append(
            (
                "bad count sum",
                {"judge_distributions": bad_count_sum},
                "counts must sum to 5",
            )
        )

        bad_frequency = json.loads(json.dumps(reference))
        bad_frequency["presentation"]["frequencies"]["1"] = 0.99
        cases.append(
            (
                "bad frequency",
                {"reference_distributions": bad_frequency},
                "frequency does not equal count / sample_count",
            )
        )

        nonfinite_frequency = json.loads(json.dumps(predicted))
        nonfinite_frequency["significance"]["frequencies"]["1"] = float("nan")
        cases.append(
            (
                "nonfinite frequency",
                {"predicted_distributions": nonfinite_frequency},
                "frequency must be a finite number",
            )
        )

        boolean_count = json.loads(json.dumps(reference))
        boolean_count["originality"]["counts"]["1"] = True
        cases.append(
            (
                "boolean count",
                {"reference_distributions": boolean_count},
                "count must be an integer",
            )
        )

        per_paper_linkage = json.loads(json.dumps(reference))
        per_paper_linkage["soundness"]["paper_ids"] = ["paper-batch-00"]
        cases.append(
            (
                "per-paper linkage",
                {"reference_distributions": per_paper_linkage},
                "keys do not match schema",
            )
        )

        mismatched_prediction = json.loads(json.dumps(predicted))
        mismatched_prediction["soundness"]["counts"]["1"] = 1
        mismatched_prediction["soundness"]["counts"]["2"] = 2
        mismatched_prediction["soundness"]["frequencies"]["1"] = 0.2
        mismatched_prediction["soundness"]["frequencies"]["2"] = 0.4
        cases.append(
            (
                "mismatched prediction",
                {"predicted_distributions": mismatched_prediction},
                "does not match publish_bundles",
            )
        )

        for label, overrides, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as parent:
                fake = FakeWandb()
                output = Path(parent) / "wandb"
                with self.assertRaisesRegex(ValueError, expected):
                    self.call_batch(
                        tracking,
                        fake,
                        str(output),
                        publish_bundles=bundles,
                        **overrides,
                    )
                self.assertEqual(fake.settings_calls, [])
                self.assertEqual(fake.init_calls, [])
                self.assertFalse(output.exists())

    def test_rejects_identifier_terms_and_sensitive_markers_before_init(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking_privacy_scan")
        cases: list[
            tuple[str, list[dict[str, object]], dict[str, object], list[str]]
        ] = []

        identifier = publish_bundles()
        identifier[0]["generated_review"]["summary"] = (  # type: ignore[index]
            "SECRET PAPER TITLE presents a grounded method."
        )
        cases.append(("identifier", identifier, {}, ["Secret Paper Title"]))

        raw_marker = publish_bundles()
        raw_marker[0]["generated_review"]["summary"] = (  # type: ignore[index]
            "The private forum_id is embedded here."
        )
        cases.append(("raw marker", raw_marker, {}, []))

        source_path = publish_bundles()
        source_path[0]["judge"]["rationale"] = (  # type: ignore[index]
            "Evidence was copied from /Users/alice/private-paper.pdf."
        )
        cases.append(("source path", source_path, {}, []))

        config_identifier = publish_bundles()
        config = {**valid_config(), "reviewer_model": "PrivateModel-123"}
        cases.append(
            (
                "config identifier",
                config_identifier,
                {"config": config},
                ["privatemodel-123"],
            )
        )

        for label, bundles, overrides, forbidden in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as parent:
                fake = FakeWandb()
                output = Path(parent) / "wandb"
                with self.assertRaisesRegex(ValueError, "privacy scan") as raised:
                    self.call_batch(
                        tracking,
                        fake,
                        str(output),
                        publish_bundles=bundles,
                        forbidden_terms=forbidden,
                        **overrides,
                    )
                for term in forbidden:
                    self.assertNotIn(term.casefold(), str(raised.exception).casefold())
                self.assertEqual(fake.settings_calls, [])
                self.assertEqual(fake.init_calls, [])
                self.assertFalse(output.exists())

    def test_rejects_invalid_forbidden_term_contract_before_init(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking_forbidden_terms")

        for forbidden_terms in ([""], ["  "], [123], "one-string"):
            with self.subTest(forbidden_terms=forbidden_terms), tempfile.TemporaryDirectory() as parent:
                fake = FakeWandb()
                output = Path(parent) / "wandb"
                with self.assertRaisesRegex(ValueError, "forbidden_terms"):
                    self.call_batch(
                        tracking,
                        fake,
                        str(output),
                        forbidden_terms=forbidden_terms,
                    )
                self.assertEqual(fake.init_calls, [])
                self.assertFalse(output.exists())

    def test_rejects_boundary_sensitive_category_marker_variants_before_init(
        self,
    ) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking_marker_variants")
        markers = (
            "source_url",
            "source url",
            "source-url",
            "original_title",
            "original title",
            "original-title",
            "reference_id",
            "reference id",
            "reference-id",
        )

        for marker in markers:
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as parent:
                bundles = publish_bundles()
                bundles[0]["generated_review"]["summary"] = (  # type: ignore[index]
                    f"The private {marker} value is present."
                )
                fake = FakeWandb()
                output = Path(parent) / "wandb"
                with self.assertRaisesRegex(ValueError, "privacy scan"):
                    self.call_batch(
                        tracking,
                        fake,
                        str(output),
                        publish_bundles=bundles,
                        forbidden_terms=[],
                    )
                self.assertEqual(fake.settings_calls, [])
                self.assertEqual(fake.init_calls, [])
                self.assertFalse(output.exists())

    def test_boundary_sensitive_category_scan_does_not_reject_originality(
        self,
    ) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking_originality")
        bundles = publish_bundles()
        bundles[0]["generated_review"]["summary"] = (  # type: ignore[index]
            "The originality assessment is supported by concrete evidence."
        )
        fake = FakeWandb()

        with tempfile.TemporaryDirectory() as directory:
            self.call_batch(
                tracking,
                fake,
                directory,
                publish_bundles=bundles,
                forbidden_terms=[],
            )

        self.assertEqual(len(fake.init_calls), 1)


if __name__ == "__main__":
    unittest.main()
