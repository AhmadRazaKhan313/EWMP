/**
 * E-08: bulk import: check the file first (nothing is created), then import;
 * row errors are shown, temporary passwords are offered once.
 *
 * Run:  cd frontend && npm test -- ImportEmployeesPage
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/services/api-client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
import apiClient from "@/services/api-client";
import ImportEmployeesPage from "../import/page";

const api = apiClient as unknown as Record<"get" | "post", ReturnType<typeof vi.fn>>;
const dry = {
  dry_run: true, total: 2, created: 1, failed: 1,
  rows: [
    { row: 2, email: "ok@example.com", ok: true, error: null },
    { row: 3, email: "bad@example.com", ok: false, error: "Unknown role 'Nope'." },
  ],
};
const real = {
  dry_run: false, total: 2, created: 1, failed: 1,
  rows: [
    { row: 2, email: "ok@example.com", ok: true, error: null, employee_code: "EMP-0001", temporary_password: "Secret123!" },
    dry.rows[1],
  ],
};

beforeEach(() => vi.clearAllMocks());

function show() {
  const qc = new QueryClient();
  return render(<QueryClientProvider client={qc}><ImportEmployeesPage /></QueryClientProvider>);
}

describe("import page", () => {
  it("checks first, shows row errors, then imports and offers the passwords", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValueOnce({ data: dry }).mockResolvedValueOnce({ data: real });
    show();
    const check = screen.getByRole("button", { name: "Check file" }) as HTMLButtonElement;
    expect(check.disabled).toBe(true); // no file yet
    await user.upload(screen.getByLabelText("CSV file"), new File(["a,b"], "people.csv", { type: "text/csv" }));
    await user.click(check);
    expect(await screen.findByText(/1 ready, 1 with errors, 2 rows/)).toBeTruthy();
    expect(screen.getByText("Unknown role 'Nope'.")).toBeTruthy();
    expect(api.post.mock.calls[0]![2].params).toEqual({ dry_run: true });
    expect(screen.queryByText(/Download login passwords/)).toBeNull(); // nothing created yet

    await user.click(screen.getByRole("button", { name: /Import 1 valid row/ }));
    await waitFor(() => expect(api.post.mock.calls[1]![2].params).toEqual({ dry_run: false }));
    expect(await screen.findByText(/Import finished: 1 created, 1 with errors/)).toBeTruthy();
    expect(screen.getByText("EMP-0001")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Download login passwords/ })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Check file" }) as HTMLButtonElement).disabled).toBe(true); // no double import
  });

  it("will not import when no row is valid", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValueOnce({ data: { ...dry, created: 0, failed: 2, rows: [dry.rows[1]] } });
    show();
    await user.upload(screen.getByLabelText("CSV file"), new File(["x"], "p.csv", { type: "text/csv" }));
    await user.click(screen.getByRole("button", { name: "Check file" }));
    await screen.findByText(/0 ready/);
    expect((screen.getByRole("button", { name: /^Import/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});
