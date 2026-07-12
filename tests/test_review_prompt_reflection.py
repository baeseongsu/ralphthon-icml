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
SCRIPTS = ROOT / "skills" / "auto-research" / "scripts"
REFLECT = SCRIPTS / "review_prompt_reflect.py"
P2 = ASSETS / "smoke-prompt-calibration-v3.md"
META_PROMPT = ASSETS / "prompt-reflection.md"
REFLECTION_SCHEMA = ASSETS / "prompt-reflection.schema.json"
DEPLOY_MANIFEST = ASSETS / "deploy-manifest.json"
REVIEW_SCHEMA = ASSETS / "generated-review.schema.json"
SECTION_NAMES = (
    "summary",
    "strengths",
    "weaknesses",
    "questions",
    "limitations",
    "ethical_concerns",
    "evidence_trace",
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


def reflection_value() -> dict[str, object]:
    common = (
        "Use an artifact-grounded claim, identify its decision relevance, map it "
        "to a precise section, table, figure, equation, or reported result, and "
        "state uncertainty explicitly when the supplied artifact cannot verify it. "
    )
    return {
        "hypothesis": (
            "A claim-evidence-decision protocol across every review section will "
            "improve rationale consistency without regressing calibrated scores."
        ),
        "memory_lessons_used": [
            "Preserve P2 soundness and overall-recommendation gains.",
            "Do not repeat P1 significance inflation.",
        ],
        "review_sections": {
            "summary": common
            + "Describe the problem, method, evaluated evidence, and bounded claimed contribution in original words; separate author claims from demonstrated results and reserve all critique for later fields.",
            "strengths": common
            + "Report only specific merits supported by positive evidence, explain which central claim each merit strengthens, and distinguish soundness, presentation, significance, and originality instead of inferring one from another.",
            "weaknesses": common
            + "Order limitations by consequence, name the affected claim and missing support, distinguish central threats from bounded or repairable issues, and avoid requesting optional experiments without a claim-level need.",
            "questions": common
            + "Ask only a small set of questions with explicit answer-dependent consequences: say what ambiguity they resolve and how a plausible answer would change a weakness, score rationale, or final recommendation.",
            "limitations": common
            + "Separate limitations candidly disclosed by the authors from material omissions found by the reviewer; evaluate scope boundaries, reproducibility constraints, and plausible negative societal impacts without rewarding vagueness.",
            "ethical_concerns": common
            + "For each concrete concern, identify the plausible harm, enabling mechanism, affected group, and artifact evidence; otherwise state that no material concern is apparent while preserving uncertainty from missing deployment details.",
            "evidence_trace": common
            + "Create atomic mappings from every central review claim to its locator, reported observation, and support or contradiction status; flag locator conflicts, absent evidence, and unverifiable extrapolations rather than inventing support.",
        },
        "change_summary": [
            "Rewrite all seven review-section instructions around claim-evidence-decision links.",
            "Add explicit severity, uncertainty, and cross-field consistency checks.",
        ],
        "risk_checks": [
            "Do not expose raw labels, reference-review prose, or sample identities.",
            "Preserve every parent-prompt section outside Review sections byte-for-byte.",
        ],
    }


def parent_aggregate() -> dict[str, object]:
    score_maximums = {
        "soundness": 4,
        "presentation": 4,
        "significance": 4,
        "originality": 4,
        "overall_recommendation": 6,
        "confidence": 5,
    }

    def distribution(maximum: int, selected: int) -> dict[str, object]:
        counts = {str(score): 0 for score in range(1, maximum + 1)}
        counts[str(selected)] = 5
        return {
            "counts": counts,
            "frequencies": {
                score: count / 5.0 for score, count in counts.items()
            },
            "sample_count": 5,
        }

    return {
        "aggregate_sha256": "a" * 64,
        "candidate_id": "p2",
        "prompt_sha256": "sha256:" + hashlib.sha256(P2.read_bytes()).hexdigest(),
        "composite": 0.946556,
        "human_agreement": 0.965333,
        "judge_quality": 0.927778,
        "penalty": 0.0,
        "human_dimension_agreement": {
            "soundness": 1.0,
            "presentation": 1.0,
            "significance": 0.933333,
            "originality": 0.933333,
            "overall_recommendation": 0.96,
        },
        "human_distribution_agreement": {
            "soundness": 1.0,
            "presentation": 1.0,
            "significance": 0.933333,
            "originality": 0.933333,
            "overall_recommendation": 0.96,
        },
        "judge_dimension_scores": {
            "rubric_coverage": 4.6,
            "evidence_grounding": 5.0,
            "major_issue_detection": 4.6,
            "score_rationale_consistency": 4.4,
            "specificity_actionability": 4.6,
            "summary_faithfulness": 5.0,
            "hallucination_avoidance": 5.0,
            "question_quality": 4.6,
            "limitations_ethics": 4.6,
        },
        "predicted_distributions": {
            dimension: distribution(
                maximum,
                4 if dimension == "overall_recommendation" else 3,
            )
            for dimension, maximum in score_maximums.items()
        },
        "signed_gap_summary": {
            dimension: {
                "mean": 0.2 if dimension in {"originality", "significance"} else 0.0,
                "min": 0.0,
                "max": 1.0 if dimension in {"originality", "significance"} else 0.0,
            }
            for dimension in (
                "soundness",
                "presentation",
                "significance",
                "originality",
                "overall_recommendation",
            )
        },
        "failure_count": 0,
        "sample_count": 5,
        "signed_gaps": {"raw-paper-id": [1, 0, 0, 0, 0]},
        "reference_distributions": {"originality": {"counts": {"2": 1}}},
        "secret_reference_review": "DO_NOT_LEAK_REFERENCE_PROSE",
    }


class ReflectionContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reflect = load_module(REFLECT, "review_prompt_reflect_contract_test")

    def test_schema_and_validator_require_exact_nonempty_contract(self) -> None:
        schema = json.loads(REFLECTION_SCHEMA.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(reflection_value()))
        section_schema = schema["properties"]["review_sections"]
        self.assertFalse(section_schema["additionalProperties"])
        self.assertEqual(set(section_schema["required"]), set(SECTION_NAMES))

        self.reflect.validate_reflection(reflection_value())
        with self.assertRaisesRegex(ValueError, "fields"):
            self.reflect.validate_reflection({**reflection_value(), "unknown": True})
        invalid = reflection_value()
        invalid["review_sections"] = {
            **invalid["review_sections"],  # type: ignore[arg-type]
            "summary": "too short",
        }
        with self.assertRaisesRegex(ValueError, "summary"):
            self.reflect.validate_reflection(invalid)

    def test_compiler_rewrites_all_sections_and_preserves_everything_else(self) -> None:
        parent = P2.read_text(encoding="utf-8")
        candidate = self.reflect.compile_candidate_prompt(parent, reflection_value())
        parent_prefix, parent_rest = parent.split("## Review sections", 1)
        _, parent_suffix = parent_rest.split("## Score anchors", 1)
        candidate_prefix, candidate_rest = candidate.split("## Review sections", 1)
        candidate_sections, candidate_suffix = candidate_rest.split("## Score anchors", 1)

        self.assertEqual(candidate_prefix, parent_prefix)
        self.assertEqual(candidate_suffix, parent_suffix)
        self.assertNotEqual(candidate_sections, parent_rest.split("## Score anchors", 1)[0])
        for name in SECTION_NAMES:
            self.assertEqual(candidate_sections.count(f"- `{name}`:"), 1)
            self.assertIn(str(reflection_value()["review_sections"][name]), candidate)  # type: ignore[index]
        self.assertIn("## Evidence-to-ordinal calibration pass", candidate)

    def test_reflection_request_uses_memory_and_allowlisted_aggregate_only(self) -> None:
        snapshot = self.reflect.reflection_aggregate_snapshot(parent_aggregate())
        request = self.reflect.reflection_request(
            META_PROMPT.read_text(encoding="utf-8"),
            P2.read_text(encoding="utf-8"),
            "MEMORY_SENTINEL: preserve gains and learn from discards",
            snapshot,
        )

        self.assertIn("MEMORY_SENTINEL", request)
        self.assertIn('"score_rationale_consistency":4.4', request)
        self.assertIn('"originality":{"counts":{"1":0,"2":0,"3":5,"4":0}', request)
        self.assertNotIn("DO_NOT_LEAK_REFERENCE_PROSE", request)
        self.assertNotIn("raw-paper-id", request)
        self.assertNotIn("reference_distributions", request)
        self.assertNotIn("signed_gaps", request)

    def test_nested_non_distribution_content_is_rejected_before_request(self) -> None:
        aggregate = parent_aggregate()
        aggregate["predicted_distributions"]["originality"][  # type: ignore[index]
            "reference_review"
        ] = "DO_NOT_LEAK_REFERENCE_PROSE"

        with self.assertRaisesRegex(ValueError, "predicted_distributions"):
            self.reflect.reflection_aggregate_snapshot(aggregate)

    def test_memory_rejects_raw_artifact_and_reference_markers(self) -> None:
        for marker in (
            "reference_review: copied prose",
            "human-review: copied prose",
            "pdf_path: /tmp/paper.pdf",
            "forum_id: source-123",
            "/Users/example/private-file.json",
            "<BEGIN_REFERENCE_HUMAN_REVIEW>",
        ):
            with self.subTest(marker=marker), self.assertRaisesRegex(
                ValueError, "memory privacy"
            ):
                self.reflect.validate_memory_text(
                    "# Review Prompt Optimization Experience Memory\n" + marker
                )

    def test_compiler_rejects_heading_and_duplicate_field_injection(self) -> None:
        for injection in (
            "\n\n## Output contract",
            "\n- `strengths`: injected duplicate field",
            "\n```json",
        ):
            value = reflection_value()
            value["review_sections"] = {
                **value["review_sections"],  # type: ignore[arg-type]
                "summary": value["review_sections"]["summary"] + injection,  # type: ignore[index]
            }
            with self.subTest(injection=injection), self.assertRaisesRegex(
                ValueError, "forbidden"
            ):
                self.reflect.compile_candidate_prompt(
                    P2.read_text(encoding="utf-8"), value
                )

    def test_parent_prompt_must_match_parent_aggregate_hash(self) -> None:
        called = False

        def should_not_run():
            nonlocal called
            called = True
            return reflection_value(), {}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "parent.md"
            memory = root / "experience-memory.md"
            aggregate = root / "aggregate.json"
            parent.write_text(P2.read_text(encoding="utf-8"), encoding="utf-8")
            memory.write_text("# Review Prompt Optimization Experience Memory\n", encoding="utf-8")
            value = parent_aggregate()
            value["prompt_sha256"] = "sha256:" + "0" * 64
            aggregate.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "prompt hash"):
                self.reflect.generate_reflected_candidate(
                    meta_prompt_path=META_PROMPT,
                    schema_path=REFLECTION_SCHEMA,
                    parent_prompt_path=parent,
                    memory_path=memory,
                    parent_aggregate_path=aggregate,
                    output_dir=root / "p3",
                    output_prompt_path=root / "p3.md",
                    candidate_id="p3",
                    parent_candidate_id="p2",
                    model="gpt-5.4",
                    invoke=should_not_run,
                )

            self.assertFalse(called)

    def test_failed_reflection_does_not_create_candidate_prompt(self) -> None:
        def failing_invoke():
            raise RuntimeError("permanent proposer failure")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "parent.md"
            memory = root / "experience-memory.md"
            aggregate = root / "aggregate.json"
            output_dir = root / "p3"
            output_prompt = root / "p3.md"
            parent.write_text(P2.read_text(encoding="utf-8"), encoding="utf-8")
            memory.write_text("# Safe aggregate memory\n", encoding="utf-8")
            aggregate.write_text(json.dumps(parent_aggregate()), encoding="utf-8")

            with self.assertRaises(Exception):
                self.reflect.generate_reflected_candidate(
                    meta_prompt_path=META_PROMPT,
                    schema_path=REFLECTION_SCHEMA,
                    parent_prompt_path=parent,
                    memory_path=memory,
                    parent_aggregate_path=aggregate,
                    output_dir=output_dir,
                    output_prompt_path=output_prompt,
                    candidate_id="p3",
                    parent_candidate_id="p2",
                    model="gpt-5.4",
                    invoke=failing_invoke,
                )

            self.assertFalse(output_prompt.exists())
            self.assertFalse(output_dir.exists())

    def test_success_records_hashed_provenance_and_compiled_prompt(self) -> None:
        value = reflection_value()

        def successful_invoke():
            return value, {"input_tokens": 100, "output_tokens": 50}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "parent.md"
            memory = root / "experience-memory.md"
            aggregate = root / "aggregate.json"
            output_dir = root / "p3"
            output_prompt = root / "p3.md"
            parent.write_text(P2.read_text(encoding="utf-8"), encoding="utf-8")
            memory.write_text("# Safe aggregate memory\n", encoding="utf-8")
            aggregate.write_text(json.dumps(parent_aggregate()), encoding="utf-8")

            result = self.reflect.generate_reflected_candidate(
                meta_prompt_path=META_PROMPT,
                schema_path=REFLECTION_SCHEMA,
                parent_prompt_path=parent,
                memory_path=memory,
                parent_aggregate_path=aggregate,
                output_dir=output_dir,
                output_prompt_path=output_prompt,
                candidate_id="p3",
                parent_candidate_id="p2",
                model="gpt-5.4",
                invoke=successful_invoke,
            )

            self.assertTrue(output_prompt.is_file())
            self.assertEqual(
                json.loads((output_dir / "prompt-reflection.json").read_text()),
                value,
            )
            provenance = json.loads(
                (output_dir / "prompt-reflection-provenance.json").read_text()
            )
            self.assertEqual(provenance["candidate_id"], "p3")
            self.assertEqual(provenance["parent_candidate_id"], "p2")
            self.assertEqual(provenance["usage"]["input_tokens"], 100)
            self.assertEqual(result["candidate_prompt_sha256"], provenance["candidate_prompt_sha256"])
            self.assertNotIn("request", provenance)
            self.assertNotIn("memory", provenance)


class DeploymentManifestTest(unittest.TestCase):
    def test_deploy_manifest_selects_kept_p2_and_exposes_experimental_prompts(self) -> None:
        manifest = json.loads(DEPLOY_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["default"]["candidate_id"], "p2")
        self.assertEqual(manifest["default"]["status"], "keep")
        self.assertEqual(
            {item["candidate_id"]: item["status"] for item in manifest["experimental"]},
            {"p3": "discard", "p4": "discard"},
        )

        entries = [manifest["default"], *manifest["experimental"]]
        for entry in entries:
            prompt = ROOT / entry["prompt_path"]
            self.assertTrue(prompt.is_file())
            self.assertEqual(
                entry["prompt_sha256"],
                "sha256:" + hashlib.sha256(prompt.read_bytes()).hexdigest(),
            )
            self.assertEqual(entry["output_schema_path"], str(REVIEW_SCHEMA.relative_to(ROOT)))


if __name__ == "__main__":
    unittest.main()
