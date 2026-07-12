from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "reviewer-agent"
ASSETS = SKILL_ROOT / "assets"
MANIFEST = ASSETS / "deploy-manifest.json"
P2 = ASSETS / "reviewer-prompt.md"
SOURCE_P2 = (
    ROOT
    / "skills"
    / "auto-research"
    / "assets"
    / "review-optimization"
    / "smoke-prompt-calibration-v3.md"
)
FIXTURE = (
    ROOT
    / "skills"
    / "auto-research"
    / "assets"
    / "review-optimization"
    / "smoke-fixture.json"
)
RUNNER = SKILL_ROOT / "scripts" / "run_review.py"


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path: Path, name: str):
    scripts_directory = str(path.parent)
    if scripts_directory not in sys.path:
        sys.path.insert(0, scripts_directory)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def valid_review() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["generated_review"]


def deploy_args(pdf: Path, output: Path) -> Namespace:
    return Namespace(
        paper_pdf=pdf,
        output_dir=output,
        model=None,
        codex_bin="codex",
        pdftotext_bin="pdftotext",
        timeout_seconds=60,
        max_attempts=1,
    )


class DeploymentManifestContractTest(unittest.TestCase):
    def test_manifest_pins_p2_model_prompt_and_schema_hashes(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        prompt = SKILL_ROOT / manifest["prompt_path"]
        schema = SKILL_ROOT / manifest["output_schema_path"]

        self.assertEqual(manifest["candidate_id"], "p2")
        self.assertEqual(manifest["status"], "keep")
        self.assertEqual(manifest["model"], "gpt-5.4")
        self.assertEqual(manifest["prompt_sha256"], sha256_file(prompt))
        self.assertEqual(manifest["output_schema_sha256"], sha256_file(schema))
        self.assertEqual(prompt.read_bytes(), SOURCE_P2.read_bytes())


class ReviewerOnlyDeploymentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.deploy = load_module(RUNNER, "review_prompt_deploy_test")

    def test_manifest_loader_returns_only_kept_p2_deployment(self) -> None:
        deployment = self.deploy.load_deployment(SKILL_ROOT, MANIFEST)

        self.assertEqual(deployment.candidate_id, "p2")
        self.assertEqual(deployment.status, "keep")
        self.assertEqual(deployment.model, "gpt-5.4")
        self.assertEqual(deployment.prompt_path, P2)
        self.assertEqual(
            self.deploy.sha256_file(deployment.prompt_path),
            deployment.prompt_sha256,
        )

    def test_manifest_loader_rejects_manifest_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "deploy-manifest.json"
            manifest.write_text(MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "inside the repository"):
                self.deploy.load_deployment(SKILL_ROOT, manifest)

    def test_request_contains_p2_and_paper_but_no_reference_or_judge(self) -> None:
        request = self.deploy.deployment_request(
            P2.read_text(encoding="utf-8"),
            "DEPLOYMENT PAPER SENTINEL",
        )

        self.assertIn("ICML 2026 Review Agent", request)
        self.assertIn("BEGIN_UNTRUSTED_PAPER_TEXT", request)
        self.assertIn("DEPLOYMENT PAPER SENTINEL", request)
        self.assertNotIn("REFERENCE_HUMAN_REVIEW", request)
        self.assertNotIn("independent Judge", request)
        self.assertNotIn("human review", request.lower())

    def test_success_writes_exact_reviewer_only_outputs(self) -> None:
        captured: list[tuple[str, Path, str]] = []

        def fake_invoke(request: str, schema: Path, model: str):
            captured.append((request, schema, model))
            return valid_review(), {"input_tokens": 100, "output_tokens": 50}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            output = root / "review-output"
            pdf.write_bytes(b"%PDF-1.7 synthetic deployment fixture")

            result = self.deploy.run(
                deploy_args(pdf, output),
                reviewer_invoke=fake_invoke,
                preflight=lambda _: ("codex-cli test", "chatgpt"),
                extract=lambda _pdf, _binary: "paper evidence " * 200,
            )

            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"review.json", "review.md", "provenance.json"},
            )
            review = json.loads((output / "review.json").read_text(encoding="utf-8"))
            provenance = json.loads(
                (output / "provenance.json").read_text(encoding="utf-8")
            )
            markdown = (output / "review.md").read_text(encoding="utf-8")
            self.assertEqual(review, valid_review())
            self.assertEqual(provenance["candidate_id"], "p2")
            self.assertEqual(provenance["review_sha256"], result["review_sha256"])
            self.assertEqual(provenance["reviewer_usage"]["input_tokens"], 100)
            self.assertNotIn("paper evidence", json.dumps(provenance).lower())
            self.assertNotIn("judge", json.dumps(provenance).lower())
            self.assertNotIn("reference", json.dumps(provenance).lower())
            self.assertIn("# ICML Review", markdown)
            self.assertIn("## Score Rationales", markdown)
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0][2], "gpt-5.4")

    def test_invalid_review_removes_new_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            output = root / "review-output"
            pdf.write_bytes(b"%PDF-1.7 synthetic deployment fixture")

            with self.assertRaises(Exception):
                self.deploy.run(
                    deploy_args(pdf, output),
                    reviewer_invoke=lambda _request, _schema, _model: (
                        {"summary": "schema-invalid"},
                        {},
                    ),
                    preflight=lambda _: ("codex-cli test", "chatgpt"),
                    extract=lambda _pdf, _binary: "paper evidence " * 200,
                )

            self.assertFalse(output.exists())

    def test_cli_is_pdf_only_and_has_no_evaluation_arguments(self) -> None:
        parser = self.deploy.build_parser()
        option_strings = {
            option
            for action in parser._actions
            for option in action.option_strings
        }

        self.assertIn("--paper-pdf", option_strings)
        self.assertIn("--output-dir", option_strings)
        for forbidden in (
            "--human-review-json",
            "--judge-prompt",
            "--judge-model",
            "--wandb-mode",
            "--reviewer-prompt",
        ):
            self.assertNotIn(forbidden, option_strings)


if __name__ == "__main__":
    unittest.main()
