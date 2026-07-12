#!/usr/bin/env python3
"""Run one deterministic ICML review-prompt optimization smoke candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from review_prompt_scoring import score_candidate
from review_prompt_tracking import append_record, record_wandb_offline


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"input file does not exist: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def render_reflection(candidate_id: str, metrics: Mapping[str, Any]) -> str:
    gaps = metrics["human_dimension_agreement"]
    if not isinstance(gaps, Mapping) or not gaps:
        raise ValueError("human_dimension_agreement must be nonempty")
    weakest = min(gaps, key=lambda dimension: float(gaps[dimension]))
    return (
        f"# Reflection — {candidate_id}\n\n"
        f"- Composite: {float(metrics['composite']):.6f}\n"
        f"- Human agreement: {float(metrics['human_agreement']):.6f}\n"
        f"- Judge quality: {float(metrics['judge_quality']):.6f}\n"
        f"- Penalty: {float(metrics['penalty']):.6f}\n"
        f"- Weakest agreement dimension: {weakest}\n"
    )


def load_fixture(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid smoke fixture: {path}") from error
    if not isinstance(value, dict):
        raise ValueError("smoke fixture must contain one JSON object")
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    fixture = load_fixture(args.fixture)
    prompt_sha256 = sha256_file(args.prompt)
    fixture_sha256 = sha256_file(args.fixture)
    generated_review = fixture["generated_review"]
    judge = fixture["judge"]
    metrics = score_candidate(
        human_scores=fixture["human_scores"],
        predicted_scores=generated_review["scores"],
        judge_scores=judge["scores"],
        penalties=fixture["penalties"],
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "generated-review.json", generated_review)
    write_json(args.output_dir / "judge.json", judge)
    write_json(args.output_dir / "metrics.json", metrics)
    (args.output_dir / "reflection.md").write_text(
        render_reflection(args.candidate_id, metrics),
        encoding="utf-8",
    )

    record: dict[str, Any] = {
        "campaign_id": args.campaign_id,
        "candidate_id": args.candidate_id,
        "paper_id": fixture["paper_id"],
        "prompt_sha256": prompt_sha256,
        "fixture_sha256": fixture_sha256,
        **metrics,
    }
    if args.wandb_mode == "offline":
        try:
            import wandb
        except ImportError as error:
            raise RuntimeError(
                "W&B offline mode requires the wandb SDK; run with "
                "`uv run --with wandb`"
            ) from error
        run_id, run_directory = record_wandb_offline(
            wandb_module=wandb,
            directory=args.output_dir / ".wandb-offline",
            entity=args.wandb_entity,
            project=args.wandb_project,
            campaign_id=args.campaign_id,
            candidate_id=args.candidate_id,
            config={
                "prompt_sha256": prompt_sha256,
                "fixture_sha256": fixture_sha256,
                "objective_human_weight": 0.5,
                "objective_judge_weight": 0.5,
            },
            metrics={
                "objective/composite": metrics["composite"],
                "objective/human_agreement": metrics["human_agreement"],
                "objective/judge_quality": metrics["judge_quality"],
                "objective/penalty": metrics["penalty"],
            },
            paper_id=fixture["paper_id"],
            generated_review=generated_review,
            judge=judge,
        )
        record["wandb_run_id"] = run_id
        record["wandb_run_directory"] = run_directory

    append_record(args.output_dir / "experiments.jsonl", record)
    return record


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one credential-free review-prompt smoke candidate."
    )
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument(
        "--wandb-mode",
        choices=("disabled", "offline"),
        default="disabled",
    )
    parser.add_argument("--wandb-entity", default="local-smoke")
    parser.add_argument("--wandb-project", default="review-prompt-smoke")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    record = run(args)
    print(
        json.dumps(
            {
                "candidate_id": record["candidate_id"],
                "composite": record["composite"],
                "output_dir": str(args.output_dir),
                "generated_review": str(
                    args.output_dir / "generated-review.json"
                ),
                "judge": str(args.output_dir / "judge.json"),
                "metrics": str(args.output_dir / "metrics.json"),
                "reflection": str(args.output_dir / "reflection.md"),
                "ledger": str(args.output_dir / "experiments.jsonl"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
