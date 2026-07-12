#!/usr/bin/env python3
"""Persist local evidence and mirror allowlisted review data to W&B offline."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, TextIO

from review_prompt_scoring import (
    PAPER_ID_PATTERN,
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
    }
)
ALLOWED_WANDB_METRIC_FIELDS = frozenset(
    {
        "objective/composite",
        "objective/human_agreement",
        "objective/judge_quality",
        "objective/penalty",
    }
)


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
