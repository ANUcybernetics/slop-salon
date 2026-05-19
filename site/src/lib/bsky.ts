import type { Agent } from "./agents.ts";

const APPVIEW = "https://public.api.bsky.app";

export type FeedImage = {
  thumb: string;
  fullsize: string;
  alt: string;
  aspectRatio?: { width: number; height: number };
};

export type FeedItem = {
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
};

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

type BskyEmbedView =
  | { $type: "app.bsky.embed.images#view"; images: BskyImageView[] }
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
};

function rkey(uri: string): string {
  return uri.split("/").pop() ?? "";
}

function bskyPostUrl(handle: string, uri: string): string {
  return `https://bsky.app/profile/${handle}/post/${rkey(uri)}`;
}

function extractImages(embed: BskyEmbedView | undefined): FeedImage[] {
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

async function fetchAuthorFeed(agent: Agent, limit = 20): Promise<FeedItem[]> {
  const url = `${APPVIEW}/xrpc/app.bsky.feed.getAuthorFeed?actor=${encodeURIComponent(agent.handle)}&limit=${limit}&filter=posts_and_author_threads`;
  let res: Response;
  try {
    res = await fetch(url, { headers: { accept: "application/json" } });
  } catch (err) {
    console.warn(`[bsky] fetch failed for ${agent.handle}:`, err);
    return [];
  }
  if (!res.ok) {
    console.warn(`[bsky] ${agent.handle} returned ${res.status}`);
    return [];
  }
  const data = (await res.json()) as AuthorFeedResponse;
  return data.feed.map((entry) => {
    const post = entry.post;
    const isRepost = entry.reason?.$type === "app.bsky.feed.defs#reasonRepost";
    return {
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
      images: extractImages(post.embed),
    };
  });
}

export async function loadCombinedFeed(agents: Agent[], perAgent = 20): Promise<FeedItem[]> {
  const live = agents.filter((a) => a.live);
  const results = await Promise.all(live.map((a) => fetchAuthorFeed(a, perAgent)));
  return results.flat().toSorted((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
}
