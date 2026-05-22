import type { Agent } from "./agents.ts";

const APPVIEW = "https://public.api.bsky.app";

export type Profile = {
  handle: string;
  description: string;
  avatar: string;
  banner: string;
  followersCount: number;
  followsCount: number;
  postsCount: number;
};

type BskyProfile = {
  handle: string;
  description?: string;
  avatar?: string;
  banner?: string;
  followersCount?: number;
  followsCount?: number;
  postsCount?: number;
};

export async function fetchProfile(handle: string): Promise<Profile | null> {
  const url = `${APPVIEW}/xrpc/app.bsky.actor.getProfile?actor=${encodeURIComponent(handle)}`;
  let res: Response;
  try {
    res = await fetch(url, { headers: { accept: "application/json" } });
  } catch (err) {
    console.warn(`[profile] fetch failed for ${handle}:`, err);
    return null;
  }
  if (!res.ok) {
    console.warn(`[profile] ${handle} returned ${res.status}`);
    return null;
  }
  const data = (await res.json()) as BskyProfile;
  return {
    handle: data.handle,
    description: data.description ?? "",
    avatar: data.avatar ?? "",
    banner: data.banner ?? "",
    followersCount: data.followersCount ?? 0,
    followsCount: data.followsCount ?? 0,
    postsCount: data.postsCount ?? 0,
  };
}

export async function loadProfiles(
  agents: Agent[],
): Promise<Map<string, Profile>> {
  const results = await Promise.all(
    agents.map(async (a) => [a.name, await fetchProfile(a.handle)] as const),
  );
  const map = new Map<string, Profile>();
  for (const [name, profile] of results) {
    if (profile) map.set(name, profile);
  }
  return map;
}
