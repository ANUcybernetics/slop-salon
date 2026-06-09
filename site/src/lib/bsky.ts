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
  return results.flat().toSorted((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
}

export async function loadCombinedHistory(agents: Agent[]): Promise<FeedItem[]> {
  const live = agents.filter((a) => a.live);
  const results = await Promise.all(live.map(fetchAuthorFeedAll));
  return results.flat().toSorted((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
}
