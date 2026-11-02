/** D-01 Absent card. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AbsentTodayCard } from "../AbsentTodayCard";

vi.mock("@/services/api-client", () => ({ default: { get: vi.fn() } }));
import apiClient from "@/services/api-client";
const get = apiClient.get as ReturnType<typeof vi.fn>;

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

describe("AbsentTodayCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the count and opens the list with red / amber badges", async () => {
    get.mockResolvedValue({ data: { date: "2026-10-14", absent: 1, not_checked_in: 1, total: 2, employees: [
      { employee_id: "1", employee_code: "E1", employee_name: "Ali Raza", department_name: "Ops", shift_name: "Day", status: "absent" },
      { employee_id: "2", employee_code: "E2", employee_name: "Sara Khan", department_name: null, shift_name: null, status: "not_checked_in" },
    ] } });
    wrap(<AbsentTodayCard />);
    expect(await screen.findByText("1 absent · 1 yet to check in")).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/dashboard/absent");
    fireEvent.click(screen.getByRole("button", { name: /absent today/i }));
    expect(await screen.findByText("Ali Raza")).toBeTruthy();
    expect(screen.getByText("Absent")).toBeTruthy();
    expect(screen.getByText("Not checked in")).toBeTruthy();
  });

  it("says everyone is in when the list is empty", async () => {
    get.mockResolvedValue({ data: { date: "2026-10-14", absent: 0, not_checked_in: 0, total: 0, employees: [] } });
    wrap(<AbsentTodayCard />);
    fireEvent.click(await screen.findByRole("button", { name: /absent today/i }));
    expect(await screen.findByText(/everyone expected today is in/i)).toBeTruthy();
  });
});
