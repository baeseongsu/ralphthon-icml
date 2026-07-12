#!/usr/bin/env python3
"""Run a bounded sequence of versioned review-prompt candidates."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from review_prompt_smoke import write_json

MAX_COMPONENT_REGRESSION = 0.02
MAX_DIMENSION_REGRESSION = 0.05


def candidate_decisions(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        raise ValueError("at least one candidate record is required")
    decisions: list[dict[str, Any]] = []
    best_id = str(records[0]["candidate_id"])
    best_score = float(records[0]["composite"])
    best_record = records[0]
    decisions.append(
        {
            "candidate_id": best_id,
            "parent_candidate_id": "none",
            "composite": best_score,
            "delta": 0.0,
            "decision": "baseline",
            "rejection_reason": "none",
        }
    )
    for record in records[1:]:
        candidate_id = str(record["candidate_id"])
        score = float(record["composite"])
        delta = score - best_score
        human_regression = (
            float(record["human_agreement"])
            < float(best_record["human_agreement"]) - MAX_COMPONENT_REGRESSION
        )
        judge_regression = (
            float(record["judge_quality"])
            < float(best_record["judge_quality"]) - MAX_COMPONENT_REGRESSION
        )
        candidate_dimensions = record["human_dimension_agreement"]
        best_dimensions = best_record["human_dimension_agreement"]
        dimension_regression = any(
            float(candidate_dimensions[dimension])
            < float(best_dimensions[dimension]) - MAX_DIMENSION_REGRESSION
            for dimension in best_dimensions
        )
        if delta <= 0:
            decision, rejection_reason = "discard", "no_composite_gain"
        elif human_regression or judge_regression:
            decision, rejection_reason = "discard", "component_regression"
        elif dimension_regression:
            decision, rejection_reason = "discard", "dimension_regression"
        else:
            decision, rejection_reason = "keep", "none"
        decisions.append(
            {
                "candidate_id": candidate_id,
                "parent_candidate_id": best_id,
                "composite": score,
                "delta": delta,
                "decision": decision,
                "rejection_reason": rejection_reason,
            }
        )
        if decision == "keep":
            best_id, best_score = candidate_id, score
            best_record = record
    return decisions


def next_parent_id(records: Sequence[Mapping[str, Any]]) -> str:
    decisions = candidate_decisions(records)
    for decision in reversed(decisions):
        if decision["decision"] in {"baseline", "keep"}:
            return str(decision["candidate_id"])
    raise ValueError("campaign has no eligible parent")


def parse_candidate(value: str) -> tuple[str, Path]:
    candidate_id, separator, prompt = value.partition("=")
    if not separator or not candidate_id.strip() or not prompt.strip():
        raise argparse.ArgumentTypeError("candidate must be ID=/path/to/prompt.md")
    return candidate_id.strip(), Path(prompt)


def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.output_root.exists():
        raise ValueError(f"output root already exists: {args.output_root}")
    args.output_root.mkdir(parents=True)
    records: list[dict[str, Any]] = []
    parent_id = "none"
    for candidate_id, prompt in args.candidate:
        output = args.output_root / candidate_id
        command = [
            sys.executable, str(args.runner),
            "--paper-pdf", str(args.paper_pdf),
            "--human-review-json", str(args.human_review_json),
            "--reviewer-prompt", str(prompt),
            "--judge-prompt", str(args.judge_prompt),
            "--review-schema", str(args.review_schema),
            "--judge-schema", str(args.judge_schema),
            "--output-dir", str(output),
            "--campaign-id", args.campaign_id,
            "--candidate-id", candidate_id,
            "--parent-candidate-id", parent_id,
            "--reviewer-model", args.reviewer_model,
            "--judge-model", args.judge_model,
            "--codex-bin", args.codex_bin,
            "--pdftotext-bin", args.pdftotext_bin,
            "--pdfinfo-bin", args.pdfinfo_bin,
            "--timeout-seconds", str(args.timeout_seconds),
            "--wandb-mode", args.wandb_mode,
            "--wandb-entity", args.wandb_entity,
            "--wandb-project", args.wandb_project,
        ]
        completed = subprocess.run(command, check=False, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"candidate failed: {candidate_id}")
        shutil.copy2(prompt, output / "candidate-prompt.md")
        metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
        score = float(metrics["composite"])
        records.append({"candidate_id": candidate_id, **metrics})
        parent_id = next_parent_id(records)
    decisions = candidate_decisions(records)
    write_json(args.output_root / "campaign.json", {"campaign_id": args.campaign_id, "candidates": decisions})
    return decisions


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a bounded review-prompt optimization loop.")
    parser.add_argument("--paper-pdf", type=Path, required=True)
    parser.add_argument("--human-review-json", type=Path, required=True)
    parser.add_argument("--candidate", type=parse_candidate, action="append", required=True)
    parser.add_argument("--judge-prompt", type=Path, required=True)
    parser.add_argument("--review-schema", type=Path, required=True)
    parser.add_argument("--judge-schema", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--reviewer-model", required=True)
    parser.add_argument("--judge-model", required=True)
    parser.add_argument("--runner", type=Path, default=Path(__file__).with_name("review_prompt_codex.py"))
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--pdftotext-bin", default="pdftotext")
    parser.add_argument("--pdfinfo-bin", default="pdfinfo")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--wandb-mode", choices=("disabled", "offline"), default="disabled")
    parser.add_argument("--wandb-entity", default="local-smoke")
    parser.add_argument("--wandb-project", default="review-prompt-smoke")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    decisions = run(parse_args(argv))
    print(json.dumps(decisions, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
