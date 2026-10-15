import { describe, it, expect } from "vitest";
import { apiErrorText } from "../api-error";

const err = (data: unknown) => ({ response: { data } });

describe("apiErrorText", () => {
  it("returns a string detail", () => expect(apiErrorText(err({ detail: "No." }), "x")).toBe("No."));
  it("never returns an object for {field,message,type} lists", () => {
    const t = apiErrorText(err({ message: "Request validation failed", detail: [{ field: "body → period_end", message: "Field required", type: "missing" }] }), "x");
    expect(typeof t).toBe("string");
    expect(t).toBe("period_end: Field required");
  });
  it("handles FastAPI {loc,msg}", () => expect(apiErrorText(err({ detail: [{ loc: ["body", "name"], msg: "bad" }] }), "x")).toBe("name: bad"));
  it("falls back to message then fallback", () => {
    expect(apiErrorText(err({ message: "Boom" }), "x")).toBe("Boom");
    expect(apiErrorText(new Error("net"), "fallback")).toBe("fallback");
  });
});
