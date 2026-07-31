# /// script
# requires-python = ">=3.12"
# dependencies = ["scikit-learn", "numpy"]
# ///
"""Robustness analysis for the flow pilot (see pilot_flow.py in
research-papers/slop-salon-neurips-2026/analysis/). The paper's headline flow
finding is that cross-agent similarity of newly written text is higher within
the same week (0.552) than across different weeks (0.391). This script
reruns that comparison under four confound-control variants plus a temporal
baseline swap and a permutation test, so reviewers' objections can be
checked directly rather than argued about:

  1. BASELINE       - replicate the existing flow numbers (sanity check).
  2. NO-DOSSIERS     - drop files that are explicitly about siblings (each
                       agent keeps a SIBLINGS.md/SIBLINGS-archive.md dossier
                       and notes/ reply-to-sibling files that quote and name
                       siblings directly) so same-week synchrony isn't just
                       agents echoing each other's names/quotes back.
  3. SCRUBBED        - strip ISO dates/timestamps and the six agent names
                       from the text before vectorising, so synchrony isn't
                       just shared date-stamps or name-dropping.
  4. NO-DOSSIERS + SCRUBBED combined (the "strongest" control).
  5. LAG-1 BASELINE  - swap "all different-week pairs" for adjacent-week
                       (lag-1) cross-agent pairs only, since global temporal
                       drift (the stock-view divergence) deflates the
                       all-pairs baseline; reported with and without week 1
                       (2026-05-25), which still carries seed vocabulary.
  6. PERMUTATION TEST - for the no-dossiers+scrubbed variant, shuffle each
                       agent's week labels (keeping their set of weekly
                       documents fixed) 1000 times and see how extreme the
                       observed same-minus-different gap is.

This repo (slop-salon) pins requires-python >=3.14 in pyproject.toml; this
script deliberately stays a self-contained uv script (>=3.12, its own inline
deps) rather than adding scikit-learn/numpy to the project, matching how
pilot_drift.py / pilot_flow.py are shipped in the paper repo.
"""

import itertools
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# The six agent repos are cloned (full history) outside both git trees, into
# the session scratchpad, per the coordinator's instruction not to touch
# either the papers repo or the slop-salon harness repo with clone data:
AGENT_REPOS_DIR = Path(
    "/tmp/claude-1001/-home-ben-projects-research-papers"
    "/89c40643-6b8f-4177-9498-55c96b682692/scratchpad/agent-repos"
)

AGENTS = ["rahel", "vita", "lelia", "mina", "lou", "gert"]
START = date(2026, 5, 25)
END = date(2026, 7, 27)
WEEK1 = START.isoformat()

DocKey = tuple[str, str]  # (agent, week-label)

# --- dossier exclusion -------------------------------------------------
# Every repo carries a top-level SIBLINGS.md + SIBLINGS-archive.md (running
# per-sibling observation logs, one ## section per sibling, quoting their
# posts by name) and notes/ files that are explicit replies to a named
# sibling (e.g. notes/2026-07-19T23b-reply-lelia.md, or lou's own
# notes/SIBLINGS.md). We exclude any *.md path where a path component
# (directory name or filename stem) contains the literal word "sibling(s)"
# or one of the *other* five agents' names as a whole word - e.g.
# "reply-lelia-transition" and "2026-05-20-vita-lelia" match, but
# "2026-07-21-envelope-discriminant" does NOT (naive substring matching
# would wrongly hit "mina" inside "discriminant"; \b prevents that).
DOSSIER_RE_CACHE: dict[str, re.Pattern[str]] = {}


def dossier_pattern(agent: str) -> re.Pattern[str]:
    if agent not in DOSSIER_RE_CACHE:
        siblings = [s for s in AGENTS if s != agent]
        DOSSIER_RE_CACHE[agent] = re.compile(
            rf"\b(siblings?|{'|'.join(siblings)})\b", re.IGNORECASE
        )
    return DOSSIER_RE_CACHE[agent]


def is_dossier_path(agent: str, path: str) -> bool:
    pattern = dossier_pattern(agent)
    parts = [Path(p).stem for p in Path(path).parts]
    return any(pattern.search(part) for part in parts)


# --- scrubbing -----------------------------------------------------------
# ISO date (with optional T-time, colon- or hyphen-separated minutes/seconds)
# and bare-time patterns, plus the six agent names, stripped before
# vectorising for the SCRUBBED variants.
DATE_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}[:-]\d{2}(?:[:-]\d{2})?"  # 2026-07-11T19-08:03 etc
    r"|\d{4}-\d{2}-\d{2}"  # 2026-07-11
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\b"  # 21:09, 08:13:00
)
NAME_RE = re.compile(r"\b(" + "|".join(AGENTS) + r")\b", re.IGNORECASE)


def scrub(text: str) -> str:
    text = DATE_RE.sub(" ", text)
    text = NAME_RE.sub(" ", text)
    return text


# --- corpus construction ---------------------------------------------------


