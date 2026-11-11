/**
 * Taxes page: sales vs purchases tax by rate, net payable, date range, export, permission gating.
 *
 * Run:  cd frontend && npm test -- TaxesPage
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }));
vi.mock("@/services/api-client", () => ({ default: { get: getMock, post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { useAuthStore } from "@/store/auth.store";
import TaxesPage from "../page";

const REPORT = {
  date_from: "2026-10-01", date_to: "2026-10-31", currency: "PKR",
  sales: { rows: [
    { tax_rate_id: "g10", name: "GST 10", percent: "10", taxable: "3000.00", tax: "300.00", documents: 2 },
    { tax_rate_id: "g5", name: "GST 5", percent: "5", taxable: "400.00", tax: "20.00", documents: 1 },
  ], taxable: "3400.00", tax: "320.00" },
  purchases: { rows: [{ tax_rate_id: "g10", name: "GST 10", percent: "10", taxable: "1500.00", tax: "150.00", documents: 1 }], taxable: "1500.00", tax: "150.00" },
  net_tax_payable: "170.00",
};
const EMPTY = { ...REPORT, sales: { rows: [], taxable: "0.00", tax: "0.00" }, purchases: { rows: [], taxable: "0.00", tax: "0.00" }, net_tax_payable: "0.00" };

function wire(data: unknown = REPORT) {
  getMock.mockImplementation(async (url: string) => {
    if (url === "/finance/reports/taxes") return { data };
    if (url === "/finance/reports/export") return { data: new Blob(["x"]) };
    throw new Error(`unexpected GET ${url}`);
  });
}
function setPerms(perms: string[]) { useAuthStore.setState({ hasPermission: (p: string) => perms.includes(p) } as never); }
function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><TaxesPage /></QueryClientProvider>);
}
const calls = () => getMock.mock.calls.filter((c) => c[0] === "/finance/reports/taxes") as [string, { params: Record<string, string> }][];

beforeEach(() => {
  vi.clearAllMocks();
  wire();
  setPerms(["finance.view", "finance.export"]);
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
});

describe("Taxes page", () => {
  it("shows the net payable and both sides by rate", async () => {
    renderPage();
    expect(await screen.findByTestId("net-tax")).toHaveTextContent("Rs 170");
    expect(screen.getAllByText("GST 10")).toHaveLength(2);
    expect(screen.getByText("GST 5")).toBeInTheDocument();
    expect(screen.getByTestId("Sales (tax you charged)-tax")).toHaveTextContent("Rs 320");
    expect(screen.getByTestId("Purchases (tax you paid)-tax")).toHaveTextContent("Rs 150");
  });

  it("asks the server for the chosen range", async () => {
    renderPage();
    await screen.findByTestId("net-tax");
    const first = calls()[0]![1].params;
    expect(first.date_from! <= first.date_to!).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Last year" }));
    await waitFor(() => expect(calls().at(-1)![1].params.date_from).toMatch(/-01-01$/));
    expect(screen.getByRole("button", { name: "Last year" })).toHaveAttribute("aria-pressed", "true");
  });

  it("a backwards range shows a message and does not call the API for it", async () => {
    renderPage();
    await screen.findByTestId("net-tax");
    const n = calls().length;
    const from = screen.getByLabelText("From") as HTMLInputElement;
    await userEvent.clear(from);
    await userEvent.type(from, "2099-01-01");
    expect(await screen.findByRole("alert")).toHaveTextContent(/after the end date/i);
    expect(calls().length).toBe(n);
    expect(screen.getByRole("button", { name: "Excel" })).toBeDisabled();
  });

  it("an empty period says so, and a negative net says it can be claimed back", async () => {
    wire(EMPTY);
    renderPage();
    expect(await screen.findByText("No taxed documents in this period")).toBeInTheDocument();
    wire({ ...REPORT, net_tax_payable: "-40.00" });
    renderPage();
    expect(await screen.findByText(/claim it back/i)).toBeInTheDocument();
  });

  it("exports Excel with the range, only for people who can export", async () => {
    renderPage();
    await screen.findByTestId("net-tax");
    await userEvent.click(screen.getByRole("button", { name: "Excel" }));
    await waitFor(() => expect(getMock).toHaveBeenCalledWith("/finance/reports/export", expect.objectContaining({
      params: expect.objectContaining({ report: "taxes", format: "xlsx" }) })));
  });

  it("hides export without the permission", async () => {
    setPerms(["finance.view"]);
    renderPage();
    await screen.findByTestId("net-tax");
    expect(screen.queryByRole("button", { name: "Excel" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "CSV" })).not.toBeInTheDocument();
  });
});
