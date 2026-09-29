import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../App";
import { useAuthStore } from "../store/authStore";
import * as apiClient from "@shared/api-client";

vi.mock("@shared/api-client", async () => {
  const actual = await vi.importActual<typeof import("@shared/api-client")>("@shared/api-client");
  return { ...actual, hasServerConfigured: vi.fn() };
});

// Mirrors main.tsx's real provider wrapping — AuthenticatedPlaceholder now
// reads notification-badge data via useQuery, which throws without one.
function renderApp(): ReturnType<typeof render> {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

describe("App — auth-driven routing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      status: "checking",
      user: null,
      error: null,
      restoreSession: vi.fn().mockResolvedValue(undefined),
    });
  });

  it("shows the server setup screen when no server is configured yet", async () => {
    vi.mocked(apiClient.hasServerConfigured).mockResolvedValue(false);
    renderApp();
    await waitFor(() => expect(screen.getByText(/connect to your server/i)).toBeInTheDocument());
  });

  it("shows the login screen once a server is configured and session restores to unauthenticated", async () => {
    vi.mocked(apiClient.hasServerConfigured).mockResolvedValue(true);
    useAuthStore.setState({
      restoreSession: vi.fn(async () => {
        useAuthStore.setState({ status: "unauthenticated" });
      }),
    });
    renderApp();
    await waitFor(() => expect(screen.getByRole("heading", { name: /sign in/i })).toBeInTheDocument());
  });

  it("shows the authenticated placeholder once a server is configured and session restores to authenticated", async () => {
    vi.mocked(apiClient.hasServerConfigured).mockResolvedValue(true);
    useAuthStore.setState({
      restoreSession: vi.fn(async () => {
        useAuthStore.setState({
          status: "authenticated",
          user: { id: "1", email: "a@b.com", full_name: "Ada Lovelace", avatar_url: null, must_change_password: false },
        });
      }),
    });
    renderApp();
    await waitFor(() => expect(screen.getByText(/ada lovelace/i)).toBeInTheDocument());
  });

  it("shows the forced change-password screen when the session restores with must_change_password", async () => {
    vi.mocked(apiClient.hasServerConfigured).mockResolvedValue(true);
    useAuthStore.setState({
      restoreSession: vi.fn(async () => {
        useAuthStore.setState({
          status: "authenticated",
          user: { id: "1", email: "a@b.com", full_name: "Ada Lovelace", avatar_url: null, must_change_password: true },
        });
      }),
    });
    renderApp();
    await waitFor(() => expect(screen.getByText(/set a new password/i)).toBeInTheDocument());
  });

  it("does not call restoreSession until a server is configured", async () => {
    vi.mocked(apiClient.hasServerConfigured).mockResolvedValue(false);
    const restoreSpy = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({ restoreSession: restoreSpy });
    renderApp();
    await waitFor(() => expect(screen.getByText(/connect to your server/i)).toBeInTheDocument());
    expect(restoreSpy).not.toHaveBeenCalled();
  });
});
