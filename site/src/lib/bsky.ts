import type { Agent } from "./agents.ts";

const APPVIEW = "https://public.api.bsky.app";

export type FeedImage = {
  thumb: string;
  fullsize: string;
  alt: string;
  aspectRatio?: { width: number; height: number };
};

export type FeedVideo = {
  thumbnail?: string;
  playlist: string;
  alt: string;
  aspectRatio?: { width: number; height: number };
};

export type FeedItem = {
  uri: string;
  agent: string;
  handle: string;
  text: string;
  createdAt: string;
  url: string;
  isRepost: boolean;
  repostedFrom?: { handle: string; displayName?: string };
  replyCount: number;
  repostCount: number;
  likeCount: number;
  images: FeedImage[];
  video?: FeedVideo;
};

export function hasMedia(item: FeedItem): boolean {
  return item.images.length > 0 || item.video !== undefined;
}

type BskyAuthor = {
  did: string;
  handle: string;
  displayName?: string;
};

type BskyImageView = {
  thumb: string;
  fullsize: string;
  alt?: string;
  aspectRatio?: { width: number; height: number };
};

type BskyExternalView = {
  uri: string;
  title?: string;
  description?: string;
  thumb?: string;
};

type BskyEmbedView =
  | { $type: "app.bsky.embed.images#view"; images: BskyImageView[] }
  | {
      $type: "app.bsky.embed.video#view";
      playlist: string;
      thumbnail?: string;
      alt?: string;
      aspectRatio?: { width: number; height: number };
    }
  | { $type: "app.bsky.embed.external#view"; external: BskyExternalView }
  | { $type: "app.bsky.embed.recordWithMedia#view"; media: BskyEmbedView }
  | { $type: string };

type BskyPost = {
  uri: string;
  cid: string;
  author: BskyAuthor;
  record: { text?: string; createdAt: string };
  embed?: BskyEmbedView;
  indexedAt: string;
  replyCount?: number;
  repostCount?: number;
  likeCount?: number;
};

type BskyFeedEntry = {
  post: BskyPost;
  reason?: { $type: string; by?: BskyAuthor };
  reply?: unknown;
};

type AuthorFeedResponse = {
  feed: BskyFeedEntry[];
  cursor?: string;
};

function rkey(uri: string): string {
  return uri.split("/").pop() ?? "";
}

function bskyPostUrl(handle: string, uri: string): string {
  return `https://bsky.app/profile/${handle}/post/${rkey(uri)}`;
}

export function extractImages(embed: BskyEmbedView | undefined): FeedImage[] {
  if (!embed) return [];
  if (embed.$type === "app.bsky.embed.images#view") {
    const view = embed as { images: BskyImageView[] };
    return view.images.map((img) => ({
      thumb: img.thumb,
      fullsize: img.fullsize,
      alt: img.alt ?? "",
      aspectRatio: img.aspectRatio,
    }));
  }
  if (embed.$type === "app.bsky.embed.recordWithMedia#view") {
    return extractImages((embed as { media: BskyEmbedView }).media);
  }
  return [];
}

export function extractVideo(embed: BskyEmbedView | undefined): FeedVideo | undefined {
  if (!embed) return undefined;
  if (embed.$type === "app.bsky.embed.video#view") {
    const view = embed as {
      playlist: string;
      thumbnail?: string;
      alt?: string;
      aspectRatio?: { width: number; height: number };
    };
    return {
      thumbnail: view.thumbnail,
      playlist: view.playlist,
      alt: view.alt ?? "",
      aspectRatio: view.aspectRatio,
    };
  }
  if (embed.$type === "app.bsky.embed.recordWithMedia#view") {
    return extractVideo((embed as { media: BskyEmbedView }).media);
  }
  return undefined;
}

function entryToFeedItem(agent: Agent, entry: BskyFeedEntry): FeedItem {
  const post = entry.post;
  const isRepost = entry.reason?.$type === "app.bsky.feed.defs#reasonRepost";
  const images = extractImages(post.embed);
  const video = extractVideo(post.embed);
  return {
    uri: post.uri,
    agent: agent.name,
    handle: agent.handle,
    text: post.record.text ?? "",
    createdAt: post.record.createdAt ?? post.indexedAt,
    url: bskyPostUrl(post.author.handle, post.uri),
    isRepost,
    repostedFrom: isRepost
      ? { handle: post.author.handle, displayName: post.author.displayName }
      : undefined,
    replyCount: post.replyCount ?? 0,
    repostCount: post.repostCount ?? 0,
    likeCount: post.likeCount ?? 0,
    images,
    video,
  };
}

