"""Profile the ICML 2026 Hugging Face review dataset for the report.

The script is intentionally read-only with respect to the source dataset. It
writes compact, versionable CSV/JSON summaries that can feed report figures.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from datasets import load_from_disk


SCORE_FIELDS = (
    "soundness",
    "presentation",
    "significance",
    "originality",
    "overall_recommendation",
    "confidence",
)
TEXT_FIELDS = (
    "summary",
    "strengths_and_weaknesses",
    "key_questions_for_authors",
    "limitations",
)


def word_count(value: object) -> int:
    return len(value.split()) if isinstance(value, str) else 0


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def describe(values: list[float]) -> dict[str, float | int | None]:
    return {
        "n": len(values),
        "mean": statistics.fmean(values) if values else None,
        "std": statistics.stdev(values) if len(values) > 1 else None,
        "min": min(values) if values else None,
        "q25": quantile(values, 0.25),
        "median": quantile(values, 0.50),
        "q75": quantile(values, 0.75),
        "max": max(values) if values else None,
    }


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    import csv

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, default=Path("analysis/icml2026"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    dataset = load_from_disk(str(args.dataset))
    papers = list(dataset)
    reviews: list[dict[str, object]] = []
    per_paper_disagreement = {field: [] for field in SCORE_FIELDS}

    for paper in papers:
        paper_reviews = json.loads(paper["reviews_json"])
        for review in paper_reviews:
            reviews.append({"forum_id": paper["forum_id"], **review})
        for field in SCORE_FIELDS:
            scores = [review[field] for review in paper_reviews if isinstance(review.get(field), (int, float))]
            if len(scores) > 1:
                per_paper_disagreement[field].append(statistics.stdev(scores))

    decisions = Counter(paper["decision"] or "Missing" for paper in papers)
    areas = Counter(paper["primary_area"] or "Missing" for paper in papers)
    review_counts = Counter(paper["num_reviews"] for paper in papers)
    authors_per_paper = [len(paper["authors"]) for paper in papers]
    keywords_per_paper = [len(paper["keywords"]) for paper in papers]
    abstract_words = [word_count(paper["abstract"]) for paper in papers]
    review_words = [sum(word_count(review.get(field)) for field in TEXT_FIELDS) for review in reviews]

    summary = {
        "dataset_path": str(args.dataset.resolve()),
        "papers": len(papers),
        "reviews": len(reviews),
        "reviews_per_paper": describe([paper["num_reviews"] for paper in papers]),
        "authors_per_paper": describe(authors_per_paper),
        "keywords_per_paper": describe(keywords_per_paper),
        "abstract_words": describe(abstract_words),
        "review_text_words": describe(review_words),
        "unique_primary_areas": len(areas),
        "unique_authors": len({author for paper in papers for author in paper["authors"]}),
        "decisions": dict(decisions.most_common()),
    }
    (args.output / "dataset_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    write_csv(
        args.output / "area_distribution.csv",
        ["primary_area", "papers", "percent"],
        [
            {"primary_area": area, "papers": count, "percent": 100 * count / len(papers)}
            for area, count in areas.most_common()
        ],
    )
    write_csv(
        args.output / "decision_distribution.csv",
        ["decision", "papers", "percent"],
        [
            {"decision": decision, "papers": count, "percent": 100 * count / len(papers)}
            for decision, count in decisions.most_common()
        ],
    )
    write_csv(
        args.output / "review_count_distribution.csv",
        ["num_reviews", "papers", "percent"],
        [
            {"num_reviews": count, "papers": papers_n, "percent": 100 * papers_n / len(papers)}
            for count, papers_n in sorted(review_counts.items())
        ],
    )

    score_rows = []
    for field in SCORE_FIELDS:
        values = [float(review[field]) for review in reviews if isinstance(review.get(field), (int, float))]
        score_rows.append({"field": field, **describe(values)})
    write_csv(
        args.output / "review_score_summary.csv",
        ["field", "n", "mean", "std", "min", "q25", "median", "q75", "max"],
        score_rows,
    )

    disagreement_rows = [
        {"field": field, **describe(values)} for field, values in per_paper_disagreement.items()
    ]
    write_csv(
        args.output / "reviewer_disagreement_summary.csv",
        ["field", "n", "mean", "std", "min", "q25", "median", "q75", "max"],
        disagreement_rows,
    )

    paper_missing_rows = []
    for field in dataset.column_names:
        if field == "reviews_json":
            continue
        missing = sum(value is None or value == "" or value == [] for value in dataset[field])
        paper_missing_rows.append(
            {"level": "paper", "field": field, "missing": missing, "percent": 100 * missing / len(papers)}
        )
    review_missing_rows = []
    review_fields = sorted({field for review in reviews for field in review if field != "forum_id"})
    for field in review_fields:
        missing = sum(review.get(field) is None or review.get(field) == "" for review in reviews)
        review_missing_rows.append(
            {"level": "review", "field": field, "missing": missing, "percent": 100 * missing / len(reviews)}
        )
    write_csv(
        args.output / "missingness.csv",
        ["level", "field", "missing", "percent"],
        paper_missing_rows + review_missing_rows,
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Wrote summaries to {args.output}")


if __name__ == "__main__":
    main()
