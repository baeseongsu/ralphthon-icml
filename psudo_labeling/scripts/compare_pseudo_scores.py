"""Compare pseudo-label scores with human reviews and the full ICML dataset.

All human-review distributions are computed at the paper level: reviewer
scores are averaged within a paper before papers are compared. This prevents
papers with more reviewers from receiving greater weight.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from datasets import load_from_disk


SCORES = (
    ("Soundness", "soundness", 4),
    ("Presentation", "presentation", 4),
    ("Significance", "significance", 4),
    ("Originality", "originality", 4),
    ("Overall recommendation", "overall_recommendation", 6),
    ("Confidence", "confidence", 5),
)
GROUPS = (
    ("Full review\n(n=6,341)", "full", "#A9BBC7"),
    ("Sampled review\n(n=175)", "matched", "#2878B5"),
    ("Pseudo-label\n(n=175)", "pseudo", "#E6863B"),
)


def describe(values: list[float]) -> dict[str, float | int]:
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "sd": statistics.stdev(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def ecdf(values: list[float]) -> tuple[np.ndarray, np.ndarray]:
    x = np.sort(np.asarray(values, dtype=float))
    y = np.arange(1, len(x) + 1) / len(x)
    return x, y


def ks_distance(left: list[float], right: list[float]) -> float:
    support = np.unique(np.concatenate([left, right]))
    left_sorted = np.sort(left)
    right_sorted = np.sort(right)
    left_cdf = np.searchsorted(left_sorted, support, side="right") / len(left_sorted)
    right_cdf = np.searchsorted(right_sorted, support, side="right") / len(right_sorted)
    return float(np.max(np.abs(left_cdf - right_cdf)))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": "#AAB7C0",
            "axes.labelcolor": "#36454F",
            "xtick.color": "#52616B",
            "ytick.color": "#52616B",
            "grid.color": "#D8E1E7",
            "grid.linewidth": 0.7,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("pseudo_labels", type=Path)
    parser.add_argument("--output", type=Path, default=Path("analysis/icml2026/pseudo_score_comparison"))
    parser.add_argument("--figures", type=Path, default=Path("figure/icml2026/pseudo_score_comparison"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.figures.mkdir(parents=True, exist_ok=True)

    dataset = load_from_disk(str(args.dataset))
    papers = {paper["forum_id"]: paper for paper in dataset}
    pseudo = {}
    for path in sorted(args.pseudo_labels.glob("*.json")):
        label = json.loads(path.read_text(encoding="utf-8"))
        pseudo[label["forum_id"]] = label
    unmatched = sorted(set(pseudo) - set(papers))
    if unmatched:
        raise ValueError(f"Pseudo-label IDs missing from dataset: {unmatched}")

    paper_scores: dict[str, dict[str, float]] = {}
    paper_ranges: dict[str, dict[str, tuple[float, float]]] = {}
    for forum_id, paper in papers.items():
        reviews = json.loads(paper["reviews_json"])
        paper_scores[forum_id] = {}
        paper_ranges[forum_id] = {}
        for _, field, _ in SCORES:
            values = [float(review[field]) for review in reviews]
            paper_scores[forum_id][field] = statistics.fmean(values)
            paper_ranges[forum_id][field] = (min(values), max(values))

    distributions: dict[str, dict[str, list[float]]] = {}
    summary_rows = []
    paired_rows = []
    pseudo_ids = sorted(pseudo)
    for label, field, _ in SCORES:
        full = [scores[field] for scores in paper_scores.values()]
        matched = [paper_scores[forum_id][field] for forum_id in pseudo_ids]
        generated = [float(pseudo[forum_id][field]) for forum_id in pseudo_ids]
        distributions[field] = {"full": full, "matched": matched, "pseudo": generated}
        for group, values in (("full_human", full), ("matched_human", matched), ("pseudo_label", generated)):
            summary_rows.append({"field": field, "group": group, **describe(values)})
        differences = [p - h for p, h in zip(generated, matched)]
        within_range = [
            paper_ranges[forum_id][field][0] <= pseudo[forum_id][field] <= paper_ranges[forum_id][field][1]
            for forum_id in pseudo_ids
        ]
        paired_rows.append(
            {
                "field": field,
                "n": len(pseudo_ids),
                "pseudo_minus_human_mean": statistics.fmean(differences),
                "mae": statistics.fmean(abs(value) for value in differences),
                "rmse": math.sqrt(statistics.fmean(value * value for value in differences)),
                "exact_match_with_rounded_human_mean_percent": 100
                * sum(p == round(h) for p, h in zip(generated, matched))
                / len(pseudo_ids),
                "within_human_score_range_percent": 100 * sum(within_range) / len(within_range),
                "ks_pseudo_vs_matched_human": ks_distance(generated, matched),
                "ks_matched_human_vs_full_human": ks_distance(matched, full),
            }
        )

    write_csv(
        args.output / "score_summary.csv",
        ["field", "group", "n", "mean", "sd", "median", "min", "max"],
        summary_rows,
    )
    write_csv(
        args.output / "paired_comparison.csv",
        [
            "field",
            "n",
            "pseudo_minus_human_mean",
            "mae",
            "rmse",
            "exact_match_with_rounded_human_mean_percent",
            "within_human_score_range_percent",
            "ks_pseudo_vs_matched_human",
            "ks_matched_human_vs_full_human",
        ],
        paired_rows,
    )

    style()

    # Figure 1: means and 95% normal intervals.
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 7.8))
    fig.subplots_adjust(left=0.07, right=0.98, top=0.86, bottom=0.10, wspace=0.30, hspace=0.48)
    fig.suptitle("Mean Score Comparison", x=0.07, ha="left", fontsize=18, fontweight="bold", color="#183B56")
    fig.text(0.07, 0.905, "Paper-level human means compared with 175 generated pseudo-labels", color="#667681", fontsize=10)
    for ax, (label, field, maximum) in zip(axes.flat, SCORES):
        for x_pos, (group_label, key, color) in enumerate(GROUPS):
            values = distributions[field][key]
            mean = statistics.fmean(values)
            ci = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
            ax.errorbar(x_pos, mean, yerr=ci, fmt="o", markersize=8, capsize=4, linewidth=1.8, color=color)
            ax.text(x_pos, mean + ci + maximum * 0.035, f"{mean:.2f}", ha="center", fontsize=8, fontweight="bold", color=color)
        ax.set_xticks(range(3), [group[0] for group in GROUPS])
        ax.set_ylim(0.65, maximum + 0.2)
        ax.set_yticks(range(1, maximum + 1))
        ax.set_title(label, loc="left", fontweight="bold")
        ax.set_ylabel("Score")
        ax.grid(axis="y")
    fig.text(0.07, 0.025, "Error bars show 95% normal intervals. Human scores are averaged within each paper before aggregation.", fontsize=8, color="#667681")
    fig.savefig(args.figures / "score_means_comparison.png", dpi=300, bbox_inches="tight", facecolor="white")

    # Figure 2: empirical cumulative distributions retain all distributional information.
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 7.8))
    fig.subplots_adjust(left=0.07, right=0.98, top=0.86, bottom=0.12, wspace=0.30, hspace=0.45)
    fig.suptitle("Score Distribution Comparison", x=0.07, ha="left", fontsize=18, fontweight="bold", color="#183B56")
    fig.text(0.07, 0.905, "Empirical cumulative distributions at the paper level", color="#667681", fontsize=10)
    for ax, (label, field, maximum) in zip(axes.flat, SCORES):
        for group_label, key, color in GROUPS:
            x, y = ecdf(distributions[field][key])
            ax.step(x, y, where="post", label=group_label.replace("\n", " "), color=color, linewidth=2.2 if key == "pseudo" else 1.8, alpha=0.95)
        ax.set_xlim(0.8, maximum + 0.2)
        ax.set_ylim(0, 1.02)
        ax.set_xticks(range(1, maximum + 1))
        ax.set_title(label, loc="left", fontweight="bold")
        ax.set_xlabel("Score")
        ax.set_ylabel("Cumulative proportion")
        ax.grid(alpha=0.8)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 0.025))
    fig.savefig(args.figures / "score_distributions_comparison.png", dpi=300, bbox_inches="tight", facecolor="white")

    # Figure 3 set: one conventional overlaid histogram per score dimension.
    individual_dir = args.figures / "individual_distributions"
    individual_dir.mkdir(parents=True, exist_ok=True)
    for index, (label, field, maximum) in enumerate(SCORES, start=1):
        fig, ax = plt.subplots(figsize=(7.2, 4.8))
        bins = np.arange(0.875, maximum + 1.126, 0.25)
        full = distributions[field]["full"]
        matched = distributions[field]["matched"]
        generated = distributions[field]["pseudo"]
        ax.hist(
            full,
            bins=bins,
            density=True,
            color="#A9BBC7",
            alpha=0.42,
            label="Full review (n=6,341)",
        )
        ax.hist(
            matched,
            bins=bins,
            density=True,
            histtype="step",
            linewidth=2.4,
            color="#2878B5",
            label="Sampled review (n=175)",
        )
        ax.hist(
            generated,
            bins=bins,
            density=True,
            histtype="step",
            linewidth=2.8,
            color="#E6863B",
            label="Pseudo-label (n=175)",
        )
        for values, color, linestyle in (
            (full, "#869DAA", "--"),
            (matched, "#2878B5", "--"),
            (generated, "#E6863B", "-"),
        ):
            ax.axvline(statistics.fmean(values), color=color, linestyle=linestyle, linewidth=1.6, alpha=0.95)
        ax.set_xlim(0.8, maximum + 0.2)
        ax.set_xticks(range(1, maximum + 1))
        ax.set_xlabel("Paper-level score")
        ax.set_ylabel("Density")
        ax.set_title(f"{label} Distribution", loc="left", fontsize=15, fontweight="bold", color="#183B56", pad=12)
        ax.grid(axis="y")
        ax.legend(frameon=False, fontsize=8.5)
        filename = field.replace("overall_recommendation", "recommendation")
        fig.savefig(
            individual_dir / f"{index:02d}_{filename}_distribution.png",
            dpi=300,
            bbox_inches="tight",
            facecolor="white",
        )
        plt.close(fig)
    plt.close("all")

    print(f"Matched pseudo-labels: {len(pseudo_ids)}")
    print(args.figures / "score_means_comparison.png")
    print(args.figures / "score_distributions_comparison.png")
    print(individual_dir)


if __name__ == "__main__":
    main()
