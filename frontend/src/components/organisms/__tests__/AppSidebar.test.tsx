/**
 * AppSidebar (Untitled UI style): what each kind of user sees, which row is
 * "current", and the account card.
 *
 * Run:  cd frontend && npm test -- AppSidebar
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { pathnameMock } = vi.hoisted(() => ({ pathnameMock: vi.fn(() => "/dashboard") }));
vi.mock("next/navigation", () => ({ usePathname: () => pathnameMock() }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

import { useAuthStore } from "@/store/auth.store";
import { AppSidebar } from "../AppSidebar";

function signIn(over: Record<string, unknown> = {}) {
  useAuthStore.setState({
    isAuthenticated: true,
    user: {
      id: "u1", first_name: "Ahmad", last_name: "Raza", full_name: "Ahmad Raza",
      email: "ahmad@company.com", avatar_url: null,
      is_platform_admin: false, has_full_access: false, permissions: [], roles: [],
      ...over,
    } as never,
  });
}

const link = (name: string) => screen.queryByRole("link", { name });

describe("AppSidebar — who sees what", () => {
  beforeEach(() => pathnameMock.mockReturnValue("/dashboard"));

  it("shows a limited user only what their permissions allow", () => {
    signIn({ permissions: ["employees.view", "attendance.view_own"] });
    render(<AppSidebar />);
    expect(link("Dashboard")).toBeInTheDocument();
    expect(link("Employees")).toBeInTheDocument();
    expect(link("AI Assistant")).toBeInTheDocument();         // open to everyone
    expect(link("Payroll")).not.toBeInTheDocument();
    expect(link("Settings")).not.toBeInTheDocument();
    expect(link("Billing")).not.toBeInTheDocument();
  });

  it("hides a section label when nothing under it is visible", () => {
    signIn({ permissions: ["employees.view"] });
    render(<AppSidebar />);
    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("Tools")).toBeInTheDocument();      // AI Assistant / Marketplace are open
    expect(screen.queryByText("Operations")).not.toBeInTheDocument();
    expect(screen.queryByText("Admin")).not.toBeInTheDocument();
  });

  it("an owner (full access) sees every section but not the platform-admin item", () => {
    signIn({ has_full_access: true });
    render(<AppSidebar />);
    for (const s of ["General", "Operations", "Tools", "Admin"]) expect(screen.getByText(s)).toBeInTheDocument();
    expect(link("Payroll")).toBeInTheDocument();
    expect(link("Settings")).toBeInTheDocument();
    expect(link("Organizations")).not.toBeInTheDocument();
  });

  it("a platform admin also gets Organizations", () => {
    signIn({ is_platform_admin: true });
    render(<AppSidebar />);
    expect(link("Organizations")).toBeInTheDocument();
  });

  it("a group is dropped when none of its children are allowed", () => {
    signIn({ permissions: ["leave.apply"] });   // sees Leave Requests, not Leave Types
    pathnameMock.mockReturnValue("/leave");
    render(<AppSidebar />);
    expect(link("Leave Requests")).toBeInTheDocument();
    expect(link("Leave Types")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Organization/ })).not.toBeInTheDocument();
  });
});

describe("AppSidebar — the current page", () => {
  beforeEach(() => signIn({ has_full_access: true }));

  it("marks the matching top-level row as the current page", () => {
    pathnameMock.mockReturnValue("/employees/123");
    render(<AppSidebar />);
    expect(link("Employees")).toHaveAttribute("aria-current", "page");
    expect(link("Dashboard")).not.toHaveAttribute("aria-current");
  });

  it("opens the group that holds the current page and marks only that child", () => {
    pathnameMock.mockReturnValue("/devices/alerts");
    render(<AppSidebar />);
    expect(link("Activity Alerts")).toHaveAttribute("aria-current", "page");
    // /devices/alerts also starts with /devices -- the parent page must not light up too.
    expect(link("All Devices")).not.toHaveAttribute("aria-current");
  });

  it("keeps other groups closed until they are opened by hand", async () => {
    pathnameMock.mockReturnValue("/dashboard");
    render(<AppSidebar />);
    expect(link("Shifts")).not.toBeInTheDocument();
    const attendance = screen.getByRole("button", { name: "Attendance" });
    expect(attendance).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(attendance);
    expect(attendance).toHaveAttribute("aria-expanded", "true");
    expect(link("Shifts")).toBeInTheDocument();
  });
});

describe("AppSidebar — account card", () => {
  beforeEach(() => {
    pathnameMock.mockReturnValue("/dashboard");
    signIn({ has_full_access: true });
  });

  it("shows the signed-in user's name, email and initials", () => {
    render(<AppSidebar />);
    expect(screen.getByText("Ahmad Raza")).toBeInTheDocument();
    expect(screen.getByText("ahmad@company.com")).toBeInTheDocument();
    expect(screen.getByText("AR")).toBeInTheDocument();
  });

  it("opens a menu with My profile and Log out, and Log out signs out", async () => {
    const logout = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({ logout });
    render(<AppSidebar />);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Ahmad Raza/ }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: /My profile/ })).toHaveAttribute("href", "/profile");

    await userEvent.click(within(menu).getByRole("menuitem", { name: /Log out/ }));
    expect(logout).toHaveBeenCalledTimes(1);
  });

  it("closes the menu with Escape and when clicking elsewhere", async () => {
    render(<AppSidebar />);
    const card = screen.getByRole("button", { name: /Ahmad Raza/ });
    await userEvent.click(card);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await userEvent.click(card);
    await userEvent.click(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
