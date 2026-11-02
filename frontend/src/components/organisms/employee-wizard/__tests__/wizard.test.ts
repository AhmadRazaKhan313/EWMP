import { describe, it, expect } from "vitest";
import {
  DEFAULT_VALUES, buildCreatePayload, buildFollowUpPatch, crossFieldErrors, employeeWizardSchema,
  firstStepWithError, serverFieldErrors, validateDocumentFile, STEPS,
} from "../wizard";

const valid = {
  ...DEFAULT_VALUES, first_name: "Ali", last_name: "Raza", email: "ali@company.com",
  role_id: "role-1", date_of_joining: "2026-10-01",
};
const fieldsFailing = (v: object) => {
  const r = employeeWizardSchema.safeParse(v);
  return r.success ? [] : r.error.issues.map((i) => String(i.path[0]));
};

describe("schema", () => {
  it("accepts the minimum a new employee needs", () => {
    expect(fieldsFailing(valid)).toEqual([]);
  });
  it("requires name, email, role and joining date", () => {
    expect([...new Set(fieldsFailing(DEFAULT_VALUES))].sort()).toEqual(["date_of_joining", "email", "first_name", "last_name", "role_id"]);
  });
  it("rejects a malformed email and a future birth date", () => {
    expect(fieldsFailing({ ...valid, email: "nope" })).toContain("email");
    expect(fieldsFailing({ ...valid, date_of_birth: "2999-01-01" })).toContain("date_of_birth");
  });
  it("accepts international phone formats and rejects junk", () => {
    expect(fieldsFailing({ ...valid, phone: "+92 300 1234567" })).toEqual([]);
    expect(fieldsFailing({ ...valid, phone: "(021) 555-0100" })).toEqual([]);
    expect(fieldsFailing({ ...valid, phone: "call me" })).toContain("phone");
  });
  it("validates salary as a non-negative amount with at most 2 decimals", () => {
    expect(fieldsFailing({ ...valid, current_salary: "85000.50" })).toEqual([]);
    expect(fieldsFailing({ ...valid, current_salary: "-5" })).toContain("current_salary");
    expect(fieldsFailing({ ...valid, current_salary: "1.234" })).toContain("current_salary");
    expect(fieldsFailing({ ...valid, current_salary: "abc" })).toContain("current_salary");
  });
});

describe("cross-field rule", () => {
  it("asks for a contact name when only a phone was entered", () => {
    expect(crossFieldErrors({ ...DEFAULT_VALUES, emergency_phone: "123456" })[0]?.field).toBe("emergency_name");
  });
  it("is fine with nothing, or with a name alone", () => {
    expect(crossFieldErrors(DEFAULT_VALUES)).toEqual([]);
    expect(crossFieldErrors({ ...DEFAULT_VALUES, emergency_name: "Jane" })).toEqual([]);
  });
});

describe("payload", () => {
  it("sends blanks as null and salary as a number", () => {
    const p = buildCreatePayload({ ...valid, current_salary: "85000.5" });
    expect(p).toMatchObject({
      email: "ali@company.com", role_id: "role-1", department_id: null, phone: null, gender: null,
      current_salary: 85000.5, currency: "USD", emergency_contact: null, is_remote: false,
    });
  });
  it("builds the emergency contact object only when a name exists", () => {
    const p = buildCreatePayload({ ...valid, emergency_name: "Jane", emergency_phone: "123456", emergency_relationship: "spouse" });
    expect(p.emergency_contact).toEqual({ name: "Jane", phone: "123456", relationship: "spouse" });
  });
  it("saves nationality, blood group and emergency contact with a follow-up patch", () => {
    expect(buildFollowUpPatch(valid)).toBeNull();
    const patch = buildFollowUpPatch({ ...valid, nationality: "Pakistani", blood_group: "O+", emergency_name: "Jane" });
    expect(patch).toEqual({ nationality: "Pakistani", blood_group: "O+", emergency_contact: { name: "Jane", phone: null, relationship: null } });
  });
});

describe("step helpers", () => {
  it("has six steps", () => expect(STEPS).toHaveLength(6));
  it("jumps to the earliest step that has an error", () => {
    expect(firstStepWithError(["currency", "email", "role_id"])).toBe(0);
    expect(firstStepWithError(["role_id", "current_salary"])).toBe(1);
    expect(firstStepWithError(["unknown"])).toBe(-1);
  });
  it("maps server field errors to wizard fields", () => {
    const err = { response: { data: { detail: [{ loc: ["body", "email"], msg: "already registered" }, { loc: ["body", "zzz"], msg: "x" }] } } };
    expect(serverFieldErrors(err)).toEqual([{ field: "email", message: "already registered" }]);
  });
});

describe("document file rules", () => {
  const f = (name: string, size = 10) => new File([new Uint8Array(size)], name);
  it("accepts the allowed types", () => expect(validateDocumentFile(f("cnic.pdf"))).toBeNull());
  it("rejects other types, empty files and files over 15 MB", () => {
    expect(validateDocumentFile(f("run.exe"))).toMatch(/PDF/);
    expect(validateDocumentFile(f("a.pdf", 0))).toMatch(/empty/);
    expect(validateDocumentFile(f("a.pdf", 15 * 1024 * 1024 + 1))).toMatch(/15 MB/);
    expect(validateDocumentFile(null)).toMatch(/Choose/);
  });
});
