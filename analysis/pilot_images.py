# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "httpx>=0.27",
#     "pillow>=10",
#     "numpy>=1.26",
#     "torch>=2.2",
#     "transformers>=4.49",
#     "sentencepiece>=0.2",
#     "protobuf>=4",
# ]
# ///
"""Image-embedding pilot: do the six agents' posted works actually form
distinct visual "niches", and is the late-season drift toward technical
plots (main.tex Figure 3's caption) real across the full pools?

Companion to pilot_drift.py and pilot_flow.py in this directory (lexical,
TF-IDF over markdown) and make_mosaic.py (which this script's fetch step is
adapted from). This one is visual: every image
each agent has ever posted, embedded locally, no external inference APIs.

Two embedding spaces, run side by side:
  - SigLIP 2 base (google/siglip2-base-patch16-224) --- text-aligned, so it
    also does the zero-shot technical-plot classification for (d).
  - DINOv2 base (facebook/dinov2-base) --- purely visual, no text tower. The
    robustness check: if "visual niches" only show up in a text-aligned
    space, that space may be measuring subject matter (what the alt-text-ish
    content of a work is *about*) rather than visual style. DINOv2 has no
    language grounding at all, so agreement between the two is the stronger
    claim. (ColNomic-style late-interaction retrieval models were considered
    and rejected --- they're built for multi-vector document retrieval, not
    single-vector image style embedding; DINOv2 is the deliberate substitute
    for "a second, independent embedding space".)

Pipeline:
  1. Fetch each agent's full pool of posted images + post timestamps from the
     Bluesky public API (same app.bsky.feed.getAuthorFeed approach as
     make_mosaic.py: one image per post, the post's first image only).
     Feed metadata and raw image bytes are cached under CACHE_DIR so reruns
     are cheap --- season one is over, the feeds are static.
  2. Embed every image in both spaces. Both are base-size encoders, small
     enough to batch on CPU; uses CUDA if torch reports it available, but
     never requires it. Embeddings (and SigLIP 2's technical-plot logit
     margin, computed in the same forward pass) are cached to .npz files
     keyed by image URL.
  3. Four analyses, printed with clear labels and dumped to JSON. (a), (b),
     (c) run in BOTH spaces; (d) is SigLIP 2 only (it is the only one with a
     text tower to run zero-shot against prompts):
       a. leave-one-out agent identification (nearest-centroid, 5-NN)
       b. within- vs between-agent cosine similarity, + pairwise matrix
       c. temporal: same-week vs different-week cross-agent similarity,
          and a per-week between-agent similarity curve (image-space
          analogue of Figure 4a)
       d. zero-shot CLIP-style classification against two prompts to
          quantify the late-season drift toward labelled technical plots
          (Figure 3): fraction classified as technical plot per agent per
          week

Run: uv run analysis/pilot_images.py | tee analysis/pilot-images-results.txt
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import numpy as np
import torch
from PIL import Image, UnidentifiedImageError

API = "https://public.api.bsky.app/xrpc"
AGENTS = ["rahel", "vita", "lelia", "mina", "lou", "gert"]
START = date(2026, 5, 25)
END = date(2026, 7, 27)
END_CUTOFF = datetime(2026, 7, 27, 23, 59, 59, tzinfo=UTC)

# Model tier: "base" (CPU-friendly) or "large" (current-gen, wants a GPU).
# DINOv3 would be the current-gen visual-only pick, but its checkpoints are
# gated on Hugging Face (403 without per-account approval), so the large tier
# uses DINOv2-giant: same family, ungated, and still a pure-vision encoder.
TIER = os.environ.get("PILOT_IMAGES_TIER", "base")
if TIER == "large":
    SIGLIP_MODEL = "google/siglip2-so400m-patch16-384"
    DINO_MODEL = "facebook/dinov2-giant"
else:
    SIGLIP_MODEL = "google/siglip2-base-patch16-224"
    DINO_MODEL = "facebook/dinov2-base"
TECH_PROMPT = "a scientific plot or chart with labelled axes and text"
ABSTRACT_PROMPT = "an abstract artwork or photograph"

CACHE_DIR = Path(
    "/tmp/claude-1001/-home-ben-projects-research-papers/"
    "89c40643-6b8f-4177-9498-55c96b682692/scratchpad/slop-images"
)
IMAGES_DIR = CACHE_DIR / "images"
HF_CACHE_DIR = CACHE_DIR / "hf-weights"
_SUF = "" if TIER == "base" else f"-{TIER}"
SIGLIP_EMB_CACHE = CACHE_DIR / f"embeddings-siglip2{_SUF}.npz"
SIGLIP_MARGIN_CACHE = CACHE_DIR / f"tech-margin-siglip2{_SUF}.npz"
DINO_EMB_CACHE = CACHE_DIR / f"embeddings-dinov2{_SUF}.npz"

HERE = Path(__file__).parent
DATA_JSON = HERE / f"pilot-images-data{_SUF}.json"

K_NEIGHBOURS = 5
DOWNLOAD_WORKERS = 12
BATCH_SIZE = 64

# DINOv2's published preprocessing (resize shortest edge 256, center-crop 224,
# ImageNet normalisation). Done by hand with PIL/numpy rather than via
# transformers' AutoImageProcessor, which pulls in torchvision as a hard
# import-time dependency in current transformers even when unused --- a much
# heavier and more version-fragile dependency than this ~10-line reimplementation.
DINO_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
DINO_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


@dataclass(slots=True)
class Work:
    agent: str
    url: str
    created_at: datetime
    week: str = field(default="")

    @property
    def cache_path(self) -> Path:
        h = hashlib.sha1(self.url.encode()).hexdigest()
        return IMAGES_DIR / f"{h}.bin"


# --------------------------------------------------------------------------
# 1. Fetch: Bluesky feed metadata + image bytes, cached under CACHE_DIR.
# --------------------------------------------------------------------------


def get_json_with_backoff(client: httpx.Client, url: str, params: dict) -> dict:
    delay = 1.0
    for attempt in range(6):
        r = client.get(url, params=params)
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == 5:
                r.raise_for_status()
            print(
                f"  {r.status_code} on {url}, retry {attempt + 1} in {delay:.0f}s",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay = min(delay * 2, 60)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("unreachable")


def fetch_agent_feed(client: httpx.Client, handle: str) -> list[dict]:
    """Return [{"url": fullsize image url, "createdAt": iso str}, ...], newest first.

    One image per post (the post's first image), matching make_mosaic.py's
    all_images() convention. Cached to disk --- season one's feeds are static.
    """
    cache_file = CACHE_DIR / f"feed-{handle}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    items: list[dict] = []
    cursor = None
    while True:
        params = {"actor": f"{handle}.slopsalon.art", "filter": "posts_with_media", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        data = get_json_with_backoff(client, f"{API}/app.bsky.feed.getAuthorFeed", params)
        for item in data.get("feed", []):
            post = item["post"]
            embed = post.get("embed", {}) or {}
            images = embed.get("images") or (embed.get("media", {}) or {}).get("images")
            if images:
                created_at = post.get("record", {}).get("createdAt") or post.get("indexedAt")
                items.append({"url": images[0]["fullsize"], "createdAt": created_at})
        cursor = data.get("cursor")
        if not cursor:
            break
        time.sleep(0.2)  # be polite between pages

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(items))
    return items


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso_week_monday(d: date) -> str:
    iso_year, iso_week, _ = d.isocalendar()
    return date.fromisocalendar(iso_year, iso_week, 1).isoformat()


def fetch_all_pools(client: httpx.Client) -> dict[str, list[Work]]:
    pools: dict[str, list[Work]] = {}
    for agent in AGENTS:
        raw = fetch_agent_feed(client, agent)
        works = []
        for item in raw:
            dt = parse_dt(item["createdAt"])
            if dt <= END_CUTOFF:
                w = Work(agent=agent, url=item["url"], created_at=dt)
                w.week = iso_week_monday(dt.date())
                works.append(w)
        pools[agent] = works
        n_after_cutoff = len(raw) - len(works)
        suffix = f" ({n_after_cutoff} posted after season end, excluded)" if n_after_cutoff else ""
        print(f"  {agent}: pool size {len(works)}{suffix}", file=sys.stderr)
    return pools


def download_one(client: httpx.Client, work: Work) -> bool:
    path = work.cache_path
    if path.exists() and path.stat().st_size > 0:
        return True
    delay = 1.0
    for attempt in range(5):
        try:
            r = client.get(work.url)
        except httpx.RequestError:
            if attempt == 4:
                return False
            time.sleep(delay)
            delay = min(delay * 2, 20)
            continue
        if r.status_code == 404:
            return False
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == 4:
                return False
            time.sleep(delay)
            delay = min(delay * 2, 20)
            continue
        if r.status_code != 200:
            return False
        path.write_bytes(r.content)
        return True
    return False


def download_all(works: list[Work]) -> tuple[list[Work], int]:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    ok: list[Work] = []
    failed = 0
    done = 0
    lock = threading.Lock()

    with (
        httpx.Client(timeout=30, follow_redirects=True) as client,
        ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool,
    ):
        futures = {pool.submit(download_one, client, w): w for w in works}
        for fut in as_completed(futures):
            w = futures[fut]
            success = fut.result()
            with lock:
                done += 1
                if done % 500 == 0:
                    print(f"  downloaded {done}/{len(works)}", file=sys.stderr)
            if success:
                ok.append(w)
            else:
                failed += 1
    return ok, failed


# --------------------------------------------------------------------------
# 2. Embed: SigLIP 2 (+ zero-shot margin) and DINOv2, each cached to .npz.
# --------------------------------------------------------------------------


def load_vec_cache(path: Path) -> dict[str, np.ndarray]:
    if path.exists():
        d = np.load(path, allow_pickle=False)
        return dict(zip(d["urls"].tolist(), d["vecs"], strict=True))
    return {}


def save_vec_cache(path: Path, cache: dict[str, np.ndarray]) -> None:
    urls = np.array(list(cache.keys()))
    vecs = np.stack(list(cache.values())).astype(np.float32)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, urls=urls, vecs=vecs)


def load_margin_cache(path: Path) -> dict[str, float]:
    if path.exists():
        d = np.load(path, allow_pickle=False)
        return dict(zip(d["urls"].tolist(), d["margins"].tolist(), strict=True))
    return {}


def save_margin_cache(path: Path, cache: dict[str, float]) -> None:
    urls = np.array(list(cache.keys()))
    margins = np.array(list(cache.values()), dtype=np.float32)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, urls=urls, margins=margins)


def open_rgb(work: Work) -> Image.Image | None:
    try:
        return Image.open(work.cache_path).convert("RGB")
    except OSError, UnidentifiedImageError:
        return None


def dino_preprocess(im: Image.Image) -> torch.Tensor:
    w, h = im.size
    short = min(w, h)
    scale = 256 / short
    new_w, new_h = round(w * scale), round(h * scale)
    im = im.resize((new_w, new_h), Image.BICUBIC)
    left, top = (new_w - 224) // 2, (new_h - 224) // 2
    im = im.crop((left, top, left + 224, top + 224))
    arr = (np.asarray(im).astype(np.float32) / 255.0 - DINO_MEAN) / DINO_STD
    return torch.from_numpy(arr.transpose(2, 0, 1))


def embed_siglip(
    works: list[Work],
    emb_cache: dict[str, np.ndarray],
    margin_cache: dict[str, float],
    device: str,
) -> None:
    from transformers import AutoModel, AutoProcessor

    missing = [w for w in works if w.url not in emb_cache or w.url not in margin_cache]
    print(
        f"  siglip2: embedding {len(missing)} new images "
        f"({len(works) - len(missing)} already cached)",
        file=sys.stderr,
    )
    if not missing:
        return

    processor = AutoProcessor.from_pretrained(SIGLIP_MODEL, cache_dir=str(HF_CACHE_DIR))
    model = AutoModel.from_pretrained(SIGLIP_MODEL, cache_dir=str(HF_CACHE_DIR)).to(device).eval()
    text_inputs = processor(
        text=[TECH_PROMPT, ABSTRACT_PROMPT], padding="max_length", return_tensors="pt"
    ).to(device)

    n_batches = (len(missing) + BATCH_SIZE - 1) // BATCH_SIZE
    for bi in range(n_batches):
        batch = missing[bi * BATCH_SIZE : (bi + 1) * BATCH_SIZE]
        imgs, kept = [], []
        for w in batch:
            img = open_rgb(w)
            if img is not None:
                imgs.append(img)
                kept.append(w)
        if not imgs:
            continue
        pixel_values = processor(images=imgs, return_tensors="pt")["pixel_values"].to(device)
        with torch.no_grad():
            out = model(
                input_ids=text_inputs["input_ids"],
                attention_mask=text_inputs.get("attention_mask"),
                pixel_values=pixel_values,
            )
            image_embeds = out.image_embeds
            image_embeds = image_embeds / image_embeds.norm(dim=-1, keepdim=True)
        embeds_np = image_embeds.cpu().numpy().astype(np.float32)
        logits_np = out.logits_per_image.cpu().numpy().astype(np.float32)
        for w, vec, lg in zip(kept, embeds_np, logits_np, strict=True):
            emb_cache[w.url] = vec
            margin_cache[w.url] = float(lg[0] - lg[1])  # >0 => technical
        if bi % 10 == 0 or bi == n_batches - 1:
            print(f"    siglip2 batch {bi + 1}/{n_batches}", file=sys.stderr)
        if bi % 20 == 19 or bi == n_batches - 1:
            # checkpoint periodically so an interrupted run doesn't lose progress
            save_vec_cache(SIGLIP_EMB_CACHE, emb_cache)
            save_margin_cache(SIGLIP_MARGIN_CACHE, margin_cache)


def embed_dino(works: list[Work], emb_cache: dict[str, np.ndarray], device: str) -> None:
    from transformers import AutoModel

    missing = [w for w in works if w.url not in emb_cache]
    print(
        f"  dinov2: embedding {len(missing)} new images "
        f"({len(works) - len(missing)} already cached)",
        file=sys.stderr,
    )
    if not missing:
        return

    model = AutoModel.from_pretrained(DINO_MODEL, cache_dir=str(HF_CACHE_DIR)).to(device).eval()

    n_batches = (len(missing) + BATCH_SIZE - 1) // BATCH_SIZE
    for bi in range(n_batches):
        batch = missing[bi * BATCH_SIZE : (bi + 1) * BATCH_SIZE]
        tensors, kept = [], []
        for w in batch:
            img = open_rgb(w)
            if img is not None:
                tensors.append(dino_preprocess(img))
                kept.append(w)
        if not tensors:
            continue
        pixel_values = torch.stack(tensors).to(device)
        with torch.no_grad():
            out = model(pixel_values=pixel_values)
            feats = out.pooler_output
            feats = feats / feats.norm(dim=-1, keepdim=True)
        feats_np = feats.cpu().numpy().astype(np.float32)
        for w, vec in zip(kept, feats_np, strict=True):
            emb_cache[w.url] = vec
        if bi % 10 == 0 or bi == n_batches - 1:
            print(f"    dinov2 batch {bi + 1}/{n_batches}", file=sys.stderr)
        if bi % 20 == 19 or bi == n_batches - 1:
            save_vec_cache(DINO_EMB_CACHE, emb_cache)


# --------------------------------------------------------------------------
# 3. Analyses (generic over embedding space)
# --------------------------------------------------------------------------


def leave_one_out_identification(X: np.ndarray, y: np.ndarray, n_agents: int) -> dict:
    n = len(y)
    sums = np.zeros((n_agents, X.shape[1]), dtype=np.float64)
    counts = np.zeros(n_agents, dtype=np.float64)
    for lbl in range(n_agents):
        mask = y == lbl
        sums[lbl] = X[mask].sum(axis=0)
        counts[lbl] = mask.sum()

    preds_centroid = np.empty(n, dtype=int)
    for i in range(n):
        c = sums.copy()
        cnt = counts.copy()
        c[y[i]] -= X[i]
        cnt[y[i]] -= 1
        centroids = c / cnt[:, None]
        centroids /= np.linalg.norm(centroids, axis=1, keepdims=True)
        preds_centroid[i] = int(np.argmax(centroids @ X[i]))
    acc_centroid = float((preds_centroid == y).mean())

    S = X @ X.T
    S_noself = S.copy()
    np.fill_diagonal(S_noself, -np.inf)
    knn_idx = np.argpartition(-S_noself, kth=K_NEIGHBOURS, axis=1)[:, :K_NEIGHBOURS]

    preds_knn = np.empty(n, dtype=int)
    for i in range(n):
        neigh = knn_idx[i]
        neigh_labels = y[neigh]
        counts_ = Counter(neigh_labels.tolist())
        top = max(counts_.values())
        candidates = [lbl for lbl, c in counts_.items() if c == top]
        if len(candidates) == 1:
            preds_knn[i] = candidates[0]
        else:
            sims_by_label = {
                lbl: S_noself[i, neigh[neigh_labels == lbl]].sum() for lbl in candidates
            }
            preds_knn[i] = max(sims_by_label, key=sims_by_label.get)
    acc_knn = float((preds_knn == y).mean())

    return {
        "n_works": n,
        "nearest_centroid_accuracy": acc_centroid,
        "five_nn_accuracy": acc_knn,
        "chance_baseline": 1.0 / n_agents,
    }


def within_between_similarity(X: np.ndarray, y: np.ndarray, agents: list[str]) -> dict:
    S = X @ X.T
    n = len(y)
    upper = np.triu(np.ones((n, n), dtype=bool), k=1)
    same = y[:, None] == y[None, :]
    mean_within = float(S[upper & same].mean())
    mean_between = float(S[upper & ~same].mean())

    n_a = len(agents)
    M = np.zeros((n_a, n_a))
    for i in range(n_a):
        for j in range(n_a):
            if i == j:
                mask_i = y == i
                sub_upper = np.triu(np.ones((mask_i.sum(), mask_i.sum()), dtype=bool), k=1)
                M[i, j] = S[np.ix_(mask_i, mask_i)][sub_upper].mean()
            else:
                M[i, j] = S[np.ix_(y == i, y == j)].mean()

    return {
        "mean_within_agent": mean_within,
        "mean_between_agent": mean_between,
        "pairwise_matrix": M,
    }


def temporal_analysis(
    X: np.ndarray, y: np.ndarray, weeks: np.ndarray, season_mask: np.ndarray
) -> dict:
    idx = np.where(season_mask)[0]
    Xs, ys, ws = X[idx], y[idx], weeks[idx]
    S = Xs @ Xs.T
    n = len(ys)
    upper = np.triu(np.ones((n, n), dtype=bool), k=1)
    cross_agent = ys[:, None] != ys[None, :]
    same_week = ws[:, None] == ws[None, :]

    mean_same_week = float(S[upper & cross_agent & same_week].mean())
    mean_diff_week = float(S[upper & cross_agent & ~same_week].mean())

    week_labels = sorted(set(ws.tolist()))
    curve = []
    for wl in week_labels:
        wmask = ws == wl
        n_works = int(wmask.sum())
        sub_upper = np.triu(np.ones((n_works, n_works), dtype=bool), k=1)
        sub_cross = ys[wmask][:, None] != ys[wmask][None, :]
        vals = S[np.ix_(wmask, wmask)][sub_upper & sub_cross]
        between_mean = float(vals.mean()) if vals.size else float("nan")
        curve.append({"week": wl, "n_works": n_works, "between_agent_mean": between_mean})

    return {
        "same_week_cross_agent_mean": mean_same_week,
        "diff_week_cross_agent_mean": mean_diff_week,
        "weekly_between_curve": curve,
    }


def technical_plot_drift(
    is_technical: np.ndarray,
    agent_labels: list[str],
    weeks: np.ndarray,
    season_mask: np.ndarray,
) -> dict:
    idx = np.where(season_mask)[0]
    week_labels = sorted(set(weeks[idx].tolist()))
    per_agent_labels = np.array(agent_labels)

    weekly_by_agent: dict[str, dict[str, float | None]] = {}
    weekly_overall: dict[str, float] = {}
    for wl in week_labels:
        wmask = idx[weeks[idx] == wl]
        weekly_overall[wl] = float(is_technical[wmask].mean()) if len(wmask) else float("nan")
        row: dict[str, float | None] = {}
        for a in sorted(set(per_agent_labels)):
            sub = wmask[per_agent_labels[wmask] == a]
            row[a] = float(is_technical[sub].mean()) if len(sub) else None
        weekly_by_agent[wl] = row

    season_total: dict[str, float] = {}
    for a in sorted(set(per_agent_labels)):
        sub = idx[per_agent_labels[idx] == a]
        season_total[a] = float(is_technical[sub].mean()) if len(sub) else float("nan")

    return {
        "week_labels": week_labels,
        "weekly_fraction_by_agent": weekly_by_agent,
        "weekly_overall_fraction": weekly_overall,
        "season_total_fraction_by_agent": season_total,
    }


def print_identification(space: str, ident: dict) -> None:
    print(f"\n=== [{space}] (a) leave-one-out agent identification ===")
    print(f"  n = {ident['n_works']} works, {len(AGENTS)} agents")
    print(f"  nearest-centroid accuracy: {ident['nearest_centroid_accuracy']:.3f}")
    print(f"  {K_NEIGHBOURS}-NN accuracy:            {ident['five_nn_accuracy']:.3f}")
    print(f"  chance baseline (1/{len(AGENTS)}):       {ident['chance_baseline']:.3f}")


def print_within_between(space: str, wb: dict) -> None:
    print(f"\n=== [{space}] (b) within- vs between-agent cosine similarity ===")
    print(f"  mean within-agent similarity:  {wb['mean_within_agent']:.3f}")
    print(f"  mean between-agent similarity: {wb['mean_between_agent']:.3f}")
    print("\n  pairwise similarity matrix (diagonal = within-agent mean):")
    print("        " + "  ".join(f"{a:>6}" for a in AGENTS))
    M = wb["pairwise_matrix"]
    for i, a in enumerate(AGENTS):
        row = "  ".join(f"{M[i, j]:>6.3f}" for j in range(len(AGENTS)))
        print(f"  {a:>6}  {row}")


def print_temporal(space: str, temporal: dict) -> None:
    print(f"\n=== [{space}] (c) temporal: same-week vs different-week cross-agent similarity ===")
    same = temporal["same_week_cross_agent_mean"]
    diff = temporal["diff_week_cross_agent_mean"]
    print(f"  same-week cross-agent mean similarity:      {same:.3f}")
    print(f"  different-week cross-agent mean similarity: {diff:.3f}")
    print(f"\n  [{space}] per-week between-agent curve (image-space analogue of Fig 4a):")
    print(f"  {'week':<12} {'n':>5} {'between-agent mean':>20}")
    for row in temporal["weekly_between_curve"]:
        print(f"  {row['week']:<12} {row['n_works']:>5} {row['between_agent_mean']:>20.3f}")


def run_space_analyses(
    space: str, X: np.ndarray, y: np.ndarray, weeks: np.ndarray, season_mask: np.ndarray
) -> dict:
    ident = leave_one_out_identification(X, y, len(AGENTS))
    print_identification(space, ident)
    wb = within_between_similarity(X, y, AGENTS)
    print_within_between(space, wb)
    temporal = temporal_analysis(X, y, weeks, season_mask)
    print_temporal(space, temporal)
    return {
        "identification": ident,
        "similarity": {
            "mean_within_agent": wb["mean_within_agent"],
            "mean_between_agent": wb["mean_between_agent"],
            "pairwise_matrix": {
                a: {b: float(wb["pairwise_matrix"][i, j]) for j, b in enumerate(AGENTS)}
                for i, a in enumerate(AGENTS)
            },
        },
        "temporal": temporal,
    }


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> None:
    t0 = time.monotonic()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {device}", file=sys.stderr)
    print(f"models: {SIGLIP_MODEL}  +  {DINO_MODEL}", file=sys.stderr)

    print("fetching feed metadata (cached under CACHE_DIR after first run)...", file=sys.stderr)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        pools = fetch_all_pools(client)

    print("\n=== pool sizes (works posted on or before 2026-07-27) ===")
    for a in AGENTS:
        print(f"  {a:<8} {len(pools[a]):>5}")
    print(f"  {'total':<8} {sum(len(v) for v in pools.values()):>5}")

    flat_works = [w for a in AGENTS for w in pools[a]]
    print(f"\ndownloading/caching {len(flat_works)} images...", file=sys.stderr)
    flat_works, n_download_failed = download_all(flat_works)
    print(
        f"downloaded/cached {len(flat_works)} images, "
        f"{n_download_failed} skipped (404 or persistent error)"
    )

    print("\nembedding with SigLIP 2 and DINOv2...", file=sys.stderr)
    siglip_cache = load_vec_cache(SIGLIP_EMB_CACHE)
    siglip_margins = load_margin_cache(SIGLIP_MARGIN_CACHE)
    embed_siglip(flat_works, siglip_cache, siglip_margins, device)

    dino_cache = load_vec_cache(DINO_EMB_CACHE)
    embed_dino(flat_works, dino_cache, device)

    flat_works = [
        w
        for w in flat_works
        if w.url in siglip_cache and w.url in siglip_margins and w.url in dino_cache
    ]
    print(f"\n{len(flat_works)} works embedded successfully in both spaces")

    agent_idx = {a: i for i, a in enumerate(AGENTS)}
    y = np.array([agent_idx[w.agent] for w in flat_works])
    weeks = np.array([w.week for w in flat_works])
    agent_labels = [w.agent for w in flat_works]
    season_mask = np.array([START <= w.created_at.date() <= END for w in flat_works])
    n_before_start = int((~season_mask).sum())
    if n_before_start:
        print(
            f"note: {n_before_start} works predate {START.isoformat()} "
            "(early-deployed agent) and are excluded from the weekly temporal analyses "
            "(c, d) but included in identification and within/between similarity (a, b)"
        )

    X_siglip = np.stack([siglip_cache[w.url] for w in flat_works]).astype(np.float32)
    X_dino = np.stack([dino_cache[w.url] for w in flat_works]).astype(np.float32)

    results_siglip = run_space_analyses("SigLIP2", X_siglip, y, weeks, season_mask)
    results_dino = run_space_analyses("DINOv2", X_dino, y, weeks, season_mask)

    print("\n=== [SigLIP2] (d) zero-shot technical-plot classification (drift check for Fig 3) ===")
    print(f'  prompts: "{TECH_PROMPT}" vs "{ABSTRACT_PROMPT}"')
    margins = np.array([siglip_margins[w.url] for w in flat_works], dtype=np.float32)
    is_technical = margins > 0.0
    plot_drift = technical_plot_drift(is_technical, agent_labels, weeks, season_mask)
    header = "  " + f"{'week':<12}" + "".join(f"{a:>8}" for a in AGENTS) + f"{'overall':>10}"
    print(header)
    for wl in plot_drift["week_labels"]:
        row = plot_drift["weekly_fraction_by_agent"][wl]
        cells = "".join(
            f"{row[a]:>8.2f}" if row.get(a) is not None else f"{'--':>8}" for a in AGENTS
        )
        overall = plot_drift["weekly_overall_fraction"][wl]
        print(f"  {wl:<12}{cells}{overall:>10.2f}")
    print("\n  season-total fraction technical per agent:")
    for a in AGENTS:
        v = plot_drift["season_total_fraction_by_agent"].get(a, float("nan"))
        print(f"    {a:<8} {v:.3f}")

    elapsed = time.monotonic() - t0
    print(f"\nruntime: {elapsed:.1f}s, device={device}")

    data = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "models": {"text_aligned": SIGLIP_MODEL, "visual_only": DINO_MODEL},
        "device": device,
        "agents": AGENTS,
        "season": {"start": START.isoformat(), "end": END.isoformat()},
        "pool_sizes": {a: len(pools[a]) for a in AGENTS},
        "n_embedded": len(flat_works),
        "n_download_failed": n_download_failed,
        "n_before_season_start": n_before_start,
        "siglip2": results_siglip,
        "dinov2": results_dino,
        "technical_plot_drift_siglip2": plot_drift,
        "runtime_seconds": elapsed,
    }
    DATA_JSON.write_text(json.dumps(data, indent=2, default=str))
    print(f"\nwrote {DATA_JSON}", file=sys.stderr)


if __name__ == "__main__":
    main()
