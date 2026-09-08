import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ServerSetupScreen from "../ServerSetupScreen";
import * as connectionService from "../../services/serverConnectionService";
import { setServerBaseUrl } from "@shared/api-client";

vi.mock("../../services/serverConnectionService");
vi.mock("@shared/api-client", async () => {
  const actual = await vi.importActual<typeof import("@shared/api-client")>("@shared/api-client");
  return { ...actual, setServerBaseUrl: vi.fn() };
});

describe("ServerSetupScreen", () => {
  beforeEach(() => vi.clearAllMocks());

  it("saves the server URL and calls onConnected when health check succeeds", async () => {
    vi.mocked(connectionService.checkServerHealth).mockResolvedValue({ ok: true, message: "Connected" });
    vi.mocked(connectionService.normalizeServerUrl).mockReturnValue("http://192.168.1.50:8000");
    const onConnected = vi.fn();

    render(<ServerSetupScreen onConnected={onConnected} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/server address/i), "192.168.1.50:8000");
    await user.click(screen.getByRole("button", { name: /connect/i }));

    await waitFor(() => expect(onConnected).toHaveBeenCalled());
    expect(setServerBaseUrl).toHaveBeenCalledWith("http://192.168.1.50:8000");
    expect(screen.getByRole("status")).toHaveTextContent("Connected");
  });

  it("shows an error and does not call onConnected when the health check fails", async () => {
    vi.mocked(connectionService.checkServerHealth).mockResolvedValue({
      ok: false,
      message: "Could not reach that address",
    });
    const onConnected = vi.fn();

    render(<ServerSetupScreen onConnected={onConnected} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/server address/i), "bad-address");
    await user.click(screen.getByRole("button", { name: /connect/i }));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Could not reach"));
    expect(onConnected).not.toHaveBeenCalled();
    expect(setServerBaseUrl).not.toHaveBeenCalled();
  });
});
