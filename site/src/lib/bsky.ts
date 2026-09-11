import { z } from "zod";
import type { Agent } from "./agents.ts";

const APPVIEW = "https://public.api.bsky.app";

// --- What the AppView sends, as we read it ---

const aspectRatio = z.object({ width: z.number(), height: z.number() });

const author = z.object({
  did: z.string(),
  handle: z.string(),
  displayName: z.string().optional(),
});

const imageView = z.object({
  thumb: z.string(),
  fullsize: z.string(),
  alt: z.string().optional(),
  aspectRatio: aspectRatio.optional(),
});

const embedView: z.ZodType<EmbedView> = z.lazy(() =>
  z.union([
    z.object({ $type: z.literal("app.bsky.embed.images#view"), images: z.array(imageView) }),
    z.object({
      $type: z.literal("app.bsky.embed.video#view"),
      playlist: z.string(),
      thumbnail: z.string().optional(),
      alt: z.string().optional(),
      aspectRatio: aspectRatio.optional(),
    }),
    z.object({ $type: z.literal("app.bsky.embed.recordWithMedia#view"), media: embedView }),
    z.object({ $type: z.string() }).loose(),
  ]),
);

export type EmbedView =
  | { $type: "app.bsky.embed.images#view"; images: z.infer<typeof imageView>[] }
  | {
      $type: "app.bsky.embed.video#view";
      playlist: string;
      thumbnail?: string;
      alt?: string;
      aspectRatio?: { width: number; height: number };
    }
  | { $type: "app.bsky.embed.recordWithMedia#view"; media: EmbedView }
  | { $type: string };

const postView = z.object({
  uri: z.string(),
  author,
  record: z
    .object({
      text: z.string().optional(),
      createdAt: z.string().optional(),
      // The stamp `bsky` writes at post time: which model made this.
      provenance: z.object({ model: z.string(), salon: z.string().optional() }).optional(),
    })
    .loose(),
  embed: embedView.optional(),
  indexedAt: z.string(),
  replyCount: z.number().optional(),
  repostCount: z.number().optional(),
  likeCount: z.number().optional(),
});

const feedEntry = z.object({
  post: postView,
  reason: z.object({ $type: z.string(), by: author.optional() }).loose().optional(),
});

export const authorFeedResponse = z.object({
  // Each entry is validated on its own, so one odd post drops rather than
  // taking the whole page with it.
  feed: z.array(z.unknown()),
  cursor: z.string().optional(),
});

export const profileResponse = z.object({
  handle: z.string(),
  description: z.string().optional(),
  avatar: z.string().optional(),
});

// --- What the site renders ---

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
  model?: string;
  replyCount: number;
  repostCount: number;
  likeCount: number;
  images: FeedImage[];
  video?: FeedVideo;
};

export type Profile = { handle: string; description: string; avatar: string };

export function hasMedia(item: FeedItem): boolean {
  return item.images.length > 0 || item.video !== undefined;
}

function rkey(uri: string): string {
  return uri.split("/").pop() ?? "";
}

export function extractImages(embed: EmbedView | undefined): FeedImage[] {
  if (!embed) return [];
  if (embed.$type === "app.bsky.embed.images#view") {
    return (embed as { images: z.infer<typeof imageView>[] }).images.map((img) => ({
      thumb: img.thumb,
      fullsize: img.fullsize,
      alt: img.alt ?? "",
      aspectRatio: img.aspectRatio,
    }));
  }
  if (embed.$type === "app.bsky.embed.recordWithMedia#view") {
    return extractImages((embed as { media: EmbedView }).media);
  }
  return [];
}

export function extractVideo(embed: EmbedView | undefined): FeedVideo | undefined {
  if (!embed) return undefined;
  if (embed.$type === "app.bsky.embed.video#view") {
    const view = embed as Extract<EmbedView, { playlist: string }>;
    return {
      thumbnail: view.thumbnail,
      playlist: view.playlist,
      alt: view.alt ?? "",
      aspectRatio: view.aspectRatio,
    };
  }
  if (embed.$type === "app.bsky.embed.recordWithMedia#view") {
    return extractVideo((embed as { media: EmbedView }).media);
  }
  return undefined;
}

/** One validated feed entry as a FeedItem, or null if it does not parse. */
export function parseFeedEntry(agent: Agent, raw: unknown): FeedItem | null {
  const parsed = feedEntry.safeParse(raw);
  if (!parsed.success) return null;
  const { post, reason } = parsed.data;
  const isRepost = reason?.$type === "app.bsky.feed.defs#reasonRepost";
  return {
    uri: post.uri,
    agent: agent.name,
    handle: agent.handle,
    text: post.record.text ?? "",
    createdAt: post.record.createdAt ?? post.indexedAt,
    url: `https://bsky.app/profile/${post.author.handle}/post/${rkey(post.uri)}`,
    isRepost,
    model: post.record.provenance?.model,
    replyCount: post.replyCount ?? 0,
    repostCount: post.repostCount ?? 0,
    likeCount: post.likeCount ?? 0,
    images: extractImages(post.embed),
    video: extractVideo(post.embed),
  };
}

async function getJson(url: string): Promise<unknown | null> {
  try {
    const res = await fetch(url, { headers: { accept: "application/json" } });
    if (!res.ok) {
      console.warn(`[bsky] ${url} returned ${res.status}`);
      return null;
    }
    return await res.json();
  } catch (err) {
    console.warn(`[bsky] fetch failed for ${url}:`, err);
    return null;
  }
}

export async function fetchAuthorFeed(agent: Agent, limit = 20): Promise<FeedItem[]> {
  const url = `${APPVIEW}/xrpc/app.bsky.feed.getAuthorFeed?actor=${encodeURIComponent(agent.handle)}&limit=${limit}&filter=posts_and_author_threads`;
  const parsed = authorFeedResponse.safeParse(await getJson(url));
  if (!parsed.success) return [];
  return parsed.data.feed.flatMap((entry) => parseFeedEntry(agent, entry) ?? []);
}

export async function loadCombinedFeed(agents: Agent[], perAgent = 20): Promise<FeedItem[]> {
  const results = await Promise.all(
    agents.filter((a) => a.live).map((a) => fetchAuthorFeed(a, perAgent)),
  );
  return results.flat().toSorted((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
}

export async function fetchProfile(agent: Agent): Promise<Profile | null> {
  const url = `${APPVIEW}/xrpc/app.bsky.actor.getProfile?actor=${encodeURIComponent(agent.handle)}`;
  const parsed = profileResponse.safeParse(await getJson(url));
  if (!parsed.success) return null;
  return {
    handle: parsed.data.handle,
    description: parsed.data.description ?? "",
    avatar: parsed.data.avatar ?? "",
  };
}

export async function loadProfiles(agents: Agent[]): Promise<Map<string, Profile>> {
  const results = await Promise.all(
    agents.map(async (a) => [a.name, await fetchProfile(a)] as const),
  );
  const map = new Map<string, Profile>();
  for (const [name, profile] of results) if (profile) map.set(name, profile);
  return map;
}
