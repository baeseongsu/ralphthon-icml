#!/usr/bin/env python3
"""Render the aggregate P0-P4 review-prompt autoresearch trajectory."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA = ROOT / "docs" / "figures" / "review-prompt-autoresearch-data.csv"
DEFAULT_OUTPUT = ROOT / "docs" / "figures" / "review-prompt-autoresearch-trajectory"
EXPECTED_CANDIDATES = ("p0", "p1", "p2", "p3", "p4")
METRICS = (
    ("human_agreement", "Human agreement", "#0072B2", "o"),
    ("judge_quality", "Judge quality", "#E69F00", "^"),
    ("composite", "Composite", "#CC79A7", "s"),
)
STATUS_COLORS = {
    "baseline": "#6B7280",
    "keep": "#009E73",
    "discard": "#D55E00",
}


def load_rows(path: Path) -> list[dict[str, str | float]]:
    with path.open(newline="", encoding="utf-8") as source:
        raw_rows = list(csv.DictReader(source))
    candidates = tuple(row.get("candidate", "") for row in raw_rows)
    if candidates != EXPECTED_CANDIDATES:
        raise ValueError(f"expected candidate order {EXPECTED_CANDIDATES}, got {candidates}")
    rows: list[dict[str, str | float]] = []
    for row in raw_rows:
        normalized: dict[str, str | float] = dict(row)
        for field, _, _, _ in METRICS:
            value = float(str(row[field]))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{row['candidate']} {field} must be finite within 0..1")
            normalized[field] = value
        decision = str(row["decision"])
        if decision not in STATUS_COLORS:
            raise ValueError(f"unsupported decision: {decision}")
        rows.append(normalized)
    return rows


def render(rows: Sequence[dict[str, str | float]], output_prefix: Path) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 17,
            "axes.labelsize": 11,
            "axes.edgecolor": "#9CA3AF",
            "axes.linewidth": 0.8,
            "xtick.color": "#374151",
            "ytick.color": "#374151",
            "text.color": "#111827",
        }
    )
    x_values = list(range(len(rows)))
    labels = [str(row["candidate"]).upper() for row in rows]
    figure = plt.figure(figsize=(12.4, 7.4), facecolor="white")
    grid = figure.add_gridspec(2, 1, height_ratios=(4.5, 1.25), hspace=0.08)
    axis = figure.add_subplot(grid[0])
    lane = figure.add_subplot(grid[1], sharex=axis)

    axis.set_facecolor("white")
    axis.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    axis.grid(axis="x", visible=False)
    axis.axvspan(1.72, 2.28, color=STATUS_COLORS["keep"], alpha=0.07, zorder=0)

    for field, label, color, marker in METRICS:
        values = [float(row[field]) for row in rows]
        linewidth = 3.0 if field == "composite" else 2.2
        axis.plot(
            x_values,
            values,
            label=label,
            color=color,
            marker=marker,
            markersize=7.5,
            markeredgecolor="white",
            markeredgewidth=1.2,
            linewidth=linewidth,
            zorder=4 if field == "composite" else 3,
        )

    axis.scatter(
        [2],
        [float(rows[2]["composite"])],
        marker="*",
        s=230,
        color=STATUS_COLORS["keep"],
        edgecolor="white",
        linewidth=1.1,
        zorder=6,
    )
    axis.annotate(
        "P2 kept parent\nand deployment winner",
        xy=(2, float(rows[2]["composite"])),
        xytext=(2.30, 0.977),
        ha="left",
        va="top",
        color="#065F46",
        fontsize=10,
        fontweight="bold",
        arrowprops={"arrowstyle": "->", "color": STATUS_COLORS["keep"], "lw": 1.4},
    )
    axis.annotate(
        "Highest raw composite,\ndiscarded by regression gate",
        xy=(3, float(rows[3]["composite"])),
        xytext=(3.18, 0.900),
        ha="left",
        va="bottom",
        color="#9A3412",
        fontsize=9,
        arrowprops={"arrowstyle": "->", "color": STATUS_COLORS["discard"], "lw": 1.2},
    )

    axis.set_ylim(0.86, 0.985)
    axis.set_yticks([0.86, 0.88, 0.90, 0.92, 0.94, 0.96, 0.98])
    axis.set_ylabel("Normalized objective value")
    axis.tick_params(axis="x", labelbottom=False, length=0)
    axis.spines[["top", "right"]].set_visible(False)
    axis.set_title(
        "ICML Review-Prompt Autoresearch Trajectory",
        loc="left",
        pad=27,
        fontweight="bold",
    )
    axis.text(
        0.0,
        1.02,
        "Frozen development set (N=5) · identical Reviewer/Judge configuration · higher is better",
        transform=axis.transAxes,
        ha="left",
        va="bottom",
        color="#6B7280",
        fontsize=10,
    )
    axis.legend(
        loc="upper left",
        bbox_to_anchor=(0.0, 0.985),
        ncol=3,
        frameon=False,
        handlelength=2.5,
        columnspacing=1.8,
    )

    lane.set_ylim(-0.52, 0.62)
    lane.axis("off")
    lane.text(
        -0.48,
        0.28,
        "Decision",
        ha="right",
        va="center",
        color="#4B5563",
        fontsize=10,
        fontweight="bold",
    )
    for index in range(len(rows) - 1):
        lane.add_patch(
            FancyArrowPatch(
                (index + 0.12, 0.28),
                (index + 0.88, 0.28),
                arrowstyle="->",
                mutation_scale=10,
                color="#9CA3AF",
                linewidth=1.2,
            )
        )
    reason_labels = {
        "none": "",
        "dimension_regression": "dimension regression",
        "component_regression": "component regression",
        "no_composite_gain": "no composite gain",
    }
    for index, row in enumerate(rows):
        decision = str(row["decision"])
        color = STATUS_COLORS[decision]
        lane.scatter(
            [index],
            [0.28],
            s=520 if decision == "keep" else 410,
            color=color,
            edgecolor="white",
            linewidth=2,
            zorder=4,
        )
        lane.text(
            index,
            0.28,
            labels[index],
            ha="center",
            va="center",
            color="white",
            fontsize=9,
            fontweight="bold",
            zorder=5,
        )
        status = "BASELINE" if decision == "baseline" else decision.upper()
        lane.text(
            index,
            -0.06,
            status,
            ha="center",
            va="top",
            color=color,
            fontsize=9,
            fontweight="bold",
        )
        reason = reason_labels[str(row["rejection_reason"])]
        if reason:
            lane.text(
                index,
                -0.27,
                reason,
                ha="center",
                va="top",
                color="#6B7280",
                fontsize=8,
            )
    lane.text(
        2,
        -0.49,
        "Parent trajectory: P0 → P0 → P2 → P2 → P2",
        ha="center",
        va="top",
        color="#4B5563",
        fontsize=9,
    )

    figure.subplots_adjust(left=0.075, right=0.965, top=0.90, bottom=0.08)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        output_prefix.with_suffix(".png"),
        dpi=220,
        facecolor="white",
        bbox_inches="tight",
    )
    figure.savefig(
        output_prefix.with_suffix(".svg"),
        facecolor="white",
        bbox_inches="tight",
    )
    plt.close(figure)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output-prefix", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    render(load_rows(args.data), args.output_prefix)
    print(args.output_prefix.with_suffix(".png"))
    print(args.output_prefix.with_suffix(".svg"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
