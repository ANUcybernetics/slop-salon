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
    0.943,
    0.644,
    0.626,
    0.626,
    0.630,
    0.618,
    0.628,
    0.622,
    0.617,
    0.611,
    0.630,
]
STOCK_SELF_PREV = [
    None,
    None,
    0.897,
    0.901,
    0.932,
    0.912,
    0.938,
    0.937,
    0.946,
    0.952,
    0.968,
]

# pilot-flow-results.txt (added lines only; no seed value). All ten snapshots
# carry n=6 since the pilots moved to author-date bucketing; the n=5 week in the
# earlier run was one agent's 16-day push failure, not a quiet week.
FLOW_PAIRWISE = [
    None,
    0.601,
    0.472,
    0.533,
    0.555,
    0.504,
    0.539,
    0.558,
    0.617,
    0.591,
    0.587,
]
FLOW_SELF_PREV = [
    None,
    None,
    0.398,
    0.415,
    0.441,
    0.449,
    0.434,
    0.444,
    0.513,
    0.479,
    0.527,
]

# Panel (b): what a week's new writing is closest to. Cross-agent same-week
# beats an agent's own previous week in all nine comparable weeks, which is the
# claim the abstract makes and the bars have to show.
SAME_WEEK, CROSS_WEEK = 0.556, 0.390
OWN_PREV_WEEK = 0.456


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
        "0.64",
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
    ax.set_title("(a) divergence appears early, then holds", fontsize=8, loc="left", pad=6)
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

    # Siblings first, own-previous-week second: the gap between bars one and
    # two is the finding, so they have to sit next to each other.
    vals = [SAME_WEEK, OWN_PREV_WEEK, CROSS_WEEK]
    bars = ax.bar(
        [0, 1, 2],
        vals,
        width=0.5,
        color=[FLOW, STOCK, FLOW],
        edgecolor="white",
        linewidth=1.0,
        zorder=2,
    )
    for bar, val in zip(bars, vals, strict=True):
        ax.annotate(
            f"{val:.2f}",
            (bar.get_x() + bar.get_width() / 2, val),
            textcoords="offset points",
            xytext=(0, 3),
            ha="center",
            fontsize=7.5,
            color=INK,
        )

    ax.set_xlim(-0.6, 2.6)
    ax.set_ylim(0, 0.68)
    ax.set_xticks([0, 1, 2])
    ax.set_xticklabels(
        ["siblings\nthis week", "itself\nlast week", "siblings\nother weeks"], fontsize=6.5
    )
    ax.set_ylabel("mean cosine similarity")
    ax.set_title("(b) what a week's new writing resembles", fontsize=8, loc="left", pad=6)


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
