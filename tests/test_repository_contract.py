from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = {
    "hello-ralphthon-icml",
    "auto-research",
    "wandb-onboarding",
    "vessl-cloud-onboarding",
    "world-model-ideation",
}


def load_validator():
    path = ROOT / "scripts" / "validate_plugin.py"
    spec = importlib.util.spec_from_file_location("validate_plugin", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_recorder():
    path = ROOT / "skills" / "auto-research" / "scripts" / "record_experiment.py"
    spec = importlib.util.spec_from_file_location("record_experiment", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def complete_a100_summary(**overrides: object) -> dict[str, object]:
    summary: dict[str, object] = {
        "val_bpb": 1.2345,
        "peak_vram_mb": 2048.0,
        "training_seconds": 120.1,
        "total_seconds": 141.2,
        "parameters": 786_468,
        "depth": 2,
        "vocab_size": 1024,
        "max_seq_len": 256,
        "device_batch_size": 64,
        "total_batch_size": 2**14,
        "eval_tokens": 2**18,
        "time_budget": 120,
        "window_pattern": "L",
    }
    summary.update(overrides)
    return summary


class RepositoryContractTest(unittest.TestCase):
    def test_expected_skill_catalog_exists_without_commands(self) -> None:
        skills = {path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md")}

        self.assertEqual(skills, EXPECTED_SKILLS)
        self.assertFalse((ROOT / "commands").exists())
        self.assertFalse((ROOT / "docs" / "superpowers").exists())

    def test_validator_exposes_general_repository_validation(self) -> None:
        validator = load_validator()

        self.assertTrue(hasattr(validator, "validate_repository"))
        if hasattr(validator, "validate_repository"):
            self.assertEqual(validator.validate_repository(ROOT), [])

    def test_validator_rejects_skill_name_directory_mismatch(self) -> None:
        validator = load_validator()
        if not hasattr(validator, "validate_repository"):
            self.fail("validator must expose validate_repository")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plugin"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            skill = root / "skills" / "hello-ralphthon-icml" / "SKILL.md"
            skill.write_text(
                skill.read_text().replace(
                    "name: hello-ralphthon-icml",
                    "name: wrong-skill-name",
                    1,
                )
            )

            messages = [error.message for error in validator.validate_repository(root)]

        self.assertTrue(any("directory name" in message for message in messages))

    def test_validator_rejects_legacy_command_files(self) -> None:
        validator = load_validator()
        if not hasattr(validator, "validate_repository"):
            self.fail("validator must expose validate_repository")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plugin"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            commands = root / "commands"
            commands.mkdir(exist_ok=True)
            (commands / "legacy.md").write_text("legacy command\n")

            messages = [error.message for error in validator.validate_repository(root)]

        self.assertTrue(any("integrate behavior into skills" in message for message in messages))

    def test_manifest_advertises_full_workflow(self) -> None:
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text())
        searchable = " ".join(manifest["keywords"] + manifest["interface"]["defaultPrompt"]).lower()

        for phrase in ("auto-research", "wandb", "vessl", "world-model"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, searchable)

    def test_readme_documents_full_catalog_and_privacy_boundary(self) -> None:
        text = (ROOT / "README.md").read_text()

        for phrase in (
            "hello-ralphthon-icml",
            "auto-research",
            "wandb-onboarding",
            "vessl-cloud-onboarding",
            "world-model-ideation",
            "16:30",
            "W&B",
            "VESSL Cloud",
            "private participant",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

        self.assertNotIn("slash commands", text)
        hello_skill = (ROOT / "skills/hello-ralphthon-icml/SKILL.md").read_text()
        self.assertNotIn("world-model sponsor narrative", hello_skill)

    def test_a100_micro_integration_docs_and_metadata(self) -> None:
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["version"], "0.4.0")
        manifest_text = json.dumps(manifest, ensure_ascii=False)
        for phrase in ("A100-micro-v1", "Karpathy", "W&B", "VESSL"):
            with self.subTest(manifest_phrase=phrase):
                self.assertIn(phrase, manifest_text)

        readme = (ROOT / "README.md").read_text()
        for phrase in (
            "A100-micro-v1",
            "786,468",
            "karpathy/autoresearch",
            "record_experiment.py",
            "Training path",
            "Track 2-only",
            "single A100",
            "W&B offline",
            "live cost",
        ):
            with self.subTest(readme_phrase=phrase):
                self.assertIn(phrase, readme)

        ui = (ROOT / "skills/auto-research/agents/openai.yaml").read_text()
        for phrase in ("A100-micro-v1", "W&B", "VESSL"):
            with self.subTest(ui_phrase=phrase):
                self.assertIn(phrase, ui)

        self.assertFalse((ROOT / "docs" / "superpowers").exists())
        bundle = (ROOT / "skills/auto-research/SKILL.md").read_text()
        for phrase in (
            "A100-micro-v1",
            "786,468",
            "228791fb499afffb54b46200aca536f79142f117",
            "record_experiment.py",
        ):
            with self.subTest(skill_phrase=phrase):
                self.assertIn(phrase, bundle)

    def test_each_skill_contains_integrated_execution_contract(self) -> None:
        for skill_name in EXPECTED_SKILLS:
            text = (ROOT / "skills" / skill_name / "SKILL.md").read_text()
            for heading in ("Preflight", "Workflow", "Verification", "Output", "Next Steps"):
                with self.subTest(skill=skill_name, heading=heading):
                    self.assertIn(f"## {heading}", text)

    def test_skill_references_resolve(self) -> None:
        for skill_name in EXPECTED_SKILLS:
            skill_path = ROOT / "skills" / skill_name / "SKILL.md"
            with self.subTest(skill=skill_name):
                self.assertTrue(skill_path.is_file())
                if not skill_path.is_file():
                    continue
                text = skill_path.read_text()
                for relative in self._reference_links(text):
                    self.assertTrue(
                        (skill_path.parent / relative).is_file(),
                        f"missing reference from {skill_name}: {relative}",
                    )

    @staticmethod
    def _reference_links(text: str) -> list[str]:
        links: list[str] = []
        marker = "](references/"
        for line in text.splitlines():
            offset = 0
            while (start := line.find(marker, offset)) >= 0:
                path_start = start + 2
                path_end = line.find(")", path_start)
                if path_end < 0:
                    break
                links.append(line[path_start:path_end])
                offset = path_end + 1
        return links


class SkillBehaviorContractTest(unittest.TestCase):
    def read_skill(self, name: str) -> str:
        path = ROOT / "skills" / name / "SKILL.md"
        self.assertTrue(path.is_file(), f"missing skill: {name}")
        return path.read_text() if path.is_file() else ""

    def read_auto_research_bundle(self) -> str:
        root = ROOT / "skills" / "auto-research"
        return "\n".join(
            path.read_text()
            for path in sorted(root.rglob("*.md"))
            if path.is_file()
        )

    def test_auto_research_encodes_both_tracks_and_hard_cut(self) -> None:
        text = self.read_skill("auto-research")

        for phrase in (
            "Track 1",
            "2-4 page",
            "Track 2",
            "ICML-style review",
            "16:30",
            "Ralph Loop",
            "self-review",
            "research spec",
            "falsifiable hypothesis",
            "baseline",
            "evaluation metric",
            "evidence",
            "failure modes",
            "Do not fabricate",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

        for relative in (
            "assets/track-1-submission-template.md",
            "assets/track-2-agent-template.md",
            "assets/track-2-review-template.md",
        ):
            with self.subTest(asset=relative):
                self.assertTrue((ROOT / "skills" / "auto-research" / relative).is_file())

        readme = (ROOT / "README.md").read_text()
        for name, document in (("skill", text), ("readme", readme)):
            with self.subTest(general_track_1=name):
                self.assertIn("General Track 1 path", document)
                self.assertIn("does not automatically require W&B, VESSL, or A100", document)
        self.assertIn("review-agent.md", text)
        self.assertIn("Track 2 Review Agent", text)

        skill_training = text.split("### Training path", 1)[1].split(
            "### General Track 1 path", 1
        )[0]
        self.assertIn("For Both", skill_training)
        self.assertIn("review-agent.md", skill_training)
        self.assertIn("track-2-agent-template.md", skill_training)
        self.assertIn("track-2-review-template.md", skill_training)

        output_contract = text.split("## Output", 1)[1].split("## Next Steps", 1)[0]
        for phrase in (
            "exact experiment count",
            "best confirmed `val_bpb`",
            "artifact paths",
        ):
            with self.subTest(training_output=phrase):
                self.assertIn(phrase, output_contract)

    def test_auto_research_encodes_pinned_a100_micro_runtime(self) -> None:
        text = self.read_auto_research_bundle()

        for phrase in (
            "228791fb499afffb54b46200aca536f79142f117",
            "A100-micro-v1",
            "wandb-onboarding",
            "vessl-cloud-onboarding",
            "resource-spec list --usable-only",
            "nvidia-smi",
            "DEPTH=2",
            "ASPECT_RATIO=64",
            "HEAD_DIM=128",
            'WINDOW_PATTERN="L"',
            "VOCAB_SIZE=1024",
            "MAX_SEQ_LEN=256",
            "DEVICE_BATCH_SIZE=64",
            "TOTAL_BATCH_SIZE=2**14",
            "EVAL_TOKENS=2**18",
            "TIME_BUDGET=120",
            "evaluation steps: 16",
            "786,468",
            "prepare.py --num-shards 1",
            "isolated cache",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

        layers = 2
        width = 128
        heads = 1
        vocab = 1024
        value_embedding_layers = (layers + 1) // 2
        parameter_count = (
            (2 + value_embedding_layers) * vocab * width
            + 12 * layers * width**2
            + value_embedding_layers * 32 * heads
            + 2 * layers
        )
        tokens_per_step = 64 * 256

        self.assertEqual(parameter_count, 786_468)
        self.assertEqual(2**14 % tokens_per_step, 0)
        self.assertEqual((2**18) // tokens_per_step, 16)

    def test_auto_research_binds_cost_secret_and_experiment_gates(self) -> None:
        text = self.read_auto_research_bundle()

        for phrase in (
            "explicit confirmation",
            "hourly price",
            "credit",
            "storage",
            "cleanup",
            "Do not fall back",
            "baseline",
            "three candidate trials",
            "winner confirmation",
            "one hypothesis",
            "one change",
            "train.py",
            "experiments.jsonl",
            "dataset fingerprint",
            "tokenizer fingerprint",
            "W&B allowlist",
            "MFU",
            "val_bpb",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

        for forbidden in (
            "git reset --hard",
            "git add -A",
            "wandb login $WANDB_API_KEY",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_auto_research_recorder_parses_and_appends_allowlisted_evidence(self) -> None:
        path = ROOT / "skills" / "auto-research" / "scripts" / "record_experiment.py"
        self.assertTrue(path.is_file())
        if not path.is_file():
            return

        module = load_recorder()

        summary = module.parse_training_summary(
            "\n".join(
                (
                    "val_bpb:          1.234500",
                    "training_seconds: 120.1",
                    "total_seconds:    141.2",
                    "peak_vram_mb:     2048.0",
                    "num_params_M:     0.8",
                    "parameters:       786468",
                    "depth:            2",
                    "vocab_size:       1024",
                    "max_seq_len:      256",
                    "device_batch_size: 64",
                    "total_batch_size: 16384",
                    "eval_tokens:      262144",
                    "time_budget:      120",
                    "window_pattern:   L",
                )
            )
        )
        self.assertEqual(summary["val_bpb"], 1.2345)
        self.assertEqual(summary["peak_vram_mb"], 2048.0)
        self.assertEqual(summary["depth"], 2)

        record = module.build_record(
            run_tag="campaign-42",
            trial="candidate-1",
            git_sha="abc1234",
            hypothesis="smaller warmdown improves BPB",
            change="WARMDOWN_RATIO only",
            status="keep",
            failure=None,
            next_hint="confirm unchanged",
            summary=summary,
            wandb_run="offline-run-id",
        )
        self.assertEqual(
            set(record),
            {
                "trial",
                "run_tag",
                "git_sha",
                "hypothesis",
                "change",
                "val_bpb",
                "peak_vram_mb",
                "parameters",
                "elapsed_seconds",
                "status",
                "failure",
                "next_hint",
                "wandb_run",
            },
        )
        self.assertEqual(record["parameters"], 786_468)

        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "experiments.jsonl"
            module.append_record(ledger, record)
            self.assertEqual(json.loads(ledger.read_text()), record)

        source = path.read_text()
        self.assertIn('mode="offline"', source)
        self.assertNotIn("--api-key", source)
        self.assertNotIn("mode=\"online\"", source)

    def test_auto_research_recorder_rejects_incomplete_or_malformed_evidence(self) -> None:
        module = load_recorder()
        complete = complete_a100_summary()
        common = {
            "run_tag": "campaign-42",
            "trial": "candidate-1",
            "git_sha": "abc1234",
            "hypothesis": "one testable hypothesis",
            "change": "one train.py change",
            "failure": None,
            "next_hint": None,
            "wandb_run": "offline-run-id",
        }

        for status in ("keep", "discard", "confirmation"):
            for missing in ("val_bpb", "peak_vram_mb", "total_seconds", "parameters"):
                summary = dict(complete)
                summary.pop(missing)
                with self.subTest(status=status, missing=missing):
                    with self.assertRaises(ValueError):
                        module.build_record(status=status, summary=summary, **common)

        with self.assertRaises(ValueError):
            module.build_record(
                status="keep",
                summary={**complete, "parameters": 786_467},
                **common,
            )
        with self.assertRaises(ValueError):
            module.build_record(status="crash", summary={}, **common)
        with self.assertRaises(ValueError):
            module.build_record(
                status="crash",
                summary={},
                **{**common, "failure": "   "},
            )
        with self.assertRaises(ValueError):
            module.build_record(
                status="keep",
                summary=complete,
                **{**common, "run_tag": ""},
            )
        crash = module.build_record(
            status="crash",
            summary={},
            **{**common, "failure": "CUDA kernel incompatibility"},
        )
        self.assertEqual(crash["failure"], "CUDA kernel incompatibility")
        self.assertIsNone(crash["val_bpb"])
        valid = module.build_record(status="keep", summary=complete, **common)
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "experiments.jsonl"
            with self.assertRaises(ValueError):
                module.append_record(ledger, {**valid, "run_tag": 42})
            with self.assertRaises(ValueError):
                module.append_record(ledger, {**valid, "parameters": 786_468.0})
        with self.assertRaises(ValueError):
            module.parse_training_summary("val_bpb: not-a-number")

    def test_auto_research_recorder_rejects_preset_and_duration_drift(self) -> None:
        module = load_recorder()
        expected = complete_a100_summary()
        common = {
            "run_tag": "campaign-42",
            "trial": "candidate-1",
            "git_sha": "abc1234",
            "hypothesis": "one testable hypothesis",
            "change": "one train.py change",
            "status": "keep",
            "failure": None,
            "next_hint": None,
            "wandb_run": "offline-candidate-1",
        }

        valid = module.build_record(summary=expected, **common)
        self.assertEqual(valid["parameters"], 786_468)

        drift_cases = {
            "depth": 3,
            "vocab_size": 2048,
            "max_seq_len": 512,
            "device_batch_size": 32,
            "total_batch_size": 2**15,
            "eval_tokens": 2**19,
            "time_budget": 300,
            "window_pattern": "SSSL",
            "training_seconds": 119.9,
            "total_seconds": 240.1,
        }
        for field, value in drift_cases.items():
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    module.build_record(summary={**expected, field: value}, **common)

        parsed = module.parse_training_summary(
            "\n".join(
                (
                    "window_pattern: L",
                    "vocab_size: 1024",
                    "max_seq_len: 256",
                    "device_batch_size: 64",
                    "total_batch_size: 16384",
                    "eval_tokens: 262144",
                    "time_budget: 120",
                )
            )
        )
        self.assertEqual(parsed.get("window_pattern"), "L")
        self.assertEqual(parsed.get("eval_tokens"), 2**18)

    def test_auto_research_recorder_enforces_campaign_sequence(self) -> None:
        module = load_recorder()
        complete = complete_a100_summary()

        def record(
            trial: str,
            status: str,
            *,
            run_tag: str = "campaign-42",
        ) -> dict[str, object]:
            return module.build_record(
                run_tag=run_tag,
                trial=trial,
                git_sha="abc1234",
                hypothesis="one testable hypothesis",
                change="one train.py change",
                status=status,
                failure="training command failed" if status == "crash" else None,
                next_hint=None,
                summary={} if status == "crash" else complete,
                wandb_run=f"offline-{trial}",
            )

        for run_tag in ("Campaign_42", "campaign_42", "-campaign", "campaign-", "a/b"):
            with self.subTest(invalid_run_tag=run_tag):
                with self.assertRaises(ValueError):
                    record("candidate-1", "keep", run_tag=run_tag)

        normalized = module.build_record(
            run_tag="  campaign-42  ",
            trial="  candidate-1  ",
            git_sha="abc1234",
            hypothesis="one testable hypothesis",
            change="one train.py change",
            status="keep",
            failure=None,
            next_hint=None,
            summary=complete,
            wandb_run="offline-candidate-1",
        )
        self.assertEqual(normalized["run_tag"], "campaign-42")
        self.assertEqual(normalized["trial"], "candidate-1")

        for trial, status in (
            ("baseline", "discard"),
            ("baseline", "confirmation"),
            ("candidate-1", "confirmation"),
            ("winner-confirmation", "keep"),
            ("winner-confirmation", "discard"),
            ("candidate-4", "keep"),
        ):
            with self.subTest(trial=trial, invalid_status=status):
                with self.assertRaises(ValueError):
                    record(trial, status)

        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "experiments.jsonl"
            baseline = record("baseline", "keep")
            candidate_1 = record("candidate-1", "keep")
            ledger.write_text(
                json.dumps(baseline) + "\n" + json.dumps(candidate_1) + "\n",
                encoding="utf-8",
            )

            module.validate_ledger_sequence(
                ledger,
                run_tag="campaign-42",
                trial="candidate-2",
                status="keep",
            )
            module.validate_ledger_sequence(
                ledger,
                run_tag="campaign-42",
                trial="winner-confirmation",
                status="confirmation",
            )
            for run_tag, trial, status in (
                ("campaign-42", "candidate-1", "keep"),
                ("campaign-42", "candidate-3", "keep"),
                ("other-campaign", "candidate-2", "keep"),
                ("campaign-42", "baseline", "keep"),
            ):
                with self.subTest(run_tag=run_tag, trial=trial, status=status):
                    with self.assertRaises(ValueError):
                        module.validate_ledger_sequence(
                            ledger,
                            run_tag=run_tag,
                            trial=trial,
                            status=status,
                        )

            discarded_candidate = record("candidate-1", "discard")
            ledger.write_text(
                json.dumps(baseline) + "\n" + json.dumps(discarded_candidate) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "kept candidate"):
                module.validate_ledger_sequence(
                    ledger,
                    run_tag="campaign-42",
                    trial="winner-confirmation",
                    status="confirmation",
                )

            skipped_candidate = record("candidate-2", "keep")
            ledger.write_text(
                json.dumps(baseline) + "\n" + json.dumps(skipped_candidate) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "expected candidate-1"):
                module.validate_ledger_sequence(
                    ledger,
                    run_tag="campaign-42",
                    trial="winner-confirmation",
                    status="confirmation",
                )

            ledger.write_text(
                json.dumps(baseline) + "\n" + json.dumps(baseline) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate trial"):
                module.validate_ledger_sequence(
                    ledger,
                    run_tag="campaign-42",
                    trial="candidate-1",
                    status="keep",
                )

            crashed_baseline = record("baseline", "crash")
            ledger.write_text(json.dumps(crashed_baseline) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "baseline crashed"):
                module.validate_ledger_sequence(
                    ledger,
                    run_tag="campaign-42",
                    trial="candidate-1",
                    status="keep",
                )

    def test_auto_research_recorder_requires_and_binds_destination(self) -> None:
        module = load_recorder()
        required = ("--entity", "--project", "--run-tag")
        action_by_flag = {
            action.option_strings[0]: action
            for action in module.build_parser()._actions
            if action.option_strings
        }
        for flag in required:
            with self.subTest(flag=flag):
                self.assertIn(flag, action_by_flag)
                self.assertTrue(action_by_flag[flag].required)

        calls: dict[str, object] = {}

        class FakeSettings:
            def __init__(self, **kwargs):
                calls["settings"] = kwargs

        class FakeRun:
            id = "offline-123"

            def __init__(self, directory: Path):
                self.dir = str(directory / "offline-run-123" / "files")
                Path(self.dir).mkdir(parents=True)

            def log(self, metrics):
                calls["metrics"] = metrics

            def finish(self):
                calls["finished"] = True

        def fake_init(**kwargs):
            calls["init"] = kwargs
            return FakeRun(Path(kwargs["dir"]))

        fake_wandb = types.SimpleNamespace(Settings=FakeSettings, init=fake_init)
        summary = complete_a100_summary(val_bpb=1.25, total_seconds=140.0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.dict(sys.modules, {"wandb": fake_wandb}):
                run_id, run_directory = module.record_offline_run(
                    wandb_directory=root / "wandb",
                    entity="approved-entity",
                    project="approved-project",
                    run_tag="campaign-42",
                    trial="candidate-1",
                    git_sha="abc1234",
                    gpu_identity="NVIDIA A100-SXM4-80GB",
                    dataset_fingerprint="data-sha256",
                    tokenizer_fingerprint="tokenizer-sha256",
                    status="keep",
                    summary=summary,
                )

            self.assertEqual(run_id, "offline-123")
            self.assertEqual(Path(run_directory).name, "offline-run-123")
            self.assertEqual(
                calls["settings"],
                {
                    "console": "off",
                    "disable_git": True,
                    "x_disable_meta": True,
                    "x_disable_stats": True,
                    "x_save_requirements": False,
                    "save_code": False,
                },
            )
            init = calls["init"]
            self.assertEqual(init["entity"], "approved-entity")
            self.assertEqual(init["project"], "approved-project")
            self.assertEqual(init["name"], "campaign-42-candidate-1")
            self.assertEqual(init["mode"], "offline")
            self.assertFalse(init["save_code"])
            self.assertEqual(
                init["config"],
                {
                    "run_tag": "campaign-42",
                    "trial": "candidate-1",
                    "git_sha": "abc1234",
                    "preset": "A100-micro-v1",
                    "gpu_identity": "NVIDIA A100-SXM4-80GB",
                    "dataset_fingerprint": "data-sha256",
                    "tokenizer_fingerprint": "tokenizer-sha256",
                    "parameters": 786_468,
                    "status": "keep",
                },
            )
            self.assertEqual(
                calls["metrics"],
                {
                    "val_bpb": 1.25,
                    "peak_vram_mb": 2048.0,
                    "elapsed_seconds": 140.0,
                },
            )
            self.assertTrue(calls["finished"])

            ledger = root / "experiments.jsonl"
            first = module.build_record(
                run_tag="campaign-42",
                trial="baseline",
                git_sha="abc1234",
                hypothesis="frozen baseline",
                change="none",
                status="keep",
                failure=None,
                next_hint="candidate-1",
                summary=summary,
                wandb_run="offline-001",
            )
            second = module.build_record(
                run_tag="campaign-42",
                trial="candidate-1",
                git_sha="def5678",
                hypothesis="one testable hypothesis",
                change="one train.py change",
                status="discard",
                failure=None,
                next_hint="try another hypothesis",
                summary=summary,
                wandb_run="offline-002",
            )
            module.append_record(ledger, first)
            original_line = ledger.read_text().splitlines()[0]
            module.append_record(ledger, second)
            lines = ledger.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0], original_line)
            self.assertEqual(json.loads(lines[0]), first)
            self.assertEqual(json.loads(lines[1]), second)

    def test_auto_research_recorder_prevalidates_and_cleans_only_failed_run(self) -> None:
        module = load_recorder()
        base_args = [
            "--summary", "summary.txt",
            "--ledger", "experiments.jsonl",
            "--wandb-dir", ".wandb-offline",
            "--entity", "approved-entity",
            "--project", "approved-project",
            "--run-tag", "campaign-42",
            "--trial", "candidate-1",
            "--git-sha", "abc1234",
            "--hypothesis", "one testable hypothesis",
            "--change", "one train.py change",
            "--status", "keep",
            "--gpu-identity", "NVIDIA A100-SXM4-80GB",
            "--dataset-fingerprint", "data-sha256",
            "--tokenizer-fingerprint", "tokenizer-sha256",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary_path = root / "summary.txt"
            summary_path.write_text("val_bpb: 1.2\n")
            args = [str(root / value) if value == "summary.txt" else value for value in base_args]
            with mock.patch.object(module, "record_offline_run") as offline:
                with self.assertRaises(ValueError):
                    module.main(args)
            offline.assert_not_called()

            summary_path.write_text(
                "val_bpb: 1.2\npeak_vram_mb: 2048\ntraining_seconds: 120.1\n"
                "total_seconds: 140\nparameters: 786468\ndepth: 2\n"
                "vocab_size: 1024\nmax_seq_len: 256\ndevice_batch_size: 64\n"
                "total_batch_size: 16384\neval_tokens: 262144\ntime_budget: 120\n"
                "window_pattern: L\n"
            )
            for flag in (
                "--gpu-identity",
                "--dataset-fingerprint",
                "--tokenizer-fingerprint",
            ):
                empty_args = [
                    str(root / value) if value == "summary.txt" else value
                    for value in base_args
                ]
                empty_args[empty_args.index(flag) + 1] = ""
                with self.subTest(empty_evidence=flag), mock.patch.object(
                    module, "record_offline_run"
                ) as offline:
                    with self.assertRaises(ValueError):
                        module.main(empty_args)
                    offline.assert_not_called()

            blocked_ledger = root / "ledger-directory"
            blocked_ledger.mkdir()
            blocked_args = [
                str(root / value) if value == "summary.txt" else value
                for value in base_args
            ]
            blocked_args[blocked_args.index("--ledger") + 1] = str(blocked_ledger)
            with mock.patch.object(module, "record_offline_run") as offline:
                with self.assertRaisesRegex(ValueError, "not a regular file"):
                    module.main(blocked_args)
            offline.assert_not_called()

            ledger = root / "experiments.jsonl"
            baseline = module.build_record(
                run_tag="campaign-42",
                trial="baseline",
                git_sha="abc1234",
                hypothesis="frozen baseline",
                change="none",
                status="keep",
                failure=None,
                next_hint="candidate-1",
                summary=complete_a100_summary(val_bpb=1.3, total_seconds=140.0),
                wandb_run="offline-baseline",
            )
            preserved_line = json.dumps(baseline, separators=(",", ":")) + "\n"
            ledger.write_text(preserved_line)

            ledger.write_text(preserved_line + preserved_line)
            duplicate_args = [
                str(root / value) if value in {"summary.txt", "experiments.jsonl", ".wandb-offline"} else value
                for value in base_args
            ]
            with mock.patch.object(module, "record_offline_run") as offline:
                with self.assertRaisesRegex(ValueError, "duplicate trial"):
                    module.main(duplicate_args)
            offline.assert_not_called()
            ledger.write_text(preserved_line)

            run_directory = root / ".wandb-offline" / "offline-run-new"
            run_directory.mkdir(parents=True)
            (run_directory / "files").mkdir()
            sibling = root / ".wandb-offline" / "offline-run-existing"
            sibling.mkdir()
            cleanup_args = [
                str(root / value) if value in {"summary.txt", "experiments.jsonl", ".wandb-offline"} else value
                for value in base_args
            ]
            with mock.patch.object(
                module,
                "record_offline_run",
                return_value=("new-run", str(run_directory)),
            ), mock.patch.object(module, "append_record", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(RuntimeError, "ledger append failed"):
                    module.main(cleanup_args)

            self.assertFalse(run_directory.exists())
            self.assertTrue(sibling.exists())
            self.assertEqual(ledger.read_text(), preserved_line)

    def test_auto_research_onboarding_is_conditional_and_runbook_is_executable(self) -> None:
        skill = self.read_skill("auto-research")
        runbook = (
            ROOT / "skills/auto-research/references/a100-micro-runbook.md"
        ).read_text()
        ledger = (ROOT / "skills/auto-research/assets/experiment-ledger.md").read_text()
        control = (ROOT / "skills/auto-research/assets/AUTORESEARCH.md").read_text()
        run_card = (ROOT / "skills/auto-research/assets/a100-run-card.md").read_text()

        for phrase in (
            "new Karpathy training evidence",
            "frozen Track 1 paper",
            "skip",
            "Select exactly one path",
            "Training path (Track 1 or Both)",
            "Track 2-only frozen-paper path",
            "does not require `val_bpb`",
            "does not require a GPU",
            "does not require W&B or VESSL",
        ):
            with self.subTest(skill_phrase=phrase):
                self.assertIn(phrase, skill)

        for phrase in (
            "git clone https://github.com/karpathy/autoresearch.git",
            'git switch --detach "$UPSTREAM_SHA"',
            "git switch -c autoresearch/$RUN_TAG",
            "uv sync --frozen",
            "prepare.py --num-shards 1",
            "sha256sum",
            "uv run train.py",
            'WANDB_VERSION="0.28.0"',
            'uv run --with "wandb==$WANDB_VERSION" python record_experiment.py',
            "git restore --source",
            'uv run --with "wandb==$WANDB_VERSION" wandb sync --entity "$WANDB_ENTITY" --project "$WANDB_PROJECT" --skip-console --no-sync-tensorboard',
            'GPU_IDENTITY="$(nvidia-smi',
            'sha256sum prepare.py record_experiment.py > evidence/invariant-files.sha256',
            'sha256sum train.py > evidence/baseline-train.sha256',
            'git commit --only -m "chore: freeze A100-micro-v1 executable inputs" -- prepare.py train.py record_experiment.py',
            "Raw data, tokenizer contents, outputs, and checkpoints are never committed",
            'RECORDER_JSON="outputs/$TRIAL.recorder.json"',
            '> "$RECORDER_JSON"',
            'WANDB_RUN_DIRECTORY="$(python3 -c',
            'timeout --signal=TERM --kill-after=30s "${RUN_TIMEOUT_SECONDS}s"',
            '--status crash',
            '--failure "$FAILURE"',
            'TRIAL="candidate-1"',
        ):
            with self.subTest(runbook_phrase=phrase):
                self.assertIn(phrase, runbook)

        preset_index = runbook.find("Freeze the complete pre-baseline preset")
        prepare_index = runbook.find("prepare.py --num-shards 1")
        recorder_index = runbook.find(
            'cp "$PLUGIN_ROOT/skills/auto-research/scripts/record_experiment.py"'
        )
        invariant_index = runbook.find(
            "sha256sum prepare.py record_experiment.py > evidence/invariant-files.sha256"
        )
        self.assertGreaterEqual(preset_index, 0)
        self.assertGreaterEqual(prepare_index, 0)
        self.assertGreaterEqual(recorder_index, 0)
        self.assertGreaterEqual(invariant_index, 0)
        if min(preset_index, prepare_index) >= 0:
            self.assertLess(preset_index, prepare_index)
        if min(recorder_index, invariant_index) >= 0:
            self.assertLess(recorder_index, invariant_index)
        self.assertNotIn('--gpu-identity "NVIDIA A100', runbook)
        self.assertGreaterEqual(runbook.count('--gpu-identity "$GPU_IDENTITY"'), 2)

        candidate = runbook.split("### Candidate template", 1)[1].split(
            "Repeat sequentially", 1
        )[0]
        attempt_commit = candidate.index(
            'git commit --only -m "experiment: attempt $RUN_TAG $TRIAL" -- train.py'
        )
        candidate_sha = candidate.index('CANDIDATE_SHA="$(git rev-parse HEAD)"')
        training_marker = (
            'if timeout --signal=TERM --kill-after=30s "${RUN_TIMEOUT_SECONDS}s"'
        )
        self.assertIn(training_marker, candidate)
        training = candidate.find(training_marker)
        recorder = candidate.find("python record_experiment.py", max(training, 0))
        self.assertGreaterEqual(recorder, 0)
        self.assertLess(attempt_commit, candidate_sha)
        if training >= 0:
            self.assertLess(candidate_sha, training)
            if recorder >= 0:
                self.assertLess(training, recorder)
        self.assertGreaterEqual(candidate.count('--git-sha "$CANDIDATE_SHA"'), 2)
        self.assertGreaterEqual(
            candidate.count(
                'git commit --only -m "experiment: restore after $TRIAL" -- train.py'
            ),
            2,
        )
        self.assertIn('export LAST_KEPT_SHA="$CANDIDATE_SHA"', candidate)
        self.assertNotIn('git commit -m "experiment: keep', candidate)
        self.assertIn(
            'if ! git commit --only -m "experiment: attempt $RUN_TAG $TRIAL" -- train.py; then',
            candidate,
        )
        self.assertIn(
            'if ! git diff --quiet "$CANDIDATE_SHA" -- train.py; then',
            candidate,
        )
        self.assertIn("exit 1", candidate)

        winner = runbook.split("Rerun the best kept candidate", 1)[1]
        self.assertIn(
            'if ! git diff --quiet "$LAST_KEPT_SHA" -- train.py; then', winner
        )
        self.assertIn('CONFIRMATION_SHA="$(git rev-parse HEAD)"', winner)
        self.assertIn("export CONFIRMATION_SHA", winner)
        self.assertIn('--git-sha "$CONFIRMATION_SHA"', winner)
        self.assertIn("exit 1", winner)

    def test_auto_research_runbook_fails_closed_and_rechecks_frozen_inputs(self) -> None:
        skill = self.read_skill("auto-research")
        runbook = (
            ROOT / "skills/auto-research/references/a100-micro-runbook.md"
        ).read_text()
        ledger = (ROOT / "skills/auto-research/assets/experiment-ledger.md").read_text()
        control = (ROOT / "skills/auto-research/assets/AUTORESEARCH.md").read_text()
        run_card = (ROOT / "skills/auto-research/assets/a100-run-card.md").read_text()
        baseline = runbook.split("### Baseline template", 1)[1].split(
            "### Candidate template", 1
        )[0]
        candidate = runbook.split("### Candidate template", 1)[1].split(
            "Repeat sequentially", 1
        )[0]
        winner = runbook.split("Rerun the best kept candidate", 1)[1]

        self.assertIn('export RUN_TIMEOUT_SECONDS="240"', runbook)
        baseline_files = (
            "prepare.py train.py record_experiment.py "
            "evidence/data-files.sha256 evidence/tokenizer-files.sha256 "
            "evidence/invariant-files.sha256 evidence/baseline-train.sha256"
        )
        self.assertIn(f"git add -- {baseline_files}", runbook)
        self.assertIn(
            f'git commit --only -m "chore: freeze A100-micro-v1 executable inputs" -- {baseline_files}',
            runbook,
        )
        self.assertNotIn("git add -A", runbook)

        for name, section in (
            ("baseline", baseline),
            ("candidate", candidate),
            ("winner", winner),
        ):
            with self.subTest(section=name):
                self.assertIn("set -euo pipefail", section)
                self.assertIn(
                    "sha256sum --check evidence/invariant-files.sha256", section
                )
                self.assertIn(
                    "sha256sum --check evidence/data-files.sha256", section
                )
                self.assertIn(
                    "| cmp -s - evidence/data-files.sha256", section
                )
                self.assertIn(
                    'git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256',
                    section,
                )
                self.assertIn(
                    "sha256sum --check evidence/tokenizer-files.sha256", section
                )
                self.assertIn(
                    'timeout --signal=TERM --kill-after=30s "${RUN_TIMEOUT_SECONDS}s"',
                    section,
                )
                self.assertNotIn('export WANDB_RUN_DIRECTORY="$(python3', section)

        self.assertIn(
            "sha256sum --check evidence/baseline-train.sha256", baseline
        )
        self.assertIn(
            'git diff --quiet "$CANDIDATE_SHA" -- train.py', candidate
        )
        self.assertIn(
            'git diff --quiet "$LAST_KEPT_SHA" -- train.py', winner
        )

        training_marker = (
            'if timeout --signal=TERM --kill-after=30s "${RUN_TIMEOUT_SECONDS}s"'
        )
        for name, section in (
            ("baseline", baseline),
            ("candidate", candidate),
            ("winner", winner),
        ):
            success_branch = section.split(training_marker, 1)[1]
            recorder_index = success_branch.index("python record_experiment.py")
            for post_run_gate in (
                'git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256',
                "sha256sum --check evidence/invariant-files.sha256",
                "sha256sum --check evidence/data-files.sha256",
                "| cmp -s - evidence/data-files.sha256",
                "sha256sum --check evidence/tokenizer-files.sha256",
            ):
                with self.subTest(section=name, post_run_gate=post_run_gate):
                    gate_index = success_branch.find(post_run_gate)
                    self.assertGreaterEqual(gate_index, 0)
                    self.assertLess(gate_index, recorder_index)

        for name, document in (
            ("skill", skill),
            ("control", control),
            ("run-card", run_card),
            ("runbook", runbook),
        ):
            with self.subTest(allowlist_document=name):
                self.assertIn("W&B allowlist", document)
                self.assertIn("`run_tag`", document)
                self.assertIn("`trial`", document)

        self.assertIn("initialize it as an empty file", ledger)
        self.assertIn("example only", ledger)
        self.assertIn("Do not copy", ledger)
        self.assertNotIn('"val_bpb":null', ledger)
        self.assertIn('"run_tag"', ledger)

    def test_auto_research_scoped_baseline_commit_handles_untracked_recorder(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args: str) -> str:
                result = subprocess.run(
                    ("git", *args),
                    cwd=root,
                    check=True,
                    text=True,
                    capture_output=True,
                )
                return result.stdout.strip()

            git("init", "-q")
            git("config", "user.name", "Contract Test")
            git("config", "user.email", "contract@example.invalid")
            for name in ("prepare.py", "train.py", "unrelated.txt"):
                (root / name).write_text("initial\n")
            git("add", "--", "prepare.py", "train.py", "unrelated.txt")
            git("commit", "-q", "-m", "initial")

            (root / "prepare.py").write_text("preset\n")
            (root / "train.py").write_text("micro model\n")
            (root / "record_experiment.py").write_text("recorder\n")
            (root / "evidence").mkdir()
            manifest_names = (
                "data-files.sha256",
                "tokenizer-files.sha256",
                "invariant-files.sha256",
                "baseline-train.sha256",
            )
            for name in manifest_names:
                (root / "evidence" / name).write_text(f"{name}\n")
            (root / "unrelated.txt").write_text("must remain staged\n")
            git("add", "--", "unrelated.txt")
            baseline_files = (
                "prepare.py",
                "train.py",
                "record_experiment.py",
                *(f"evidence/{name}" for name in manifest_names),
            )
            git("add", "--", *baseline_files)
            git(
                "commit",
                "-q",
                "--only",
                "-m",
                "freeze inputs",
                "--",
                *baseline_files,
            )

            self.assertEqual(
                set(git("show", "--pretty=", "--name-only", "HEAD").splitlines()),
                set(baseline_files),
            )
            self.assertEqual(git("diff", "--cached", "--name-only"), "unrelated.txt")

            baseline_sha = git("rev-parse", "HEAD")
            (root / "evidence" / "data-files.sha256").write_text("regenerated\n")
            drift = subprocess.run(
                (
                    "git",
                    "diff",
                    "--quiet",
                    baseline_sha,
                    "--",
                    "evidence/data-files.sha256",
                ),
                cwd=root,
            )
            self.assertNotEqual(drift.returncode, 0)

    def test_auto_research_dataset_manifest_rejects_added_shard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            (data / "shard-0.parquet").write_text("first shard\n")
            manifest = root / "data-files.sha256"
            create = (
                "find data -type f -print0 | sort -z | "
                "xargs -0 sha256sum"
            )
            with manifest.open("w") as output:
                subprocess.run(
                    ("bash", "-c", create), cwd=root, check=True, stdout=output
                )
            verify = f"{create} | cmp -s - {manifest.name}"
            self.assertEqual(
                subprocess.run(("bash", "-c", verify), cwd=root).returncode,
                0,
            )
            (data / "shard-1.parquet").write_text("unexpected shard\n")
            self.assertNotEqual(
                subprocess.run(("bash", "-c", verify), cwd=root).returncode,
                0,
            )

    def test_wandb_onboarding_keeps_secrets_interactive_and_runs_offline_first(self) -> None:
        text = self.read_skill("wandb-onboarding")

        for phrase in (
            "wandb login --verify",
            "WANDB_MODE=offline",
            "interactive prompt",
            "Never ask",
            "explicit confirmation",
            "entity",
            "project",
            "visibility",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

        self.assertNotIn("wandb login $WANDB_API_KEY", text)
        asset = ROOT / "skills/wandb-onboarding/assets/wandb-quickstart.py"
        self.assertTrue(asset.is_file())
        asset_text = asset.read_text() if asset.is_file() else ""
        self.assertIn("WANDB_ENTITY", asset_text)
        self.assertIn("WANDB_PROJECT", asset_text)
        self.assertIn("--relogin --cloud --verify", text)

    def test_vessl_cloud_onboarding_separates_verification_from_billable_compute(self) -> None:
        text = self.read_skill("vessl-cloud-onboarding")

        for phrase in (
            "https://cloud.vessl.ai",
            "vesslctl auth status",
            "vesslctl config show",
            "vesslctl billing show",
            "vesslctl org list",
            "vesslctl team list",
            "vesslctl cluster list",
            "resource-spec list --usable-only",
            "hourly price",
            "credit",
            "image",
            "duration",
            "cleanup",
            "explicit confirmation",
            "Pause",
            "Terminate",
            "legacy",
            "vesslctl auth login --web",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

        self.assertNotIn("app.vessl.ai/login", text)
        cost_card = ROOT / "skills/vessl-cloud-onboarding/assets/workspace-cost-card.md"
        self.assertTrue(cost_card.is_file())
        cost_text = cost_card.read_text() if cost_card.is_file() else ""
        for phrase in ("Storage capacity", "Storage hourly price", "Estimated storage cost"):
            with self.subTest(cost_phrase=phrase):
                self.assertIn(phrase, cost_text)

    def test_world_model_ideation_produces_testable_research_not_only_brand_copy(self) -> None:
        text = self.read_skill("world-model-ideation")

        for phrase in (
            "falsifiable hypothesis",
            "baseline",
            "evaluation metric",
            "failure mode",
            "minimum experiment",
            "Track 1",
            "Track 2",
            "Do not claim",
            "Dalpha",
            "unconfirmed",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

        self.assertTrue(
            (ROOT / "skills/world-model-ideation/assets/research-spec-template.md").is_file()
        )


if __name__ == "__main__":
    unittest.main()
