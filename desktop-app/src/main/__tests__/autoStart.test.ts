import { describe, it, expect } from "vitest";
import { loginItemOptions, shouldStartHidden, HIDDEN_FLAG } from "../autoStart";

describe("loginItemOptions", () => {
  it("registers a packaged Windows app to start hidden at login", () => {
    expect(loginItemOptions(true, "win32")).toEqual({ openAtLogin: true, openAsHidden: true, args: [HIDDEN_FLAG] });
  });
  it("registers on macOS too", () => {
    expect(loginItemOptions(true, "darwin")?.openAtLogin).toBe(true);
  });
  it("never registers a dev run", () => {
    expect(loginItemOptions(false, "win32")).toBeNull();
  });
  it("does nothing on Linux", () => {
    expect(loginItemOptions(true, "linux")).toBeNull();
  });
});

describe("shouldStartHidden", () => {
  it("is hidden with the flag", () => {
    expect(shouldStartHidden(["app.exe", HIDDEN_FLAG], false)).toBe(true);
  });
  it("is hidden when the OS says it was opened at login", () => {
    expect(shouldStartHidden(["app.exe"], true)).toBe(true);
  });
  it("is visible on a normal launch", () => {
    expect(shouldStartHidden(["app.exe"], false)).toBe(false);
  });
});
