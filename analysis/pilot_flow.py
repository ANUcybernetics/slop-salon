# /// script
# requires-python = ">=3.12"
# dependencies = ["scikit-learn", "numpy"]
# ///
"""Flow variant of the drift pilot: compare each agent's NEW writing per week
(added lines in *.md files), not the cumulative corpus. Pairwise similarity of
weekly flow is the cleaner convergence/divergence measure."""

import itertools
import subprocess
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

BASE = Path(__file__).parent
# Clone the six public agent repos (ANUcybernetics/slop-salon-<name>)
# into analysis/agent-repos/ before running; the directory is gitignored.
AGENT_REPOS_DIR = BASE / "agent-repos"
AGENTS = ["rahel", "vita", "lelia", "mina", "lou", "gert"]
START = date(2026, 5, 25)
END = date(2026, 7, 27)


def weekly_flow(repo: Path, since: date, until: date) -> str:
    out = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "log",
            f"--since={since.isoformat()}T00:00:00",
            f"--until={until.isoformat()}T00:00:00",
            "-p",
            "--diff-filter=AM",
            "--",
            "*.md",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    added = [
        line[1:] for line in out.splitlines() if line.startswith("+") and not line.startswith("+++")
    ]
    return "\n".join(added)


def main() -> None:
    weeks = []
    d = START
    while d <= END:
        weeks.append(d)
        d += timedelta(days=7)

    docs: dict[tuple[str, str], str] = {}
    for agent in AGENTS:
        repo = AGENT_REPOS_DIR / f"slop-salon-{agent}"
        for wk in weeks:
            text = weekly_flow(repo, wk - timedelta(days=7), wk)
            if len(text) > 500:  # skip near-empty weeks
                docs[(agent, wk.isoformat())] = text

    keys = list(docs)
    vec = TfidfVectorizer(sublinear_tf=True, min_df=2)
    X = vec.fit_transform([docs[k] for k in keys])
    sim = cosine_similarity(X)
    idx = {k: i for i, k in enumerate(keys)}

    def s(a: tuple[str, str], b: tuple[str, str]) -> float:
        return float(sim[idx[a], idx[b]])

    print(f"{'week':<12} {'n':>2} {'self→prev':>10} {'pairwise':>10}")
    prev: str | None = None
    for wk in weeks:
        label = wk.isoformat()
        present = [a for a in AGENTS if (a, label) in idx]
        if len(present) < 2:
            prev = label
            continue
        pairwise = np.mean(
            [s((a, label), (b, label)) for a, b in itertools.combinations(present, 2)]
        )
        selfprev = (
            np.mean([s((a, label), (a, prev)) for a in present if prev and (a, prev) in idx])
            if prev
            else float("nan")
        )
        print(f"{label:<12} {len(present):>2} {selfprev:>10.3f} {pairwise:>10.3f}")
        prev = label

    last = END.isoformat()
    present = [a for a in AGENTS if (a, last) in idx]
    print("\nfinal-week flow pairwise matrix:")
    print("        " + "  ".join(f"{a:>6}" for a in present))
    for a in present:
        row = "  ".join(f"{s((a, last), (b, last)):>6.3f}" if a != b else "     -" for b in present)
        print(f"{a:>6}  {row}")

    # cross-agent same-week vs cross-week baseline: is same-week flow more
    # similar than different-week flow (shared arcs pulling them together)?
    same_week, cross_week = [], []
    for (a, wa), (b, wb) in itertools.combinations(keys, 2):
        if a == b:
            continue
        (same_week if wa == wb else cross_week).append(s((a, wa), (b, wb)))
    print(
        f"\ncross-agent similarity: same week {np.mean(same_week):.3f} "
        f"vs different weeks {np.mean(cross_week):.3f}"
    )


main()
