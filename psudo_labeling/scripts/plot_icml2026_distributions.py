"""Create a report-ready overview of ICML 2026 dataset distributions."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from datasets import load_from_disk
from matplotlib.transforms import Bbox


SCORE_FIELDS = (
    ("Soundness", "soundness", 4),
    ("Presentation", "presentation", 4),
    ("Significance", "significance", 4),
    ("Originality", "originality", 4),
    ("Recommendation", "overall_recommendation", 6),
    ("Confidence", "confidence", 5),
)
COLORS = {
    "navy": "#183B56",
    "blue": "#2878B5",
    "cyan": "#55A6C1",
    "orange": "#E6863B",
    "gold": "#E8B44C",
    "light": "#DCEAF2",
    "gray": "#667681",
}


def clean_area(value: str) -> str:
    leaf = value.split("->")[-1]
    return leaf.replace("_", " ").title()


def words(value: object) -> int:
    return len(value.split()) if isinstance(value, str) else 0


def panel_label(ax: mpl.axes.Axes, label: str, title: str) -> None:
    ax.text(-0.08, 1.08, label, transform=ax.transAxes, fontsize=13, fontweight="bold", va="top")
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold", pad=10)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, default=Path("figures/icml2026/distributions"))
    args = parser.parse_args()

    ds = load_from_disk(str(args.dataset))
    papers = list(ds)
    reviews_by_paper = [json.loads(paper["reviews_json"]) for paper in papers]
    reviews = [review for group in reviews_by_paper for review in group]

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
            "svg.fonttype": "none",
        }
    )

    fig, axes = plt.subplots(2, 3, figsize=(15.5, 9.2))
    fig.subplots_adjust(left=0.075, right=0.98, top=0.88, bottom=0.09, wspace=0.34, hspace=0.42)
    fig.suptitle("ICML 2026 Accepted-Paper Review Dataset", x=0.075, ha="left", fontsize=19, fontweight="bold", color=COLORS["navy"])
    fig.text(0.075, 0.915, f"6,341 papers  •  {len(reviews):,} official reviews  •  84 primary areas", color=COLORS["gray"], fontsize=10.5)

    # A: top primary areas.
    ax = axes[0, 0]
    areas = Counter(paper["primary_area"] for paper in papers)
    top = areas.most_common(12)
    labels = [clean_area(area) for area, _ in top][::-1]
    counts = [count for _, count in top][::-1]
    bars = ax.barh(labels, counts, color=[COLORS["orange"] if i == len(counts) - 1 else COLORS["blue"] for i in range(len(counts))])
    ax.bar_label(bars, labels=[f"{v:,}" for v in counts], padding=3, fontsize=7.5, color=COLORS["gray"])
    ax.set_xlim(0, max(counts) * 1.16)
    ax.set_xlabel("Number of papers")
    ax.grid(axis="x")
    panel_label(ax, "A", "Largest primary areas")

    # B: review count per paper.
    ax = axes[0, 1]
    review_counts = Counter(paper["num_reviews"] for paper in papers)
    xs = list(range(min(review_counts), max(review_counts) + 1))
    ys = [review_counts[x] for x in xs]
    bars = ax.bar(xs, ys, width=0.72, color=COLORS["cyan"], edgecolor="white")
    ax.bar_label(bars, labels=[f"{v:,}\n({100*v/len(papers):.1f}%)" for v in ys], padding=3, fontsize=8)
    ax.set_xticks(xs)
    ax.set_ylim(0, max(ys) * 1.16)
    ax.set_xlabel("Official reviews per paper")
    ax.set_ylabel("Number of papers")
    ax.grid(axis="y")
    panel_label(ax, "B", "Review coverage per paper")

    # C: complete discrete score distributions as a heatmap.
    ax = axes[0, 2]
    score_matrix = np.full((len(SCORE_FIELDS), 6), np.nan)
    for row, (_, field, maximum) in enumerate(SCORE_FIELDS):
        counts_by_score = Counter(review[field] for review in reviews)
        total = sum(counts_by_score.values())
        for score in range(1, maximum + 1):
            score_matrix[row, score - 1] = 100 * counts_by_score[score] / total
    masked = np.ma.masked_invalid(score_matrix)
    image = ax.imshow(masked, aspect="auto", cmap=mpl.colors.LinearSegmentedColormap.from_list("scores", ["#F4F8FA", COLORS["blue"], COLORS["navy"]]), vmin=0, vmax=np.nanmax(score_matrix))
    for i in range(score_matrix.shape[0]):
        for j in range(score_matrix.shape[1]):
            value = score_matrix[i, j]
            if not np.isnan(value):
                ax.text(j, i, f"{value:.1f}", ha="center", va="center", fontsize=8, color="white" if value > 30 else COLORS["navy"])
    ax.set_xticks(range(6), range(1, 7))
    ax.set_yticks(range(len(SCORE_FIELDS)), [item[0] for item in SCORE_FIELDS])
    ax.set_xlabel("Score (% of reviews)")
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    colorbar = fig.colorbar(image, ax=ax, fraction=0.045, pad=0.03)
    colorbar.set_label("Percent")
    panel_label(ax, "C", "Review score distributions")

    # D: within-paper reviewer disagreement.
    ax = axes[1, 0]
    disagreement = []
    for label, field, _ in SCORE_FIELDS:
        values = []
        for group in reviews_by_paper:
            scores = [review[field] for review in group]
            values.append(statistics.stdev(scores))
        disagreement.append(values)
    violin = ax.violinplot(disagreement, showmeans=False, showmedians=True, showextrema=False)
    for body in violin["bodies"]:
        body.set_facecolor(COLORS["blue"])
        body.set_edgecolor("none")
        body.set_alpha(0.75)
    violin["cmedians"].set_color(COLORS["orange"])
    violin["cmedians"].set_linewidth(2)
    ax.set_xticks(range(1, 7), ["Sound.", "Present.", "Signif.", "Orig.", "Recom.", "Conf."], rotation=25, ha="right")
    ax.set_ylabel("Within-paper score SD")
    ax.grid(axis="y")
    panel_label(ax, "D", "Reviewer disagreement")

    # E: text-length distributions; clip only the visual tail and report it.
    ax = axes[1, 1]
    abstract_lengths = np.array([words(paper["abstract"]) for paper in papers])
    review_lengths = np.array([
        sum(words(review.get(field)) for field in ("summary", "strengths_and_weaknesses", "key_questions_for_authors", "limitations"))
        for review in reviews
    ])
    bins = np.linspace(0, 1200, 49)
    ax.hist(review_lengths, bins=bins, density=True, alpha=0.78, color=COLORS["blue"], label=f"Official review (median {np.median(review_lengths):.0f})")
    ax.hist(abstract_lengths, bins=bins, density=True, alpha=0.75, color=COLORS["orange"], label=f"Abstract (median {np.median(abstract_lengths):.0f})")
    ax.set_xlim(0, 1200)
    ax.set_xlabel("Words")
    ax.set_ylabel("Density")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y")
    panel_label(ax, "E", "Text-length distributions")

    # F: accepted-paper decision composition.
    ax = axes[1, 2]
    decisions = Counter(paper["decision"] for paper in papers)
    decision_labels = ["Regular", "Spotlight"]
    decision_values = [decisions["Accept (regular)"], decisions["Accept (spotlight)"]]
    wedges, _ = ax.pie(
        decision_values,
        startangle=90,
        counterclock=False,
        colors=[COLORS["blue"], COLORS["gold"]],
        wedgeprops={"width": 0.38, "edgecolor": "white", "linewidth": 2},
    )
    ax.text(0, 0.08, f"{sum(decision_values):,}", ha="center", va="center", fontsize=19, fontweight="bold", color=COLORS["navy"])
    ax.text(0, -0.14, "accepted papers", ha="center", va="center", fontsize=8.5, color=COLORS["gray"])
    legend_labels = [f"{label}: {value:,} ({100*value/sum(decision_values):.1f}%)" for label, value in zip(decision_labels, decision_values)]
    ax.legend(wedges, legend_labels, loc="lower center", bbox_to_anchor=(0.5, -0.12), frameon=False, fontsize=8)
    panel_label(ax, "F", "Decision composition")

    fig.text(0.075, 0.025, "Source: ICML 2026 accepted papers and official OpenReview reviews. Percentages may not sum to 100 due to rounding.", fontsize=8, color=COLORS["gray"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output.with_suffix(".png"), dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(args.output.with_suffix(".svg"), bbox_inches="tight", facecolor="white")

    # Export every panel independently while preserving the exact composite
    # styling. Include the colorbar in the score-distribution panel crop.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    panel_outputs = (
        (axes[0, 0], "01_primary_area_distribution", []),
        (axes[0, 1], "02_reviews_per_paper", []),
        (axes[0, 2], "03_review_score_distributions", [colorbar.ax]),
        (axes[1, 0], "04_reviewer_disagreement", []),
        (axes[1, 1], "05_text_length_distributions", []),
        (axes[1, 2], "06_decision_composition", []),
    )
    individual_dir = args.output.parent / "individual"
    individual_dir.mkdir(parents=True, exist_ok=True)
    for figure_text in fig.texts:
        figure_text.set_visible(False)
    for panel_ax, filename, extra_axes in panel_outputs:
        for figure_ax in fig.axes:
            figure_ax.set_visible(False)
        panel_ax.set_visible(True)
        for extra_ax in extra_axes:
            extra_ax.set_visible(True)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        boxes = [panel_ax.get_tightbbox(renderer)]
        boxes.extend(extra_ax.get_tightbbox(renderer) for extra_ax in extra_axes)
        extent = Bbox.union(boxes).transformed(fig.dpi_scale_trans.inverted())
        extent = extent.expanded(1.08, 1.12)
        panel_path = individual_dir / f"{filename}.png"
        fig.savefig(panel_path, dpi=300, bbox_inches=extent, facecolor="white")
        print(panel_path)
    for figure_ax in fig.axes:
        figure_ax.set_visible(True)
    for figure_text in fig.texts:
        figure_text.set_visible(True)
    print(args.output.with_suffix(".png"))
    print(args.output.with_suffix(".svg"))


if __name__ == "__main__":
    main()
