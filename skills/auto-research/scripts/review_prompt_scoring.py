#!/usr/bin/env python3
"""Validate and score one ICML review-prompt optimization candidate."""

from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence


SCORE_RANGES = {
    "soundness": (1.0, 4.0),
    "presentation": (1.0, 4.0),
    "significance": (1.0, 4.0),
    "originality": (1.0, 4.0),
    "overall_recommendation": (1.0, 6.0),
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
PENALTY_FIELDS = (
    "hallucination",
    "schema_failure",
    "missing_evidence",
    "api_failure",
)
REVIEW_SCORE_RANGES = {
    **SCORE_RANGES,
    "confidence": (1.0, 5.0),
}
GENERATED_REVIEW_FIELDS = frozenset(
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
    }
)
JUDGE_FIELDS = frozenset({"scores", "rationale"})
FIXTURE_FIELDS = frozenset(
    {"paper_id", "human_scores", "generated_review", "judge", "penalties"}
)
PAPER_ID_PATTERN = re.compile(r"^paper-[a-z0-9]+(?:-[a-z0-9]+)*$")
HUMAN_REVIEW_FIELDS = frozenset(
    {
        "forum_id",
        "summary",
        "strengths_and_weaknesses",
        "soundness",
        "presentation",
        "significance",
        "originality",
        "key_questions_for_authors",
        "limitations",
        "overall_recommendation",
        "confidence",
    }
)


