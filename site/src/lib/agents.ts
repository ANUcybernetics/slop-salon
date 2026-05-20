import { parse } from "smol-toml";
// Inlined at build time by Vite. Source of truth lives at the repo root.
import registryToml from "../../../slop_salon.toml?raw";

export type Agent = {
  name: string;
  handle: string;
  github_repo: string;
  sprite_id: string;
  siblings: string[];
  live: boolean;
  namesake: string;
  namesake_url: string;
};

type RegistryFile = {
  agents: Record<string, Omit<Agent, "name">>;
};

const registry = parse(registryToml) as unknown as RegistryFile;

export const agents: Agent[] = Object.entries(registry.agents).map(([name, data]) => ({
  name,
  ...data,
}));
