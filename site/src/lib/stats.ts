import type { FeedItem } from "./bsky.ts";

export type AgentStats = {
  posts: number;
  originals: number;
  reposts: number;
  withImages: number;
  totalLikes: number;
  totalReposts: number;
  totalReplies: number;
  firstAt: string | null;
  lastAt: string | null;
};

export function computeStats(items: FeedItem[]): AgentStats {
  if (items.length === 0) {
    return {
      posts: 0,
      originals: 0,
      reposts: 0,
      withImages: 0,
      totalLikes: 0,
      totalReposts: 0,
      totalReplies: 0,
      firstAt: null,
      lastAt: null,
    };
  }

  let reposts = 0;
  let withImages = 0;
  let totalLikes = 0;
  let totalReposts = 0;
  let totalReplies = 0;
  let minT = Number.POSITIVE_INFINITY;
  let maxT = Number.NEGATIVE_INFINITY;
  let firstAt = "";
  let lastAt = "";

  for (const item of items) {
    if (item.isRepost) reposts++;
    if (item.images.length > 0) withImages++;
    totalLikes += item.likeCount;
    totalReposts += item.repostCount;
    totalReplies += item.replyCount;
    const t = Date.parse(item.createdAt);
    if (!Number.isNaN(t)) {
      if (t < minT) {
        minT = t;
        firstAt = item.createdAt;
      }
      if (t > maxT) {
        maxT = t;
        lastAt = item.createdAt;
      }
    }
  }

  return {
    posts: items.length,
    originals: items.length - reposts,
    reposts,
    withImages,
    totalLikes,
    totalReposts,
    totalReplies,
    firstAt: firstAt || null,
    lastAt: lastAt || null,
  };
}