def _finite_number(field: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _ordinal_integer(
    field: str,
    value: object,
    minimum: int | float,
    maximum: int | float,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(
            f"{field} integer score must be within {minimum:g}..{maximum:g}"
        )
    return value


def _mapping(field: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _exact_keys(
    field: str,
    value: Mapping[str, Any],
    expected: set[str] | frozenset[str],
) -> None:
    actual = set(value)
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        unexpected = sorted(actual - set(expected))
        raise ValueError(
            f"{field} keys do not match schema; "
            f"missing={missing}, unexpected={unexpected}"
        )


def _nonempty_text(field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value.strip()


def _text_list(field: str, value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a nonempty list")
    return [_nonempty_text(f"{field}[{index}]", item) for index, item in enumerate(value)]


def validate_generated_review(value: object) -> Mapping[str, Any]:
    review = _mapping("generated_review", value)
    _exact_keys("generated_review", review, GENERATED_REVIEW_FIELDS)
    for field in ("summary", "limitations", "ethical_concerns"):
        _nonempty_text(f"generated_review.{field}", review[field])
    for field in ("strengths", "weaknesses", "questions", "evidence_trace"):
        _text_list(f"generated_review.{field}", review[field])

    scores = _mapping("generated_review.scores", review["scores"])
    _exact_keys(
        "generated_review.scores",
        scores,
        set(REVIEW_SCORE_RANGES),
    )
    for dimension, (minimum, maximum) in REVIEW_SCORE_RANGES.items():
        _ordinal_integer(dimension, scores[dimension], minimum, maximum)

    rationales = _mapping(
        "generated_review.score_rationales",
        review["score_rationales"],
    )
    _exact_keys(
        "generated_review.score_rationales",
        rationales,
        set(REVIEW_SCORE_RANGES),
    )
    for dimension in REVIEW_SCORE_RANGES:
        _nonempty_text(
            f"generated_review.score_rationales.{dimension}",
            rationales[dimension],
        )
    return review


def validate_judge(value: object) -> Mapping[str, Any]:
    judge = _mapping("judge", value)
    _exact_keys("judge", judge, JUDGE_FIELDS)
    scores = _mapping("judge.scores", judge["scores"])
    _exact_keys("judge.scores", scores, set(JUDGE_DIMENSIONS))
    for dimension in JUDGE_DIMENSIONS:
        _ordinal_integer(dimension, scores[dimension], 1, 5)
    _nonempty_text("judge.rationale", judge["rationale"])
    return judge


def validate_smoke_fixture(value: object) -> Mapping[str, Any]:
    fixture = _mapping("fixture", value)
    _exact_keys("fixture", fixture, FIXTURE_FIELDS)
    paper_id = _nonempty_text("paper_id", fixture["paper_id"])
    if PAPER_ID_PATTERN.fullmatch(paper_id) is None:
        raise ValueError("paper_id must be a pseudonymous paper-* identifier")

    human_scores = _mapping("human_scores", fixture["human_scores"])
    _exact_keys("human_scores", human_scores, set(SCORE_RANGES))
    human_targets(human_scores)
    validate_generated_review(fixture["generated_review"])
    validate_judge(fixture["judge"])

    penalties = _mapping("penalties", fixture["penalties"])
    _exact_keys("penalties", penalties, set(PENALTY_FIELDS))
    for field in PENALTY_FIELDS:
        penalty = _finite_number(field, penalties[field])
        if not 0.0 <= penalty <= 1.0:
            raise ValueError(f"{field} penalty must be within 0..1")
    return fixture


def validate_human_review_record(value: object) -> Mapping[str, Any]:
    review = _mapping("human_review", value)
    _exact_keys("human_review", review, HUMAN_REVIEW_FIELDS)
    _nonempty_text("human_review.forum_id", review["forum_id"])
    for field in (
        "summary",
        "strengths_and_weaknesses",
        "key_questions_for_authors",
        "limitations",
    ):
        _nonempty_text(f"human_review.{field}", review[field])
    for dimension, (minimum, maximum) in REVIEW_SCORE_RANGES.items():
        score = _finite_number(dimension, review[dimension])
        if not minimum <= score <= maximum:
            raise ValueError(f"{dimension} score must be within {minimum:g}..{maximum:g}")
    return review


def human_labels_from_reviews(
    reviews: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    if not reviews:
        raise ValueError("at least one human review is required")
    validated = [validate_human_review_record(review) for review in reviews]
    forum_ids = {str(review["forum_id"]).strip() for review in validated}
    if len(forum_ids) != 1:
        raise ValueError("all human reviews must have the same forum_id")
    return {
        "human_scores": {
            dimension: [float(review[dimension]) for review in validated]
            for dimension in SCORE_RANGES
        },
        "human_confidence": [
            float(review["confidence"]) for review in validated
        ],
        "reviewer_count": len(validated),
    }


def human_targets(
    human_scores: Mapping[str, Sequence[int | float]],
) -> dict[str, float]:
    """Return dimension-wise arithmetic means for valid human scores."""

    targets: dict[str, float] = {}
    for dimension, (minimum, maximum) in SCORE_RANGES.items():
        values = list(human_scores.get(dimension, ()))
        if not values:
            raise ValueError(f"{dimension} requires at least one human score")
        normalized: list[float] = []
        for value in values:
            number = _finite_number(dimension, value)
            if not minimum <= number <= maximum:
                raise ValueError(
                    f"{dimension} contains an out-of-range human score"
                )
            normalized.append(number)
        targets[dimension] = sum(normalized) / len(normalized)
    return targets


def _agreement(
    predicted: float,
    target: float,
    minimum: float,
    maximum: float,
) -> float:
    return 1.0 - abs(predicted - target) / (maximum - minimum)


def score_candidate(
    *,
    human_scores: Mapping[str, Sequence[int | float]],
    predicted_scores: Mapping[str, int | float],
    judge_scores: Mapping[str, int | float],
    penalties: Mapping[str, int | float],
) -> dict[str, object]:
    """Return normalized human, Judge, penalty, and composite metrics."""

    targets = human_targets(human_scores)
    dimension_agreement: dict[str, float] = {}
    distribution_agreement: dict[str, float] = {}
    for dimension, (minimum, maximum) in SCORE_RANGES.items():
        predicted = _ordinal_integer(
            dimension,
            predicted_scores.get(dimension),
            minimum,
            maximum,
        )
        dimension_agreement[dimension] = _agreement(
            predicted,
            targets[dimension],
            minimum,
            maximum,
        )
        distribution_agreement[dimension] = sum(
            _agreement(
                predicted,
                _finite_number(dimension, value),
                minimum,
                maximum,
            )
            for value in human_scores[dimension]
        ) / len(human_scores[dimension])

    normalized_judge: list[float] = []
    for dimension in JUDGE_DIMENSIONS:
        value = _ordinal_integer(dimension, judge_scores.get(dimension), 1, 5)
        normalized_judge.append((value - 1.0) / 4.0)

    penalty_values: list[float] = []
    for field in PENALTY_FIELDS:
        value = _finite_number(field, penalties.get(field))
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{field} penalty must be within 0..1")
        penalty_values.append(value)

    human_agreement = sum(dimension_agreement.values()) / len(
        dimension_agreement
    )
    judge_quality = sum(normalized_judge) / len(normalized_judge)
    penalty = sum(penalty_values) / len(penalty_values)
    composite = max(
        0.0,
        min(
            1.0,
            0.5 * human_agreement + 0.5 * judge_quality - 0.25 * penalty,
        ),
    )
    return {
        "human_targets": targets,
        "human_dimension_agreement": dimension_agreement,
        "human_distribution_agreement": distribution_agreement,
        "human_agreement": human_agreement,
        "judge_quality": judge_quality,
        "penalty": penalty,
        "composite": composite,
    }


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be within 0..1")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * quantile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _numeric_summary(
    field: str,
    values: Sequence[int | float],
    *,
    nonnegative: bool = False,
) -> dict[str, float]:
    if not values:
        raise ValueError(f"{field} requires at least one value")
    normalized = [_finite_number(field, value) for value in values]
    if nonnegative and any(value < 0.0 for value in normalized):
        raise ValueError(f"{field} values must be nonnegative")
    return {
        "total": sum(normalized),
        "mean": sum(normalized) / len(normalized),
        "p50": _percentile(normalized, 0.50),
        "p95": _percentile(normalized, 0.95),
        "min": min(normalized),
        "max": max(normalized),
    }


def ordinal_distribution(
    values: Sequence[object],
    minimum: int,
    maximum: int,
    *,
    field: str = "ordinal score",
) -> dict[str, object]:
    if not values:
        raise ValueError(f"{field} requires at least one value")
    counts = {str(category): 0 for category in range(minimum, maximum + 1)}
    for value in values:
        score = _ordinal_integer(field, value, minimum, maximum)
        counts[str(score)] += 1
    sample_count = len(values)
    return {
        "counts": counts,
        "frequencies": {
            category: count / sample_count for category, count in counts.items()
        },
        "sample_count": sample_count,
    }


def _reference_distribution(
    values: Sequence[object],
    minimum: int,
    maximum: int,
    *,
    field: str,
) -> dict[str, object]:
    if not values:
        raise ValueError(f"{field} requires at least one value")
    normalized = [_finite_number(field, value) for value in values]
    if any(value < minimum or value > maximum for value in normalized):
        raise ValueError(f"{field} contains an out-of-range score")
    categories = {float(category) for category in range(minimum, maximum + 1)}
    categories.update(normalized)
    ordered_categories = sorted(categories)
    counts: dict[str, int] = {}
    for category in ordered_categories:
        key = str(int(category)) if category.is_integer() else format(category, ".12g")
        counts[key] = sum(value == category for value in normalized)
    return {
        "counts": counts,
        "frequencies": {
            category: count / len(normalized) for category, count in counts.items()
        },
        "sample_count": len(normalized),
    }


def _mean_metric(
    records: Sequence[Mapping[str, Any]],
    field: str,
) -> float:
    values = [_finite_number(field, record[field]) for record in records]
    return sum(values) / len(values)


def _merge_numeric_totals(
    target: dict[str, Any],
    value: Mapping[str, Any],
    *,
    field: str,
) -> None:
    for key, raw in value.items():
        child_field = f"{field}.{key}"
        if isinstance(raw, Mapping):
            child = target.setdefault(key, {})
            if not isinstance(child, dict):
                raise ValueError(f"{child_field} has inconsistent structure")
            _merge_numeric_totals(child, raw, field=child_field)
            continue
        number = _finite_number(child_field, raw)
        if number < 0.0:
            raise ValueError(f"{child_field} must be nonnegative")
        target[key] = float(target.get(key, 0.0)) + number


def aggregate_paper_records(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    """Aggregate ordered paper evidence into one candidate-level record."""

    if not records:
        raise ValueError("at least one paper record is required")

    seen_paper_ids: set[str] = set()
    completed_metrics: list[Mapping[str, Any]] = []
    predicted: dict[str, list[int]] = {
        dimension: [] for dimension in REVIEW_SCORE_RANGES
    }
    references: dict[str, list[float]] = {
        dimension: [] for dimension in SCORE_RANGES
    }
    judge_values: dict[str, list[int]] = {
        dimension: [] for dimension in JUDGE_DIMENSIONS
    }
    signed_gaps: dict[str, list[float]] = {
        dimension: [] for dimension in SCORE_RANGES
    }
    timing_values: dict[str, list[float]] = {}
    usage_totals: dict[str, Any] = {}
    attempt_counts: dict[str, int] = {"reviewer": 0, "judge": 0}
    failure_count = 0

    for index, raw_record in enumerate(records):
        record = _mapping(f"records[{index}]", raw_record)
        paper_id = _nonempty_text(f"records[{index}].paper_id", record.get("paper_id"))
        if paper_id in seen_paper_ids:
            raise ValueError(f"duplicate paper_id: {paper_id}")
        seen_paper_ids.add(paper_id)

        timing = _mapping(f"records[{index}].timing", record.get("timing"))
        for field, raw_value in timing.items():
            value = _finite_number(f"timing.{field}", raw_value)
            if value < 0.0:
                raise ValueError(f"timing.{field} must be nonnegative")
            timing_values.setdefault(field, []).append(value)

        usage = _mapping(f"records[{index}].usage", record.get("usage"))
        _merge_numeric_totals(usage_totals, usage, field="usage")

        attempts = _mapping(f"records[{index}].attempts", record.get("attempts"))
        for role in ("reviewer", "judge"):
            count = attempts.get(role)
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise ValueError(f"attempts.{role} must be an integer >= 1")
            attempt_counts[role] += count

        if record.get("failure") is not None:
            failure_count += 1
            continue

        review = validate_generated_review(record.get("generated_review"))
        judge = validate_judge(record.get("judge"))
        metrics = _mapping(f"records[{index}].metrics", record.get("metrics"))
        human_targets_value = _mapping(
            f"records[{index}].metrics.human_targets",
            metrics.get("human_targets"),
        )
        dimension_agreement = _mapping(
            f"records[{index}].metrics.human_dimension_agreement",
            metrics.get("human_dimension_agreement"),
        )
        distribution_agreement = _mapping(
            f"records[{index}].metrics.human_distribution_agreement",
            metrics.get("human_distribution_agreement"),
        )
        _exact_keys("human_targets", human_targets_value, set(SCORE_RANGES))
        _exact_keys("human_dimension_agreement", dimension_agreement, set(SCORE_RANGES))
        _exact_keys(
            "human_distribution_agreement",
            distribution_agreement,
            set(SCORE_RANGES),
        )
        for metric_field in ("human_agreement", "judge_quality", "penalty"):
            _finite_number(metric_field, metrics.get(metric_field))

        review_scores = _mapping("generated_review.scores", review["scores"])
        judge_scores = _mapping("judge.scores", judge["scores"])
        for dimension, (minimum, maximum) in REVIEW_SCORE_RANGES.items():
            predicted[dimension].append(
                _ordinal_integer(dimension, review_scores[dimension], minimum, maximum)
            )
        for dimension, (minimum, maximum) in SCORE_RANGES.items():
            target = _finite_number(dimension, human_targets_value[dimension])
            if not minimum <= target <= maximum:
                raise ValueError(f"{dimension} human target is out of range")
            references[dimension].append(target)
            signed_gaps[dimension].append(float(review_scores[dimension]) - target)
            _finite_number(dimension, dimension_agreement[dimension])
            _finite_number(dimension, distribution_agreement[dimension])
        for dimension in JUDGE_DIMENSIONS:
            judge_values[dimension].append(
                _ordinal_integer(dimension, judge_scores[dimension], 1, 5)
            )
        completed_metrics.append(metrics)

    if not completed_metrics:
        raise ValueError("no completed paper records are available to aggregate")

    human_agreement = _mean_metric(completed_metrics, "human_agreement")
    judge_quality = _mean_metric(completed_metrics, "judge_quality")
    penalty = _mean_metric(completed_metrics, "penalty")
    composite = max(
        0.0,
        min(1.0, 0.5 * human_agreement + 0.5 * judge_quality - 0.25 * penalty),
    )
    human_dimension_agreement = {
        dimension: sum(
            _finite_number(
                dimension,
                _mapping(
                    "human_dimension_agreement",
                    metrics["human_dimension_agreement"],
                )[dimension],
            )
            for metrics in completed_metrics
        )
        / len(completed_metrics)
        for dimension in SCORE_RANGES
    }
    human_distribution_agreement = {
        dimension: sum(
            _finite_number(
                dimension,
                _mapping(
                    "human_distribution_agreement",
                    metrics["human_distribution_agreement"],
                )[dimension],
            )
            for metrics in completed_metrics
        )
        / len(completed_metrics)
        for dimension in SCORE_RANGES
    }
    timing = {
        field: _numeric_summary(field, values, nonnegative=True)
        for field, values in timing_values.items()
    }
    total_attempts = sum(attempt_counts.values())
    minimum_attempts = 2 * len(records)
    return {
        "sample_count": len(records),
        "completed_count": len(completed_metrics),
        "failure_count": failure_count,
        "human_agreement": human_agreement,
        "judge_quality": judge_quality,
        "penalty": penalty,
        "composite": composite,
        "human_dimension_agreement": human_dimension_agreement,
        "human_distribution_agreement": human_distribution_agreement,
        "judge_dimension_scores": {
            dimension: sum(values) / len(values)
            for dimension, values in judge_values.items()
        },
        "predicted_distributions": {
            dimension: ordinal_distribution(
                values,
                int(REVIEW_SCORE_RANGES[dimension][0]),
                int(REVIEW_SCORE_RANGES[dimension][1]),
                field=dimension,
            )
            for dimension, values in predicted.items()
        },
        "reference_distributions": {
            dimension: _reference_distribution(
                values,
                int(SCORE_RANGES[dimension][0]),
                int(SCORE_RANGES[dimension][1]),
                field=dimension,
            )
            for dimension, values in references.items()
        },
        "judge_distributions": {
            dimension: ordinal_distribution(values, 1, 5, field=dimension)
            for dimension, values in judge_values.items()
        },
        "signed_gaps": signed_gaps,
        "signed_gap_summary": {
            dimension: _numeric_summary(dimension, values)
            for dimension, values in signed_gaps.items()
        },
        "timing": timing,
        "usage": usage_totals,
        "attempts": {
            **attempt_counts,
            "total": total_attempts,
            "retries": max(0, total_attempts - minimum_attempts),
        },
    }
