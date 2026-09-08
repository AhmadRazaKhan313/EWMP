import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConsentNotice from "../ConsentNotice";
import { useDeviceStore } from "../../store/deviceStore";

function reset(): void {
  useDeviceStore.setState({ status: "needs_consent", error: null });
}

describe("ConsentNotice", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("explains monitoring scope and shows the acknowledge button", () => {
    render(<ConsentNotice />);
    expect(screen.getByText(/device monitoring notice/i)).toBeInTheDocument();
    expect(screen.getByText(/when an administrator explicitly requests one/i)).toBeInTheDocument();
    expect(screen.getByTestId("consent-acknowledge-button")).toHaveTextContent("I Understand, Continue");
  });

  it("clicking the button calls acknowledgeAndEnroll", async () => {
    const spy = vi.fn().mockResolvedValue(undefined);
    useDeviceStore.setState({ acknowledgeAndEnroll: spy });
    render(<ConsentNotice />);
    const user = userEvent.setup();

    await user.click(screen.getByTestId("consent-acknowledge-button"));

    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("disables the button and shows a spinner while enrolling", async () => {
    useDeviceStore.setState({ status: "enrolling" });
    render(<ConsentNotice />);
    await waitFor(() => expect(screen.getByTestId("consent-acknowledge-button")).toBeDisabled());
  });

  it("shows a non-alarming error if enrollment failed, without blocking re-use", () => {
    useDeviceStore.setState({ status: "needs_finish", error: "Network unreachable" });
    render(<ConsentNotice />);
    expect(screen.getByRole("alert")).toHaveTextContent(/network unreachable/i);
    expect(screen.getByRole("alert")).toHaveTextContent(/you can keep using the app/i);
  });
});
