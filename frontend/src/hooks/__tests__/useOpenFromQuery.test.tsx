/** D-03: quick actions deep-link into a create dialog exactly once. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useOpenFromQuery } from "../useOpenFromQuery";

afterEach(() => window.history.replaceState(null, "", "/"));

describe("useOpenFromQuery", () => {
  it("opens when the param is present and strips it from the URL", () => {
    window.history.replaceState(null, "", "/leave?apply=1&x=2");
    const open = vi.fn();
    renderHook(() => useOpenFromQuery("apply", open));
    expect(open).toHaveBeenCalledTimes(1);
    expect(window.location.search).toBe("?x=2");
  });

  it("does nothing without the param", () => {
    window.history.replaceState(null, "", "/leave");
    const open = vi.fn();
    renderHook(() => useOpenFromQuery("apply", open));
    expect(open).not.toHaveBeenCalled();
  });
});
