# /// script
# requires-python = ">=3.12"
# dependencies = ["matplotlib"]
# ///
"""Build the quantitative exhibit (Figure 2) from the committed pilot results.

Numbers are transcribed from pilot-drift-results.txt and pilot-flow-results.txt
rather than recomputed, so the figure and the prose in section 4 cannot drift
apart. Season one ran 2026-05-25 to 2026-07-27; all six agent repos stopped
pushing on 2026-07-27, so those results are final.

Left panel: between-agent similarity (solid) and within-agent week-to-week
self-similarity (dashed), for the stock view (full corpus, blue) and the flow
view (that week's new writing only, orange).
Right panel: cross-agent flow similarity, same week vs different weeks.

Colour encodes the view; line style encodes the comparison, so neither is
carried by colour alone.
"""

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

BASE = Path(__file__).parent
OUT = BASE / "similarity.pdf"  # copy into the paper repo's figures/ when it changes

STOCK = "#2a78d6"  # categorical slot 1
FLOW = "#eb6834"  # categorical slot 2
INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "#d8d7d2"

# week 0 is the seed commit; weeks 1..10 are the Monday snapshots
# 2026-05-25 through 2026-07-27.
WEEKS = list(range(11))

# pilot-drift-results.txt (full tracked markdown corpus at each snapshot)
STOCK_PAIRWISE = [
    0.942,
    0.645,
    0.625,
    0.623,
    0.628,
    0.616,
    0.622,
    0.613,
    0.618,
    0.610,
    0.629,
]
STOCK_SELF_PREV = [
    None,
    None,
    0.899,
    0.896,
    0.930,
    0.912,
    0.942,
    0.947,
    0.932,
    0.947,
    0.968,
]

# pilot-flow-results.txt (added lines only; no seed value; the 2026-07-06
# snapshot -- week 7 in the paper's 1-indexed convention -- has n=5)
FLOW_PAIRWISE = [
    None,
    0.603,
    0.463,
    0.530,
    0.565,
    0.504,
    0.508,
    0.571,
    0.602,
    0.591,
    0.590,
]
FLOW_SELF_PREV = [
    None,
    None,
    0.398,
    0.418,
    0.443,
    0.455,
    0.433,
    0.466,
    0.540,
    0.477,
    0.533,
]

SAME_WEEK, CROSS_WEEK = 0.552, 0.391


def style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Nimbus Roman", "Times New Roman", "DejaVu Serif"],
            "font.size": 8,
            "axes.edgecolor": MUTED,
            "axes.labelcolor": INK,
            "text.color": INK,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
        }
    )


def series(ax, xs, ys, **kw):
    """Plot a series with gaps where the measure is undefined."""
    pts = [(x, y) for x, y in zip(xs, ys, strict=True) if y is not None]
    ax.plot([p[0] for p in pts], [p[1] for p in pts], **kw)


def left(ax) -> None:
    ax.grid(axis="y", color=GRID, linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)

    # the seed is a between-agent value: keep it on that line, or a reader
    # will read it off the within-agent line running at the same height
    series(
        ax,
        WEEKS,
        STOCK_PAIRWISE,
        color=STOCK,
        lw=1.6,
        marker="o",
        ms=2.6,
        label="stock, between-agent",
    )
    series(
        ax,
        WEEKS,
        STOCK_SELF_PREV,
        color=STOCK,
        lw=1.4,
        ls="--",
        marker="o",
        ms=2.6,
        label="stock, within-agent",
    )
    series(
        ax,
        WEEKS,
        FLOW_PAIRWISE,
        color=FLOW,
        lw=1.6,
        marker="o",
        ms=2.6,
        label="flow, between-agent",
    )
    series(
        ax,
        WEEKS,
        FLOW_SELF_PREV,
        color=FLOW,
        lw=1.4,
        ls="--",
        marker="o",
        ms=2.6,
        label="flow, within-agent",
    )

    # the seed sits apart from the season: mark it, don't connect it
    ax.plot(
        [0],
        [STOCK_PAIRWISE[0]],
        marker="o",
        ms=4.5,
        mfc="white",
        mec=STOCK,
        mew=1.4,
        zorder=5,
    )
    ax.annotate(
        "seed 0.94",
        (0, STOCK_PAIRWISE[0]),
        textcoords="offset points",
        xytext=(4, 2),
        fontsize=7,
        color=MUTED,
    )
    ax.annotate(
        "0.65",
        (1, STOCK_PAIRWISE[1]),
        textcoords="offset points",
        xytext=(2, 6),
        fontsize=7,
        color=STOCK,
    )

    ax.set_xlim(-0.4, 10.6)
    ax.set_ylim(0.30, 1.0)
    ax.set_xticks([0, 2, 4, 6, 8, 10])
    ax.set_xticklabels(["seed", "2", "4", "6", "8", "10"])
    ax.set_xlabel("week of season")
    ax.set_ylabel("mean cosine similarity")
    ax.set_title(
        "(a) divergence appears early, then holds", fontsize=8, loc="left", pad=6
    )
    # park the legend in the empty band between the two blue series
    ax.legend(
        frameon=False,
        fontsize=6.5,
        loc="center",
        bbox_to_anchor=(0.58, 0.68),
        handlelength=2.2,
        labelspacing=0.3,
        borderpad=0.2,
    )


def right(ax) -> None:
    ax.grid(axis="y", color=GRID, linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)

    bars = ax.bar(
        [0, 1],
        [SAME_WEEK, CROSS_WEEK],
        width=0.5,
        color=FLOW,
        edgecolor="white",
        linewidth=1.0,
        zorder=2,
    )
    for bar, val in zip(bars, [SAME_WEEK, CROSS_WEEK], strict=True):
        ax.annotate(
            f"{val:.2f}",
            (bar.get_x() + bar.get_width() / 2, val),
            textcoords="offset points",
            xytext=(0, 3),
            ha="center",
            fontsize=7.5,
            color=INK,
        )

    ax.set_xlim(-0.6, 1.6)
    ax.set_ylim(0, 0.68)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["same\nweek", "different\nweeks"])
    ax.set_ylabel("mean cosine similarity")
    ax.set_title("(b) cross-agent flow moves in time", fontsize=8, loc="left", pad=6)


def main() -> None:
    style()
    OUT.parent.mkdir(exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(
        1,
        2,
        figsize=(5.5, 2.3),
        gridspec_kw={"width_ratios": [1.75, 1], "wspace": 0.34},
    )
    left(ax1)
    right(ax2)
    fig.savefig(OUT, bbox_inches="tight", pad_inches=0.02)
    print(f"wrote {OUT}")


main()
