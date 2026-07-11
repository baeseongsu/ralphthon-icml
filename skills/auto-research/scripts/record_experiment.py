#!/usr/bin/env python3
"""Record one A100-micro experiment locally and in a W&B offline run."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence


PARAMETERS = 786_468
PRESET = "A100-micro-v1"
MAX_TOTAL_SECONDS = 240.0
EXPECTED_SUMMARY = {
    "depth": 2,
    "vocab_size": 1_024,
    "max_seq_len": 256,
    "device_batch_size": 64,
    "total_batch_size": 2**14,
    "eval_tokens": 2**18,
    "time_budget": 120,
    "window_pattern": "L",
}
ALLOWED_STATUSES = frozenset({"keep", "discard", "crash", "confirmation"})
RUN_TAG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TRIAL_STATUSES = {
    "baseline": frozenset({"keep", "crash"}),
    "candidate-1": frozenset({"keep", "discard", "crash"}),
    "candidate-2": frozenset({"keep", "discard", "crash"}),
    "candidate-3": frozenset({"keep", "discard", "crash"}),
    "winner-confirmation": frozenset({"confirmation", "crash"}),
}
CANDIDATE_TRIALS = ("candidate-1", "candidate-2", "candidate-3")
SUMMARY_FIELDS = {
    "val_bpb": float,
    "training_seconds": float,
    "total_seconds": float,
    "peak_vram_mb": float,
    "num_params_M": float,
    "num_params": int,
    "parameters": int,
    "depth": int,
    "vocab_size": int,
    "max_seq_len": int,
    "device_batch_size": int,
    "total_batch_size": int,
    "eval_tokens": int,
    "time_budget": int,
    "window_pattern": str,
}
RECORD_FIELDS = (
    "run_tag",
    "trial",
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
)


def parse_training_summary(text: str) -> dict[str, int | float | str]:
    """Parse only known scalar fields from Karpathy's training summary."""

    summary: dict[str, int | float | str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([A-Za-z_]+)\s*:\s*(\S+)\s*$", line)
        if not match:
            continue
        key, raw_value = match.groups()
        converter = SUMMARY_FIELDS.get(key)
        if converter is None:
            continue
        try:
            value = converter(raw_value)
        except ValueError as error:
            raise ValueError(f"invalid {key} value: {raw_value!r}") from error
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"invalid {key} value: {raw_value!r}")
        summary[key] = value
    return summary


def _require_text(field: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value.strip()


def validate_run_tag(run_tag: Any) -> str:
    """Return a normalized campaign tag only when it is shell/name safe."""

    value = _require_text("run_tag", run_tag)
    if RUN_TAG_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "run_tag must use lowercase letters and digits separated by single hyphens"
        )
    return value


def validate_trial_status(trial: Any, status: Any) -> tuple[str, str]:
    """Bind each fixed trial identifier to its allowed outcome statuses."""

    trial_value = _require_text("trial", trial)
    if not isinstance(status, str) or status not in ALLOWED_STATUSES:
        raise ValueError("record contains an invalid status")
    allowed = TRIAL_STATUSES.get(trial_value)
    if allowed is None:
        raise ValueError(f"invalid trial: {trial_value}")
    if status not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{trial_value} status must be one of: {choices}")
    return trial_value, status


def validate_record(record: Mapping[str, Any]) -> None:
    """Reject records that cannot support their declared outcome."""

    if set(record) != set(RECORD_FIELDS):
        raise ValueError(f"record fields must be exactly: {', '.join(RECORD_FIELDS)}")
    run_tag = validate_run_tag(record["run_tag"])
    trial, status = validate_trial_status(record["trial"], record["status"])
    assert run_tag and trial
    for field in ("git_sha", "hypothesis", "change", "wandb_run"):
        _require_text(field, record[field])

    if status in {"keep", "discard", "confirmation"}:
        for field in ("val_bpb", "peak_vram_mb", "elapsed_seconds"):
            value = record[field]
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{status} requires a finite {field}")
        if type(record["parameters"]) is not int or record["parameters"] != PARAMETERS:
            raise ValueError(f"{status} requires parameters={PARAMETERS}")
    elif type(record["parameters"]) is not int or record["parameters"] != PARAMETERS:
        raise ValueError(f"record parameters must equal {PARAMETERS}")

    if status == "crash":
        _require_text("failure", record["failure"])


