import type { Agent } from "./agents.ts";

function rawUrl(repo: string): string {
  return `https://raw.githubusercontent.com/${repo}/main/ABOUT.md`;
}

export async function fetchAbout(repo: string): Promise<string | null> {
  const url = rawUrl(repo);
  let res: Response;
  try {
    res = await fetch(url, { headers: { accept: "text/plain" } });
  } catch (err) {
    console.warn(`[about] fetch failed for ${repo}:`, err);
    return null;
  }
  if (res.status === 404) return null;
  if (!res.ok) {
    console.warn(`[about] ${repo} returned ${res.status}`);
    return null;
  }
  return await res.text();
}

export async function loadAbouts(agents: Agent[]): Promise<Map<string, string>> {
  const results = await Promise.all(
    agents.map(async (a) => [a.name, await fetchAbout(a.github_repo)] as const),
  );
  const map = new Map<string, string>();
  for (const [name, content] of results) {
    if (content) map.set(name, content);
  }
  return map;
}
