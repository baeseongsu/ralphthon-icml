#!/usr/bin/env python3
"""Run resumable N=5 review-prompt candidates and aggregate their evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from review_prompt_codex import CodexAttemptsExhausted, run as run_codex_paper
from review_prompt_dataset import canonical_json_bytes, verify_manifest_file
from review_prompt_loop import candidate_decisions, next_parent_id
from review_prompt_scoring import (
    JUDGE_DIMENSIONS,
    PAPER_ID_PATTERN,
    SCORE_RANGES,
    aggregate_paper_records,
    score_candidate,
)
from review_prompt_smoke import sha256_file, write_json
from review_prompt_tracking import record_wandb_batch_offline


REQUIRED_PAPER_FILES = (
    "generated-review.json",
    "judge.json",
    "metrics.json",
    "provenance.json",
    "timing.json",
    "attempts.json",
    "publish-bundle.json",
)
SHARED_CONFIG_EXCLUSIONS = frozenset(
    {"candidate_id", "parent_candidate_id", "prompt_sha256"}
)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def shared_configuration_sha256(config: Mapping[str, Any]) -> str:
    shared = {
        key: value
        for key, value in config.items()
        if key not in SHARED_CONFIG_EXCLUSIONS
    }
    return _sha256_json(shared)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label}: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be one JSON object")
    return value


def load_sample_manifest(path: Path, *, required_count: int = 5) -> dict[str, Any]:
    if not verify_manifest_file(path):
        raise ValueError("sample manifest hash verification failed")
    value = _load_json(path, "sample manifest")
    if value.get("split") != "development":
        raise ValueError("sample manifest must contain only development entries")
    entries = value.get("entries")
    if not isinstance(entries, list) or len(entries) != required_count:
        raise ValueError(f"sample manifest must contain exactly {required_count} entries")
    if value.get("count") != required_count:
        raise ValueError("sample manifest count does not match entries")
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ValueError(f"sample entry {index} must be an object")
        if entry.get("split") != "development":
            raise ValueError("holdout/non-development entry is forbidden")
        paper_id = entry.get("paper_id")
        if not isinstance(paper_id, str) or PAPER_ID_PATTERN.fullmatch(paper_id) is None:
            raise ValueError(f"sample entry {index} has invalid paper_id")
        if paper_id in seen:
            raise ValueError(f"duplicate sample paper_id: {paper_id}")
        seen.add(paper_id)
        for field in ("pdf_path", "label_path"):
            raw_path = entry.get(field)
            if not isinstance(raw_path, str) or not raw_path:
                raise ValueError(f"sample entry {paper_id} requires {field}")
            if not Path(raw_path).is_file():
                raise ValueError(f"sample entry {paper_id} {field} does not exist")
    return value


def _candidate_config(
    *,
    sample_manifest: Mapping[str, Any],
    prompt_path: Path,
    candidate_id: str,
    parent_candidate_id: str,
    judge_prompt_path: Path,
    review_schema_path: Path,
    judge_schema_path: Path,
    reviewer_model: str,
    judge_model: str,
    max_attempts: int,
    workers: int,
) -> dict[str, Any]:
    config = {
        "candidate_id": candidate_id,
        "parent_candidate_id": parent_candidate_id,
        "sample_manifest_sha256": str(sample_manifest["manifest_sha256"]),
        "selector_version": str(sample_manifest.get("selector_version", "unknown")),
        "sample_seed": int(sample_manifest.get("seed", 0)),
        "sample_count": int(sample_manifest["count"]),
        "prompt_sha256": sha256_file(prompt_path),
        "judge_prompt_sha256": sha256_file(judge_prompt_path),
        "review_schema_sha256": sha256_file(review_schema_path),
        "judge_schema_sha256": sha256_file(judge_schema_path),
        "reviewer_model": reviewer_model,
        "judge_model": judge_model,
        "max_attempts": max_attempts,
        "workers": workers,
        "objective_human_weight": 0.5,
        "objective_judge_weight": 0.5,
        "objective_penalty_weight": 0.25,
        "target_source": "pseudo_label",
    }
    config["shared_configuration_sha256"] = shared_configuration_sha256(config)
    return config


def _load_existing_config(path: Path, expected: Mapping[str, Any]) -> None:
    actual = _load_json(path, "candidate config")
    if actual != dict(expected):
        raise ValueError("candidate configuration changed after the run started")


def _paper_output_is_complete(path: Path) -> bool:
    return path.is_dir() and all((path / name).is_file() for name in REQUIRED_PAPER_FILES)


def _paper_record(
    *,
    output_dir: Path,
    paper_id: str,
    prompt_sha256: str,
) -> dict[str, Any]:
    if not _paper_output_is_complete(output_dir):
        raise ValueError(f"paper output is incomplete: {paper_id}")
    generated_review = _load_json(output_dir / "generated-review.json", "generated review")
    judge = _load_json(output_dir / "judge.json", "Judge output")
    metrics = _load_json(output_dir / "metrics.json", "paper metrics")
    provenance = _load_json(output_dir / "provenance.json", "paper provenance")
    timing = _load_json(output_dir / "timing.json", "paper timing")
    attempts = _load_json(output_dir / "attempts.json", "paper attempts")
    publish_bundle = _load_json(
        output_dir / "publish-bundle.json",
        "paper publish bundle",
    )
    if provenance.get("reviewer_prompt_sha256") != prompt_sha256:
        raise ValueError(f"paper output prompt hash mismatch: {paper_id}")
    if publish_bundle.get("paper_id") != paper_id:
        raise ValueError(f"paper output pseudonym mismatch: {paper_id}")
    if set(publish_bundle) != {
        "schema_version",
        "paper_id",
        "generated_review",
        "judge",
    }:
        raise ValueError(f"paper publish bundle fields changed: {paper_id}")
    reviewer_attempts = attempts.get("reviewer")
    judge_attempts = attempts.get("judge")
    if not isinstance(reviewer_attempts, Mapping) or not isinstance(
        judge_attempts,
        Mapping,
    ):
        raise ValueError(f"paper attempts are invalid: {paper_id}")
    return {
        "paper_id": paper_id,
        "generated_review": generated_review,
        "judge": judge,
        "metrics": metrics,
        "timing": timing,
        "usage": {
            "reviewer": provenance.get("reviewer_usage", {}),
            "judge": provenance.get("judge_usage", {}),
        },
        "attempts": {
            "reviewer": int(reviewer_attempts.get("attempt_count", 0)),
            "judge": int(judge_attempts.get("attempt_count", 0)),
        },
        "failure": None,
        "publish_bundle": publish_bundle,
    }


def _render_batch_reflection(aggregate: Mapping[str, Any]) -> str:
    dimensions = aggregate["human_dimension_agreement"]
    judge_dimensions = aggregate["judge_dimension_scores"]
    signed_gaps = aggregate["signed_gap_summary"]
    weakest = min(dimensions, key=lambda name: float(dimensions[name]))
    lowest_judge = min(
        judge_dimensions,
        key=lambda name: float(judge_dimensions[name]),
    )
    largest_bias = max(
        signed_gaps,
        key=lambda name: abs(float(signed_gaps[name]["mean"])),
    )
    return (
        f"# Candidate reflection — {aggregate['candidate_id']}\n\n"
        f"- Parent: {aggregate['parent_candidate_id']}\n"
        f"- Composite: {float(aggregate['composite']):.6f}\n"
        f"- Reference-score agreement: {float(aggregate['human_agreement']):.6f}\n"
        f"- Judge review quality: {float(aggregate['judge_quality']):.6f}\n"
        f"- Weakest agreement dimension: {weakest} "
        f"({float(dimensions[weakest]):.6f})\n"
        f"- Largest mean signed prediction gap: {largest_bias} "
        f"({float(signed_gaps[largest_bias]['mean']):+.6f})\n"
        f"- Lowest Judge dimension: {lowest_judge} "
        f"({float(judge_dimensions[lowest_judge]):.6f})\n"
        f"- Completed: {aggregate['completed_count']}/{aggregate['sample_count']}\n"
        f"- Active wall time: {float(aggregate['wall_clock_seconds']):.3f}s\n"
    )


def wandb_metrics_from_aggregate(
    aggregate: Mapping[str, Any],
) -> dict[str, int | float]:
    metrics: dict[str, int | float] = {
        "objective/composite": float(aggregate["composite"]),
        "objective/human_agreement": float(aggregate["human_agreement"]),
        "objective/judge_quality": float(aggregate["judge_quality"]),
        "objective/penalty": float(aggregate["penalty"]),
        "timing/wall_clock_seconds": float(aggregate["wall_clock_seconds"]),
        "ops/sample_count": int(aggregate["sample_count"]),
        "ops/completed_count": int(aggregate["completed_count"]),
        "ops/failure_count": int(aggregate["failure_count"]),
        "ops/reviewer_attempts": int(aggregate["attempts"]["reviewer"]),
        "ops/judge_attempts": int(aggregate["attempts"]["judge"]),
        "ops/attempts_total": int(aggregate["attempts"]["total"]),
        "ops/retries": int(aggregate["attempts"]["retries"]),
        "throughput/papers_per_hour": float(aggregate["papers_per_hour"]),
    }
    for dimension in SCORE_RANGES:
        metrics[f"agreement/{dimension}"] = float(
            aggregate["human_dimension_agreement"][dimension]
        )
        metrics[f"distribution_agreement/{dimension}"] = float(
            aggregate["human_distribution_agreement"][dimension]
        )
        metrics[f"gap/{dimension}/mean"] = float(
            aggregate["signed_gap_summary"][dimension]["mean"]
        )
        metrics[f"gap/{dimension}/p50"] = float(
            aggregate["signed_gap_summary"][dimension]["p50"]
        )
    for dimension in JUDGE_DIMENSIONS:
        metrics[f"judge/{dimension}"] = float(
            aggregate["judge_dimension_scores"][dimension]
        )
    for role in ("reviewer_seconds", "judge_seconds", "total_seconds"):
        for summary in ("total", "mean", "p50", "p95", "min", "max"):
            metrics[f"timing/{role}/{summary}"] = float(
                aggregate["timing"][role][summary]
            )
    for role in ("reviewer", "judge"):
        usage = aggregate["usage"][role]
        for field in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        ):
            if field in usage:
                metrics[f"usage/{role}_{field}"] = float(usage[field])
    return metrics


def _prefixed_sha256(value: object) -> str:
    text = str(value)
    return text if text.startswith("sha256:") else f"sha256:{text}"


def _candidate_runtime_identity(candidate_root: Path) -> tuple[str, str]:
    versions: set[str] = set()
    auth_modes: set[str] = set()
    for path in sorted((candidate_root / "papers").glob("paper-*/provenance.json")):
        value = _load_json(path, "paper provenance")
        versions.add(str(value.get("codex_cli_version", "")))
        auth_modes.add(str(value.get("auth_mode", "")))
    if len(versions) != 1 or "" in versions:
        raise ValueError("candidate papers do not share one Codex CLI version")
    if len(auth_modes) != 1 or "" in auth_modes:
        raise ValueError("candidate papers do not share one auth mode")
    return next(iter(versions)), next(iter(auth_modes))


def _forbidden_terms(
    sample_manifest: Mapping[str, Any],
) -> list[str]:
    terms = {
        "forum_id",
        "human_scores",
        "human_targets",
        "reference_review",
        "raw_human_review",
        "label_path",
        "pdf_path",
        "source_id",
    }
    entries = sample_manifest.get("entries", [])
    assert isinstance(entries, list)
    for entry in entries:
        assert isinstance(entry, Mapping)
        for field in ("source_id", "title", "authors"):
            value = str(entry.get(field, "")).strip()
            if value:
                terms.add(value)
        for field in ("pdf_path", "label_path"):
            value = str(entry.get(field, "")).strip()
            if value:
                path = Path(value)
                terms.add(path.name)
                terms.add(path.stem)
        title = str(entry.get("title", ""))
        if ":" in title:
            terms.add(title.split(":", 1)[0].strip())
        authors = str(entry.get("authors", ""))
        terms.update(
            part.strip()
            for part in re.split(r",|;|\band\b", authors)
            if part.strip()
        )
    secret = os.environ.get("WANDB_API_KEY", "").strip()
    if secret:
        terms.add(secret)
    return sorted((term for term in terms if term), key=len, reverse=True)


def publish_candidate_offline(
    *,
    sample_manifest_path: Path,
    campaign_root: Path,
    campaign_id: str,
    candidate_id: str,
    entity: str,
    project: str,
    source_git_sha: str,
    kept_git_sha: str | None = None,
    wandb_module: Any | None = None,
) -> dict[str, Any]:
    candidate_root = campaign_root / "candidates" / candidate_id
    result_path = candidate_root / "wandb-offline.json"
    if result_path.exists():
        return _load_json(result_path, "W&B offline result")
    aggregate = _stored_aggregate(
        candidate_root / "aggregate.json",
        _load_json(candidate_root / "candidate-config.json", "candidate config"),
    )
    config_source = _load_json(
        candidate_root / "candidate-config.json",
        "candidate config",
    )
    sample_manifest = load_sample_manifest(sample_manifest_path)
    if str(sample_manifest["manifest_sha256"]) != str(
        aggregate["sample_manifest_sha256"]
    ):
        raise ValueError("publisher sample manifest differs from candidate run")
    publish_bundles = json.loads(
        (candidate_root / "publish-bundles.json").read_text(encoding="utf-8")
    )
    if not isinstance(publish_bundles, list):
        raise ValueError("publish-bundles.json must contain one array")
    cli_version, auth_mode = _candidate_runtime_identity(candidate_root)
    config: dict[str, Any] = {
        "campaign_id": campaign_id,
        "candidate_id": candidate_id,
        "parent_candidate_id": str(aggregate["parent_candidate_id"]),
        "sample_manifest_sha256": _prefixed_sha256(
            aggregate["sample_manifest_sha256"]
        ),
        "reviewer_prompt_sha256": str(config_source["prompt_sha256"]),
        "judge_prompt_sha256": str(config_source["judge_prompt_sha256"]),
        "review_schema_sha256": str(config_source["review_schema_sha256"]),
        "judge_schema_sha256": str(config_source["judge_schema_sha256"]),
        "reviewer_model": str(config_source["reviewer_model"]),
        "judge_model": str(config_source["judge_model"]),
        "codex_cli_version": cli_version,
        "auth_mode": auth_mode,
        "source_git_sha": source_git_sha,
        "target_source": "pseudo_label",
        "objective_human_weight": 0.5,
        "objective_judge_weight": 0.5,
        "objective_penalty_weight": 0.25,
    }
    if kept_git_sha is not None:
        config["kept_git_sha"] = kept_git_sha
    if wandb_module is None:
        os.environ.setdefault(
            "WANDB_DATA_DIR",
            "/tmp/wandb-review-prompt-data",
        )
        Path(os.environ["WANDB_DATA_DIR"]).mkdir(parents=True, exist_ok=True)
        try:
            import wandb as imported_wandb
        except ImportError as error:
            raise RuntimeError(
                "W&B publishing requires `uv run --with wandb`"
            ) from error
        wandb_module = imported_wandb
    run_id, run_directory = record_wandb_batch_offline(
        wandb_module=wandb_module,
        directory=candidate_root / ".wandb-offline",
        entity=entity,
        project=project,
        campaign_id=campaign_id,
        candidate_id=candidate_id,
        config=config,
        metrics=wandb_metrics_from_aggregate(aggregate),
        publish_bundles=publish_bundles,
        predicted_distributions=aggregate["predicted_distributions"],
        reference_distributions=aggregate["reference_distributions"],
        judge_distributions=aggregate["judge_distributions"],
        forbidden_terms=_forbidden_terms(sample_manifest),
    )
    result = {
        "campaign_id": campaign_id,
        "candidate_id": candidate_id,
        "run_id": run_id,
        "run_directory": run_directory,
        "entity": entity,
        "project": project,
        "source_git_sha": source_git_sha,
        "kept_git_sha": kept_git_sha,
    }
    write_json(result_path, result)
    return result


def _stored_aggregate(path: Path, expected_config: Mapping[str, Any]) -> dict[str, Any]:
    value = _load_json(path, "candidate aggregate")
    expected_hash = value.pop("aggregate_sha256", None)
    if expected_hash != _sha256_json(value):
        raise ValueError("candidate aggregate hash verification failed")
    value["aggregate_sha256"] = expected_hash
    if value.get("shared_configuration_sha256") != expected_config.get(
        "shared_configuration_sha256"
    ):
        raise ValueError("stored aggregate uses a different shared configuration")
    return value


def run_candidate(
    *,
    sample_manifest_path: Path,
    prompt_path: Path,
    campaign_root: Path,
    campaign_id: str,
    candidate_id: str,
    parent_candidate_id: str,
    judge_prompt_path: Path,
    review_schema_path: Path,
    judge_schema_path: Path,
    reviewer_model: str,
    judge_model: str,
    workers: int = 2,
    max_attempts: int = 2,
    paper_runner: Callable[[argparse.Namespace], Mapping[str, Any]] | None = None,
    codex_bin: str = "codex",
    pdftotext_bin: str = "pdftotext",
    pdfinfo_bin: str = "pdfinfo",
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    if not re.fullmatch(r"p(?:0|[1-9][0-9]*)", candidate_id):
        raise ValueError("candidate_id must be p0, p1, p2, ...")
    if workers < 1 or workers > 4:
        raise ValueError("workers must be within 1..4")
    if max_attempts not in (1, 2):
        raise ValueError("max_attempts must be 1 or 2")
    sample_manifest = load_sample_manifest(sample_manifest_path)
    config = _candidate_config(
        sample_manifest=sample_manifest,
        prompt_path=prompt_path,
        candidate_id=candidate_id,
        parent_candidate_id=parent_candidate_id,
        judge_prompt_path=judge_prompt_path,
        review_schema_path=review_schema_path,
        judge_schema_path=judge_schema_path,
        reviewer_model=reviewer_model,
        judge_model=judge_model,
        max_attempts=max_attempts,
        workers=workers,
    )
    candidate_root = campaign_root / "candidates" / candidate_id
    papers_root = candidate_root / "papers"
    candidate_root.mkdir(parents=True, exist_ok=True)
    papers_root.mkdir(exist_ok=True)
    config_path = candidate_root / "candidate-config.json"
    if config_path.exists():
        _load_existing_config(config_path, config)
    else:
        write_json(config_path, config)
    prompt_copy = candidate_root / "candidate-prompt.md"
    if prompt_copy.exists():
        if sha256_file(prompt_copy) != config["prompt_sha256"]:
            raise ValueError("candidate prompt copy changed after run start")
    else:
        shutil.copy2(prompt_path, prompt_copy)

    aggregate_path = candidate_root / "aggregate.json"
    if aggregate_path.exists():
        return _stored_aggregate(aggregate_path, config)

    entries = sample_manifest["entries"]
    assert isinstance(entries, list)
    existing_ids: set[str] = set()
    existing_seconds = 0.0
    missing: list[Mapping[str, Any]] = []
    for entry in entries:
        assert isinstance(entry, Mapping)
        paper_id = str(entry["paper_id"])
        output_dir = papers_root / paper_id
        if output_dir.exists():
            record = _paper_record(
                output_dir=output_dir,
                paper_id=paper_id,
                prompt_sha256=str(config["prompt_sha256"]),
            )
            existing_ids.add(paper_id)
            existing_seconds += float(record["timing"].get("total_seconds", 0.0))
        else:
            missing.append(entry)

    runner = paper_runner or run_codex_paper
    started = time.perf_counter()

    def invoke(entry: Mapping[str, Any]) -> Mapping[str, Any]:
        paper_id = str(entry["paper_id"])
        args = argparse.Namespace(
            paper_pdf=Path(str(entry["pdf_path"])),
            human_review_json=Path(str(entry["label_path"])),
            reviewer_prompt=prompt_path,
            judge_prompt=judge_prompt_path,
            review_schema=review_schema_path,
            judge_schema=judge_schema_path,
            output_dir=papers_root / paper_id,
            campaign_id=campaign_id,
            candidate_id=candidate_id,
            parent_candidate_id=parent_candidate_id,
            paper_id=paper_id,
            reviewer_model=reviewer_model,
            judge_model=judge_model,
            codex_bin=codex_bin,
            pdftotext_bin=pdftotext_bin,
            pdfinfo_bin=pdfinfo_bin,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            wandb_mode="disabled",
            wandb_entity="unused",
            wandb_project="unused",
        )
        return runner(args)

    failures: list[dict[str, Any]] = []
    if missing:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(invoke, entry): entry for entry in missing}
            for future in as_completed(futures):
                entry = futures[future]
                paper_id = str(entry["paper_id"])
                try:
                    future.result()
                except Exception as error:
                    failure = {
                        "paper_id": paper_id,
                        "error_type": type(error).__name__,
                        "message": str(error)[-2000:],
                        "attempt_evidence": getattr(error, "evidence", None),
                    }
                    failures.append(failure)
                    failure_root = candidate_root / "failures"
                    failure_root.mkdir(exist_ok=True)
                    write_json(failure_root / f"{paper_id}.json", failure)
    invocation_seconds = time.perf_counter() - started
    if failures:
        write_json(
            candidate_root / "candidate-failure.json",
            {
                "campaign_id": campaign_id,
                "candidate_id": candidate_id,
                "failure_count": len(failures),
                "failures": failures,
            },
        )
        raise RuntimeError(
            f"candidate {candidate_id} failed on {len(failures)} paper(s)"
        )

    records: list[dict[str, Any]] = []
    publish_bundles: list[dict[str, Any]] = []
    for entry in entries:
        assert isinstance(entry, Mapping)
        paper_id = str(entry["paper_id"])
        record = _paper_record(
            output_dir=papers_root / paper_id,
            paper_id=paper_id,
            prompt_sha256=str(config["prompt_sha256"]),
        )
        publish_bundles.append(dict(record.pop("publish_bundle")))
        records.append(record)

    aggregate = aggregate_paper_records(records)
    sample_count = int(sample_manifest["count"])
    if (
        aggregate["completed_count"] != sample_count
        or aggregate["failure_count"] != 0
    ):
        raise RuntimeError(
            f"candidate did not complete the frozen {sample_count}/{sample_count} sample"
        )
    wall_clock_seconds = existing_seconds + invocation_seconds
    serial_equivalent_seconds = float(
        aggregate["timing"]["total_seconds"]["total"]
    )
    aggregate.update(
        {
            "campaign_id": campaign_id,
            "candidate_id": candidate_id,
            "parent_candidate_id": parent_candidate_id,
            "prompt_sha256": config["prompt_sha256"],
            "sample_manifest_sha256": config["sample_manifest_sha256"],
            "shared_configuration_sha256": config["shared_configuration_sha256"],
            "workers": workers,
            "resumed_paper_count": len(existing_ids),
            "new_paper_count": len(missing),
            "runner_invocation_seconds": invocation_seconds,
            "serial_equivalent_seconds": serial_equivalent_seconds,
            "wall_clock_seconds": wall_clock_seconds,
            "papers_per_hour": 3600.0 * sample_count / wall_clock_seconds
            if wall_clock_seconds > 0
            else 0.0,
        }
    )
    aggregate["aggregate_sha256"] = _sha256_json(aggregate)
    write_json(candidate_root / "publish-bundles.json", publish_bundles)
    write_json(aggregate_path, aggregate)
    write_json(candidate_root / "candidate-record.json", aggregate)
    (candidate_root / "reflection.md").write_text(
        _render_batch_reflection(aggregate),
        encoding="utf-8",
    )
    return aggregate


def _candidate_order(path: Path) -> int:
    match = re.fullmatch(r"p([0-9]+)", path.name)
    return int(match.group(1)) if match else 10**9


def write_candidate_spec(
    *,
    campaign_root: Path,
    candidate_id: str,
    parent_candidate_id: str,
    hypothesis: str,
    change_summary: Sequence[str],
) -> dict[str, Any]:
    if not hypothesis.strip():
        raise ValueError("candidate hypothesis must be nonempty")
    normalized_changes = [item.strip() for item in change_summary if item.strip()]
    if not normalized_changes:
        raise ValueError("candidate change_summary must be nonempty")
    value = {
        "candidate_id": candidate_id,
        "parent_candidate_id": parent_candidate_id,
        "hypothesis": hypothesis.strip(),
        "change_summary": normalized_changes,
    }
    path = campaign_root / "candidates" / candidate_id / "candidate-spec.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = _load_json(path, "candidate spec")
        if existing != value:
            raise ValueError("candidate spec changed after it was recorded")
        return existing
    write_json(path, value)
    return value


def _candidate_specs(campaign_root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted((campaign_root / "candidates").glob("p*/candidate-spec.json")):
        value = _load_json(path, "candidate spec")
        candidate_id = str(value.get("candidate_id", ""))
        if candidate_id:
            result[candidate_id] = value
    return result


def render_experience_memory(
    records: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    specs: Mapping[str, Mapping[str, Any]],
) -> str:
    if len(records) != len(decisions):
        raise ValueError("experience records and decisions must align")
    by_id = {str(record["candidate_id"]): record for record in records}
    lines = [
        "# Review Prompt Optimization Experience Memory",
        "",
        "This cumulative memory is an input to every next-candidate reflection. ",
        "It preserves both successful rules and discarded failure modes; a higher ",
        "Composite alone never erases a component or dimension regression.",
        "",
    ]
    baseline = records[0]
    lines.extend(
        [
            "## Baseline — " + str(baseline["candidate_id"]),
            "",
            f"- Composite: {float(baseline['composite']):.6f}",
            f"- Reference-score agreement: {float(baseline['human_agreement']):.6f}",
            f"- Judge review quality: {float(baseline['judge_quality']):.6f}",
            "",
        ]
    )
    for decision in decisions[1:]:
        candidate_id = str(decision["candidate_id"])
        parent_id = str(decision["parent_candidate_id"])
        candidate = by_id[candidate_id]
        parent = by_id[parent_id]
        spec = specs.get(candidate_id, {})
        verdict = str(decision["decision"])
        reason = str(decision["rejection_reason"])
        composite_delta = float(candidate["composite"]) - float(parent["composite"])
        human_delta = float(candidate["human_agreement"]) - float(
            parent["human_agreement"]
        )
        judge_delta = float(candidate["judge_quality"]) - float(
            parent["judge_quality"]
        )
        candidate_dimensions = candidate["human_dimension_agreement"]
        parent_dimensions = parent["human_dimension_agreement"]
        dimension_deltas = {
            dimension: float(candidate_dimensions[dimension])
            - float(parent_dimensions[dimension])
            for dimension in parent_dimensions
        }
        gains = [
            dimension
            for dimension, delta in dimension_deltas.items()
            if delta > 1e-12
        ]
        regressions = [
            dimension
            for dimension, delta in dimension_deltas.items()
            if delta < -1e-12
        ]
        lines.extend(
            [
                f"## Experience — {candidate_id} — {verdict}",
                "",
                f"- Parent: {parent_id}",
                f"- Hypothesis: {spec.get('hypothesis', 'not recorded')}",
                f"- Decision: {verdict} (`{reason}`)",
                f"- Composite delta: {composite_delta:+.6f}",
                f"- Reference-score agreement delta: {human_delta:+.6f}",
                f"- Judge review-quality delta: {judge_delta:+.6f}",
                "- Dimension agreement deltas:",
            ]
        )
        for dimension, delta in dimension_deltas.items():
            lines.append(f"  - {dimension}: {delta:+.6f}")
        changes = spec.get("change_summary", [])
        if isinstance(changes, list) and changes:
            lines.append("- Prompt intervention:")
            lines.extend(f"  - {item}" for item in changes)
        lines.extend(
            [
                "- Meta-level experience:",
                "  - Preserve observed gains: "
                + (", ".join(gains) if gains else "none measured"),
                "  - Do not repeat unmodified behavior affecting: "
                + (", ".join(regressions) if regressions else "none measured"),
                "  - Next-candidate constraint: preserve the current parent and "
                + (
                    "explicitly recover " + ", ".join(regressions)
                    if regressions
                    else "seek a new bounded improvement without regressions"
                )
                + ".",
                "  - Selection lesson: optimize the gated objective, not Composite "
                "in isolation.",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def update_experience_memory(
    campaign_root: Path,
    records: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
) -> Path:
    path = campaign_root / "experience-memory.md"
    path.write_text(
        render_experience_memory(records, decisions, _candidate_specs(campaign_root)),
        encoding="utf-8",
    )
    return path


def decide_campaign(campaign_root: Path, campaign_id: str) -> dict[str, Any]:
    records = [
        _load_json(path / "candidate-record.json", "candidate record")
        for path in sorted((campaign_root / "candidates").glob("p*"), key=_candidate_order)
        if (path / "candidate-record.json").is_file()
    ]
    if not records:
        raise ValueError("campaign has no completed candidates")
    decisions = candidate_decisions(records)
    value = {
        "campaign_id": campaign_id,
        "candidate_count": len(records),
        "current_parent_candidate_id": next_parent_id(records),
        "consecutive_discards": 0,
        "candidates": decisions,
    }
    consecutive_discards = 0
    for decision in reversed(decisions):
        if decision["decision"] == "discard":
            consecutive_discards += 1
        else:
            break
    value["consecutive_discards"] = consecutive_discards
    write_json(campaign_root / "campaign.json", value)
    update_experience_memory(campaign_root, records, decisions)
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run-candidate")
    run_parser.add_argument("--sample-manifest", type=Path, required=True)
    run_parser.add_argument("--prompt", type=Path, required=True)
    run_parser.add_argument("--campaign-root", type=Path, required=True)
    run_parser.add_argument("--campaign-id", required=True)
    run_parser.add_argument("--candidate-id", required=True)
    run_parser.add_argument("--parent-candidate-id", required=True)
    run_parser.add_argument("--judge-prompt", type=Path, required=True)
    run_parser.add_argument("--review-schema", type=Path, required=True)
    run_parser.add_argument("--judge-schema", type=Path, required=True)
    run_parser.add_argument("--reviewer-model", required=True)
    run_parser.add_argument("--judge-model", required=True)
    run_parser.add_argument("--workers", type=int, default=2)
    run_parser.add_argument("--max-attempts", type=int, choices=(1, 2), default=2)
    run_parser.add_argument("--codex-bin", default="codex")
    run_parser.add_argument("--pdftotext-bin", default="pdftotext")
    run_parser.add_argument("--pdfinfo-bin", default="pdfinfo")
    run_parser.add_argument("--timeout-seconds", type=int, default=1800)

    decide_parser = subparsers.add_parser("decide")
    decide_parser.add_argument("--campaign-root", type=Path, required=True)
    decide_parser.add_argument("--campaign-id", required=True)
    publish_parser = subparsers.add_parser("publish-offline")
    publish_parser.add_argument("--sample-manifest", type=Path, required=True)
    publish_parser.add_argument("--campaign-root", type=Path, required=True)
    publish_parser.add_argument("--campaign-id", required=True)
    publish_parser.add_argument("--candidate-id", required=True)
    publish_parser.add_argument("--entity", required=True)
    publish_parser.add_argument("--project", required=True)
    publish_parser.add_argument("--source-git-sha", required=True)
    publish_parser.add_argument("--kept-git-sha")
    spec_parser = subparsers.add_parser("record-spec")
    spec_parser.add_argument("--campaign-root", type=Path, required=True)
    spec_parser.add_argument("--candidate-id", required=True)
    spec_parser.add_argument("--parent-candidate-id", required=True)
    spec_parser.add_argument("--hypothesis", required=True)
    spec_parser.add_argument("--change-summary", action="append", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run-candidate":
        value = run_candidate(
            sample_manifest_path=args.sample_manifest,
            prompt_path=args.prompt,
            campaign_root=args.campaign_root,
            campaign_id=args.campaign_id,
            candidate_id=args.candidate_id,
            parent_candidate_id=args.parent_candidate_id,
            judge_prompt_path=args.judge_prompt,
            review_schema_path=args.review_schema,
            judge_schema_path=args.judge_schema,
            reviewer_model=args.reviewer_model,
            judge_model=args.judge_model,
            workers=args.workers,
            max_attempts=args.max_attempts,
            codex_bin=args.codex_bin,
            pdftotext_bin=args.pdftotext_bin,
            pdfinfo_bin=args.pdfinfo_bin,
            timeout_seconds=args.timeout_seconds,
        )
    elif args.command == "decide":
        value = decide_campaign(args.campaign_root, args.campaign_id)
    elif args.command == "publish-offline":
        value = publish_candidate_offline(
            sample_manifest_path=args.sample_manifest,
            campaign_root=args.campaign_root,
            campaign_id=args.campaign_id,
            candidate_id=args.candidate_id,
            entity=args.entity,
            project=args.project,
            source_git_sha=args.source_git_sha,
            kept_git_sha=args.kept_git_sha,
        )
    else:
        value = write_candidate_spec(
            campaign_root=args.campaign_root,
            candidate_id=args.candidate_id,
            parent_candidate_id=args.parent_candidate_id,
            hypothesis=args.hypothesis,
            change_summary=args.change_summary,
        )
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