def weekly_flow(repo: Path, agent: str, since: date, until: date, exclude_dossiers: bool) -> str:
    """Added *.md lines in [since, until), optionally dropping lines that
    belong to a dossier/sibling-reply file. Mirrors pilot_flow.py's
    weekly_flow() exactly when exclude_dossiers=False."""
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

    added = []
    skip = False
    for line in out.splitlines():
        if line.startswith("+++ "):
            fpath = line[4:]
            if fpath.startswith("b/"):
                fpath = fpath[2:]
            skip = exclude_dossiers and is_dossier_path(agent, fpath)
            continue
        if line.startswith("+") and not line.startswith("+++") and not skip:
            added.append(line[1:])
    return "\n".join(added)


def weekly_grid() -> list[date]:
    weeks = []
    d = START
    while d <= END:
        weeks.append(d)
        d += timedelta(days=7)
    return weeks


def build_docs(exclude_dossiers: bool) -> dict[DocKey, str]:
    """Near-empty-week filtering (>500 chars) is applied before scrubbing
    (scrubbing happens afterwards, separately, by the caller) so dossier
    exclusion can legitimately drop a week (that's the point of the
    control) but scrubbing - which only removes short date/name tokens -
    can't spuriously change which weeks are in-sample across variants."""
    docs: dict[DocKey, str] = {}
    for agent in AGENTS:
        repo = AGENT_REPOS_DIR / f"slop-salon-{agent}"
        for wk in weekly_grid():
            text = weekly_flow(repo, agent, wk - timedelta(days=7), wk, exclude_dossiers)
            if len(text) > 500:
                docs[(agent, wk.isoformat())] = text
    return docs


def count_excluded_files() -> dict[str, int]:
    """Count how many *.md files (top-level + notes/, i.e. anything git
    tracks that pilot_flow.py's pathspec would ever surface) match the
    dossier-exclusion pattern per agent, for reporting."""
    counts = {}
    for agent in AGENTS:
        repo = AGENT_REPOS_DIR / f"slop-salon-{agent}"
        files = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "*.md"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        counts[agent] = sum(1 for f in files if is_dossier_path(agent, f))
    return counts


# --- similarity machinery ---------------------------------------------------


def similarity_matrix(docs: dict[DocKey, str]) -> tuple[list[DocKey], np.ndarray]:
    keys = list(docs)
    vec = TfidfVectorizer(sublinear_tf=True, min_df=2)
    tfidf = vec.fit_transform([docs[k] for k in keys])
    return keys, cosine_similarity(tfidf)


def same_vs_diff(
    keys: list[DocKey],
    sim: np.ndarray,
    idx: dict[DocKey, int],
    mode: str = "all",
    exclude_week1: bool = False,
) -> tuple[float, float, int, int]:
    """mode='all' replicates pilot_flow.py's cross-agent same-week vs
    different-week comparison exactly. mode='lag1' restricts the
    different-week bucket to calendar-adjacent (lag-1) weeks only."""
    grid = [w.isoformat() for w in weekly_grid()]
    week_index = {w: i for i, w in enumerate(grid)}
    same_vals, other_vals = [], []
    for (a, wa), (b, wb) in itertools.combinations(keys, 2):
        if a == b:
            continue
        if exclude_week1 and (wa == WEEK1 or wb == WEEK1):
            continue
        sv = sim[idx[(a, wa)], idx[(b, wb)]]
        if wa == wb:
            same_vals.append(sv)
        elif mode == "all":
            other_vals.append(sv)
        elif mode == "lag1":
            if abs(week_index[wa] - week_index[wb]) == 1:
                other_vals.append(sv)
        else:
            raise ValueError(f"unknown mode {mode!r}")
    same_mean = float(np.mean(same_vals)) if same_vals else float("nan")
    other_mean = float(np.mean(other_vals)) if other_vals else float("nan")
    return same_mean, other_mean, len(same_vals), len(other_vals)


def print_weekly_table(docs: dict[DocKey, str], keys: list[DocKey], sim: np.ndarray) -> None:
    """Reproduces pilot_flow.py's main per-week table + final-week matrix
    verbatim, for the BASELINE reproducibility check."""
    idx = {k: i for i, k in enumerate(keys)}

    def s(a: DocKey, b: DocKey) -> float:
        return float(sim[idx[a], idx[b]])

    print(f"{'week':<12} {'n':>2} {'self→prev':>10} {'pairwise':>10}")
    prev: str | None = None
    for wk in weekly_grid():
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


# --- permutation test --------------------------------------------------


