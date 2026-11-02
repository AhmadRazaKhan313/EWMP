/** Settings -> Management hub: only pages the user may open, grouped. */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a>,
}));

import { useAuthStore } from "@/store/auth.store";
import ManagementPage from "@/app/(dashboard)/settings/management/page";

function signIn(over: Record<string, unknown> = {}) {
  useAuthStore.setState({
    isAuthenticated: true,
    user: { id: "u1", first_name: "A", last_name: "R", full_name: "A R", email: "a@c.com",
      is_platform_admin: false, has_full_access: false, permissions: [], roles: [], ...over } as never,
  });
}

describe("Settings -> Management", () => {
  it("shows every finished management page to an owner", () => {
    signIn({ has_full_access: true });
    render(<ManagementPage />);
    for (const name of ["Departments", "Branches", "Teams", "Designations", "Shifts", "Leave Types", "Recruitment", "Assets"]) {
      expect(screen.getByRole("link", { name: new RegExp(name) })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: /Departments/ })).toHaveAttribute("href", "/departments");
    // unfinished features stay hidden
    expect(screen.queryByRole("link", { name: /Billing/ })).not.toBeInTheDocument();
  });

  it("shows only what the role allows, and hides empty groups", () => {
    signIn({ permissions: ["leave.manage_types"] });
    render(<ManagementPage />);
    expect(screen.getByRole("link", { name: /Leave Types/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Departments/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Organization")).not.toBeInTheDocument();
    expect(screen.getByText("Attendance & Leave")).toBeInTheDocument();
  });

  it("explains when there is nothing to show", () => {
    signIn({ permissions: ["employees.view"] });
    render(<ManagementPage />);
    expect(screen.getByText(/don.t have access to any management pages/)).toBeInTheDocument();
  });
});
