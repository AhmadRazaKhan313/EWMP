/**
 * CommandPalette (Ctrl/Cmd+K): finds pages the user may open and employees by
 * name, and is fully keyboard-driven.
 *
 * Run:  cd frontend && npm test -- CommandPalette
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { push, getMock } = vi.hoisted(() => ({ push: vi.fn(), getMock: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/services/api-client", () => ({ default: { get: getMock } }));

import { useAuthStore } from "@/store/auth.store";
import { CommandPalette } from "../CommandPalette";

function signIn(over: Record<string, unknown> = {}) {
  useAuthStore.setState({
    isAuthenticated: true,
    user: {
      id: "u1", first_name: "Ahmad", last_name: "Raza", full_name: "Ahmad Raza", email: "a@c.com",
      is_platform_admin: false, has_full_access: true, permissions: [], roles: [], ...over,
    } as never,
  });
}

function show(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <CommandPalette open onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

const box = () => screen.getByRole("combobox");

beforeEach(() => {
  push.mockReset();
  getMock.mockReset();
  getMock.mockResolvedValue({ data: { items: [] } });
});

describe("CommandPalette", () => {
  it("renders nothing while closed", () => {
    signIn();
    const qc = new QueryClient();
    render(<QueryClientProvider client={qc}><CommandPalette open={false} onClose={() => {}} /></QueryClientProvider>);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("focuses the box and lists pages, including management pages", () => {
    signIn();
    show();
    expect(box()).toHaveFocus();
    expect(screen.getByRole("option", { name: /Dashboard/ })).toBeInTheDocument();
  });

  it("finds a management page by its name and by a keyword", async () => {
    signIn();
    show();
    await userEvent.type(box(), "shift");
    expect(screen.getByRole("option", { name: /Shifts/ })).toBeInTheDocument();
    expect(screen.getByText(/Management · Attendance & Leave/)).toBeInTheDocument();

    await userEvent.clear(box());
    await userEvent.type(box(), "laptop");           // a keyword of Assets
    expect(screen.getByRole("option", { name: /Assets/ })).toBeInTheDocument();
  });

  it("never offers a page the user may not open", async () => {
    signIn({ has_full_access: false, permissions: ["employees.view"] });
    show();
    await userEvent.type(box(), "payroll");
    expect(screen.queryByRole("option", { name: /Payroll/ })).not.toBeInTheDocument();
    expect(await screen.findByText(/No results/)).toBeInTheDocument();
  });

  it("Enter opens the highlighted page; arrows move the highlight", async () => {
    signIn();
    const onClose = show();
    await userEvent.type(box(), "leave");
    // "Leave" (exact) ranks first, "Leave Types" after it.
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(push).toHaveBeenCalledWith("/leave-types");
    expect(onClose).toHaveBeenCalled();
  });

  it("Escape closes it", async () => {
    signIn();
    const onClose = show();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("finds employees by name and opens their profile", async () => {
    signIn();
    getMock.mockResolvedValue({
      data: { items: [{ id: "e1", employee_code: "EMP-007", first_name: "Sara", last_name: "Khan", full_name: "Sara Khan" }] },
    });
    show();
    await userEvent.type(box(), "sara");
    const hit = await screen.findByRole("option", { name: /Sara Khan/ });
    expect(getMock).toHaveBeenCalledWith("/employees", { params: { query: "sara", page_size: 6 } });
    expect(hit).toHaveTextContent("EMP-007");
    await userEvent.click(hit.querySelector("button")!);
    expect(push).toHaveBeenCalledWith("/employees/e1");
  });

  it("does not search employees for someone without employees.view", async () => {
    signIn({ has_full_access: false, permissions: ["attendance.view_own"] });
    show();
    await userEvent.type(box(), "sara");
    await new Promise((r) => setTimeout(r, 400));
    expect(getMock).not.toHaveBeenCalled();
    expect(box()).toHaveAttribute("placeholder", "Search pages…");
  });

  it("waits for a pause in typing before asking the server", async () => {
    signIn();
    show();
    await userEvent.type(box(), "sa");
    expect(getMock).not.toHaveBeenCalled();
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(1));
  });
});
