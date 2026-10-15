/**
 * Add-Employee wizard: navigation, validation, kept values, review/edit,
 * create success + failure, duplicate-submit guard, permissions.
 *
 * Run:  cd frontend && npm test -- employee-wizard
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { push, post, patch, get, toastError } = vi.hoisted(() => ({
  push: vi.fn(), post: vi.fn(), patch: vi.fn(), get: vi.fn(), toastError: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/employees/new" }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...r }: { href: string; children: React.ReactNode }) => <a href={href} {...r}>{children}</a>,
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { error: toastError, success: vi.fn(), custom: vi.fn(), dismiss: vi.fn() }),
}));
vi.mock("@/services/api-client", () => ({ default: { get, post, patch } }));

import { useAuthStore } from "@/store/auth.store";
import { EmployeeWizard } from "../EmployeeWizard";

const lists: Record<string, unknown> = {
  "/departments": { items: [{ id: "d1", name: "Engineering" }] },
  "/designations": { items: [{ id: "g1", title: "Developer" }] },
  "/branches": { items: [{ id: "b1", name: "Karachi HQ" }] },
  "/shifts": { items: [{ id: "s1", name: "Day", start_time: "09:00:00", end_time: "18:00:00", is_active: true }] },
  "/roles": { items: [{ id: "r1", name: "Employee" }] },
};

function setup(permissions = ["employees.create"]) {
  useAuthStore.setState({
    isAuthenticated: true,
    user: { id: "u1", first_name: "A", last_name: "R", full_name: "A R", email: "a@b.c", avatar_url: null,
      is_platform_admin: false, has_full_access: false, permissions, roles: [] } as never,
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><EmployeeWizard /></QueryClientProvider>);
  return userEvent.setup();
}

async function fillPersonal(u: ReturnType<typeof userEvent.setup>) {
  await u.type(screen.getByLabelText(/first name/i), "Ali");
  await u.type(screen.getByLabelText(/last name/i), "Raza");
  await u.type(screen.getByLabelText(/work email/i), "ali@company.com");
}
const next = (u: ReturnType<typeof userEvent.setup>) => u.click(screen.getByRole("button", { name: /next step/i }));
async function fillRole(u: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => expect(within(screen.getByLabelText(/^role/i, { selector: "select" })).getByText("Employee")).toBeInTheDocument());
  await u.selectOptions(screen.getByLabelText(/^role/i, { selector: "select" }), "r1");
  await u.type(screen.getByLabelText(/date of joining/i), "2026-10-01");
}
async function toReview(u: ReturnType<typeof userEvent.setup>) {
  await fillPersonal(u); await next(u);
  await fillRole(u); await next(u);
  await next(u); await next(u); await next(u);
  await screen.findByRole("heading", { name: /review & create/i });
}

beforeEach(() => {
  vi.clearAllMocks();
  get.mockImplementation((url: string) => Promise.resolve({ data: lists[url] ?? { items: [] } }));
  post.mockResolvedValue({ data: { id: "emp-1", employee_code: "EMP-0001", temporary_password: "Tmp#1234" } });
  patch.mockResolvedValue({ data: {} });
});

describe("EmployeeWizard", () => {
  it("opens on step 1 of 6 with the full-page title and breadcrumb", () => {
    setup();
    expect(screen.getByRole("heading", { name: /add new employee/i })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: /breadcrumb/i })).toHaveTextContent("Employees");
    expect(screen.getByRole("heading", { name: /let's start with the basics/i })).toBeInTheDocument();
    expect(screen.getAllByText(/step 1 of 6/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
  });

  it("blocks Next on missing required fields and stays on the step", async () => {
    const u = setup();
    await next(u);
    expect(await screen.findByText(/first name is required/i)).toBeInTheDocument();
    expect(screen.getByText(/work email is required/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /let's start with the basics/i })).toBeInTheDocument();
  });

  it("rejects an invalid email", async () => {
    const u = setup();
    await u.type(screen.getByLabelText(/first name/i), "Ali");
    await u.type(screen.getByLabelText(/last name/i), "Raza");
    await u.type(screen.getByLabelText(/work email/i), "not-an-email");
    await next(u);
    expect(await screen.findByText(/valid email/i)).toBeInTheDocument();
  });

  it("does not let the user skip ahead by clicking a later step", async () => {
    const u = setup();
    expect(screen.getByRole("button", { name: /step 4: emergency/i })).toBeDisabled();
    await u.click(screen.getByRole("button", { name: /step 6: review/i })).catch(() => {});
    expect(screen.getByRole("heading", { name: /let's start with the basics/i })).toBeInTheDocument();
  });

  it("keeps values when going Back and forward", async () => {
    const u = setup();
    await fillPersonal(u); await next(u);
    await screen.findByRole("heading", { name: /role & department/i });
    await u.click(screen.getByRole("button", { name: /previous/i }));
    expect(screen.getByLabelText(/first name/i)).toHaveValue("Ali");
    expect(screen.getByLabelText(/work email/i)).toHaveValue("ali@company.com");
  });

  it("loads role and department options from the API", async () => {
    const u = setup();
    await fillPersonal(u); await next(u);
    await waitFor(() => expect(screen.getByRole("option", { name: "Engineering" })).toBeInTheDocument());
    expect(screen.getByRole("option", { name: "Karachi HQ" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Developer" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Day \(09:00–18:00\)/ })).toBeInTheDocument();
  });

  it("requires a role before leaving the Role step", async () => {
    const u = setup();
    await fillPersonal(u); await next(u);
    await next(u);
    expect(await screen.findByText(/assign a role/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /role & department/i })).toBeInTheDocument();
  });

  it("asks for a contact name when only an emergency phone is entered", async () => {
    const u = setup();
    await fillPersonal(u); await next(u);
    await fillRole(u); await next(u); await next(u);
    await u.type(screen.getByLabelText(/phone number/i), "0300123456");
    await next(u);
    expect(await screen.findByText(/add the contact's name/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /emergency contact/i })).toBeInTheDocument();
  });

  it("Review shows the entered values and Edit returns to the right step without losing data", async () => {
    const u = setup();
    await toReview(u);
    const review = screen.getByRole("region", { name: /personal information/i });
    expect(within(review).getByText("Ali Raza")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /role & department/i })).getByText("Employee")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: /edit role & department/i }));
    expect(screen.getByRole("heading", { name: /role & department/i, level: 2 })).toBeInTheDocument();
    expect(screen.getByLabelText(/^role/i, { selector: "select" })).toHaveValue("r1");
    await u.click(screen.getByRole("button", { name: /step 1: personal/i }));
    expect(screen.getByLabelText(/first name/i)).toHaveValue("Ali");
  });

  it("creates the employee with the exact payload, then opens the profile", async () => {
    const u = setup();
    await toReview(u);
    await u.click(screen.getByRole("button", { name: /^create employee$/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/employees/emp-1"));
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith("/employees", expect.objectContaining({
      first_name: "Ali", last_name: "Raza", email: "ali@company.com", role_id: "r1",
      date_of_joining: "2026-10-01", employment_type: "full_time", job_nature: "probationary",
      department_id: null, current_salary: null, currency: "USD", emergency_contact: null,
    }));
    expect(patch).not.toHaveBeenCalled();
  });

  it("keeps the form and does not navigate when creation fails", async () => {
    post.mockRejectedValueOnce({ response: { status: 409, data: { message: "Email already registered" } } });
    const u = setup();
    await toReview(u);
    await u.click(screen.getByRole("button", { name: /^create employee$/i }));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("Email already registered"));
    expect(push).not.toHaveBeenCalled();
    await u.click(screen.getByRole("button", { name: /edit personal information/i }));
    expect(screen.getByLabelText(/work email/i)).toHaveValue("ali@company.com");
  });

  it("ignores a rapid second click while the first request is in flight", async () => {
    let resolve!: (v: unknown) => void;
    post.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    const u = setup();
    await toReview(u);
    const btn = screen.getByRole("button", { name: /^create employee$/i });
    await u.dblClick(btn);
    expect(post).toHaveBeenCalledTimes(1);
    resolve({ data: { id: "emp-1" } });
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("saves nationality / blood group / emergency contact with a follow-up update", async () => {
    const u = setup();
    await u.type(screen.getByLabelText(/nationality/i), "Pakistani");
    await toReview(u);
    await u.click(screen.getByRole("button", { name: /^create employee$/i }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/employees/emp-1", { nationality: "Pakistani" }));
  });

  it("refuses to render for a user without employees.create", () => {
    setup(["employees.view"]);
    expect(screen.getByText(/you can't add employees/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /add new employee/i })).not.toBeInTheDocument();
  });
});
