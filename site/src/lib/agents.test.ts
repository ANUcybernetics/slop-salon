import { describe, expect, it } from "vitest";
import { agents, agentsBySalon, salons, siblingsOf } from "./agents.ts";

describe("salon roster", () => {
  it("places every agent in exactly one salon group", () => {
    const grouped = agentsBySalon().flatMap((g) => g.agents.map((a) => a.name));
    expect(grouped.toSorted()).toEqual(agents.map((a) => a.name).toSorted());
  });

  it("gives every salon at least two agents (a salon of one has no siblings)", () => {
    for (const group of agentsBySalon()) {
      expect(group.agents.length, group.salon.id).toBeGreaterThanOrEqual(2);
    }
  });

  it("keeps every sibling graph closed within its salon", () => {
    for (const agent of agents) {
      for (const sibling of siblingsOf(agent)) {
        expect(sibling.salon).toBe(agent.salon);
        expect(sibling.name).not.toBe(agent.name);
      }
    }
  });

  it("labels every salon for the site", () => {
    for (const salon of salons) {
      expect(salon.label.length).toBeGreaterThan(0);
    }
  });
});
