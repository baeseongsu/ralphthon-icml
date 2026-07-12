from __future__ import annotations

import importlib.util
import hashlib
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
CODEX_RUNNER = SCRIPTS / "review_prompt_codex.py"
LOOP_RUNNER = SCRIPTS / "review_prompt_loop.py"
JUDGE_PROMPT = ASSETS / "judge-prompt.md"
REVIEW_SCHEMA = ASSETS / "generated-review.schema.json"
JUDGE_SCHEMA = ASSETS / "judge.schema.json"
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


def valid_human_review() -> dict[str, object]:
    return {
        "forum_id": "sample1234",
        "summary": "RAW HUMAN REVIEW SENTINEL summary",
        "strengths_and_weaknesses": "Detailed strengths and weaknesses.",
        "soundness": 3,
        "presentation": 3,
        "significance": 3,
        "originality": 3,
        "key_questions_for_authors": "One question.",
        "limitations": "One limitation.",
        "overall_recommendation": 4,
        "confidence": 4,
    }


def write_fake_codex(path: Path, log_path: Path) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    script = f"""#!{sys.executable}
import json
import pathlib
import sys

args = sys.argv[1:]
if args == ["login", "status"]:
    print("Logged in using ChatGPT")
    raise SystemExit(0)
if args == ["--version"]:
    print("codex-cli 0.test")
    raise SystemExit(0)
if not args or args[0] != "exec":
    raise SystemExit(2)

prompt = sys.stdin.read()
cwd = pathlib.Path.cwd()
files = sorted(item.name for item in cwd.iterdir())
entry = {{"args": args, "prompt": prompt, "files": files}}
with pathlib.Path({str(log_path)!r}).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(entry, sort_keys=True) + "\\n")

output = pathlib.Path(args[args.index("--output-last-message") + 1])
if "independent Judge" in prompt:
    payload = {fixture["judge"]!r}
else:
    payload = {fixture["generated_review"]!r}
output.write_text(json.dumps(payload), encoding="utf-8")
print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 10, "output_tokens": 5}}}}))
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def write_fake_pdf_tool(path: Path, output: str) -> None:
    path.write_text(
        f"#!{sys.executable}\nprint({output!r})\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


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
    def test_human_review_record_is_normalized_to_single_reviewer_labels(self) -> None:
        scoring = load_module(SCORING, "review_prompt_scoring")
        review = valid_human_review()

        scoring.validate_human_review_record(review)
        labels = scoring.human_labels_from_reviews([review])

        self.assertEqual(
            labels["human_scores"],
            {
                "soundness": [3.0],
                "presentation": [3.0],
                "significance": [3.0],
                "originality": [3.0],
                "overall_recommendation": [4.0],
            },
        )
        self.assertEqual(labels["human_confidence"], [4.0])
        self.assertNotIn("summary", labels)

    def test_codex_output_contracts_are_strict_and_label_blind(self) -> None:
        review_schema = json.loads(REVIEW_SCHEMA.read_text(encoding="utf-8"))
        judge_schema = json.loads(JUDGE_SCHEMA.read_text(encoding="utf-8"))
        judge_prompt = JUDGE_PROMPT.read_text(encoding="utf-8").lower()

        self.assertFalse(review_schema["additionalProperties"])
        self.assertFalse(judge_schema["additionalProperties"])
        self.assertEqual(
            set(review_schema["required"]),
            {
                "summary",
                "strengths",
                "weaknesses",
                "questions",
                "limitations",
                "ethical_concerns",
                "evidence_trace",
                "scores",
                "score_rationales",
            },
        )
        self.assertEqual(set(judge_schema["required"]), {"scores", "rationale"})
        self.assertNotIn("human_scores", judge_prompt)
        self.assertIn("reference review", judge_prompt)

    def test_codex_runner_uses_two_isolated_label_blind_read_only_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"%PDF-1.4 fake public paper")
            human_review_path = root / "human-review.json"
            human_review_path.write_text(
                json.dumps(valid_human_review()), encoding="utf-8"
            )
            invocation_log = root / "codex-invocations.jsonl"
            fake_codex = root / "codex"
            write_fake_codex(fake_codex, invocation_log)
            fake_pdftotext = root / "pdftotext"
            write_fake_pdf_tool(
                fake_pdftotext,
                "PDF-DERIVED PAPER TEXT " * 200,
            )
            fake_pdfinfo = root / "pdfinfo"
            write_fake_pdf_tool(
                fake_pdfinfo,
                "Title: Synthetic Paper\\nAuthor: Alice Example",
            )
            output = root / "run"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(CODEX_RUNNER),
                    "--paper-pdf",
                    str(pdf),
                    "--human-review-json",
                    str(human_review_path),
                    "--reviewer-prompt",
                    str(PROMPT),
                    "--judge-prompt",
                    str(JUDGE_PROMPT),
                    "--review-schema",
                    str(REVIEW_SCHEMA),
                    "--judge-schema",
                    str(JUDGE_SCHEMA),
                    "--output-dir",
                    str(output),
                    "--campaign-id",
                    "codex-smoke",
                    "--candidate-id",
                    "baseline",
                    "--reviewer-model",
                    "fake-reviewer",
                    "--judge-model",
                    "fake-judge",
                    "--codex-bin",
                    str(fake_codex),
                    "--pdftotext-bin",
                    str(fake_pdftotext),
                    "--pdfinfo-bin",
                    str(fake_pdfinfo),
                    "--wandb-mode",
                    "disabled",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            invocations = [
                json.loads(line)
                for line in invocation_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(invocations), 2)
            reviewer, judge = invocations
            for invocation in invocations:
                self.assertIn("PDF-DERIVED PAPER TEXT", invocation["prompt"])
                self.assertNotIn("human_scores", invocation["prompt"])
                self.assertIn("--ephemeral", invocation["args"])
                self.assertIn("--ignore-user-config", invocation["args"])
                self.assertIn("--output-schema", invocation["args"])
                for feature in ("shell_tool", "apps", "multi_agent"):
                    self.assertIn(feature, invocation["args"])
                self.assertIn('web_search="disabled"', invocation["args"])
                sandbox = invocation["args"].index("--sandbox")
                self.assertEqual(invocation["args"][sandbox + 1], "read-only")
            self.assertNotIn("RAW HUMAN REVIEW SENTINEL", reviewer["prompt"])
            self.assertIn("RAW HUMAN REVIEW SENTINEL", judge["prompt"])
            self.assertIn("BEGIN_REFERENCE_HUMAN_REVIEW", judge["prompt"])
            reference_block = judge["prompt"].split(
                "<BEGIN_REFERENCE_HUMAN_REVIEW>", 1
            )[1].split("<END_REFERENCE_HUMAN_REVIEW>", 1)[0]
            self.assertNotIn('"soundness"', reference_block)
            self.assertNotIn('"overall_recommendation"', reference_block)
            self.assertNotIn("Smoke Baseline", judge["prompt"])
            self.assertTrue((output / "generated-review.json").is_file())
            self.assertTrue((output / "judge.json").is_file())
            self.assertTrue((output / "metrics.json").is_file())
            provenance = json.loads(
                (output / "provenance.json").read_text(encoding="utf-8")
            )
            self.assertEqual(provenance["auth_mode"], "chatgpt")
            self.assertEqual(provenance["codex_cli_version"], "codex-cli 0.test")
            self.assertIn("paper_text_sha256", provenance)
            self.assertIn("review_schema_sha256", provenance)
            self.assertIn("judge_schema_sha256", provenance)
            self.assertIn("generated_review_sha256", provenance)
            self.assertIn("judge_sha256", provenance)

    def test_codex_runner_reports_jsonl_failure_message(self) -> None:
        runner = load_module(CODEX_RUNNER, "review_prompt_codex")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_codex = root / "codex"
            fake_codex.write_text(
                f"""#!{sys.executable}
