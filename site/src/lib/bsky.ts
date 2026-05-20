import type { Agent } from "./agents.ts";

const APPVIEW = "https://public.api.bsky.app";

export type FeedImage = {
  thumb: string;
  fullsize: string;
  alt: string;
  aspectRatio?: { width: number; height: number };
};

export type MediaType = "image" | "video" | "audio";

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
  mediaTypes: MediaType[];
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

type BskyExternalView = {
  uri: string;
  title?: string;
  description?: string;
  thumb?: string;
};

type BskyEmbedView =
  | { $type: "app.bsky.embed.images#view"; images: BskyImageView[] }
  | { $type: "app.bsky.embed.video#view"; playlist: string; thumbnail?: string }
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

const AUDIO_HOSTS = [
  "soundcloud.com",
  "bandcamp.com",
  "spotify.com",
  "music.apple.com",
  "audius.co",
  "suno.com",
];

function isAudioUrl(uri: string): boolean {
  try {
    const host = new URL(uri).hostname.toLowerCase();
    return AUDIO_HOSTS.some((h) => host === h || host.endsWith(`.${h}`));
  } catch {
    return false;
  }
}

export function extractMediaTypes(embed: BskyEmbedView | undefined): MediaType[] {
  if (!embed) return [];
  if (embed.$type === "app.bsky.embed.images#view") return ["image"];
  if (embed.$type === "app.bsky.embed.video#view") return ["video"];
  if (embed.$type === "app.bsky.embed.external#view") {
    const view = embed as { external: BskyExternalView };
    return isAudioUrl(view.external.uri) ? ["audio"] : [];
  }
  if (embed.$type === "app.bsky.embed.recordWithMedia#view") {
    return extractMediaTypes((embed as { media: BskyEmbedView }).media);
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
    const images = extractImages(post.embed);
    const mediaTypes = extractMediaTypes(post.embed);
    if (images.length > 0 && !mediaTypes.includes("image")) mediaTypes.push("image");
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
      mediaTypes,
    };
  });
}

export async function loadCombinedFeed(agents: Agent[], perAgent = 20): Promise<FeedItem[]> {
  const live = agents.filter((a) => a.live);
  const results = await Promise.all(live.map((a) => fetchAuthorFeed(a, perAgent)));
  return results.flat().toSorted((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
}
