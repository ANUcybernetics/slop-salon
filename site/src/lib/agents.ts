import { parse } from "smol-toml";
// Inlined at build time by Vite. Source of truth lives at the repo root.
import registryToml from "../../../slop_salon.toml?raw";

export type Salon = {
  id: string;
  label: string;
  provider: string;
};

export type Agent = {
  name: string;
  handle: string;
  github_repo: string;
  sprite_id: string;
  salon: string;
  live: boolean;
  namesake: string;
  namesake_url: string;
};

type RegistryFile = {
  salons: Record<string, Omit<Salon, "id">>;
  agents: Record<string, Omit<Agent, "name">>;
};

const registry = parse(registryToml) as unknown as RegistryFile;

export const salons: Salon[] = Object.entries(registry.salons).map(([id, data]) => ({
  id,
  ...data,
}));

export const agents: Agent[] = Object.entries(registry.agents).map(([name, data]) => ({
  name,
  ...data,
}));

/** Every other agent in `agent`'s salon, in registry order. */
export const siblingsOf = (agent: Agent): Agent[] =>
  agents.filter((a) => a.salon === agent.salon && a.name !== agent.name);
