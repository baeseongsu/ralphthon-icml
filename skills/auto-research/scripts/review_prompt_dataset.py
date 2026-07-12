#!/usr/bin/env python3
"""Preflight and freeze the review-prompt development dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

from review_prompt_scoring import (
    HUMAN_REVIEW_FIELDS,
    REVIEW_SCORE_RANGES,
    validate_human_review_record,
)


SELECTOR_VERSION = "score-marginal-greedy-v1"
MANIFEST_SCHEMA_VERSION = "review-prompt-dataset-v1"
SCORE_DIMENSIONS = tuple(REVIEW_SCORE_RANGES)


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    if "manifest_sha256" in payload:
        raise ValueError("manifest payload must not contain manifest_sha256")
    result = dict(payload)
    result["manifest_sha256"] = _sha256_bytes(canonical_json_bytes(payload))
    return result


def _write_manifest(
    path: Path,
    payload: Mapping[str, Any],
    *,
    mode: int = 0o600,
) -> dict[str, Any]:
    value = _manifest(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")
    path.chmod(mode)
    return value


def verify_manifest_file(path: str | Path) -> bool:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        return False
    expected = value.pop("manifest_sha256", None)
    if not isinstance(expected, str):
        return False
    return expected == _sha256_bytes(canonical_json_bytes(value))


def _strict_score(field: str, value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be within {minimum}..{maximum}")
    return value


def _source_id(row: Mapping[str, Any]) -> str:
    value = row.get("source_id")
    if not isinstance(value, str) or not value:
        raise ValueError("source_id must be a nonempty string")
    return value


def _score_mapping(row: Mapping[str, Any]) -> Mapping[str, Any]:
    scores = row.get("scores")
    if not isinstance(scores, Mapping):
        raise ValueError(f"{_source_id(row)} scores must be an object")
    for dimension, (minimum, maximum) in REVIEW_SCORE_RANGES.items():
        _strict_score(
            f"{_source_id(row)}.{dimension}",
            scores.get(dimension),
            int(minimum),
            int(maximum),
        )
    return scores


def _validated_selector_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    validated: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("selector rows must be objects")
        source_id = _source_id(row)
        if source_id in seen:
            raise ValueError(f"duplicate source_id: {source_id}")
        seen.add(source_id)
        if row.get("status", "valid") != "valid":
            raise ValueError(f"selector row {source_id} is not valid")
        _score_mapping(row)
        validated.append(row)
    return sorted(validated, key=lambda row: _source_id(row).encode("utf-8"))


def _selection_digest(seed: int, source_id: str) -> str:
    return _sha256_bytes(
        str(seed).encode("utf-8") + b"\0" + source_id.encode("utf-8")
    )


def _selection_order(seed: int, row: Mapping[str, Any]) -> tuple[str, bytes]:
    source_id = _source_id(row)
    return (_selection_digest(seed, source_id), source_id.encode("utf-8"))


def _largest_remainder_quotas(
    rows: Sequence[Mapping[str, Any]],
    count: int,
) -> dict[int, int]:
    strata = Counter(int(_score_mapping(row)["overall_recommendation"]) for row in rows)
    exact = {
        score: Fraction(count * stratum_count, len(rows))
        for score, stratum_count in strata.items()
    }
    quotas = {score: int(value) for score, value in exact.items()}
    remaining = count - sum(quotas.values())
    order = sorted(
        strata,
        key=lambda score: (-(exact[score] - quotas[score]), score),
    )
    for score in order[:remaining]:
        quotas[score] += 1
    return dict(sorted(quotas.items()))


def _marginal_l1(
    trial: Sequence[Mapping[str, Any]],
    source: Sequence[Mapping[str, Any]],
) -> Fraction:
    total = Fraction(0, 1)
    for dimension, (minimum, maximum) in REVIEW_SCORE_RANGES.items():
        trial_counts = Counter(int(_score_mapping(row)[dimension]) for row in trial)
        source_counts = Counter(int(_score_mapping(row)[dimension]) for row in source)
        for category in range(int(minimum), int(maximum) + 1):
            total += abs(
                Fraction(trial_counts[category], len(trial))
                - Fraction(source_counts[category], len(source))
            )
    return total


def select_balanced(
    rows: Sequence[Mapping[str, Any]],
    *,
    count: int,
    seed: int,
) -> list[Mapping[str, Any]]:
    """Select a deterministic score-marginal-balanced subset."""

    source = _validated_selector_rows(rows)
    if isinstance(count, bool) or not isinstance(count, int):
        raise ValueError("count must be an integer")
    if count < 0 or count > len(source):
        raise ValueError("count must be within 0..len(rows)")
    if count == 0:
        return []
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")

    quotas = _largest_remainder_quotas(source, count)
    selected: list[Mapping[str, Any]] = []
    selected_ids: set[str] = set()
    selected_strata: Counter[int] = Counter()
    while len(selected) < count:
        eligible = []
        for row in source:
            source_id = _source_id(row)
            score = int(_score_mapping(row)["overall_recommendation"])
            if source_id in selected_ids or selected_strata[score] >= quotas[score]:
                continue
            trial = [*selected, row]
            eligible.append(
                (
                    _marginal_l1(trial, source),
                    _selection_digest(seed, source_id),
                    source_id.encode("utf-8"),
                    row,
                )
            )
        if not eligible:
            raise RuntimeError("selector could not satisfy recommendation quotas")
        chosen = min(eligible, key=lambda value: value[:3])[3]
        chosen_id = _source_id(chosen)
        chosen_score = int(_score_mapping(chosen)["overall_recommendation"])
        selected.append(chosen)
        selected_ids.add(chosen_id)
        selected_strata[chosen_score] += 1

    return sorted(selected, key=lambda row: _selection_order(seed, row))


def _metadata_value(output: str, field: str) -> str:
    prefix = f"{field}:"
    for line in output.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def _run_text_command(command: Sequence[str], *, timeout_seconds: int) -> str:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"command exited {completed.returncode}")
    return completed.stdout


def _validated_label(
    *,
    path: Path,
    source_id: str,
    duplicate_forum_ids: set[str],
) -> tuple[Mapping[str, Any] | None, list[str]]:
    reasons: list[str] = []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, ["invalid_label_json"]
    if not isinstance(value, Mapping):
        return None, ["invalid_label_schema"]
    if set(value) != set(HUMAN_REVIEW_FIELDS):
        reasons.append("invalid_label_schema")
    forum_id = value.get("forum_id")
    if forum_id != source_id:
        reasons.append("forum_id_filename_mismatch")
    if isinstance(forum_id, str) and forum_id in duplicate_forum_ids:
        reasons.append("duplicate_forum_id")
    try:
        validate_human_review_record(value)
        for dimension, (minimum, maximum) in REVIEW_SCORE_RANGES.items():
            _strict_score(
                dimension,
                value.get(dimension),
                int(minimum),
                int(maximum),
            )
    except ValueError:
        if "invalid_label_schema" not in reasons:
            reasons.append("invalid_label_schema")
    return value, reasons


def preflight_pool(
    *,
    labels_dir: str | Path,
    pdfs_dir: str | Path,
    pdfinfo_bin: str = "pdfinfo",
    pdftotext_bin: str = "pdftotext",
    minimum_text_chars: int = 1000,
    timeout_seconds: int = 120,
) -> list[dict[str, object]]:
    """Classify every label/PDF stem as valid or excluded."""

    label_root = Path(labels_dir).expanduser().resolve()
    pdf_root = Path(pdfs_dir).expanduser().resolve()
    label_paths = {path.stem: path for path in label_root.glob("*.json")}
    pdf_paths = {path.stem: path for path in pdf_root.glob("*.pdf")}
    stems = sorted(set(label_paths) | set(pdf_paths), key=lambda value: value.encode("utf-8"))
    if not stems:
        raise ValueError("no JSON/PDF inputs were found")

    forum_counts: Counter[str] = Counter()
    for path in label_paths.values():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(value, Mapping) and isinstance(value.get("forum_id"), str):
            forum_counts[value["forum_id"]] += 1
    duplicate_forum_ids = {
        forum_id for forum_id, count in forum_counts.items() if count > 1
    }

    records: list[dict[str, object]] = []
    for source_id in stems:
        reasons: list[str] = []
        label_path = label_paths.get(source_id)
        pdf_path = pdf_paths.get(source_id)
        label: Mapping[str, Any] | None = None
        if label_path is None:
            reasons.append("missing_label_json")
        else:
            label, label_reasons = _validated_label(
                path=label_path,
                source_id=source_id,
                duplicate_forum_ids=duplicate_forum_ids,
            )
            reasons.extend(label_reasons)

        title = ""
        authors = ""
        paper_text = ""
        pdf_sha256 = ""
        pdf_bytes = 0
        if pdf_path is None:
            reasons.append("missing_pdf")
        else:
            try:
                pdf_bytes = pdf_path.stat().st_size
                with pdf_path.open("rb") as stream:
                    signature = stream.read(5)
                if signature != b"%PDF-":
                    reasons.append("invalid_pdf_signature")
                pdf_sha256 = _sha256_file(pdf_path)
            except OSError:
                reasons.append("unreadable_pdf")

            try:
                metadata = _run_text_command(
                    [pdfinfo_bin, str(pdf_path)],
                    timeout_seconds=timeout_seconds,
                )
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                reasons.append("pdfinfo_failed")
            else:
                title = _metadata_value(metadata, "Title")
                authors = _metadata_value(metadata, "Author")
                if not title:
                    reasons.append("missing_title_metadata")
                if not authors:
                    reasons.append("missing_author_metadata")

            try:
                paper_text = _run_text_command(
                    [
                        pdftotext_bin,
                        "-layout",
                        "-enc",
                        "UTF-8",
                        str(pdf_path),
                        "-",
                    ],
                    timeout_seconds=timeout_seconds,
                ).strip()
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                reasons.append("pdftotext_failed")
            else:
                if len(paper_text) < minimum_text_chars:
                    reasons.append("paper_text_too_short")

        scores: dict[str, int] = {}
        if label is not None:
            for dimension in SCORE_DIMENSIONS:
                value = label.get(dimension)
                if isinstance(value, int) and not isinstance(value, bool):
                    scores[dimension] = value
        record: dict[str, object] = {
            "source_id": source_id,
            "status": "valid" if not reasons else "excluded",
            "reasons": reasons,
            "label_path": str(label_path.resolve()) if label_path else "",
            "pdf_path": str(pdf_path.resolve()) if pdf_path else "",
            "label_sha256": _sha256_file(label_path) if label_path else "",
            "pdf_sha256": pdf_sha256,
            "paper_text_sha256": _sha256_bytes(paper_text.encode("utf-8"))
            if paper_text
            else "",
            "pdf_bytes": pdf_bytes,
            "paper_text_chars": len(paper_text),
            "title": title,
            "authors": authors,
            "scores": scores,
        }
        records.append(record)
    return records


def _score_marginals(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for dimension, (minimum, maximum) in REVIEW_SCORE_RANGES.items():
        counts = Counter(int(_score_mapping(row)[dimension]) for row in rows)
        result[dimension] = {
            str(category): counts[category]
            for category in range(int(minimum), int(maximum) + 1)
        }
    return result


def _pseudonymous_id(source_id: str) -> str:
    digest = _sha256_bytes(
        b"review-prompt-pseudonym-v1\0" + source_id.encode("utf-8")
    )
    return f"paper-{digest[:16]}"


def _manifest_entry(row: Mapping[str, Any], *, split: str) -> dict[str, object]:
    source_id = _source_id(row)
    scores = _score_mapping(row)
    return {
        "source_id": source_id,
        "paper_id": _pseudonymous_id(source_id),
        "split": split,
        "label_path": str(row["label_path"]),
        "pdf_path": str(row["pdf_path"]),
        "label_sha256": str(row["label_sha256"]),
        "pdf_sha256": str(row["pdf_sha256"]),
        "paper_text_sha256": str(row["paper_text_sha256"]),
        "pdf_bytes": int(row["pdf_bytes"]),
        "paper_text_chars": int(row["paper_text_chars"]),
        "title": str(row["title"]),
        "authors": str(row["authors"]),
        "scores": {dimension: int(scores[dimension]) for dimension in SCORE_DIMENSIONS},
    }


def freeze_dataset(
    pool_records: Sequence[Mapping[str, Any]],
    *,
    output_root: str | Path,
    development_count: int,
    holdout_count: int,
    sample_count: int,
    split_seed: int,
    sample_seed: int,
    permission_provenance: str,
) -> dict[str, object]:
    """Write a fresh deterministic development/holdout/sample bundle."""

    if not permission_provenance.strip():
        raise ValueError("permission_provenance must be nonempty")
    valid = [row for row in pool_records if row.get("status") == "valid"]
    excluded = [row for row in pool_records if row.get("status") != "valid"]
    if len(valid) != development_count + holdout_count:
        raise ValueError(
            "valid pool count must equal development_count + holdout_count"
        )
    if sample_count < 1 or sample_count > development_count:
        raise ValueError("sample_count must be within 1..development_count")
    _validated_selector_rows(valid)

    holdout_rows = select_balanced(valid, count=holdout_count, seed=split_seed)
    holdout_ids = {_source_id(row) for row in holdout_rows}
    development_rows = sorted(
        (row for row in valid if _source_id(row) not in holdout_ids),
        key=lambda row: _source_id(row).encode("utf-8"),
    )
    if len(development_rows) != development_count:
        raise RuntimeError("development split count is inconsistent")
    sample_rows = select_balanced(
        development_rows,
        count=sample_count,
        seed=sample_seed,
    )

    target = Path(output_root).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"output_root already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=str(target.parent))
    )
    try:
        temporary.chmod(0o700)
        sealed = temporary / "sealed"
        sealed.mkdir(mode=0o700)
        holdout_payload = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "selector_version": SELECTOR_VERSION,
            "split": "holdout",
            "seed": split_seed,
            "permission_provenance": permission_provenance,
            "count": len(holdout_rows),
            "score_marginals": _score_marginals(holdout_rows),
            "entries": [
                _manifest_entry(row, split="holdout") for row in holdout_rows
            ],
        }
        holdout_manifest = _write_manifest(
            sealed / "holdout-manifest.json",
            holdout_payload,
            mode=0o600,
        )
        development_payload = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "selector_version": SELECTOR_VERSION,
            "split": "development",
            "seed": split_seed,
            "permission_provenance": permission_provenance,
            "count": len(development_rows),
            "score_marginals": _score_marginals(development_rows),
            "holdout": {
                "count": len(holdout_rows),
                "sealed_manifest_sha256": holdout_manifest["manifest_sha256"],
            },
            "entries": [
                _manifest_entry(row, split="development")
                for row in development_rows
            ],
        }
        development_manifest = _write_manifest(
            temporary / "development-manifest.json",
            development_payload,
        )
        sample_payload = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "selector_version": SELECTOR_VERSION,
            "split": "development",
            "seed": sample_seed,
            "source_manifest_sha256": development_manifest["manifest_sha256"],
            "count": len(sample_rows),
            "score_marginals": _score_marginals(sample_rows),
            "entries": [
                _manifest_entry(row, split="development") for row in sample_rows
            ],
        }
        sample_manifest = _write_manifest(
            temporary / "sample-manifest.json",
            sample_payload,
        )
        preflight_payload = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "permission_provenance": permission_provenance,
            "pool_count": len(pool_records),
            "valid_count": len(valid),
            "excluded_count": len(excluded),
            "valid_pool_digest": _sha256_bytes(
                b"".join(
                    (
                        _source_id(row).encode("utf-8")
                        + b"\0"
                        + str(row["label_sha256"]).encode("utf-8")
                        + b"\0"
                        + str(row["pdf_sha256"]).encode("utf-8")
                        + b"\n"
                    )
                    for row in sorted(
                        valid,
                        key=lambda item: _source_id(item).encode("utf-8"),
                    )
                )
            ),
            "exclusions": [
                {
                    "source_id": _source_id(row),
                    "reasons": list(row.get("reasons", [])),
                }
                for row in sorted(
                    excluded,
                    key=lambda item: _source_id(item).encode("utf-8"),
                )
            ],
        }
        preflight_manifest = _write_manifest(
            temporary / "preflight-summary.json",
            preflight_payload,
        )
        for path in (
            sealed / "holdout-manifest.json",
            temporary / "development-manifest.json",
            temporary / "sample-manifest.json",
            temporary / "preflight-summary.json",
        ):
            if not verify_manifest_file(path):
                raise RuntimeError(f"manifest verification failed: {path.name}")
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return {
        "output_root": str(target),
        "pool_count": len(pool_records),
        "valid_count": len(valid),
        "excluded_count": len(excluded),
        "development_count": len(development_rows),
        "holdout_count": len(holdout_rows),
        "sample_count": len(sample_rows),
        "preflight_manifest_path": str(target / "preflight-summary.json"),
        "preflight_manifest_sha256": preflight_manifest["manifest_sha256"],
        "development_manifest_path": str(target / "development-manifest.json"),
        "development_manifest_sha256": development_manifest["manifest_sha256"],
        "holdout_manifest_path": str(target / "sealed" / "holdout-manifest.json"),
        "holdout_manifest_sha256": holdout_manifest["manifest_sha256"],
        "sample_manifest_path": str(target / "sample-manifest.json"),
        "sample_manifest_sha256": sample_manifest["manifest_sha256"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-dir", type=Path, required=True)
    parser.add_argument("--pdfs-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--development-count", type=int, required=True)
    parser.add_argument("--holdout-count", type=int, required=True)
    parser.add_argument("--sample-count", type=int, required=True)
    parser.add_argument("--split-seed", type=int, required=True)
    parser.add_argument("--sample-seed", type=int, required=True)
    parser.add_argument("--permission-provenance", required=True)
    parser.add_argument("--pdfinfo-bin", default="pdfinfo")
    parser.add_argument("--pdftotext-bin", default="pdftotext")
    parser.add_argument("--minimum-text-chars", type=int, default=1000)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    return parser


def main() -> int:
    args = _parser().parse_args()
    pool = preflight_pool(
        labels_dir=args.labels_dir,
        pdfs_dir=args.pdfs_dir,
        pdfinfo_bin=args.pdfinfo_bin,
        pdftotext_bin=args.pdftotext_bin,
        minimum_text_chars=args.minimum_text_chars,
        timeout_seconds=args.timeout_seconds,
    )
    result = freeze_dataset(
        pool,
        output_root=args.output_root,
        development_count=args.development_count,
        holdout_count=args.holdout_count,
        sample_count=args.sample_count,
        split_seed=args.split_seed,
        sample_seed=args.sample_seed,
        permission_provenance=args.permission_provenance,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
