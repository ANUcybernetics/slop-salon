# /// script
# requires-python = ">=3.12"
# dependencies = ["scikit-learn", "numpy"]
# ///
"""First-cut pilot: convergence/divergence of Slop Salon agents.

For each agent repo, take weekly snapshots of the full tracked markdown corpus
(top-level *.md + notes/), then compute TF-IDF cosine similarities:
  - self-to-seed: how far each agent has drifted from its own seed state
  - self-to-previous-week: identity continuity week over week
  - mean pairwise inter-agent similarity at each snapshot date
Divergence signal = pairwise similarity falling over time while week-to-week
self-similarity stays high.
"""

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


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def rev_at(repo: Path, day: date) -> str | None:
    out = git(repo, "rev-list", "-1", f"--before={day.isoformat()}T23:59:59", "HEAD")
    return out.strip() or None


def corpus_at(repo: Path, rev: str) -> str:
    files = [
        f
        for f in git(repo, "ls-tree", "-r", rev, "--name-only").splitlines()
        if f.endswith(".md") and (("/" not in f) or f.startswith("notes/"))
    ]
    parts = []
    for f in sorted(files):
        blob = subprocess.run(
            ["git", "-C", str(repo), "show", f"{rev}:{f}"],
            capture_output=True,
            text=True,
        )
        if blob.returncode == 0:
            parts.append(blob.stdout)
    return "\n".join(parts)


def main() -> None:
    weeks = []
    d = START
    while d <= END:
        weeks.append(d)
        d += timedelta(days=7)

    docs: dict[tuple[str, str], str] = {}  # (agent, label) -> text
    for agent in AGENTS:
        repo = AGENT_REPOS_DIR / f"slop-salon-{agent}"
        seed_rev = git(repo, "rev-list", "--max-parents=0", "HEAD").strip().splitlines()[-1]
        docs[(agent, "seed")] = corpus_at(repo, seed_rev)
        for wk in weeks:
            rev = rev_at(repo, wk)
            if rev:
                docs[(agent, wk.isoformat())] = corpus_at(repo, rev)

    keys = list(docs)
    vec = TfidfVectorizer(sublinear_tf=True, min_df=2)
    X = vec.fit_transform([docs[k] for k in keys])
    sim = cosine_similarity(X)
    idx = {k: i for i, k in enumerate(keys)}

    def s(a: tuple[str, str], b: tuple[str, str]) -> float:
        return float(sim[idx[a], idx[b]])

    print(f"{'week':<12} {'self→seed':>10} {'self→prev':>10} {'pairwise':>10}")
    prev_label: str | None = None
    for wk in weeks:
        label = wk.isoformat()
        present = [a for a in AGENTS if (a, label) in idx]
        to_seed = np.mean([s((a, label), (a, "seed")) for a in present])
        to_prev = (
            np.mean(
                [
                    s((a, label), (a, prev_label))
                    for a in present
                    if prev_label and (a, prev_label) in idx
                ]
            )
            if prev_label
            else float("nan")
        )
        pairwise = np.mean(
            [s((a, label), (b, label)) for a, b in itertools.combinations(present, 2)]
        )
        print(f"{label:<12} {to_seed:>10.3f} {to_prev:>10.3f} {pairwise:>10.3f}")
        prev_label = label

    print("\nfinal-week pairwise matrix:")
    last = END.isoformat()
    print("        " + "  ".join(f"{a:>6}" for a in AGENTS))
    for a in AGENTS:
        row = "  ".join(f"{s((a, last), (b, last)):>6.3f}" if a != b else "     -" for b in AGENTS)
        print(f"{a:>6}  {row}")

    print("\nseed pairwise (sanity check — should be ~identical):")
    seed_sims = [s((a, "seed"), (b, "seed")) for a, b in itertools.combinations(AGENTS, 2)]
    print(f"mean {np.mean(seed_sims):.3f}  min {np.min(seed_sims):.3f}")


main()
