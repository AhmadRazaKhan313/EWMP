import { describe, it, expect } from "vitest";
import { OWNER_ROLES, PHASES, TASK_KINDS } from "../onboarding.service";

// The editor's dropdowns must offer exactly what the backend accepts.
describe("onboarding option lists", () => {
  it("match the backend's owner roles, phases and kinds", () => {
    expect(OWNER_ROLES.map((o) => o.value)).toEqual(["hr", "it", "manager", "employee"]);
    expect(PHASES.map((o) => o.value)).toEqual(["pre_boarding", "day_1", "first_week", "probation", "exit"]);
    expect(TASK_KINDS.map((o) => o.value).sort()).toEqual(["acknowledge", "document", "form", "manual", "provision"]);
  });
});
