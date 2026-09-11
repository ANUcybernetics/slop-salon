import { describe, expect, it } from "vitest";
import { agents, agentsBySalon, modelOf, salons, siblingsOf, soulOf, souls } from "./agents.ts";

describe("salon roster", () => {
  it("places every agent in exactly one salon group", () => {
    const grouped = agentsBySalon().flatMap((g) => g.agents.map((a) => a.name));
    expect(grouped.toSorted()).toEqual(agents.map((a) => a.name).toSorted());
  });

  it("keeps every sibling graph closed within its salon", () => {
    for (const agent of agents) {
      for (const sibling of siblingsOf(agent)) {
        expect(sibling.salon).toBe(agent.salon);
        expect(sibling.name).not.toBe(agent.name);
      }
    }
  });

  it("gives every salon a label and a model", () => {
    for (const salon of salons) {
      expect(salon.label.length).toBeGreaterThan(0);
      expect(modelOf(salon)).toMatch(/^[a-z-]+\/[a-z0-9.-]+$/);
    }
  });

  it("crosses every soul with every salon exactly once", () => {
    for (const { agents: members } of agentsBySalon()) {
      const carried = members.map((a) => soulOf(a)?.id).toSorted();
      expect(carried).toEqual(souls.map((s) => s.id).toSorted());
    }
  });
});
