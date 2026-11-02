/**
 * E-02 / E-08 on the employees list: profile photo, department/branch/status/type
 * filters that reach the server, CSV export with the same filters (permission
 * gated), and saved views kept in the browser.
 *
 * Run:  cd frontend && npm test -- EmployeesListPage
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/services/api-client", () => ({ default: { get: vi.fn() } }));
let perms: string[] = [];
vi.mock("@/store/auth.store", () => ({
  useAuthStore: (sel: (s: { hasPermission: (p: string) => boolean }) => unknown) =>
    sel({ hasPermission: (p: string) => perms.includes(p) }),
}));
import apiClient from "@/services/api-client";
import EmployeesPage from "../page";

const get = (apiClient as unknown as { get: ReturnType<typeof vi.fn> }).get;
const person = (over = {}) => ({
  id: "e1", employee_code: "EMP-1", first_name: "Dana", last_name: "Hire", full_name: "Dana Hire",
  avatar_url: "/uploads/dana.png", employment_status: "active", employment_type: "full_time",
  job_nature: "permanent", date_of_joining: "2026-01-01", department_id: null, designation_id: null,
  branch_id: null, work_phone: null, is_remote: false, years_of_service: 1, ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  perms = [];
  window.localStorage.clear();
  get.mockImplementation(async (url: string) => {
    if (url === "/departments") return { data: { items: [{ id: "d1", name: "Engineering" }] } };
    if (url === "/branches") return { data: { items: [{ id: "b1", name: "Head Office" }] } };
    if (url === "/employees/stats") return { data: { total_active: 1, on_probation: 0, on_leave: 0, notice_period: 0 } };
    if (url === "/employees") return { data: { items: [person(), person({ id: "e2", employee_code: "EMP-2", full_name: "Sam Noimg", first_name: "Sam", last_name: "Noimg", avatar_url: null })], total: 2, page: 1, page_size: 25, total_pages: 1 } };
    return { data: new Blob(["x"]) };
  });
});

function show() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><EmployeesPage /></QueryClientProvider>);
}
const lastListParams = () => {
  const calls = get.mock.calls.filter((c) => c[0] === "/employees");
  return calls[calls.length - 1]![1].params as Record<string, unknown>;
};

describe("employees list", () => {
  it("shows the profile photo, or initials when there is none", async () => {
    show();
    const img = (await screen.findByAltText("Dana Hire")) as HTMLImageElement;
    expect(img.src).toContain("dana.png");
    expect(screen.getByText("SN")).toBeTruthy();
  });

  it("sends the chosen filters to the server and can clear them", async () => {
    const user = userEvent.setup();
    show();
    await screen.findByText("Dana Hire");
    await screen.findByRole("option", { name: "Engineering" });
    await user.selectOptions(screen.getByLabelText("Department filter"), "d1");
    await user.selectOptions(screen.getByLabelText("Status filter"), "probation");
    await user.selectOptions(screen.getByLabelText("Type filter"), "contract");
    await user.selectOptions(screen.getByLabelText("Branch filter"), "b1");
    await waitFor(() => expect(lastListParams()).toMatchObject({
      department_id: "d1", status: "probation", employment_type: "contract", branch_id: "b1", page: 1,
    }));
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(lastListParams().department_id).toBeUndefined());
    expect(lastListParams().status).toBeUndefined();
  });

  it("Export / Import buttons follow permissions", async () => {
    show();
    await screen.findByText("Dana Hire");
    expect(screen.queryByRole("button", { name: /Export CSV/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Import/ })).toBeNull();
  });

  it("exports the CSV with the same filters", async () => {
    perms = ["employees.export", "employees.create"];
    window.URL.createObjectURL = vi.fn(() => "blob:x");
    window.URL.revokeObjectURL = vi.fn();
    const user = userEvent.setup();
    show();
    await screen.findByText("Dana Hire");
    await screen.findByRole("option", { name: "Engineering" });
    await user.selectOptions(screen.getByLabelText("Department filter"), "d1");
    await user.click(screen.getByRole("button", { name: /Export CSV/ }));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/employees/export", expect.objectContaining({
      responseType: "blob", params: expect.objectContaining({ department_id: "d1" }),
    })));
    await user.click(screen.getByRole("button", { name: /Import/ }));
    expect(push).toHaveBeenCalledWith("/employees/import");
  });

  it("saves a view in the browser, re-applies it later and deletes it", async () => {
    const user = userEvent.setup();
    show();
    await screen.findByText("Dana Hire");
    await screen.findByRole("option", { name: "Engineering" });
    expect((screen.getByRole("button", { name: /Save view/ }) as HTMLButtonElement).disabled).toBe(true); // nothing to save
    await user.selectOptions(screen.getByLabelText("Department filter"), "d1");
    await user.selectOptions(screen.getByLabelText("Status filter"), "probation");
    await user.click(screen.getByRole("button", { name: /Save view/ }));
    await user.type(screen.getByLabelText("View name"), "Eng probation");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(JSON.parse(window.localStorage.getItem("ewmp.employees.views")!)).toEqual([
      { name: "Eng probation", filters: { department_id: "d1", status: "probation" } },
    ]);
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect((screen.getByLabelText("Status filter") as HTMLSelectElement).value).toBe("");
    await user.click(screen.getByRole("button", { name: "Eng probation" }));
    expect((screen.getByLabelText("Status filter") as HTMLSelectElement).value).toBe("probation");
    expect((screen.getByLabelText("Department filter") as HTMLSelectElement).value).toBe("d1");
    await user.click(screen.getByRole("button", { name: "Delete view Eng probation" }));
    expect(screen.queryByRole("button", { name: "Eng probation" })).toBeNull();
    expect(JSON.parse(window.localStorage.getItem("ewmp.employees.views")!)).toEqual([]);
  });

  it("ignores corrupt saved views instead of crashing", async () => {
    window.localStorage.setItem("ewmp.employees.views", "{not json");
    show();
    expect(await screen.findByText("Dana Hire")).toBeTruthy();
  });
});
