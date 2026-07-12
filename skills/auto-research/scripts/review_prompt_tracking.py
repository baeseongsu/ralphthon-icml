#!/usr/bin/env python3
"""Persist local evidence and mirror allowlisted review data to W&B offline."""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence, TextIO

from review_prompt_scoring import (
    JUDGE_DIMENSIONS,
    PAPER_ID_PATTERN,
    REVIEW_SCORE_RANGES,
    SCORE_RANGES,
    validate_generated_review,
    validate_judge,
)


ALLOWED_WANDB_CONFIG_FIELDS = frozenset(
    {
        "prompt_sha256",
        "fixture_sha256",
        "objective_human_weight",
        "objective_judge_weight",
        "objective_penalty_weight",
        "campaign_id",
        "candidate_id",
        "pdf_sha256",
        "sample_manifest_sha256",
        "reviewer_prompt_sha256",
        "judge_prompt_sha256",
        "reviewer_model",
        "judge_model",
        "codex_cli_version",
        "parent_candidate_id",
        "paper_text_sha256",
        "human_review_sha256",
        "review_schema_sha256",
        "judge_schema_sha256",
        "judge_reference_sha256",
        "generated_review_sha256",
        "judge_sha256",
        "wandb_generated_review_sha256",
        "wandb_judge_sha256",
        "auth_mode",
    }
)
ALLOWED_WANDB_METRIC_FIELDS = frozenset(
    {
        "objective/composite",
        "objective/human_agreement",
        "objective/judge_quality",
        "objective/penalty",
        "usage/reviewer_input_tokens",
        "usage/reviewer_cached_input_tokens",
        "usage/reviewer_output_tokens",
        "usage/reviewer_reasoning_output_tokens",
        "usage/judge_input_tokens",
        "usage/judge_cached_input_tokens",
        "usage/judge_output_tokens",
        "usage/judge_reasoning_output_tokens",
    }
)
REQUIRED_WANDB_BATCH_CONFIG_FIELDS = frozenset(
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
OPTIONAL_WANDB_BATCH_CONFIG_FIELDS = frozenset({"kept_git_sha"})
ALLOWED_WANDB_BATCH_CONFIG_FIELDS = (
    REQUIRED_WANDB_BATCH_CONFIG_FIELDS | OPTIONAL_WANDB_BATCH_CONFIG_FIELDS
)
ALLOWED_WANDB_BATCH_METRIC_FIELDS = frozenset(
    {
        "objective/composite",
        "objective/human_agreement",
        "objective/judge_quality",
        "objective/penalty",
        *{f"agreement/{dimension}" for dimension in SCORE_RANGES},
        *{
            f"distribution_agreement/{dimension}"
            for dimension in SCORE_RANGES
        },
        *{f"judge/{dimension}" for dimension in JUDGE_DIMENSIONS},
        *{
            f"gap/{dimension}/{summary}"
            for dimension in SCORE_RANGES
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
PUBLISH_BUNDLE_FIELDS = frozenset(
    {"schema_version", "paper_id", "generated_review", "judge"}
)
PUBLISH_BUNDLE_SCHEMA_VERSION = "review-prompt-publish-v1"
WANDB_BATCH_SIZE = 5
SHA256_VALUE_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DISTRIBUTION_FIELDS = frozenset({"counts", "frequencies", "sample_count"})
SENSITIVE_WANDB_MARKERS = (
    "forum_id",
    "source_id",
    "source_path",
    "original_id",
    "original_paper_id",
    "label_path",
    "pdf_path",
    "paper_text",
    "human_scores",
    "human_targets",
    "reference_scores",
    "reference_labels",
    "reference_review",
    "raw_human_review",
    "judge_reference",
    "strengths_and_weaknesses",
    "key_questions_for_authors",
    "wandb_api_key",
    "authorization",
    "bearer ",
)
SENSITIVE_WANDB_CATEGORY_MARKER_PATTERN = re.compile(
    r"(?<![a-z0-9])"
    r"(?:source|original|reference)"
    r"(?:[_\s-]+)"
    r"(?:id|url|uri|title|path|file|filename|stem|forum|authors?|method|"
    r"scores?|labels?|review|text)"
    r"(?![a-z0-9])"
)
JUDGE_REFERENCE_REVIEW_MARKER_PATTERN = re.compile(
    r"(?<![a-z0-9])reference(?:[_\s-]+)review(?![a-z0-9])",
    flags=re.IGNORECASE,
)


def redact_judge_reference_review_markers(
    judge: Mapping[str, Any],
) -> dict[str, Any]:
    """Redact only Judge meta-markers before the fail-closed W&B scan.

    The Judge is allowed to compare against reference prose locally, so its
    rationale may name that comparison source without copying it. The marker is
    not useful in W&B and is removed explicitly. Reviewer text and every other
    sensitive category remain subject to rejection by the privacy scanner.
    """

    validated = validate_judge(judge)
    result = dict(validated)
    if JUDGE_REFERENCE_REVIEW_MARKER_PATTERN.search(str(validated["rationale"])):
        result["rationale"] = "[REDACTED_COMPARISON_RATIONALE]"
    return result


@contextmanager
def _locked_ledger(path: Path) -> Iterator[TextIO]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not path.is_file():
        raise ValueError(f"ledger is not a regular file: {path}")
    with path.open("a+", encoding="utf-8") as ledger:
        fcntl.flock(ledger.fileno(), fcntl.LOCK_EX)
        try:
            yield ledger
        finally:
            fcntl.flock(ledger.fileno(), fcntl.LOCK_UN)


def _required_id(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value.strip()


def append_record(path: Path, record: Mapping[str, Any]) -> None:
    """Append one unique campaign/candidate record under an exclusive lock."""

    campaign_id = _required_id(record, "campaign_id")
    candidate_id = _required_id(record, "candidate_id")
    payload = json.dumps(
        dict(record),
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    with _locked_ledger(path) as ledger:
        ledger.seek(0)
        existing = [json.loads(line) for line in ledger if line.strip()]
        if any(
            item.get("campaign_id") == campaign_id
            and item.get("candidate_id") == candidate_id
            for item in existing
        ):
            raise ValueError("duplicate candidate_id in campaign ledger")
        ledger.seek(0, os.SEEK_END)
        start = ledger.tell()
        try:
            ledger.write(payload)
            ledger.flush()
            os.fsync(ledger.fileno())
        except Exception:
            ledger.seek(start)
            ledger.truncate()
            ledger.flush()
            os.fsync(ledger.fileno())
            raise


def _validated_publish_bundles(
    publish_bundles: Sequence[Mapping[str, Any]],
) -> list[tuple[str, Mapping[str, Any], Mapping[str, Any]]]:
    if len(publish_bundles) != WANDB_BATCH_SIZE:
        raise ValueError(
            f"publish_bundles must contain exactly {WANDB_BATCH_SIZE} entries"
        )

    seen_paper_ids: set[str] = set()
    validated: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    for index, bundle in enumerate(publish_bundles):
        if not isinstance(bundle, Mapping):
            raise ValueError(f"publish_bundles[{index}] must be an object")
        if set(bundle) != set(PUBLISH_BUNDLE_FIELDS):
            missing = sorted(set(PUBLISH_BUNDLE_FIELDS) - set(bundle))
            unexpected = sorted(set(bundle) - set(PUBLISH_BUNDLE_FIELDS))
            raise ValueError(
                f"publish_bundles[{index}] keys do not match schema; "
                f"missing={missing}, unexpected={unexpected}"
            )
        if bundle["schema_version"] != PUBLISH_BUNDLE_SCHEMA_VERSION:
            raise ValueError(
                f"publish_bundles[{index}].schema_version must be "
                f"{PUBLISH_BUNDLE_SCHEMA_VERSION}"
            )
        paper_id = bundle["paper_id"]
        if not isinstance(paper_id, str) or (
            PAPER_ID_PATTERN.fullmatch(paper_id.strip()) is None
        ):
            raise ValueError(
                f"publish_bundles[{index}].paper_id must be a pseudonymous "
                "paper-* identifier"
            )
        paper_id = paper_id.strip()
        if paper_id in seen_paper_ids:
            raise ValueError(f"duplicate paper_id: {paper_id}")
        seen_paper_ids.add(paper_id)
        review = validate_generated_review(bundle["generated_review"])
        judge = validate_judge(bundle["judge"])
        validated.append((paper_id, review, judge))
    return validated


def _batch_text(field: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or "\n" in value
        or "\r" in value
    ):
        raise ValueError(f"{field} must be a nonempty single-line string")
    return value


def _batch_finite_number(field: str, value: object) -> int | float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{field} must be a finite number")
    return value


def _validate_batch_config(
    config: Mapping[str, Any],
    *,
    campaign_id: str,
    candidate_id: str,
) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        raise ValueError("W&B batch config must be an object")
    actual = set(config)
    allowed = ALLOWED_WANDB_BATCH_CONFIG_FIELDS
    if not REQUIRED_WANDB_BATCH_CONFIG_FIELDS <= actual or not actual <= allowed:
        raise ValueError("W&B batch config keys do not match schema")

    text_fields = REQUIRED_WANDB_BATCH_CONFIG_FIELDS - {
        "objective_human_weight",
        "objective_judge_weight",
        "objective_penalty_weight",
    }
    text_fields |= set(config) & OPTIONAL_WANDB_BATCH_CONFIG_FIELDS
    for field in text_fields:
        value = config[field]
        if not isinstance(value, str):
            raise ValueError(
                f"W&B batch config {field} must be a finite scalar"
            )
        _batch_text(f"W&B batch config {field}", value)

    for field in (
        "objective_human_weight",
        "objective_judge_weight",
        "objective_penalty_weight",
    ):
        value = config[field]
        try:
            number = _batch_finite_number(f"W&B batch config {field}", value)
        except ValueError as error:
            raise ValueError(
                f"W&B batch config {field} must be a finite scalar"
            ) from error
        if number < 0:
            raise ValueError(f"W&B batch config {field} must be nonnegative")

    for field in (
        "sample_manifest_sha256",
        "reviewer_prompt_sha256",
        "judge_prompt_sha256",
        "review_schema_sha256",
        "judge_schema_sha256",
    ):
        if SHA256_VALUE_PATTERN.fullmatch(config[field]) is None:
            raise ValueError(f"W&B batch config {field} must be a SHA-256 value")
    for field in ("source_git_sha", "kept_git_sha"):
        if field in config and GIT_SHA_PATTERN.fullmatch(config[field]) is None:
            raise ValueError(f"W&B batch config {field} must be a full Git SHA")
    if config["target_source"] != "pseudo_label":
        raise ValueError("W&B batch config target_source must be pseudo_label")
    if config["campaign_id"] != campaign_id:
        raise ValueError("W&B batch config campaign_id mismatch")
    if config["candidate_id"] != candidate_id:
        raise ValueError("W&B batch config candidate_id mismatch")
    return dict(config)


def _validate_batch_metrics(
    metrics: Mapping[str, int | float],
) -> dict[str, int | float]:
    if not isinstance(metrics, Mapping):
        raise ValueError("W&B batch metrics must be an object")
    unexpected = set(metrics) - ALLOWED_WANDB_BATCH_METRIC_FIELDS
    if unexpected:
        raise ValueError("W&B batch metrics contain fields outside the allowlist")
    validated: dict[str, int | float] = {}
    for field, value in metrics.items():
        validated[field] = _batch_finite_number(
            f"W&B batch metric {field}",
            value,
        )
    return validated


def _validate_distributions(
    field: str,
    distributions: Mapping[str, Mapping[str, Any]],
    ranges: Mapping[str, tuple[float, float]],
) -> dict[str, dict[str, Any]]:
    if not isinstance(distributions, Mapping):
        raise ValueError(f"{field} must be an object")
    if set(distributions) != set(ranges):
        raise ValueError(f"{field} dimensions do not match schema")

    validated: dict[str, dict[str, Any]] = {}
    for dimension, (raw_minimum, raw_maximum) in ranges.items():
        minimum = int(raw_minimum)
        maximum = int(raw_maximum)
        distribution = distributions[dimension]
        child_field = f"{field}.{dimension}"
        if not isinstance(distribution, Mapping):
            raise ValueError(f"{child_field} must be an object")
        if set(distribution) != set(DISTRIBUTION_FIELDS):
            raise ValueError(f"{child_field} keys do not match schema")

        sample_count = distribution["sample_count"]
        if (
            isinstance(sample_count, bool)
            or not isinstance(sample_count, int)
            or sample_count != WANDB_BATCH_SIZE
        ):
            raise ValueError(
                f"{child_field}.sample_count must be {WANDB_BATCH_SIZE}"
            )
        counts = distribution["counts"]
        frequencies = distribution["frequencies"]
        if not isinstance(counts, Mapping):
            raise ValueError(f"{child_field}.counts must be an object")
        if not isinstance(frequencies, Mapping):
            raise ValueError(f"{child_field}.frequencies must be an object")
        categories = [str(score) for score in range(minimum, maximum + 1)]
        if set(counts) != set(categories):
            raise ValueError(f"{child_field}.counts categories do not match schema")
        if set(frequencies) != set(categories):
            raise ValueError(
                f"{child_field}.frequencies categories do not match schema"
            )

        normalized_counts: dict[str, int] = {}
        for category in categories:
            count = counts[category]
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
            ):
                raise ValueError(
                    f"{child_field}.counts[{category}] count must be an "
                    "integer >= 0"
                )
            normalized_counts[category] = count
        if sum(normalized_counts.values()) != WANDB_BATCH_SIZE:
            raise ValueError(
                f"{child_field}.counts must sum to {WANDB_BATCH_SIZE}"
            )

        normalized_frequencies: dict[str, float] = {}
        for category in categories:
            frequency = frequencies[category]
            if (
                isinstance(frequency, bool)
                or not isinstance(frequency, (int, float))
                or not math.isfinite(float(frequency))
            ):
                raise ValueError(
                    f"{child_field}.frequencies[{category}] frequency must "
                    "be a finite number"
                )
            normalized = float(frequency)
            if not 0.0 <= normalized <= 1.0:
                raise ValueError(
                    f"{child_field}.frequencies[{category}] must be within 0..1"
                )
            expected = normalized_counts[category] / WANDB_BATCH_SIZE
            if not math.isclose(
                normalized,
                expected,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    f"{child_field}.frequencies[{category}] frequency does "
                    "not equal count / sample_count"
                )
            normalized_frequencies[category] = normalized
        if not math.isclose(
            sum(normalized_frequencies.values()),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(f"{child_field}.frequencies must sum to 1")
        validated[dimension] = {
            "counts": normalized_counts,
            "frequencies": normalized_frequencies,
            "sample_count": sample_count,
        }
    return validated


def _require_bundle_distribution_match(
    field: str,
    distributions: Mapping[str, Mapping[str, Any]],
    ranges: Mapping[str, tuple[float, float]],
    values: Mapping[str, Sequence[int]],
) -> None:
    for dimension, (raw_minimum, raw_maximum) in ranges.items():
        expected = {
            str(score): sum(value == score for value in values[dimension])
            for score in range(int(raw_minimum), int(raw_maximum) + 1)
        }
        if distributions[dimension]["counts"] != expected:
            raise ValueError(
                f"{field}.{dimension} does not match publish_bundles"
            )


def _validated_forbidden_terms(forbidden_terms: Sequence[str]) -> tuple[str, ...]:
    if isinstance(forbidden_terms, (str, bytes)) or not isinstance(
        forbidden_terms,
        Sequence,
    ):
        raise ValueError("forbidden_terms must be a sequence of strings")
    validated: list[str] = []
    for index, term in enumerate(forbidden_terms):
        if not isinstance(term, str) or not term.strip():
            raise ValueError(
                f"forbidden_terms[{index}] must be a nonempty string"
            )
        validated.append(term.strip().casefold())
    return tuple(validated)


def _run_batch_privacy_scan(
    *,
    entity: str,
    project: str,
    campaign_id: str,
    candidate_id: str,
    config: Mapping[str, Any],
    metrics: Mapping[str, int | float],
    publish_bundles: Sequence[
        tuple[str, Mapping[str, Any], Mapping[str, Any]]
    ],
    predicted_distributions: Mapping[str, Mapping[str, Any]],
    reference_distributions: Mapping[str, Mapping[str, Any]],
    judge_distributions: Mapping[str, Mapping[str, Any]],
    forbidden_terms: Sequence[str],
) -> None:
    terms = _validated_forbidden_terms(forbidden_terms)
    payload = {
        "entity": entity,
        "project": project,
        "campaign_id": campaign_id,
        "candidate_id": candidate_id,
        "config": config,
        "metrics": metrics,
        "publish_bundles": [
            {
                "paper_id": paper_id,
                "generated_review": review,
                "judge": judge,
            }
            for paper_id, review, judge in publish_bundles
        ],
        "predicted_distributions": predicted_distributions,
        "aggregate_distributions": reference_distributions,
        "judge_distributions": judge_distributions,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).casefold()
    sensitive = any(marker in serialized for marker in SENSITIVE_WANDB_MARKERS)
    sensitive = sensitive or (
        SENSITIVE_WANDB_CATEGORY_MARKER_PATTERN.search(serialized) is not None
    )
    sensitive = sensitive or "/users/" in serialized
    sensitive = sensitive or "\\\\users\\\\" in serialized
    sensitive = sensitive or any(term in serialized for term in terms)
    if sensitive:
        raise ValueError("W&B batch privacy scan rejected sensitive content")


def record_wandb_offline(
    *,
    wandb_module: Any,
    directory: Path,
    entity: str,
    project: str,
    campaign_id: str,
    candidate_id: str,
    config: Mapping[str, Any],
    metrics: Mapping[str, int | float],
    paper_id: str,
    generated_review: Mapping[str, Any],
    judge: Mapping[str, Any],
) -> tuple[str, str]:
    """Create one offline W&B run with an allowlisted full-review table."""

    for field, value in (
        ("entity", entity),
        ("project", project),
        ("campaign_id", campaign_id),
        ("candidate_id", candidate_id),
        ("paper_id", paper_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a nonempty string")
    if PAPER_ID_PATTERN.fullmatch(paper_id.strip()) is None:
        raise ValueError("paper_id must be a pseudonymous paper-* identifier")
    validate_generated_review(generated_review)
    validate_judge(judge)
    unexpected_config = sorted(set(config) - ALLOWED_WANDB_CONFIG_FIELDS)
    if unexpected_config:
        raise ValueError(
            f"W&B config contains fields outside the allowlist: {unexpected_config}"
        )
    unexpected_metrics = sorted(set(metrics) - ALLOWED_WANDB_METRIC_FIELDS)
    if unexpected_metrics:
        raise ValueError(
            f"W&B metrics contain fields outside the allowlist: {unexpected_metrics}"
        )
    directory.mkdir(parents=True, exist_ok=True)
    settings = wandb_module.Settings(
        console="off",
        disable_code=True,
        disable_git=True,
        disable_job_creation=True,
        x_disable_machine_info=True,
        x_disable_meta=True,
        x_disable_stats=True,
        x_save_requirements=False,
        save_code=False,
    )
    table = wandb_module.Table(
        columns=["paper_id", "generated_review_json", "judge_json"]
    )
    table.add_data(
        paper_id.strip(),
        json.dumps(generated_review, sort_keys=True),
        json.dumps(judge, sort_keys=True),
    )

    with wandb_module.init(
        mode="offline",
        dir=str(directory),
        entity=entity.strip(),
        project=project.strip(),
        group=campaign_id.strip(),
        job_type="review-prompt-candidate",
        name=candidate_id.strip(),
        config=dict(config),
        save_code=False,
        settings=settings,
    ) as run:
        run.log({**dict(metrics), "reviews/all": table})
        for key, value in metrics.items():
            run.summary[key] = value
        run.summary["ops/status"] = "finished"
        return str(run.id), str(Path(run.dir).resolve().parent)


def record_wandb_batch_offline(
    *,
    wandb_module: Any,
    directory: Path,
    entity: str,
    project: str,
    campaign_id: str,
    candidate_id: str,
    config: Mapping[str, Any],
    metrics: Mapping[str, int | float],
    publish_bundles: Sequence[Mapping[str, Any]],
    predicted_distributions: Mapping[str, Mapping[str, Any]],
    reference_distributions: Mapping[str, Mapping[str, Any]],
    judge_distributions: Mapping[str, Mapping[str, Any]],
    forbidden_terms: Sequence[str],
) -> tuple[str, str]:
    """Create one offline W&B run for a complete review-prompt batch."""

    for field, value in (
        ("entity", entity),
        ("project", project),
        ("campaign_id", campaign_id),
        ("candidate_id", candidate_id),
    ):
        _batch_text(field, value)
    validated_bundles = [
        (paper_id, review, redact_judge_reference_review_markers(judge))
        for paper_id, review, judge in _validated_publish_bundles(publish_bundles)
    ]
    validated_config = _validate_batch_config(
        config,
        campaign_id=campaign_id,
        candidate_id=candidate_id,
    )
    validated_metrics = _validate_batch_metrics(metrics)
    judge_ranges = {dimension: (1.0, 5.0) for dimension in JUDGE_DIMENSIONS}
    validated_predicted = _validate_distributions(
        "predicted_distributions",
        predicted_distributions,
        REVIEW_SCORE_RANGES,
    )
    validated_reference = _validate_distributions(
        "reference_distributions",
        reference_distributions,
        SCORE_RANGES,
    )
    validated_judges = _validate_distributions(
        "judge_distributions",
        judge_distributions,
        judge_ranges,
    )
    predicted_values = {
        dimension: [
            int(review["scores"][dimension])
            for _, review, _ in validated_bundles
        ]
        for dimension in REVIEW_SCORE_RANGES
    }
    judge_values = {
        dimension: [
            int(judge["scores"][dimension])
            for _, _, judge in validated_bundles
        ]
        for dimension in JUDGE_DIMENSIONS
    }
    _require_bundle_distribution_match(
        "predicted_distributions",
        validated_predicted,
        REVIEW_SCORE_RANGES,
        predicted_values,
    )
    _require_bundle_distribution_match(
        "judge_distributions",
        validated_judges,
        judge_ranges,
        judge_values,
    )
    _run_batch_privacy_scan(
        entity=entity,
        project=project,
        campaign_id=campaign_id,
        candidate_id=candidate_id,
        config=validated_config,
        metrics=validated_metrics,
        publish_bundles=validated_bundles,
        predicted_distributions=validated_predicted,
        reference_distributions=validated_reference,
        judge_distributions=validated_judges,
        forbidden_terms=forbidden_terms,
    )
    reviews_table = wandb_module.Table(
        columns=["paper_id", "generated_review_json", "judge_json"]
    )
    for paper_id, review, judge in validated_bundles:
        reviews_table.add_data(
            paper_id,
            json.dumps(review, sort_keys=True),
            json.dumps(judge, sort_keys=True),
        )

    score_table = wandb_module.Table(
        columns=[
            "kind",
            "dimension",
            "score",
            "count",
            "frequency",
            "sample_count",
        ]
    )
    for kind, distributions, ranges in (
        ("predicted", validated_predicted, REVIEW_SCORE_RANGES),
        ("reference", validated_reference, SCORE_RANGES),
    ):
        for dimension, (minimum, maximum) in ranges.items():
            distribution = distributions[dimension]
            for raw_score in range(int(minimum), int(maximum) + 1):
                score = str(raw_score)
                count = distribution["counts"][score]
                score_table.add_data(
                    kind,
                    dimension,
                    score,
                    count,
                    distribution["frequencies"][score],
                    distribution["sample_count"],
                )

    judge_table = wandb_module.Table(
        columns=["dimension", "score", "count", "frequency", "sample_count"]
    )
    for dimension in JUDGE_DIMENSIONS:
        distribution = validated_judges[dimension]
        for raw_score in range(1, 6):
            score = str(raw_score)
            count = distribution["counts"][score]
            judge_table.add_data(
                dimension,
                score,
                count,
                distribution["frequencies"][score],
                distribution["sample_count"],
            )

    directory.mkdir(parents=True, exist_ok=True)
    settings = wandb_module.Settings(
        console="off",
        disable_code=True,
        disable_git=True,
        disable_job_creation=True,
        x_disable_machine_info=True,
        x_disable_meta=True,
        x_disable_stats=True,
        x_save_requirements=False,
        save_code=False,
    )
    with wandb_module.init(
        mode="offline",
        dir=str(directory),
        entity=entity.strip(),
        project=project.strip(),
        group=campaign_id.strip(),
        job_type="review-prompt-candidate",
        name=candidate_id.strip(),
        config=validated_config,
        save_code=False,
        settings=settings,
    ) as run:
        run.log(
            {
                **validated_metrics,
                "reviews/all": reviews_table,
                "score_distributions": score_table,
                "judge_distributions": judge_table,
            }
        )
        for key, value in validated_metrics.items():
            run.summary[key] = value
        run.summary["ops/status"] = "finished"
        return str(run.id), str(Path(run.dir).resolve().parent)