def build_record(
    *,
    run_tag: str,
    trial: str,
    git_sha: str,
    hypothesis: str,
    change: str,
    status: str,
    failure: str | None,
    next_hint: str | None,
    summary: Mapping[str, int | float | str],
    wandb_run: str,
) -> dict[str, Any]:
    """Build the exact append-only ledger record for one trial."""

    if status not in ALLOWED_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_STATUSES))
        raise ValueError(f"status must be one of: {allowed}")
    run_tag = validate_run_tag(run_tag)
    trial, status = validate_trial_status(trial, status)

    reported_parameters = summary.get("parameters")
    if reported_parameters is not None and int(reported_parameters) != PARAMETERS:
        raise ValueError(
            f"A100-micro-v1 must have exactly {PARAMETERS} parameters; "
            f"summary reported {reported_parameters}"
        )

    if status != "crash":
        for field, expected in EXPECTED_SUMMARY.items():
            actual = summary.get(field)
            if actual != expected or type(actual) is not type(expected):
                raise ValueError(
                    f"{PRESET} requires {field}={expected!r}; summary reported {actual!r}"
                )
        training_seconds = summary.get("training_seconds")
        total_seconds = summary.get("total_seconds")
        for field, value in (
            ("training_seconds", training_seconds),
            ("total_seconds", total_seconds),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{status} requires a finite {field}")
        if float(training_seconds) < EXPECTED_SUMMARY["time_budget"]:
            raise ValueError(
                f"training_seconds must be at least {EXPECTED_SUMMARY['time_budget']}"
            )
        if float(total_seconds) < float(training_seconds):
            raise ValueError("total_seconds must be greater than or equal to training_seconds")
        if float(total_seconds) > MAX_TOTAL_SECONDS:
            raise ValueError(f"total_seconds must not exceed {MAX_TOTAL_SECONDS:g}")

    required_text = {
        "run_tag": run_tag,
        "trial": trial,
        "git_sha": git_sha,
        "hypothesis": hypothesis,
        "change": change,
        "wandb_run": wandb_run,
    }
    for field, value in required_text.items():
        _require_text(field, value)

    elapsed_seconds = summary.get("total_seconds", summary.get("training_seconds"))
    record = {
        "run_tag": run_tag,
        "trial": trial,
        "git_sha": git_sha,
        "hypothesis": hypothesis,
        "change": change,
        "val_bpb": summary.get("val_bpb"),
        "peak_vram_mb": summary.get("peak_vram_mb"),
        "parameters": PARAMETERS if status == "crash" else reported_parameters,
        "elapsed_seconds": elapsed_seconds,
        "status": status,
        "failure": failure,
        "next_hint": next_hint,
        "wandb_run": wandb_run,
    }
    validate_record(record)
    return record


def append_record(path: Path, record: Mapping[str, Any]) -> None:
    """Append one compact JSON object without rewriting prior ledger lines."""

    validate_record(record)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as ledger:
        json.dump(record, ledger, ensure_ascii=True, separators=(",", ":"))
        ledger.write("\n")


def validate_ledger_writable(path: Path) -> None:
    """Prove the ledger can be opened for append before creating a W&B run."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not path.is_file():
        raise ValueError(f"ledger is not a regular file: {path}")
    try:
        with path.open("a", encoding="utf-8"):
            pass
    except OSError as error:
        raise ValueError(f"ledger is not writable: {path}: {error}") from error


def validate_ledger_sequence(
    path: Path,
    *,
    run_tag: str,
    trial: str,
    status: str,
) -> None:
    """Validate one campaign's append-only trial order before W&B creation."""

    run_tag = validate_run_tag(run_tag)
    trial, status = validate_trial_status(trial, status)
    assert status

    records: list[Mapping[str, Any]] = []
    if path.exists():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                raise ValueError(f"empty ledger line {line_number}")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid ledger JSON on line {line_number}") from error
            if not isinstance(record, dict):
                raise ValueError(f"ledger line {line_number} must be a JSON object")
            validate_record(record)
            if record["run_tag"] != run_tag:
                raise ValueError(
                    f"ledger run_tag mismatch on line {line_number}: "
                    f"{record['run_tag']} != {run_tag}"
                )
            records.append(record)

    seen: set[str] = set()
    candidate_count = 0
    kept_candidate = False
    confirmation_seen = False
    for index, record in enumerate(records):
        existing_trial = str(record["trial"])
        if existing_trial in seen:
            raise ValueError(f"duplicate trial in ledger: {existing_trial}")
        seen.add(existing_trial)

        if index == 0:
            if existing_trial != "baseline":
                raise ValueError("baseline must be the first ledger trial")
            continue
        if existing_trial in CANDIDATE_TRIALS:
            if confirmation_seen:
                raise ValueError("candidate cannot follow winner-confirmation")
            expected = CANDIDATE_TRIALS[candidate_count]
            if existing_trial != expected:
                raise ValueError(f"expected {expected} before {existing_trial}")
            candidate_count += 1
            kept_candidate = kept_candidate or record["status"] == "keep"
            continue
        if existing_trial == "winner-confirmation":
            if not kept_candidate:
                raise ValueError("winner-confirmation requires a kept candidate")
            if confirmation_seen or index != len(records) - 1:
                raise ValueError("winner-confirmation must be the final unique trial")
            confirmation_seen = True
            continue
        raise ValueError(f"invalid existing trial: {existing_trial}")

    if trial in seen:
        raise ValueError(f"duplicate trial in ledger: {trial}")
    if not records:
        if trial != "baseline":
            raise ValueError("baseline must be recorded before candidate trials")
        return
    if records[0]["status"] == "crash":
        raise ValueError("baseline crashed; no later trial is allowed")
    if confirmation_seen:
        raise ValueError("winner-confirmation already ended the campaign")
    if trial == "baseline":
        raise ValueError("baseline already exists")
    if trial in CANDIDATE_TRIALS:
        expected = CANDIDATE_TRIALS[candidate_count]
        if trial != expected:
            raise ValueError(f"expected next trial {expected}, got {trial}")
        return
    if trial == "winner-confirmation" and not kept_candidate:
        raise ValueError("winner-confirmation requires a kept candidate")


def remove_new_offline_run(run_directory: str, wandb_directory: Path) -> None:
    """Remove one known W&B offline run without touching siblings or its parent."""

    base = wandb_directory.resolve()
    run = Path(run_directory).resolve()
    if base not in run.parents or not run.name.startswith("offline-run-"):
        raise RuntimeError(f"refusing unsafe offline run cleanup: {run}")
    if run.exists():
        shutil.rmtree(run)


def record_offline_run(
    *,
    wandb_directory: Path,
    entity: str,
    project: str,
    run_tag: str,
    trial: str,
    git_sha: str,
    gpu_identity: str,
    dataset_fingerprint: str,
    tokenizer_fingerprint: str,
    status: str,
    summary: Mapping[str, int | float],
) -> tuple[str, str]:
    """Write approved config and metrics to one local W&B offline run."""

    entity = _require_text("entity", entity)
    project = _require_text("project", project)
    run_tag = validate_run_tag(run_tag)
    trial, status = validate_trial_status(trial, status)
    git_sha = _require_text("git_sha", git_sha)
    gpu_identity = _require_text("gpu_identity", gpu_identity)
    dataset_fingerprint = _require_text(
        "dataset_fingerprint", dataset_fingerprint
    )
    tokenizer_fingerprint = _require_text(
        "tokenizer_fingerprint", tokenizer_fingerprint
    )

    try:
        import wandb
    except ImportError as error:
        raise RuntimeError(
            "The W&B SDK is required only to execute the recorder; install wandb "
            "in the campaign environment."
        ) from error

    config = {
        "run_tag": run_tag,
        "trial": trial,
        "git_sha": git_sha,
        "preset": PRESET,
        "gpu_identity": gpu_identity,
        "dataset_fingerprint": dataset_fingerprint,
        "tokenizer_fingerprint": tokenizer_fingerprint,
        "parameters": PARAMETERS,
        "status": status,
    }
    metrics = {
        key: value
        for key, value in {
            "val_bpb": summary.get("val_bpb"),
            "peak_vram_mb": summary.get("peak_vram_mb"),
            "elapsed_seconds": summary.get(
                "total_seconds", summary.get("training_seconds")
            ),
        }.items()
        if value is not None
    }

    wandb_directory.mkdir(parents=True, exist_ok=True)
    settings = wandb.Settings(
        console="off",
        disable_git=True,
        x_disable_meta=True,
        x_disable_stats=True,
        x_save_requirements=False,
        save_code=False,
    )
    run = wandb.init(
        mode="offline",
        dir=str(wandb_directory),
        entity=entity,
        project=project,
        name=f"{run_tag}-{trial}",
        config=config,
        save_code=False,
        settings=settings,
    )
    if run is None:
        raise RuntimeError("wandb.init did not return an offline run")

    run.log(metrics)
    run_id = str(run.id)
    files_directory = Path(run.dir)
    run_directory = str(
        files_directory.parent if files_directory.name == "files" else files_directory
    )
    run.finish()
    return run_id, run_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Append an A100-micro result and create a local W&B offline run."
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, default=Path("experiments.jsonl"))
    parser.add_argument("--wandb-dir", type=Path, default=Path(".wandb-offline"))
    parser.add_argument("--entity", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--run-tag", required=True)
    parser.add_argument("--trial", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--status", choices=sorted(ALLOWED_STATUSES), required=True)
    parser.add_argument("--failure")
    parser.add_argument("--next-hint")
    parser.add_argument("--gpu-identity", required=True)
    parser.add_argument("--dataset-fingerprint", required=True)
    parser.add_argument("--tokenizer-fingerprint", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = parse_training_summary(args.summary.read_text(encoding="utf-8"))
    build_record(
        run_tag=args.run_tag,
        trial=args.trial,
        git_sha=args.git_sha,
        hypothesis=args.hypothesis,
        change=args.change,
        status=args.status,
        failure=args.failure,
        next_hint=args.next_hint,
        summary=summary,
        wandb_run="pending-offline-run",
    )
    _require_text("entity", args.entity)
    _require_text("project", args.project)
    _require_text("gpu_identity", args.gpu_identity)
    _require_text("dataset_fingerprint", args.dataset_fingerprint)
    _require_text("tokenizer_fingerprint", args.tokenizer_fingerprint)
    validate_ledger_writable(args.ledger)
    validate_ledger_sequence(
        args.ledger,
        run_tag=args.run_tag,
        trial=args.trial,
        status=args.status,
    )
    run_id, run_directory = record_offline_run(
        wandb_directory=args.wandb_dir,
        entity=args.entity,
        project=args.project,
        run_tag=args.run_tag,
        trial=args.trial,
        git_sha=args.git_sha,
        gpu_identity=args.gpu_identity,
        dataset_fingerprint=args.dataset_fingerprint,
        tokenizer_fingerprint=args.tokenizer_fingerprint,
        status=args.status,
        summary=summary,
    )
    record = build_record(
        run_tag=args.run_tag,
        trial=args.trial,
        git_sha=args.git_sha,
        hypothesis=args.hypothesis,
        change=args.change,
        status=args.status,
        failure=args.failure,
        next_hint=args.next_hint,
        summary=summary,
        wandb_run=run_id,
    )
    try:
        append_record(args.ledger, record)
    except Exception as error:
        try:
            remove_new_offline_run(run_directory, args.wandb_dir)
        except Exception as cleanup_error:
            raise RuntimeError(
                f"ledger append failed ({error}); offline run cleanup also failed: "
                f"{cleanup_error}"
            ) from error
        raise RuntimeError(
            f"ledger append failed ({error}); removed new offline run: {run_directory}"
        ) from error
    print(
        json.dumps(
            {
                "ledger": str(args.ledger),
                "wandb_run_id": run_id,
                "wandb_run_directory": run_directory,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
