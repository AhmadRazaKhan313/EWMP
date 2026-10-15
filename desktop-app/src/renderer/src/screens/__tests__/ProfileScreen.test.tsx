import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ProfileScreen from "../ProfileScreen";
import * as authService from "../../services/authService";
import { useAuthStore } from "../../store/authStore";
import type { MeResponse } from "../../types/auth";

vi.mock("../../services/authService");

const PROFILE: MeResponse = {
  id: "u1", email: "ada@example.com", first_name: "Ada", last_name: "Lovelace",
  full_name: "Ada Lovelace", avatar_url: null, phone: "0300-1234567", bio: "Loves math.",
  is_platform_admin: false, is_2fa_enabled: false, must_change_password: false, organization_id: "org1",
  roles: ["employee"], permissions: [], has_full_access: false, has_employee_profile: true,
  preferences: {},
};

function renderWithClient(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ProfileScreen />
    </QueryClientProvider>,
  );
}

describe("ProfileScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      status: "authenticated",
      user: {
        id: "u1", email: "ada@example.com", full_name: "Ada Lovelace", avatar_url: null,
        must_change_password: false,
      },
      error: null,
    });
    vi.mocked(authService.getMe).mockResolvedValue(PROFILE);
    vi.mocked(authService.resolveAvatarUrl).mockResolvedValue(null);
  });

  it("shows the profile's name, email, roles, phone, and bio", async () => {
    renderWithClient();
    await waitFor(() => expect(screen.getByText("Ada Lovelace")).toBeInTheDocument());
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByText("employee")).toBeInTheDocument();
    expect(screen.getByText("0300-1234567")).toBeInTheDocument();
    expect(screen.getByText("Loves math.")).toBeInTheDocument();
  });

  it("shows a placeholder icon (not a broken image) when there is no avatar", async () => {
    renderWithClient();
    await screen.findByText("Ada Lovelace");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("renders the resolved avatar image when one exists", async () => {
    vi.mocked(authService.resolveAvatarUrl).mockResolvedValue("https://server.example/api/v1/auth/avatar/u1");
    renderWithClient();
    const img = await screen.findByRole("img");
    expect(img).toHaveAttribute("src", "https://server.example/api/v1/auth/avatar/u1");
  });

  it("clicking Edit profile opens a pre-filled form", async () => {
    renderWithClient();
    await screen.findByText("Ada Lovelace");
    const user = userEvent.setup();
    await user.click(screen.getByTestId("edit-profile-button"));

    expect(screen.getByTestId("input-first-name")).toHaveValue("Ada");
    expect(screen.getByTestId("input-last-name")).toHaveValue("Lovelace");
    expect(screen.getByTestId("input-phone")).toHaveValue("0300-1234567");
    expect(screen.getByTestId("input-bio")).toHaveValue("Loves math.");
  });

  it("saving edits calls updateProfile with the four editable fields and syncs the header's authStore user", async () => {
    const updated: MeResponse = { ...PROFILE, first_name: "Augusta", full_name: "Augusta Lovelace" };
    vi.mocked(authService.updateProfile).mockResolvedValue(updated);
    renderWithClient();
    const user = userEvent.setup();

    await screen.findByText("Ada Lovelace");
    await user.click(screen.getByTestId("edit-profile-button"));
    await user.clear(screen.getByTestId("input-first-name"));
    await user.type(screen.getByTestId("input-first-name"), "Augusta");
    await user.click(screen.getByTestId("save-profile-button"));

    await waitFor(() =>
      expect(authService.updateProfile).toHaveBeenCalledWith({
        first_name: "Augusta", last_name: "Lovelace", phone: "0300-1234567", bio: "Loves math.",
      }),
    );
    await waitFor(() => expect(useAuthStore.getState().user?.full_name).toBe("Augusta Lovelace"));
  });

  it("Cancel discards edits without calling updateProfile", async () => {
    renderWithClient();
    const user = userEvent.setup();
    await screen.findByText("Ada Lovelace");
    await user.click(screen.getByTestId("edit-profile-button"));
    await user.clear(screen.getByTestId("input-first-name"));
    await user.type(screen.getByTestId("input-first-name"), "Someone Else");
    await user.click(screen.getByText("Cancel"));

    expect(screen.queryByTestId("profile-edit-form")).not.toBeInTheDocument();
    expect(authService.updateProfile).not.toHaveBeenCalled();
  });

  it("rejects an oversized avatar client-side without calling uploadAvatar", async () => {
    renderWithClient();
    await screen.findByText("Ada Lovelace");
    const bigFile = new File([new Uint8Array(6 * 1024 * 1024)], "big.png", { type: "image/png" });
    const input = screen.getByTestId("avatar-file-input") as HTMLInputElement;

    await userEvent.upload(input, bigFile);

    expect(await screen.findByRole("alert")).toHaveTextContent(/5 MB/);
    expect(authService.uploadAvatar).not.toHaveBeenCalled();
  });

  it("rejects a non-image-type file client-side without calling uploadAvatar", async () => {
    renderWithClient();
    await screen.findByText("Ada Lovelace");
    const badFile = new File(["hi"], "notes.txt", { type: "text/plain" });
    const input = screen.getByTestId("avatar-file-input") as HTMLInputElement;

    // fireEvent (not userEvent.upload) — userEvent.upload respects the
    // input's `accept` attribute and silently no-ops for a mismatched
    // file, which would make this test pass for the wrong reason. A
    // real drag-and-drop can still deliver a mismatched file, so the
    // client-side check itself must actually run here.
    fireEvent.change(input, { target: { files: [badFile] } });

    expect(await screen.findByRole("alert")).toHaveTextContent(/PNG, JPEG, or WebP/);
    expect(authService.uploadAvatar).not.toHaveBeenCalled();
  });

  it("uploads a valid avatar and syncs the header's authStore avatar_url", async () => {
    vi.mocked(authService.uploadAvatar).mockResolvedValue({ avatar_url: "/api/v1/auth/avatar/u1" });
    renderWithClient();
    await screen.findByText("Ada Lovelace");
    const goodFile = new File([new Uint8Array(1024)], "me.png", { type: "image/png" });
    const input = screen.getByTestId("avatar-file-input") as HTMLInputElement;

    await userEvent.upload(input, goodFile);

    // react-query 5.x passes a (variables, context) pair to mutationFn —
    // only the first argument (the File) is ours to assert on.
    await waitFor(() => expect(authService.uploadAvatar).toHaveBeenCalled());
    expect(vi.mocked(authService.uploadAvatar).mock.calls[0]?.[0]).toBe(goodFile);
    await waitFor(() => expect(useAuthStore.getState().user?.avatar_url).toBe("/api/v1/auth/avatar/u1"));
  });

  it("shows an upload error message if the backend rejects the avatar", async () => {
    vi.mocked(authService.uploadAvatar).mockRejectedValue(new Error("500"));
    renderWithClient();
    await screen.findByText("Ada Lovelace");
    const file = new File([new Uint8Array(1024)], "me.png", { type: "image/png" });
    const input = screen.getByTestId("avatar-file-input") as HTMLInputElement;

    await userEvent.upload(input, file);

    expect(await screen.findByRole("alert")).toHaveTextContent(/under 5 MB/i);
  });
});
