#!/usr/bin/env python3
"""Run the self-contained Reviewer Agent on one local PDF."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from runtime import (
    canonical_json_sha256,
    codex_preflight,
    extract_pdf_text,
    reserved_output_directory,
    reviewer_request,
    run_codex_json,
    run_codex_json_with_retry,
    sha256_file,
    validate_generated_review,
    write_json,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    SKILL_ROOT / "assets" / "deploy-manifest.json"
)
MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "status",
        "model",
        "campaign_id",
        "selection_scope",
        "prompt_path",
        "prompt_sha256",
        "output_schema_path",
        "output_schema_sha256",
        "warning",
    }
)
SCORE_ORDER = (
    "soundness",
    "presentation",
    "significance",
    "originality",
    "overall_recommendation",
    "confidence",
)


@dataclass(frozen=True)
class Deployment:
    candidate_id: str
    status: str
    model: str
    campaign_id: str
    selection_scope: str
    prompt_path: Path
    prompt_sha256: str
    schema_path: Path
    schema_sha256: str
    manifest_path: Path
    manifest_sha256: str


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label}: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return value


def _repository_file(root: Path, raw_path: object, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path or Path(raw_path).is_absolute():
        raise ValueError(f"{label} must be a repository-relative path")
    resolved_root = root.resolve()
    resolved = (resolved_root / raw_path).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"{label} must stay inside the repository")
    if not resolved.is_file():
        raise ValueError(f"{label} does not exist: {raw_path}")
    return resolved


def _expected_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} must be a lowercase sha256 digest")
    return value


def load_deployment(root: Path, manifest_path: Path) -> Deployment:
    """Load and hash-verify the only permitted Reviewer deployment."""

    resolved_root = root.resolve()
    resolved_manifest = manifest_path.resolve()
    if not resolved_manifest.is_relative_to(resolved_root):
        raise ValueError("deployment manifest must be inside the repository")
    manifest = _load_json(resolved_manifest, "deployment manifest")
    if set(manifest) != MANIFEST_FIELDS:
        raise ValueError("deployment manifest fields do not match the exact contract")
    if manifest.get("schema_version") != "reviewer-agent-deploy-v1":
        raise ValueError("unsupported deployment manifest schema_version")
    if manifest.get("candidate_id") != "p2" or manifest.get("status") != "keep":
        raise ValueError("deployment default must be the kept p2 candidate")
    model = manifest.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("deployment model must be nonempty")
    campaign_id = manifest.get("campaign_id")
    selection_scope = manifest.get("selection_scope")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise ValueError("deployment campaign_id must be nonempty")
    if not isinstance(selection_scope, str) or not selection_scope:
        raise ValueError("deployment selection_scope must be nonempty")

    prompt_path = _repository_file(
        resolved_root, manifest.get("prompt_path"), "deployment prompt_path"
    )
    schema_path = _repository_file(
        resolved_root,
        manifest.get("output_schema_path"),
        "deployment output_schema_path",
    )
    prompt_sha256 = _expected_sha256(
        manifest.get("prompt_sha256"), "deployment prompt_sha256"
    )
    schema_sha256 = _expected_sha256(
        manifest.get("output_schema_sha256"), "deployment output_schema_sha256"
    )
    if sha256_file(prompt_path) != prompt_sha256:
        raise ValueError("deployment prompt hash mismatch")
    if sha256_file(schema_path) != schema_sha256:
        raise ValueError("deployment output schema hash mismatch")
    _load_json(schema_path, "deployment output schema")

    return Deployment(
        candidate_id="p2",
        status="keep",
        model=model,
        campaign_id=campaign_id,
        selection_scope=selection_scope,
        prompt_path=prompt_path,
        prompt_sha256=prompt_sha256,
        schema_path=schema_path,
        schema_sha256=schema_sha256,
        manifest_path=resolved_manifest,
        manifest_sha256=sha256_file(resolved_manifest),
    )


def deployment_request(candidate_prompt: str, paper_text: str) -> str:
    """Build the same label-blind request used by the evaluated Reviewer."""

    return reviewer_request(candidate_prompt, paper_text)


def render_review_markdown(review: Mapping[str, Any]) -> str:
    """Render the validated JSON without adding new review claims."""

    validate_generated_review(review)
    lines = ["# ICML Review", "", "## Summary", "", str(review["summary"]), ""]
    for title, field in (
        ("Strengths", "strengths"),
        ("Weaknesses", "weaknesses"),
        ("Questions", "questions"),
    ):
        lines.extend([f"## {title}", ""])
        values = review[field]
        assert isinstance(values, list)
        lines.extend(f"- {value}" for value in values)
        lines.append("")
    lines.extend(
        [
            "## Limitations",
            "",
            str(review["limitations"]),
            "",
            "## Ethical Concerns",
            "",
            str(review["ethical_concerns"]),
            "",
            "## Evidence Trace",
            "",
        ]
    )
    evidence_trace = review["evidence_trace"]
    assert isinstance(evidence_trace, list)
    lines.extend(f"- {value}" for value in evidence_trace)
    lines.extend(["", "## Scores", "", "| Dimension | Score |", "| --- | ---: |"])
    scores = review["scores"]
    rationales = review["score_rationales"]
    assert isinstance(scores, Mapping) and isinstance(rationales, Mapping)
    for dimension in SCORE_ORDER:
        lines.append(f"| `{dimension}` | {scores[dimension]} |")
    lines.extend(["", "## Score Rationales", ""])
    for dimension in SCORE_ORDER:
        lines.extend(
            [
                f"### `{dimension}` — {scores[dimension]}",
                "",
                str(rationales[dimension]),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


ReviewerInvoke = Callable[
    [str, Path, str], tuple[dict[str, Any], dict[str, Any]]
]


def _validate_pdf(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"paper PDF does not exist: {path}")
    with path.open("rb") as source:
        if source.read(5) != b"%PDF-":
            raise ValueError("paper input is not a PDF file")


def run(
    args: argparse.Namespace,
    *,
    reviewer_invoke: ReviewerInvoke | None = None,
    preflight: Callable[[str], tuple[str, str]] = codex_preflight,
    extract: Callable[[Path, str], str] = extract_pdf_text,
) -> dict[str, Any]:
    """Run one P2 Reviewer call and write atomic local deployment evidence."""

    deployment = load_deployment(SKILL_ROOT, DEFAULT_MANIFEST)
    requested_model = getattr(args, "model", None)
    if requested_model is not None and requested_model != deployment.model:
        raise ValueError(
            f"model must match the pinned deployment model: {deployment.model}"
        )
    if args.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    _validate_pdf(args.paper_pdf)
    paper_text = extract(args.paper_pdf, args.pdftotext_bin)
    cli_version, auth_mode = preflight(args.codex_bin)
    prompt_text = deployment.prompt_path.read_text(encoding="utf-8")
    request = deployment_request(prompt_text, paper_text)

    with reserved_output_directory(args.output_dir):

        def invoke_reviewer() -> tuple[dict[str, Any], dict[str, int | float]]:
            if reviewer_invoke is not None:
                return reviewer_invoke(request, deployment.schema_path, deployment.model)
            with tempfile.TemporaryDirectory(
                prefix="review-prompt-deploy-"
            ) as directory:
                return run_codex_json(
                    codex_bin=args.codex_bin,
                    model=deployment.model,
                    prompt=request,
                    schema=deployment.schema_path,
                    workdir=Path(directory),
                    timeout_seconds=args.timeout_seconds,
                )

        review, reviewer_usage, reviewer_attempts = run_codex_json_with_retry(
            invoke=invoke_reviewer,
            validator=validate_generated_review,
            max_attempts=args.max_attempts,
        )
        validate_generated_review(review)
        review_sha256 = canonical_json_sha256(review)
        provenance = {
            "schema_version": "review-prompt-deployment-run-v1",
            "candidate_id": deployment.candidate_id,
            "candidate_status": deployment.status,
            "campaign_id": deployment.campaign_id,
            "selection_scope": deployment.selection_scope,
            "model": deployment.model,
            "auth_mode": auth_mode,
            "codex_cli_version": cli_version,
            "pdf_sha256": sha256_file(args.paper_pdf),
            "deployment_manifest_sha256": deployment.manifest_sha256,
            "prompt_sha256": deployment.prompt_sha256,
            "output_schema_sha256": deployment.schema_sha256,
            "review_sha256": review_sha256,
            "reviewer_usage": reviewer_usage,
            "reviewer_attempts": reviewer_attempts,
        }
        write_json(args.output_dir / "review.json", review)
        (args.output_dir / "review.md").write_text(
            render_review_markdown(review), encoding="utf-8"
        )
        write_json(args.output_dir / "provenance.json", provenance)
    return {
        "candidate_id": deployment.candidate_id,
        "model": deployment.model,
        "output_dir": str(args.output_dir),
        "review_sha256": review_sha256,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-pdf", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--model",
        help="Optional assertion; must equal the model pinned by deploy-manifest.json",
    )
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--pdftotext-bin", default="pdftotext")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--max-attempts", type=int, choices=(1, 2), default=2)
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    result = run(parse_args(argv))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