def permutation_test(
    keys: list[DocKey], sim: np.ndarray, n_perm: int = 1000, seed: int = 0
) -> tuple[float, np.ndarray, float]:
    """Shuffle each agent's week labels among its own present weeks
    (documents/texts fixed, labels reassigned within-agent), 1000 times,
    and recompute the cross-agent same-week-minus-different-week (all
    pairs) gap each time. Since text identity never changes, the
    similarity matrix is computed once; only the same/different
    classification of each pair is relabelled per permutation."""
    grid = [w.isoformat() for w in weekly_grid()]
    week_index = {w: i for i, w in enumerate(grid)}
    agent_idx = np.array([AGENTS.index(a) for a, _ in keys])
    orig_week = np.array([week_index[w] for _, w in keys])

    n = len(keys)
    ii, jj = np.triu_indices(n, k=1)
    cross = agent_idx[ii] != agent_idx[jj]
    ii, jj = ii[cross], jj[cross]
    pair_sims = sim[ii, jj]

    def gap_for(week_arr: np.ndarray) -> float:
        same = week_arr[ii] == week_arr[jj]
        return float(pair_sims[same].mean() - pair_sims[~same].mean())

    observed = gap_for(orig_week)

    rng = np.random.default_rng(seed)
    agent_groups = [np.where(agent_idx == ai)[0] for ai in range(len(AGENTS))]
    perm_gaps = np.empty(n_perm)
    for p in range(n_perm):
        perm_week = orig_week.copy()
        for idxs in agent_groups:
            if len(idxs) > 1:
                perm_week[idxs] = rng.permutation(orig_week[idxs])
        perm_gaps[p] = gap_for(perm_week)

    p_value = float((np.sum(perm_gaps >= observed) + 1) / (n_perm + 1))
    return observed, perm_gaps, p_value


# --- main -----------------------------------------------------------------


def main() -> None:
    print("=" * 78)
    print("1. BASELINE (replicates pilot_flow.py exactly)")
    print("=" * 78)
    base_docs = build_docs(exclude_dossiers=False)
    base_keys, base_sim = similarity_matrix(base_docs)
    base_idx = {k: i for i, k in enumerate(base_keys)}
    print_weekly_table(base_docs, base_keys, base_sim)
    b_same, b_diff, b_n_same, b_n_diff = same_vs_diff(base_keys, base_sim, base_idx, mode="all")
    print(
        f"\ncross-agent similarity: same week {b_same:.3f} (n={b_n_same}) "
        f"vs different weeks {b_diff:.3f} (n={b_n_diff})"
    )

    print()
    print("=" * 78)
    print("2-4. CONFOUND-CONTROL VARIANTS")
    print("=" * 78)
    excluded_counts = count_excluded_files()
    print("dossier files excluded per agent (of all git-tracked *.md):")
    for agent, n in excluded_counts.items():
        print(f"  {agent:<7} {n}")

    # Only two distinct git-log passes are needed (dossier-filtered or not);
    # SCRUBBED variants are derived by scrubbing the already-built docs
    # rather than re-running git log, since scrubbing never changes which
    # weeks clear the >500-char threshold (see build_docs docstring).
    nodossier_docs = build_docs(exclude_dossiers=True)
    variants: list[tuple[str, dict[DocKey, str]]] = [
        ("BASELINE", base_docs),
        ("NO-DOSSIERS", nodossier_docs),
        ("SCRUBBED", {k: scrub(v) for k, v in base_docs.items()}),
        ("NO-DOSSIERS+SCRUBBED", {k: scrub(v) for k, v in nodossier_docs.items()}),
    ]

    print()
    print(
        f"{'variant':<22} {'n_docs':>6} {'same-wk':>9} {'diff-wk':>9} {'gap':>7} "
        f"{'n_same':>7} {'n_diff':>7}"
    )
    variant_sims: dict[str, tuple[list[DocKey], np.ndarray]] = {}
    for name, docs in variants:
        keys, sim = similarity_matrix(docs)
        idx = {k: i for i, k in enumerate(keys)}
        same, diff, n_same, n_diff = same_vs_diff(keys, sim, idx, mode="all")
        variant_sims[name] = (keys, sim)
        print(
            f"{name:<22} {len(docs):>6} {same:>9.3f} {diff:>9.3f} {same - diff:>7.3f} "
            f"{n_same:>7} {n_diff:>7}"
        )

    print()
    print("=" * 78)
    print("5. LAG-1 BASELINE (adjacent-week cross-agent pairs vs same-week)")
    print("=" * 78)
    print(f"{'week1':<12} {'same-wk':>9} {'lag-1':>9} {'gap':>7} {'n_same':>7} {'n_lag1':>7}")
    for label, excl in [("included", False), ("excluded", True)]:
        same, lag1, n_same, n_lag1 = same_vs_diff(
            base_keys, base_sim, base_idx, mode="lag1", exclude_week1=excl
        )
        print(f"{label:<12} {same:>9.3f} {lag1:>9.3f} {same - lag1:>7.3f} {n_same:>7} {n_lag1:>7}")

    print()
    print("=" * 78)
    print("6. PERMUTATION TEST (strongest variant: NO-DOSSIERS+SCRUBBED)")
    print("=" * 78)
    strong_keys, strong_sim = variant_sims["NO-DOSSIERS+SCRUBBED"]
    observed, perm_gaps, p_value = permutation_test(strong_keys, strong_sim, n_perm=1000, seed=0)
    print(f"observed same-minus-different gap: {observed:.4f}")
    print(f"permuted gap mean: {perm_gaps.mean():.4f}  std: {perm_gaps.std():.4f}")
    print(f"permuted gap [min, max]: [{perm_gaps.min():.4f}, {perm_gaps.max():.4f}]")
    print(f"p-value (one-sided, permuted >= observed, 1000 perms, +1 smoothing): {p_value:.4f}")


main()
