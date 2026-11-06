/**
 * Reports page: P&L (with comparison), balance sheet, aging, general ledger, date presets, export permission.
 *
 * Run:  cd frontend && npm test -- ReportsPage
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }));
vi.mock("@/services/api-client", () => ({ default: { get: getMock } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { useAuthStore } from "@/store/auth.store";
import { presetRange } from "@/services/finance-reports.service";
import ReportsPage from "../page";

const PL = {
  currency: "PKR", date_from: "2026-01-01", date_to: "2026-12-31", net_profit: "7000.00",
  income: { rows: [{ account_id: "a1", code: "4010", name: "Client Payments", amount: "10000.00", previous: "4000.00" }], total: "10000.00", previous_total: "4000.00" },
  expenses: { rows: [{ account_id: "a2", code: "5100", name: "Grocery", amount: "3000.00", previous: "0.00" }], total: "3000.00", previous_total: "0.00" },
  previous_from: "2025-01-01", previous_to: "2025-12-31", previous_net_profit: "4000.00",
};
const bs = (balanced: boolean) => ({
  currency: "PKR", as_of: "2026-10-31", balanced,
  assets: { rows: [{ account_id: "b1", code: "1020", name: "Bank", amount: "14000.00" }], total: "14000.00" },
  liabilities: { rows: [], total: "0.00" },
  equity: { rows: [], profit_to_date: "14000.00", total: "14000.00" }, liabilities_and_equity: "14000.00",
});
const AR = {
  currency: "PKR", as_of: "2026-11-05", rows: [{ party_id: "c1", name: "Acme Ltd", current: "500.00", d1_30: "0.00", d31_60: "0.00", d61_90: "0.00", d90_plus: "600.00", total: "1100.00", items: [] }],
  totals: { current: "500.00", d1_30: "0.00", d31_60: "0.00", d61_90: "0.00", d90_plus: "600.00", total: "1100.00" },
};
const GL = {
  currency: "PKR", account: { id: "b1", code: "1020", name: "Bank", type: "asset" }, opening_balance: "4000.00", closing_balance: "14000.00",
  total_debit: "10000.00", total_credit: "0.00", truncated: false,
  lines: [{ date: "2026-10-10", number: "JE-000002", entry_id: "e1", memo: "Retainer", reference: null, description: null, debit: "10000.00", credit: "0.00", balance: "14000.00" }],
};
const ACCOUNTS = [
  { id: "b1", code: "1020", name: "Bank", type: "asset", parent_id: null, is_system: true, is_active: true },
  { id: "x1", code: "5100", name: "Grocery", type: "expense", parent_id: null, is_system: false, is_active: true },
];

let BALANCED = true;
function wire() {
  getMock.mockImplementation(async (url: string) => {
    if (url === "/finance/summary") return { data: { currency: "PKR" } };
    if (url === "/finance/accounts") return { data: { items: ACCOUNTS } };
    if (url === "/finance/reports/profit-loss") return { data: PL };
    if (url === "/finance/reports/balance-sheet") return { data: bs(BALANCED) };
    if (url === "/finance/reports/receivables-aging") return { data: AR };
    if (url === "/finance/reports/payables-aging") return { data: { ...AR, rows: [] } };
    if (url === "/finance/reports/general-ledger") return { data: GL };
    if (url === "/finance/trial-balance") return { data: { accounts: [{ account_id: "b1", code: "1020", name: "Bank", type: "asset", debit: "14000", credit: "0" }, { account_id: "z", code: "9", name: "Idle", type: "asset", debit: "0", credit: "0" }], total_debit: "14000", total_credit: "14000", balanced: true, as_of: null } };
    throw new Error(`unexpected GET ${url}`);
  });
}
function setPerms(perms: string[]) { useAuthStore.setState({ hasPermission: (p: string) => perms.includes(p) } as never); }
function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ReportsPage /></QueryClientProvider>);
}
const calls = (url: string) => getMock.mock.calls.filter((c) => c[0] === url) as [string, { params: Record<string, unknown> }][];

beforeEach(() => { vi.clearAllMocks(); BALANCED = true; wire(); setPerms(["finance.view", "finance.export"]); });

describe("presetRange", () => {
  const today = new Date(2026, 10, 5); // 5 Nov 2026
  it("covers months, quarters, years and the July–June financial year", () => {
    expect(presetRange("this_month", today)).toEqual({ from: "2026-11-01", to: "2026-11-30" });
    expect(presetRange("last_month", today)).toEqual({ from: "2026-10-01", to: "2026-10-31" });
    expect(presetRange("this_quarter", today)).toEqual({ from: "2026-10-01", to: "2026-12-31" });
    expect(presetRange("this_year", today)).toEqual({ from: "2026-01-01", to: "2026-12-31" });
    expect(presetRange("last_year", today)).toEqual({ from: "2025-01-01", to: "2025-12-31" });
    expect(presetRange("this_fy", today)).toEqual({ from: "2026-07-01", to: "2027-06-30" });
    expect(presetRange("this_fy", new Date(2026, 2, 1))).toEqual({ from: "2025-07-01", to: "2026-06-30" });
    expect(presetRange("last_month", new Date(2026, 0, 15))).toEqual({ from: "2025-12-01", to: "2025-12-31" });
    expect(presetRange("last_month", new Date(2024, 2, 10))).toEqual({ from: "2024-02-01", to: "2024-02-29" });
  });
});

describe("Reports page", () => {
  it("shows profit & loss with totals and the comparison column", async () => {
    renderPage();
    expect(await screen.findByText("Client Payments")).toBeInTheDocument();
    expect(screen.getByTestId("net-profit")).toHaveTextContent("7,000");
    expect(screen.queryByText("2025-01-01 – 2025-12-31")).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/compare with the period before/i));
    expect(await screen.findByText("2025-01-01 – 2025-12-31")).toBeInTheDocument();
    await waitFor(() => expect(calls("/finance/reports/profit-loss").at(-1)![1].params.compare).toBe(true));
  });

  it("a preset changes the requested dates; editing a date switches to Custom", async () => {
    renderPage();
    await screen.findByText("Client Payments");
    await userEvent.selectOptions(screen.getByLabelText("Period"), "last_year");
    await waitFor(() => expect(calls("/finance/reports/profit-loss").at(-1)![1].params).toMatchObject({ date_from: expect.stringMatching(/-01-01$/), date_to: expect.stringMatching(/-12-31$/) }));
    const lastYear = String(new Date().getFullYear() - 1);
    expect((calls("/finance/reports/profit-loss").at(-1)![1].params.date_from as string).startsWith(lastYear)).toBe(true);
    await userEvent.clear(screen.getByLabelText("To"));
    await userEvent.type(screen.getByLabelText("To"), "2025-06-30");
    expect(screen.getByLabelText("Period")).toHaveValue("custom");
  });

  it("warns and does not request when From is after To", async () => {
    renderPage();
    await screen.findByText("Client Payments");
    await userEvent.clear(screen.getByLabelText("From"));
    await userEvent.type(screen.getByLabelText("From"), "2027-01-01");
    expect(await screen.findByRole("alert")).toHaveTextContent(/after the “to” date/i);
    expect(calls("/finance/reports/profit-loss").some((c) => c[1].params.date_from === "2027-01-01")).toBe(false);
    expect(screen.getByRole("button", { name: /excel/i })).toBeDisabled();
  });

  it("balance sheet shows the totals and flags an unbalanced book", async () => {
    const { unmount } = renderPage();
    await userEvent.click(await screen.findByText("Balance Sheet"));
    expect(await screen.findByTestId("bs-le")).toHaveTextContent("14,000");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    unmount();
    BALANCED = false;
    renderPage();
    await userEvent.click(await screen.findByText("Balance Sheet"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/does not balance/i);
  });

  it("trial balance hides idle accounts", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Trial Balance"));
    expect(await screen.findByText("Bank")).toBeInTheDocument();
    expect(screen.queryByText("Idle")).not.toBeInTheDocument();
  });

  it("receivables aging lists buckets and totals; payables shows an empty state", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Receivables"));
    expect(await screen.findByText("Acme Ltd")).toBeInTheDocument();
    expect(screen.getByText("90+")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Payables"));
    expect(await screen.findByText("Nothing outstanding")).toBeInTheDocument();
  });

  it("general ledger waits for an account, then shows opening, lines and closing balance", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("General Ledger"));
    expect(await screen.findByText("Pick an account")).toBeInTheDocument();
    expect(calls("/finance/reports/general-ledger").length).toBe(0);
    expect(screen.getByRole("button", { name: /excel/i })).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("Account"), "b1");
    expect(await screen.findByText("JE-000002")).toBeInTheDocument();
    expect(screen.getByTestId("gl-closing")).toHaveTextContent("14,000");
    expect(screen.getByRole("button", { name: /excel/i })).toBeEnabled();
  });

  it("export sends the report name, format and the filters on screen", async () => {
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    getMock.mockImplementation(async (url: string) => {
      if (url === "/finance/reports/export") return { data: new Blob(["x"]) };
      if (url === "/finance/summary") return { data: { currency: "PKR" } };
      if (url === "/finance/accounts") return { data: { items: ACCOUNTS } };
      return { data: PL };
    });
    renderPage();
    await screen.findByText("Client Payments");
    await userEvent.click(screen.getByLabelText(/compare with the period before/i));
    await userEvent.click(screen.getByRole("button", { name: /csv/i }));
    await waitFor(() => expect(calls("/finance/reports/export").length).toBe(1));
    const cfg = calls("/finance/reports/export")[0] as unknown as [string, { params: Record<string, unknown>; responseType: string }];
    expect(cfg[1].params).toMatchObject({ report: "profit-loss", format: "csv", compare: true });
    expect(cfg[1].responseType).toBe("blob");
  });

  it("hides the export buttons without finance.export", async () => {
    setPerms(["finance.view"]);
    renderPage();
    await screen.findByText("Client Payments");
    expect(screen.queryByRole("button", { name: /excel/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /csv/i })).not.toBeInTheDocument();
  });
});
