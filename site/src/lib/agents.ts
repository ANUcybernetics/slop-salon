import { parse } from "smol-toml";
// Inlined at build time by Vite. Source of truth lives at the repo root.
import registryToml from "../../../slop_salon.toml?raw";

export type Provider = { id: string; model: string };
export type Salon = { id: string; label: string; provider: string };
export type Soul = { id: string; label: string };

export type Agent = {
  name: string;
  handle: string;
  github_repo: string;
  sprite_id: string;
  salon: string;
  soul: string;
  live: boolean;
  namesake: string;
  namesake_url: string;
};

type RegistryFile = {
  providers: Record<string, { model: string }>;
  salons: Record<string, Omit<Salon, "id">>;
  souls: Record<string, Omit<Soul, "id">>;
  agents: Record<string, Omit<Agent, "name">>;
};

const registry = parse(registryToml) as unknown as RegistryFile;

export const providers: Provider[] = Object.entries(registry.providers).map(([id, data]) => ({
  id,
  model: data.model,
}));

export const salons: Salon[] = Object.entries(registry.salons).map(([id, data]) => ({
  id,
  ...data,
}));

export const souls: Soul[] = Object.entries(registry.souls).map(([id, data]) => ({
  id,
  ...data,
}));

export const agents: Agent[] = Object.entries(registry.agents).map(([name, data]) => ({
  name,
  ...data,
}));

export const liveAgents = (): Agent[] => agents.filter((a) => a.live);

/** Every other agent in `agent`'s salon, in registry order. */
export const siblingsOf = (agent: Agent): Agent[] =>
  agents.filter((a) => a.salon === agent.salon && a.name !== agent.name);

export const salonOf = (agent: Agent): Salon | undefined =>
  salons.find((s) => s.id === agent.salon);

export const soulOf = (agent: Agent): Soul | undefined => souls.find((s) => s.id === agent.soul);

/** The bare model id a salon runs (the OpenRouter preset suffix dropped). */
export const modelOf = (salon: Salon): string =>
  providers.find((p) => p.id === salon.provider)?.model.split("@")[0] ?? "";

export type SalonGroup = { salon: Salon; agents: Agent[] };

/** The roster as the site shows it: one group per salon, in registry order. */
export const agentsBySalon = (): SalonGroup[] =>
  salons.map((salon) => ({ salon, agents: agents.filter((a) => a.salon === salon.id) }));

/** Where a past season's notes live in an agent's workshop repo. */
export const seasonNotesUrl = (agent: Agent, tag: string): string =>
  `https://github.com/${agent.github_repo}/tree/${tag}/notes`;