import json
print(json.dumps({{"type": "turn.failed", "error": {{"message": "model requires newer version"}}}}))
raise SystemExit(1)
""",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)

            with self.assertRaisesRegex(RuntimeError, "requires newer version"):
                runner.run_codex_json(
                    codex_bin=str(fake_codex),
                    model="unsupported-model",
                    prompt="diagnostic",
                    schema=JUDGE_SCHEMA,
                    workdir=root,
                    timeout_seconds=30,
                )

    def test_two_iteration_decision_keeps_only_improving_candidate(self) -> None:
        loop = load_module(LOOP_RUNNER, "review_prompt_loop")

        decisions = loop.candidate_decisions(
            [
                {
                    "candidate_id": "baseline", "composite": 0.70,
                    "human_agreement": 0.70, "judge_quality": 0.70,
                    "human_dimension_agreement": {"soundness": 0.70},
                },
                {
                    "candidate_id": "candidate-001", "composite": 0.75,
                    "human_agreement": 0.75, "judge_quality": 0.75,
                    "human_dimension_agreement": {"soundness": 0.75},
                },
            ]
        )

        self.assertEqual(decisions[0]["decision"], "baseline")
        self.assertEqual(decisions[1]["decision"], "keep")
        self.assertAlmostEqual(decisions[1]["delta"], 0.05)
        self.assertEqual(decisions[1]["parent_candidate_id"], "baseline")

    def test_higher_composite_is_discarded_on_dimension_regression(self) -> None:
        loop = load_module(LOOP_RUNNER, "review_prompt_loop_regression")
        decisions = loop.candidate_decisions(
            [
                {
                    "candidate_id": "baseline", "composite": 0.80,
                    "human_agreement": 0.80, "judge_quality": 0.80,
                    "human_dimension_agreement": {"soundness": 0.90},
                },
                {
                    "candidate_id": "candidate-001", "composite": 0.82,
                    "human_agreement": 0.84, "judge_quality": 0.80,
                    "human_dimension_agreement": {"soundness": 0.70},
                },
            ]
        )
        self.assertEqual(decisions[1]["decision"], "discard")
        self.assertEqual(decisions[1]["rejection_reason"], "dimension_regression")

    def test_discarded_candidate_never_becomes_next_parent(self) -> None:
        loop = load_module(LOOP_RUNNER, "review_prompt_loop_lineage")
        records = [
            {
                "candidate_id": "baseline", "composite": 0.80,
                "human_agreement": 0.80, "judge_quality": 0.80,
                "human_dimension_agreement": {"soundness": 0.90},
            },
            {
                "candidate_id": "discarded", "composite": 0.82,
                "human_agreement": 0.84, "judge_quality": 0.80,
                "human_dimension_agreement": {"soundness": 0.70},
            },
        ]

        self.assertEqual(loop.next_parent_id(records), "baseline")

    def test_wandb_redaction_removes_forum_title_method_and_authors(self) -> None:
        runner = load_module(CODEX_RUNNER, "review_prompt_codex_redaction")
        review = valid_human_review()
        review["forum_id"] = "5Q4hoiHhoU"
        metadata = {
            "title": "UI2CodeN: UI-to-Code Generation",
            "author": "Zhen Yang, Wenyi Hong",
        }
        payload = {
            "summary": "UI2CodeN and UI2Code-Real by Zhen Yang appear in 5Q4hoiHhoU.",
            "rationale": "UI2CodeN: UI-to-Code Generation; Wenyi Hong.",
        }

        sanitized = runner.redact_value(
            payload, runner.redaction_terms(review, metadata)
        )
        serialized = json.dumps(sanitized)

        for identifier in ("5Q4hoiHhoU", "UI2CodeN", "Zhen Yang", "Wenyi Hong"):
            self.assertNotIn(identifier, serialized)
        self.assertNotIn("UI2Code", serialized)

    def test_wandb_judge_redacts_copied_reference_phrase(self) -> None:
        runner = load_module(CODEX_RUNNER, "review_prompt_codex_reference")
        reference = {
            "summary": "The proposed system uses iterative visual feedback to refine generated code.",
            "strengths_and_weaknesses": "The experiments are broad but baseline coverage is incomplete.",
            "key_questions_for_authors": "How sensitive is the method to evaluator noise?",
            "limitations": "The compute cost is not fully reported.",
        }
        judge = {
            "scores": {dimension: 4 for dimension in JUDGE_DIMENSIONS},
            "rationale": "The proposed system uses iterative visual feedback to refine generated code.",
        }

        sanitized = runner.sanitize_judge_for_wandb(judge, [], reference)

        self.assertEqual(
            sanitized["rationale"], "[REDACTED_REFERENCE_OVERLAP]"
        )

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

    def test_wandb_accepts_aggregate_codex_usage_metrics(self) -> None:
        tracking = load_module(TRACKING, "review_prompt_tracking")
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fake = FakeWandb()
        metrics = {
            "objective/composite": 0.8,
            "usage/reviewer_input_tokens": 100,
            "usage/reviewer_output_tokens": 20,
            "usage/judge_input_tokens": 80,
            "usage/judge_output_tokens": 10,
        }

        with tempfile.TemporaryDirectory() as directory:
            tracking.record_wandb_offline(
                wandb_module=fake,
                directory=Path(directory),
                entity="smoke-entity",
                project="review-prompt-smoke",
                campaign_id="smoke-usage",
                candidate_id="baseline",
                config={"prompt_sha256": "sha256:" + "a" * 64},
                metrics=metrics,
                paper_id="paper-smoke-001",
                generated_review=fixture["generated_review"],
                judge=fixture["judge"],
            )

        self.assertEqual(
            fake.logged_payload["usage/reviewer_input_tokens"], 100
        )

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
