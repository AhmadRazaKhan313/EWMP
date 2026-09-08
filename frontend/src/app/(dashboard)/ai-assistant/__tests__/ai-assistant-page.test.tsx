/**
 * Regression tests for an infinite-render-loop bug on the AI Assistant page.
 *
 * The page had a single useEffect that both (a) fixed the placeholder
 * welcome message's epoch-0 timestamp via setMessages(prev.map(...)), and
 * (b) scrolled to the bottom — with `messages` itself as the dependency.
 *
 * Array.prototype.map() always returns a brand-new array reference, even
 * when every element inside is unchanged. So every run of the effect
 * called setMessages with a new-but-content-identical array, which React
 * treats as a state change (different reference), which re-triggered the
 * effect (its dependency, `messages`, "changed" again) — an infinite
 * render loop. React detects this as too many re-renders and logs
 * "Maximum update depth exceeded" instead of actually hanging the tab in
 * a test environment, which is what these tests assert never happens.
 *
 * The fix splits this into two effects: a mount-only one (`[]` deps) for
 * the one-time timestamp fix, and a separate scroll effect keyed on
 * `messages.length` (a primitive, immune to the array-identity churn
 * problem) instead of the `messages` array itself.
 *
 * Run:  cd frontend && npm test -- ai-assistant
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AIAssistantPage from "../page";

vi.mock("@/services/api-client", () => ({
  default: {
    post: vi.fn().mockResolvedValue({ data: { response: "Here you go.", tools_used: [] } }),
  },
}));

import apiClient from "@/services/api-client";

describe("AI Assistant page — infinite-render-loop regression", () => {
  let scrollIntoViewMock: ReturnType<typeof vi.fn>;
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();
    scrollIntoViewMock = vi.fn();
    // jsdom doesn't implement scrollIntoView at all — without this stub,
    // every render would throw "not implemented", masking the actual bug.
    Element.prototype.scrollIntoView = scrollIntoViewMock as unknown as typeof Element.prototype.scrollIntoView;
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  it("mounts, settles, and never logs React's 'Maximum update depth exceeded' loop warning", async () => {
    render(<AIAssistantPage />);

    // Give any runaway effect chain a real chance to manifest — an
    // infinite loop would have logged the warning many times over by now.
    await new Promise((resolve) => setTimeout(resolve, 200));

    const loopWarnings = consoleErrorSpy.mock.calls.filter((call: unknown[]) =>
      String(call[0]).includes("Maximum update depth exceeded"),
    );
    expect(loopWarnings).toHaveLength(0);
  });

  it("fixes the welcome message's placeholder timestamp exactly once, without re-looping", async () => {
    render(<AIAssistantPage />);

    // The welcome bubble's timestamp starts as epoch 0 (1970) and the
    // mount effect corrects it to "now" — confirm the visible clock time
    // is NOT the 1970 placeholder after the effect settles.
    await waitFor(() => {
      const timeText = screen.getByText(/^\d{1,2}:\d{2}\s?(AM|PM)$/i);
      expect(timeText).toBeInTheDocument();
    });

    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(consoleErrorSpy.mock.calls.filter((c: unknown[]) => String(c[0]).includes("Maximum update depth"))).toHaveLength(0);
  });

  it("still scrolls to the newest message when a new message arrives", async () => {
    render(<AIAssistantPage />);
    scrollIntoViewMock.mockClear(); // ignore the mount-time scroll

    const user = userEvent.setup();
    const textarea = screen.getByPlaceholderText(/ask anything/i);
    await user.type(textarea, "Hello");
    await user.click(screen.getByRole("button", { name: "" })); // send button (icon-only)

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    await waitFor(() => expect(scrollIntoViewMock).toHaveBeenCalled());
  });

  it("does not re-scroll on renders where the message count is unchanged", async () => {
    render(<AIAssistantPage />);
    await waitFor(() => expect(scrollIntoViewMock).toHaveBeenCalledTimes(1)); // mount-time scroll only

    // A render with no new/removed message (e.g. re-render from some
    // unrelated state) must not call scrollIntoView again.
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(scrollIntoViewMock).toHaveBeenCalledTimes(1);
  });
});
