import type { Agent } from "./agents.ts";

const RAW_BASE = "https://raw.githubusercontent.com";
const API_BASE = "https://api.github.com";

const GH_TOKEN = process.env.GITHUB_TOKEN ?? "";

function ghHeaders(): Record<string, string> {
  const h: Record<string, string> = {
    accept: "application/vnd.github+json",
    "x-github-api-version": "2022-11-28",
  };
  if (GH_TOKEN) h.authorization = `Bearer ${GH_TOKEN}`;
  return h;
}

export type TickNote = {
  agent: string;
  filename: string;
  stem: string;
  date: string;
  url: string;
  snippet: string;
};

export type AgentDocs = {
  soul: string | null;
  claude: string | null;
  siblings: string | null;
};

export type AgentNotebook = {
  agent: string;
  docs: AgentDocs;
  ticks: TickNote[];
};

// Covers both naming conventions in use:
//   tick-2026-05-22w.md      (lou, mina)
//   2026-05-20-basin-boundary.md  (gert, vita, lelia)
const NOTE_RE = /^(?:tick-)?(\d{4}-\d{2}-\d{2})([a-z]*)(?:-(.+))?\.md$/;

export function noteSortKey(filename: string): [string, number, string, string] {
  const m = filename.match(NOTE_RE);
  if (!m) return ["", 0, "", ""];
  return [m[1], m[2].length, m[2], m[3] ?? ""];
}

export function compareNotes(a: string, b: string): number {
  const ka = noteSortKey(a);
  const kb = noteSortKey(b);
  if (ka[0] !== kb[0]) return ka[0] < kb[0] ? 1 : -1;
  if (ka[1] !== kb[1]) return kb[1] - ka[1];
  if (ka[2] !== kb[2]) return ka[2] < kb[2] ? 1 : -1;
  if (ka[3] !== kb[3]) return ka[3] < kb[3] ? -1 : 1;
  return 0;
}

function stemOf(filename: string): string {
  return filename.replace(/\.md$/, "");
}

function dateOf(filename: string): string {
  return noteSortKey(filename)[0];
}

async function fetchRaw(repo: string, path: string): Promise<string | null> {
  const url = `${RAW_BASE}/${repo}/main/${path}`;
  try {
    const res = await fetch(url);
    if (!res.ok) {
      if (res.status !== 404) console.warn(`[notebook] ${repo}/${path} -> ${res.status}`);
      return null;
    }
    return await res.text();
  } catch (err) {
    console.warn(`[notebook] raw fetch failed ${repo}/${path}:`, err);
    return null;
  }
}

type GhContentEntry = { name: string; type: string };

async function listNotes(repo: string): Promise<string[]> {
  const url = `${API_BASE}/repos/${repo}/contents/notes`;
  try {
    const res = await fetch(url, { headers: ghHeaders() });
    if (!res.ok) {
      console.warn(`[notebook] list ${repo} -> ${res.status}`);
      return [];
    }
    const data = (await res.json()) as GhContentEntry[];
    return data.filter((e) => e.type === "file" && NOTE_RE.test(e.name)).map((e) => e.name);
  } catch (err) {
    console.warn(`[notebook] list failed for ${repo}:`, err);
    return [];
  }
}

export function snippetOf(markdown: string): string {
  // Strip leading YAML frontmatter (some agents prefix notes with --- ... ---).
  const noFrontmatter = markdown.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
  // Drop heading lines of any level — they're scaffolding, not snippet material.
  const stripped = noFrontmatter.replace(/^#+\s+.*$/gm, "");
  const paras = stripped.split(/\n\s*\n/);
  for (const raw of paras) {
    const para = raw.trim();
    if (!para) continue;
    const text = para
      .replace(/`([^`]+)`/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/[*_]+/g, "")
      .replace(/\s+/g, " ")
      .trim();
    if (!text) continue;
    return text.length > 220 ? text.slice(0, 217).trimEnd() + "…" : text;
  }
  return "";
}

async function loadTicks(agent: Agent, limit: number): Promise<TickNote[]> {
  const repo = agent.github_repo;
  const names = (await listNotes(repo)).toSorted(compareNotes).slice(0, limit);
  const bodies = await Promise.all(names.map((n) => fetchRaw(repo, `notes/${n}`)));
  return names.map((filename, i) => ({
    agent: agent.name,
    filename,
    stem: stemOf(filename),
    date: dateOf(filename),
    url: `https://github.com/${repo}/blob/main/notes/${filename}`,
    snippet: snippetOf(bodies[i] ?? ""),
  }));
}

export async function loadNotebook(agent: Agent, tickLimit = 8): Promise<AgentNotebook> {
  const repo = agent.github_repo;
  const [soul, claude, siblings, ticks] = await Promise.all([
    fetchRaw(repo, "SOUL.md"),
    fetchRaw(repo, "CLAUDE.md"),
    fetchRaw(repo, "SIBLINGS.md"),
    loadTicks(agent, tickLimit),
  ]);
  return { agent: agent.name, docs: { soul, claude, siblings }, ticks };
}

export async function loadCombinedTicks(agents: Agent[], limitPerAgent = 12): Promise<TickNote[]> {
  const live = agents.filter((a) => a.live);
  const lists = await Promise.all(live.map((a) => loadTicks(a, limitPerAgent)));
  return lists.flat().toSorted((a, b) => compareNotes(a.filename, b.filename));
}