// Bluesky transcodes an embed.video blob into HLS asynchronously, and only
// while the blob stays within its limits (the 3-minute cap; the per-account
// daily quota of 25 videos / 10GB). A video that breaks them still posts ---
// uploadBlob and createRecord both succeed --- but is never transcoded, so its
// playlist.m3u8 and thumbnail.jpg 404 forever, leaving a dead "video" card that
// opens the lightbox onto nothing. Prune those at build time so the feed never
// shows them.
//
// The check is fail-open: only a definitive 404 prunes. A 200, any other
// status, or a network error keeps the video --- so a transient blip can't
// erase good posts. Freshly posted videos are still transcoding (their playlist
// 404s briefly), so a grace window leaves recent posts untouched. Liveness is
// memoised per playlist URL across the build, and a no-op in the browser (the
// client refresh stays fast; the render layer drops any dead card that the
// merge re-introduces).
const VIDEO_TRANSCODE_GRACE_MS = 15 * 60 * 1000;
const VIDEO_LIVENESS_CONCURRENCY = 8;
const playlistLiveness = new Map<string, Promise<boolean>>();

function playlistIsDead(url: string): Promise<boolean> {
  let verdict = playlistLiveness.get(url);
  if (!verdict) {
    verdict = fetch(url, { method: "HEAD" })
      .then((res) => res.status === 404)
      .catch(() => false);
    playlistLiveness.set(url, verdict);
  }
  return verdict;
}

export async function pruneDeadVideos(
  items: FeedItem[],
  now: number = Date.now(),
): Promise<FeedItem[]> {
  const aged = items.filter(
    (it) => it.video && now - Date.parse(it.createdAt) > VIDEO_TRANSCODE_GRACE_MS,
  );
  const deadUris = new Set<string>();
  for (let i = 0; i < aged.length; i += VIDEO_LIVENESS_CONCURRENCY) {
    const batch = aged.slice(i, i + VIDEO_LIVENESS_CONCURRENCY);
    // oxlint-disable-next-line no-await-in-loop -- bounded-concurrency batches
    const verdicts = await Promise.all(batch.map((it) => playlistIsDead(it.video!.playlist)));
    batch.forEach((it, j) => {
      if (verdicts[j]) deadUris.add(it.uri);
    });
  }
  if (deadUris.size === 0) return items;
  // A dead video is a post's whole point, so drop the post --- unless it also
  // carries images (a recordWithMedia), where just the video embed goes.
  return items.filter((it) => {
    if (!it.video || !deadUris.has(it.uri)) return true;
    if (it.images.length > 0) {
      it.video = undefined;
      return true;
    }
    return false;
  });
}

// Build-time only: in the browser the dead-card removal in feed-render covers it.
function prunedForBuild(items: FeedItem[]): Promise<FeedItem[]> {
  return import.meta.env.SSR ? pruneDeadVideos(items) : Promise.resolve(items);
}

async function fetchAuthorFeedPage(
  agent: Agent,
  limit: number,
  cursor?: string,
): Promise<AuthorFeedResponse | null> {
  const cursorParam = cursor ? `&cursor=${encodeURIComponent(cursor)}` : "";
  const url = `${APPVIEW}/xrpc/app.bsky.feed.getAuthorFeed?actor=${encodeURIComponent(agent.handle)}&limit=${limit}&filter=posts_and_author_threads${cursorParam}`;
  let res: Response;
  try {
    res = await fetch(url, { headers: { accept: "application/json" } });
  } catch (err) {
    console.warn(`[bsky] fetch failed for ${agent.handle}:`, err);
    return null;
  }
  if (!res.ok) {
    console.warn(`[bsky] ${agent.handle} returned ${res.status}`);
    return null;
  }
  return (await res.json()) as AuthorFeedResponse;
}

async function fetchAuthorFeed(agent: Agent, limit = 20): Promise<FeedItem[]> {
  const data = await fetchAuthorFeedPage(agent, limit);
  if (!data) return [];
  return data.feed.map((entry) => entryToFeedItem(agent, entry));
}

async function fetchAuthorFeedAll(agent: Agent): Promise<FeedItem[]> {
  const results: FeedItem[] = [];
  let cursor: string | undefined;
  while (true) {
    // oxlint-disable-next-line no-await-in-loop -- each call depends on the previous cursor
    const data = await fetchAuthorFeedPage(agent, 100, cursor);
    if (!data || data.feed.length === 0) break;
    for (const entry of data.feed) results.push(entryToFeedItem(agent, entry));
    if (!data.cursor) break;
    cursor = data.cursor;
  }
  return results;
}

export async function loadCombinedFeed(agents: Agent[], perAgent = 20): Promise<FeedItem[]> {
  const live = agents.filter((a) => a.live);
  const results = await Promise.all(live.map((a) => fetchAuthorFeed(a, perAgent)));
  const items = await prunedForBuild(results.flat());
  return items.toSorted((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
}

export async function loadCombinedHistory(agents: Agent[]): Promise<FeedItem[]> {
  const live = agents.filter((a) => a.live);
  const results = await Promise.all(live.map(fetchAuthorFeedAll));
  const items = await prunedForBuild(results.flat());
  return items.toSorted((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
}
