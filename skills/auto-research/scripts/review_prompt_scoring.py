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


def _finite_number(field: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


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
        score = _finite_number(dimension, scores[dimension])
        if not minimum <= score <= maximum:
            raise ValueError(
                f"{dimension} score must be within {minimum:g}..{maximum:g}"
            )

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
        score = _finite_number(dimension, scores[dimension])
        if not 1.0 <= score <= 5.0:
            raise ValueError(f"{dimension} judge score must be within 1..5")
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
