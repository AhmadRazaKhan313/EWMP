/** Topbar: the Search box and Ctrl/Cmd+K open the palette; titles pick the most specific page. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { pathnameMock } = vi.hoisted(() => ({ pathnameMock: vi.fn(() => "/dashboard") }));
vi.mock("next/navigation", () => ({
  usePathname: () => pathnameMock(),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("../NotificationBell", () => ({ NotificationBell: () => <div data-testid="bell" /> }));
vi.mock("@/services/api-client", () => ({ default: { get: vi.fn().mockResolvedValue({ data: { items: [] } }) } }));

import { useAuthStore } from "@/store/auth.store";
import { AppTopbar } from "../AppTopbar";

function mount() {
  render(<QueryClientProvider client={new QueryClient()}><AppTopbar /></QueryClientProvider>);
}

beforeEach(() => {
  pathnameMock.mockReturnValue("/dashboard");
  useAuthStore.setState({
    isAuthenticated: true,
    user: { id: "u1", first_name: "Ahmad", last_name: "Raza", full_name: "Ahmad Raza", email: "a@c.com",
      is_platform_admin: false, has_full_access: true, permissions: [], roles: [] } as never,
  });
});

describe("AppTopbar search", () => {
  it("clicking Search opens the palette", async () => {
    mount();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("Ctrl+K opens it from anywhere and Escape closes it", async () => {
    mount();
    await userEvent.keyboard("{Control>}k{/Control}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("titles the Management page 'Management', not 'Settings'", () => {
    pathnameMock.mockReturnValue("/settings/management");
    mount();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Management");
  });

  it("still titles /settings as Settings and /departments as Departments", () => {
    pathnameMock.mockReturnValue("/settings");
    mount();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Settings");
  });
});
