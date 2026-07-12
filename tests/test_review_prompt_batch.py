from __future__ import annotations

import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "auto-research" / "scripts"
SCORING = SCRIPTS / "review_prompt_scoring.py"
DATASET = SCRIPTS / "review_prompt_dataset.py"
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


def pseudo_label(forum_id: str, *, recommendation: int = 4) -> dict[str, object]:
    return {
        "forum_id": forum_id,
        "summary": "A reference summary grounded in the paper.",
        "strengths_and_weaknesses": "Specific strengths and bounded weaknesses.",
        "soundness": 3,
        "presentation": 3,
        "significance": 3,
        "originality": 3,
        "key_questions_for_authors": "What evidence supports the central claim?",
        "limitations": "The reference review identifies one limitation.",
        "overall_recommendation": recommendation,
        "confidence": 4,
    }


def dataset_row(index: int, *, recommendation: int) -> dict[str, object]:
    source_id = f"source-{index:02d}"
    label = pseudo_label(source_id, recommendation=recommendation)
    scores = {
        field: label[field]
        for field in (
            "soundness",
            "presentation",
            "significance",
            "originality",
            "overall_recommendation",
            "confidence",
        )
    }
    scores["soundness"] = 2 + index % 3
    scores["presentation"] = 2 + (index + 1) % 3
    scores["significance"] = 2 + (index + 2) % 3
    scores["originality"] = 2 + (index // 2) % 3
    return {
        "source_id": source_id,
        "status": "valid",
        "reasons": [],
        "label_path": f"/labels/{source_id}.json",
        "pdf_path": f"/pdfs/{source_id}.pdf",
        "label_sha256": f"label-{index:064d}"[-64:],
        "pdf_sha256": f"pdf-{index:064d}"[-64:],
        "paper_text_sha256": f"text-{index:064d}"[-64:],
        "pdf_bytes": 2048 + index,
        "paper_text_chars": 2000 + index,
        "title": f"Synthetic Paper {index}",
        "authors": f"Author {index}",
        "scores": scores,
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


class DatasetContractTest(unittest.TestCase):
    def test_balanced_selector_is_order_independent_and_uses_exact_quotas(self) -> None:
        dataset = load_module(DATASET, "review_prompt_dataset_selector_test")
        rows = [
            dataset_row(index, recommendation=4 if index < 8 else 5)
            for index in range(10)
        ]

        selected = dataset.select_balanced(rows, count=5, seed=20260713)
        reversed_selected = dataset.select_balanced(
            list(reversed(rows)),
            count=5,
            seed=20260713,
        )

        self.assertEqual(
            [row["source_id"] for row in selected],
            [row["source_id"] for row in reversed_selected],
        )
        self.assertEqual(
            Counter(row["scores"]["overall_recommendation"] for row in selected),
            {4: 4, 5: 1},
        )

        tie_rows = [
            dataset_row(index, recommendation=4 if index < 3 else 5)
            for index in range(4)
        ]
        tie_selected = dataset.select_balanced(tie_rows, count=2, seed=7)
        self.assertEqual(
            Counter(row["scores"]["overall_recommendation"] for row in tie_selected),
            {4: 2},
        )

    def test_preflight_classifies_blank_pdf_metadata_explicitly(self) -> None:
        dataset = load_module(DATASET, "review_prompt_dataset_preflight_test")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            labels = root / "labels"
            pdfs = root / "pdfs"
            labels.mkdir()
            pdfs.mkdir()
            ids = ("valid001", "blanktitle", "nometa001")
            for source_id in ids:
                (labels / f"{source_id}.json").write_text(
                    json.dumps(pseudo_label(source_id), sort_keys=True),
                    encoding="utf-8",
                )
                (pdfs / f"{source_id}.pdf").write_bytes(
                    b"%PDF-1.7\nsynthetic public paper"
                )

            pdfinfo = root / "pdfinfo"
            pdfinfo.write_text(
                """#!/usr/bin/env python3
import pathlib
import sys

stem = pathlib.Path(sys.argv[-1]).stem
metadata = {
    "valid001": "Title: Valid Synthetic Paper\\nAuthor: Anonymous Authors",
    "blanktitle": "Title:    \\nAuthor: Anonymous Authors",
    "nometa001": "Pages: 12",
}
print(metadata[stem])
""",
                encoding="utf-8",
            )
            pdfinfo.chmod(0o755)
            pdftotext = root / "pdftotext"
            pdftotext.write_text(
                """#!/usr/bin/env python3
print("PDF-derived paper text " * 100)
""",
                encoding="utf-8",
            )
            pdftotext.chmod(0o755)

            pool = dataset.preflight_pool(
                labels_dir=labels,
                pdfs_dir=pdfs,
                pdfinfo_bin=str(pdfinfo),
                pdftotext_bin=str(pdftotext),
                minimum_text_chars=1000,
            )

        by_id = {row["source_id"]: row for row in pool}
        self.assertEqual(by_id["valid001"]["status"], "valid")
        self.assertEqual(
            by_id["blanktitle"]["reasons"],
            ["missing_title_metadata"],
        )
        self.assertEqual(
            by_id["nometa001"]["reasons"],
            ["missing_title_metadata", "missing_author_metadata"],
        )

    def test_freeze_dataset_seals_holdout_and_never_leaks_it_to_development(self) -> None:
        dataset = load_module(DATASET, "review_prompt_dataset_freeze_test")
        rows = [
            dataset_row(index, recommendation=4 if index < 8 else 5)
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = dataset.freeze_dataset(
                rows,
                output_root=root / "first",
                development_count=8,
                holdout_count=2,
                sample_count=4,
                split_seed=20260712,
                sample_seed=20260713,
                permission_provenance="user-attested-public-icml",
            )
            second = dataset.freeze_dataset(
                list(reversed(rows)),
                output_root=root / "second",
                development_count=8,
                holdout_count=2,
                sample_count=4,
                split_seed=20260712,
                sample_seed=20260713,
                permission_provenance="user-attested-public-icml",
            )

            holdout_path = Path(first["holdout_manifest_path"])
            development_path = Path(first["development_manifest_path"])
            sample_path = Path(first["sample_manifest_path"])
            holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
            development_text = development_path.read_text(encoding="utf-8")
            sample_text = sample_path.read_text(encoding="utf-8")
            development = json.loads(development_text)
            sample = json.loads(sample_text)
            second_sample = json.loads(
                Path(second["sample_manifest_path"]).read_text(encoding="utf-8")
            )

            self.assertEqual(stat.S_IMODE(holdout_path.stat().st_mode), 0o600)
            self.assertEqual(len(holdout["entries"]), 2)
            self.assertEqual(len(development["entries"]), 8)
            self.assertEqual(len(sample["entries"]), 4)
            self.assertTrue(
                all(entry["split"] == "development" for entry in sample["entries"])
            )
            for entry in holdout["entries"]:
                self.assertNotIn(entry["source_id"], development_text)
                self.assertNotIn(entry["source_id"], sample_text)
                self.assertNotIn(entry["label_sha256"], development_text)
                self.assertNotIn(entry["label_sha256"], sample_text)
            self.assertNotIn("holdout_score_marginals", development_text)
            self.assertNotIn("holdout_score_marginals", sample_text)
            self.assertEqual(
                development["holdout"],
                {
                    "count": 2,
                    "sealed_manifest_sha256": holdout["manifest_sha256"],
                },
            )
            self.assertEqual(
                [entry["source_id"] for entry in sample["entries"]],
                [entry["source_id"] for entry in second_sample["entries"]],
            )
            self.assertEqual(sample["manifest_sha256"], second_sample["manifest_sha256"])
            self.assertTrue(dataset.verify_manifest_file(sample_path))


if __name__ == "__main__":
    unittest.main()
