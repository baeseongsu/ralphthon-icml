#!/usr/bin/env python3
"""Validate and score one ICML review-prompt optimization candidate."""

from __future__ import annotations

import math
from typing import Mapping, Sequence


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


def _finite_number(field: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


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
        predicted = _finite_number(dimension, predicted_scores.get(dimension))
        if not minimum <= predicted <= maximum:
            raise ValueError(f"{dimension} predicted score is out of range")
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
        value = _finite_number(dimension, judge_scores.get(dimension))
        if not 1.0 <= value <= 5.0:
            raise ValueError(f"{dimension} judge score must be within 1..5")
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
