#!/usr/bin/env python3
"""Generate the next Reviewer prompt by reflecting on aggregate experience."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from review_prompt_batch import render_experience_memory
from review_prompt_codex import (
    codex_preflight,
    run_codex_json,
    run_codex_json_with_retry,
)
from review_prompt_scoring import JUDGE_DIMENSIONS, REVIEW_SCORE_RANGES, SCORE_RANGES
from review_prompt_smoke import reserved_output_directory, sha256_file, write_json


SECTION_NAMES = (
    "summary",
    "strengths",
    "weaknesses",
    "questions",
    "limitations",
    "ethical_concerns",
    "evidence_trace",
)
TOP_LEVEL_FIELDS = frozenset(
    {
        "hypothesis",
        "memory_lessons_used",
        "review_sections",
        "change_summary",
        "risk_checks",
    }
)
REVIEW_MARKER = "## Review sections"
SCORE_MARKER = "## Score anchors"
AGGREGATE_FIELDS = (
    "candidate_id",
    "composite",
    "human_agreement",
    "judge_quality",
    "penalty",
    "human_dimension_agreement",
    "human_distribution_agreement",
    "judge_dimension_scores",
    "predicted_distributions",
    "failure_count",
    "sample_count",
)
MEMORY_PRIVACY_PATTERN = re.compile(
    r"(?:reference[\s_-]*review|human[\s_-]*review|pdf[\s_-]*path|"
    r"label[\s_-]*path|forum[\s_-]*id|source[\s_-]*(?:id|url|uri|path|"
    r"file|title|author)|/users/|\\users\\|<begin_)",
    flags=re.IGNORECASE,
)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label}: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return value


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _nonempty_string(
    value: object,
    label: str,
    *,
    minimum: int = 1,
    maximum: int = 1000,
) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ValueError(f"{label} must be a nonempty string of at least {minimum} characters")
    if len(value) > maximum:
        raise ValueError(f"{label} exceeds the {maximum}-character limit")
    if (
        "\n" in value
        or "\r" in value
        or "```" in value
        or "## " in value
        or REVIEW_MARKER in value
        or SCORE_MARKER in value
        or any(f"- `{name}`:" in value for name in SECTION_NAMES)
    ):
        raise ValueError(f"{label} contains forbidden Markdown structure")
    return value.strip()


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 12:
        raise ValueError(f"{label} must contain 1..12 strings")
    return [
        _nonempty_string(item, f"{label}[{index}]", minimum=10)
        for index, item in enumerate(value)
    ]


def validate_reflection(value: object) -> dict[str, Any]:
    """Validate exact fields and semantic constraints beyond JSON Schema."""

    if not isinstance(value, Mapping):
        raise ValueError("reflection must be one object")
    if set(value) != TOP_LEVEL_FIELDS:
        raise ValueError("reflection fields do not match the exact contract")
    sections = value.get("review_sections")
    if not isinstance(sections, Mapping) or set(sections) != set(SECTION_NAMES):
        raise ValueError("review_sections fields do not match the exact contract")
    normalized_sections = {
        name: _nonempty_string(
            sections[name],
            f"review_sections.{name}",
            minimum=160,
            maximum=4000,
        )
        for name in SECTION_NAMES
    }
    return {
        "hypothesis": _nonempty_string(value["hypothesis"], "hypothesis", minimum=20),
        "memory_lessons_used": _string_list(
            value["memory_lessons_used"], "memory_lessons_used"
        ),
        "review_sections": normalized_sections,
        "change_summary": _string_list(value["change_summary"], "change_summary"),
        "risk_checks": _string_list(value["risk_checks"], "risk_checks"),
    }


def _finite_number(
    value: object,
    label: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not minimum <= float(value) <= maximum
    ):
        raise ValueError(f"{label} must be finite and within {minimum}..{maximum}")
    return float(value)


def _exact_numeric_map(
    value: object,
    label: str,
    fields: Sequence[str],
    *,
    minimum: float,
    maximum: float,
) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise ValueError(f"{label} fields do not match the exact aggregate contract")
    return {
        field: _finite_number(
            value[field], f"{label}.{field}", minimum=minimum, maximum=maximum
        )
        for field in fields
    }


def _validated_distribution(
    value: object,
    dimension: str,
    sample_count: int,
) -> dict[str, Any]:
    label = f"predicted_distributions.{dimension}"
    if not isinstance(value, Mapping) or set(value) != {
        "counts",
        "frequencies",
        "sample_count",
    }:
        raise ValueError(f"{label} fields do not match the exact aggregate contract")
    if value["sample_count"] != sample_count:
        raise ValueError(f"{label}.sample_count does not match the aggregate")
    minimum, maximum = REVIEW_SCORE_RANGES[dimension]
    score_keys = {
        str(score) for score in range(int(minimum), int(maximum) + 1)
    }
    counts = value["counts"]
    frequencies = value["frequencies"]
    if not isinstance(counts, Mapping) or set(counts) != score_keys:
        raise ValueError(f"{label}.counts fields are invalid")
    if not isinstance(frequencies, Mapping) or set(frequencies) != score_keys:
        raise ValueError(f"{label}.frequencies fields are invalid")
    normalized_counts: dict[str, int] = {}
    normalized_frequencies: dict[str, float] = {}
    for score in sorted(score_keys, key=int):
        count = counts[score]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"{label}.counts.{score} must be a nonnegative integer")
        frequency = _finite_number(
            frequencies[score],
            f"{label}.frequencies.{score}",
            minimum=0.0,
            maximum=1.0,
        )
        if not math.isclose(frequency, count / sample_count, abs_tol=1e-9):
            raise ValueError(f"{label} count/frequency arithmetic is invalid")
        normalized_counts[score] = count
        normalized_frequencies[score] = frequency
    if sum(normalized_counts.values()) != sample_count:
        raise ValueError(f"{label}.counts do not sum to sample_count")
    return {
        "counts": normalized_counts,
        "frequencies": normalized_frequencies,
        "sample_count": sample_count,
    }


def reflection_aggregate_snapshot(aggregate: Mapping[str, Any]) -> dict[str, Any]:
    """Project aggregate evidence onto a no-paper, no-reference allowlist."""

    missing = [field for field in AGGREGATE_FIELDS if field not in aggregate]
    if missing:
        raise ValueError("parent aggregate is missing reflection fields: " + ", ".join(missing))
    candidate_id = aggregate["candidate_id"]
    if not isinstance(candidate_id, str) or re.fullmatch(
        r"p(?:0|[1-9][0-9]*)", candidate_id
    ) is None:
        raise ValueError("parent aggregate candidate_id is invalid")
    sample_count = aggregate["sample_count"]
    failure_count = aggregate["failure_count"]
    if isinstance(sample_count, bool) or sample_count != 5:
        raise ValueError("parent aggregate sample_count must be exactly 5")
    if isinstance(failure_count, bool) or not isinstance(failure_count, int):
        raise ValueError("parent aggregate failure_count must be an integer")
    if not 0 <= failure_count <= sample_count:
        raise ValueError("parent aggregate failure_count is out of range")
    snapshot: dict[str, Any] = {
        "candidate_id": candidate_id,
        "composite": _finite_number(
            aggregate["composite"], "composite", minimum=0.0, maximum=1.0
        ),
        "human_agreement": _finite_number(
            aggregate["human_agreement"],
            "human_agreement",
            minimum=0.0,
            maximum=1.0,
        ),
        "judge_quality": _finite_number(
            aggregate["judge_quality"],
            "judge_quality",
            minimum=0.0,
            maximum=1.0,
        ),
        "penalty": _finite_number(
            aggregate["penalty"], "penalty", minimum=0.0, maximum=1.0
        ),
        "human_dimension_agreement": _exact_numeric_map(
            aggregate["human_dimension_agreement"],
            "human_dimension_agreement",
            tuple(SCORE_RANGES),
            minimum=0.0,
            maximum=1.0,
        ),
        "human_distribution_agreement": _exact_numeric_map(
            aggregate["human_distribution_agreement"],
            "human_distribution_agreement",
            tuple(SCORE_RANGES),
            minimum=0.0,
            maximum=1.0,
        ),
        "judge_dimension_scores": _exact_numeric_map(
            aggregate["judge_dimension_scores"],
            "judge_dimension_scores",
            JUDGE_DIMENSIONS,
            minimum=1.0,
            maximum=5.0,
        ),
        "failure_count": failure_count,
        "sample_count": sample_count,
    }
    predicted_distributions = aggregate["predicted_distributions"]
    if not isinstance(predicted_distributions, Mapping) or set(
        predicted_distributions
    ) != set(REVIEW_SCORE_RANGES):
        raise ValueError(
            "predicted_distributions fields do not match the exact aggregate contract"
        )
    snapshot["predicted_distributions"] = {
        dimension: _validated_distribution(
            predicted_distributions[dimension], dimension, sample_count
        )
        for dimension in REVIEW_SCORE_RANGES
    }
    signed_gap_summary = aggregate.get("signed_gap_summary")
    if not isinstance(signed_gap_summary, Mapping) or set(
        signed_gap_summary
    ) != set(SCORE_RANGES):
        raise ValueError("parent aggregate signed_gap_summary fields are invalid")
    mean_signed_prediction_gap: dict[str, float] = {}
    for dimension, summary in signed_gap_summary.items():
        if not isinstance(dimension, str) or not isinstance(summary, Mapping):
            raise ValueError("signed_gap_summary entries must be objects")
        mean = summary.get("mean")
        if isinstance(mean, bool) or not isinstance(mean, (int, float)):
            raise ValueError("signed_gap_summary mean must be numeric")
        mean_signed_prediction_gap[dimension] = float(mean)
    snapshot["mean_signed_prediction_gap"] = mean_signed_prediction_gap
    return snapshot


def validate_memory_text(memory: str) -> str:
    if not isinstance(memory, str) or not memory.strip():
        raise ValueError("experience memory must be nonempty")
    if len(memory) > 200_000 or "\x00" in memory:
        raise ValueError("memory privacy validation failed: invalid size or content")
    if MEMORY_PRIVACY_PATTERN.search(memory):
        raise ValueError("memory privacy validation failed: raw artifact marker")
    return memory


def _campaign_memory(campaign_path: Path) -> str:
    campaign = _load_json(campaign_path, "campaign state")
    decisions = campaign.get("candidates")
    if not isinstance(decisions, list) or not decisions:
        raise ValueError("campaign state has no candidate decisions")
    if campaign.get("candidate_count") != len(decisions):
        raise ValueError("campaign candidate_count does not match decisions")
    campaign_root = campaign_path.parent
    records: list[dict[str, Any]] = []
    specs: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        if not isinstance(decision, Mapping):
            raise ValueError("campaign candidate decision must be an object")
        candidate_id = decision.get("candidate_id")
        if not isinstance(candidate_id, str) or re.fullmatch(
            r"p(?:0|[1-9][0-9]*)", candidate_id
        ) is None:
            raise ValueError("campaign candidate decision has invalid candidate_id")
        candidate_root = campaign_root / "candidates" / candidate_id
        records.append(
            _load_json(candidate_root / "candidate-record.json", "candidate record")
        )
        spec_path = candidate_root / "candidate-spec.json"
        if spec_path.is_file():
            specs[candidate_id] = _load_json(spec_path, "candidate spec")
    return validate_memory_text(render_experience_memory(records, decisions, specs))


def reflection_request(
    meta_prompt: str,
    parent_prompt: str,
    memory: str,
    aggregate_snapshot: Mapping[str, Any],
) -> str:
    aggregate_json = json.dumps(
        dict(aggregate_snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        meta_prompt.strip()
        + "\n\n<BEGIN_CURRENT_KEPT_PARENT_PROMPT>\n"
        + parent_prompt.strip()
        + "\n<END_CURRENT_KEPT_PARENT_PROMPT>\n\n"
        + "<BEGIN_UNTRUSTED_AGGREGATE_EXPERIENCE_MEMORY>\n"
        + memory.strip()
        + "\n<END_UNTRUSTED_AGGREGATE_EXPERIENCE_MEMORY>\n\n"
        + "<BEGIN_ALLOWLISTED_AGGREGATE_METRICS>\n"
        + aggregate_json
        + "\n<END_ALLOWLISTED_AGGREGATE_METRICS>\n\n"
        + "The delimited blocks have ended. Return only schema-valid JSON.\n"
    )


def _split_parent_prompt(parent_prompt: str) -> tuple[str, str, str]:
    if parent_prompt.count(REVIEW_MARKER) != 1:
        raise ValueError("parent prompt must contain exactly one Review sections heading")
    if parent_prompt.count(SCORE_MARKER) != 1:
        raise ValueError("parent prompt must contain exactly one Score anchors heading")
    prefix, remainder = parent_prompt.split(REVIEW_MARKER, 1)
    section_block, suffix = remainder.split(SCORE_MARKER, 1)
    return prefix, section_block, suffix


def _existing_sections(section_block: str) -> dict[str, str]:
    label = "|".join(re.escape(name) for name in SECTION_NAMES)
    pattern = re.compile(
        rf"^- `(?P<name>{label})`: (?P<body>.*?)(?=^- `(?:{label})`:\s|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    sections: dict[str, str] = {}
    for match in pattern.finditer(section_block.strip()):
        name = match.group("name")
        body = re.sub(r"\n  ", "\n", match.group("body")).strip()
        if name in sections:
            raise ValueError(f"parent prompt repeats review section: {name}")
        sections[name] = body
    if set(sections) != set(SECTION_NAMES):
        raise ValueError("parent prompt does not contain the exact seven review sections")
    return sections


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def compile_candidate_prompt(parent_prompt: str, reflection: object) -> str:
    """Replace only the bounded Review sections block in the kept parent."""

    normalized = validate_reflection(reflection)
    prefix, parent_block, suffix = _split_parent_prompt(parent_prompt)
    existing = _existing_sections(parent_block)
    revised = normalized["review_sections"]
    for name in SECTION_NAMES:
        before = _normalized_text(existing[name])
        after = _normalized_text(revised[name])
        if before == after:
            raise ValueError(f"review section {name} was not revised")
        if len(after) < len(before) + 40:
            raise ValueError(f"review section {name} is not materially more detailed")
    rendered = "\n".join(f"- `{name}`: {revised[name]}" for name in SECTION_NAMES)
    candidate = (
        prefix
        + REVIEW_MARKER
        + "\n\n"
        + rendered
        + "\n\n"
        + SCORE_MARKER
        + suffix
    )
    if candidate.count(REVIEW_MARKER) != 1 or candidate.count(SCORE_MARKER) != 1:
        raise ValueError("compiled prompt contains duplicate bounded headings")
    for name in SECTION_NAMES:
        if candidate.count(f"- `{name}`:") != 1:
            raise ValueError(f"compiled prompt contains duplicate review field: {name}")
    return candidate


def _verify_campaign_parent(campaign_path: Path, parent_candidate_id: str) -> None:
    campaign = _load_json(campaign_path, "campaign state")
    if campaign.get("current_parent_candidate_id") != parent_candidate_id:
        raise ValueError("requested parent is not the campaign's current kept parent")


@contextmanager
def _exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ValueError(f"reflection target is already reserved: {path}") from error
    os.close(descriptor)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _atomic_write_text_no_clobber(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            destination.write(value)
            destination.flush()
            os.fsync(destination.fileno())
        os.link(temporary, path)
    except FileExistsError as error:
        raise ValueError(
            "output candidate prompt already exists; refusing to overwrite"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)


def generate_reflected_candidate(
    *,
    meta_prompt_path: Path,
    schema_path: Path,
    parent_prompt_path: Path,
    memory_path: Path,
    parent_aggregate_path: Path,
    output_dir: Path,
    output_prompt_path: Path,
    candidate_id: str,
    parent_candidate_id: str,
    model: str,
    campaign_id: str = "unknown",
    campaign_path: Path | None = None,
    codex_bin: str = "codex",
    timeout_seconds: int = 900,
    max_attempts: int = 2,
    invoke: Callable[[], tuple[dict[str, Any], dict[str, int | float]]] | None = None,
) -> dict[str, Any]:
    if re.fullmatch(r"p(?:0|[1-9][0-9]*)", candidate_id) is None:
        raise ValueError("candidate_id must be p0, p1, p2, ...")
    if re.fullmatch(r"p(?:0|[1-9][0-9]*)", parent_candidate_id) is None:
        raise ValueError("parent_candidate_id must be p0, p1, p2, ...")
    lock_path = output_prompt_path.with_name(output_prompt_path.name + ".lock")
    with _exclusive_lock(lock_path):
        if output_prompt_path.exists():
            raise ValueError(
                "output candidate prompt already exists; refusing to overwrite"
            )
        if output_dir.exists():
            raise ValueError(
                "output reflection directory already exists; refusing to overwrite"
            )
        if campaign_path is not None:
            _verify_campaign_parent(campaign_path, parent_candidate_id)
            expected_memory_path = campaign_path.parent / "experience-memory.md"
            if memory_path.resolve() != expected_memory_path.resolve():
                raise ValueError("experience memory path is not bound to the campaign")

        meta_prompt = meta_prompt_path.read_text(encoding="utf-8")
        parent_prompt = parent_prompt_path.read_text(encoding="utf-8")
        memory = validate_memory_text(memory_path.read_text(encoding="utf-8"))
        if campaign_path is not None and memory != _campaign_memory(campaign_path):
            raise ValueError("experience memory does not match canonical campaign state")
        aggregate = _load_json(parent_aggregate_path, "parent aggregate")
        if aggregate.get("candidate_id") != parent_candidate_id:
            raise ValueError(
                "parent aggregate candidate_id does not match requested parent"
            )
        parent_prompt_sha256 = sha256_file(parent_prompt_path)
        if aggregate.get("prompt_sha256") != parent_prompt_sha256:
            raise ValueError("parent prompt hash does not match parent aggregate")
        aggregate_snapshot = reflection_aggregate_snapshot(aggregate)
        request = reflection_request(
            meta_prompt, parent_prompt, memory, aggregate_snapshot
        )
        input_hashes = {
            "meta_prompt_sha256": sha256_file(meta_prompt_path),
            "reflection_schema_sha256": sha256_file(schema_path),
            "parent_prompt_sha256": parent_prompt_sha256,
            "experience_memory_sha256": sha256_file(memory_path),
            "parent_aggregate_sha256": sha256_file(parent_aggregate_path),
            "campaign_state_sha256": sha256_file(campaign_path)
            if campaign_path is not None
            else None,
        }

        cli_version = "injected-runner"
        auth_mode = "injected"
        if invoke is None:
            cli_version, auth_mode = codex_preflight(codex_bin)

            def invoke_codex():
                with tempfile.TemporaryDirectory(
                    prefix="review-prompt-reflect-"
                ) as directory:
                    return run_codex_json(
                        codex_bin=codex_bin,
                        model=model,
                        prompt=request,
                        schema=schema_path,
                        workdir=Path(directory),
                        timeout_seconds=timeout_seconds,
                    )

            active_invoke = invoke_codex
        else:
            active_invoke = invoke

        reflection, usage, attempts = run_codex_json_with_retry(
            invoke=active_invoke,
            validator=validate_reflection,
            max_attempts=max_attempts,
        )
        normalized = validate_reflection(reflection)
        candidate_prompt = compile_candidate_prompt(parent_prompt, normalized)
        candidate_prompt_sha256 = "sha256:" + hashlib.sha256(
            candidate_prompt.encode("utf-8")
        ).hexdigest()

        current_hashes = {
            "meta_prompt_sha256": sha256_file(meta_prompt_path),
            "reflection_schema_sha256": sha256_file(schema_path),
            "parent_prompt_sha256": sha256_file(parent_prompt_path),
            "experience_memory_sha256": sha256_file(memory_path),
            "parent_aggregate_sha256": sha256_file(parent_aggregate_path),
            "campaign_state_sha256": sha256_file(campaign_path)
            if campaign_path is not None
            else None,
        }
        if current_hashes != input_hashes:
            raise ValueError("reflection inputs changed during model inference")
        if campaign_path is not None:
            _verify_campaign_parent(campaign_path, parent_candidate_id)
            if memory_path.read_text(encoding="utf-8") != _campaign_memory(
                campaign_path
            ):
                raise ValueError(
                    "experience memory changed from canonical campaign state"
                )
        if output_prompt_path.exists() or output_dir.exists():
            raise ValueError("reflection target appeared during model inference")

        provenance = {
            "schema_version": "review-prompt-reflection-v1",
            "campaign_id": campaign_id,
            "candidate_id": candidate_id,
            "parent_candidate_id": parent_candidate_id,
            "model": model,
            "codex_cli_version": cli_version,
            "auth_mode": auth_mode,
            **input_hashes,
            "aggregate_snapshot_sha256": _canonical_sha256(aggregate_snapshot),
            "reflection_output_sha256": _canonical_sha256(normalized),
            "candidate_prompt_sha256": candidate_prompt_sha256,
            "usage": usage,
            "attempts": attempts,
        }
        spec = {
            "candidate_id": candidate_id,
            "parent_candidate_id": parent_candidate_id,
            "hypothesis": normalized["hypothesis"],
            "change_summary": normalized["change_summary"],
        }
        with reserved_output_directory(output_dir):
            write_json(output_dir / "prompt-reflection.json", normalized)
            write_json(
                output_dir / "prompt-reflection-provenance.json", provenance
            )
            write_json(output_dir / "prompt-reflection-attempts.json", attempts)
            write_json(output_dir / "candidate-spec.json", spec)
            (output_dir / "candidate-prompt.md").write_text(
                candidate_prompt, encoding="utf-8"
            )
            _atomic_write_text_no_clobber(output_prompt_path, candidate_prompt)
        return provenance


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meta-prompt", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--parent-prompt", type=Path, required=True)
    parser.add_argument("--memory", type=Path, required=True)
    parser.add_argument("--parent-aggregate", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--parent-candidate-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-prompt", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--max-attempts", type=int, choices=(1, 2), default=2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    value = generate_reflected_candidate(
        meta_prompt_path=args.meta_prompt,
        schema_path=args.schema,
        parent_prompt_path=args.parent_prompt,
        memory_path=args.memory,
        parent_aggregate_path=args.parent_aggregate,
        output_dir=args.output_dir,
        output_prompt_path=args.output_prompt,
        candidate_id=args.candidate_id,
        parent_candidate_id=args.parent_candidate_id,
        model=args.model,
        campaign_id=args.campaign_id,
        campaign_path=args.campaign,
        codex_bin=args.codex_bin,
        timeout_seconds=args.timeout_seconds,
        max_attempts=args.max_attempts,
    )
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
