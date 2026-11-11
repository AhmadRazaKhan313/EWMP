/**
 * Budget page: weekly / monthly / yearly tabs, previous/next, planned inputs, starting balance, read-only without finance.manage.
 *
 * Run:  cd frontend && npm test -- BudgetPage
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { getMock, putMock } = vi.hoisted(() => ({ getMock: vi.fn(), putMock: vi.fn() }));
vi.mock("@/services/api-client", () => ({ default: { get: getMock, put: putMock } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { useAuthStore } from "@/store/auth.store";
import { shiftDate } from "@/services/finance-budget.service";
import BudgetPage from "../page";

const EXP = ["Grocery", "Gifts", "Health/medical", "Upwork", "Founders Withdrawal", "All Expenses", "Assets", "Utilities", "Travel", "Debt", "Subscriptions", "Gadgets", "Loan Paid", "Salary"];
const INC = ["Founders Investment", "Upwork", "Bonus", "Client Payment", "Other", "Loan"];
const sect = (cats: string[], kind: "income" | "expense", over: Record<string, [string, string]> = {}) => {
  const rows = cats.map((category) => {
    const [planned, actual] = over[category] ?? ["0.00", "0.00"];
    const diff = kind === "expense" ? parseFloat(planned) - parseFloat(actual) : parseFloat(actual) - parseFloat(planned);
    return { category, planned, actual, diff: diff.toFixed(2) };
  });
  const sum = (i: "planned" | "actual") => rows.reduce((s, r) => s + parseFloat(r[i]), 0);
  const d = kind === "expense" ? sum("planned") - sum("actual") : sum("actual") - sum("planned");
  return { planned: sum("planned").toFixed(2), actual: sum("actual").toFixed(2), diff: d.toFixed(2), rows };
};
const budget = (period: string, over: Partial<Record<string, unknown>> = {}) => ({
  period, start: "2026-11-01", end: "2026-11-30", label: period === "year" ? "2026-27" : period === "week" ? "02 Nov - 08 Nov 2026" : "November 2026",
  starting_balance: "7000.00", starting_balance_manual: false, end_balance: "9000.00", saved: "2000.00",
  expenses: sect(EXP, "expense", { Grocery: ["2000.00", "1200.00"] }), income: sect(INC, "income", { "Client Payment": ["0.00", "5000.00"] }), ...over,
});

function wire(over: Partial<Record<string, unknown>> = {}) {
  getMock.mockImplementation(async (url: string, cfg?: { params?: { period: string } }) => {
    if (url === "/finance/summary") return { data: { currency: "PKR" } };
    if (url === "/finance/budget") return { data: budget(cfg?.params?.period ?? "month", over) };
    throw new Error(`unexpected GET ${url}`);
  });
  putMock.mockResolvedValue({ data: {} });
}
function setPerms(perms: string[]) { useAuthStore.setState({ hasPermission: (p: string) => perms.includes(p) } as never); }
function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><BudgetPage /></QueryClientProvider>);
}
const budgetCalls = () => getMock.mock.calls.filter((c) => c[0] === "/finance/budget") as [string, { params: { period: string; date: string } }][];

beforeEach(() => { vi.clearAllMocks(); wire(); setPerms(["finance.view", "finance.manage"]); });

describe("shiftDate", () => {
  it("moves by a week, a month or a year without overflowing", () => {
    expect(shiftDate("week", "2026-12-30", 1)).toBe("2027-01-06");
    expect(shiftDate("week", "2026-01-03", -1)).toBe("2025-12-27");
    expect(shiftDate("month", "2026-01-31", 1)).toBe("2026-02-28");
    expect(shiftDate("month", "2028-01-31", 1)).toBe("2028-02-29");
    expect(shiftDate("month", "2026-01-15", -1)).toBe("2025-12-15");
    expect(shiftDate("month", "2026-12-15", 1)).toBe("2027-01-15");
    expect(shiftDate("year", "2028-02-29", 1)).toBe("2029-02-28");
  });
});

describe("Budget page", () => {
  it("shows every category of the original sheet, with the headline figures", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Budget November 2026" })).toBeInTheDocument();
    const exp = within(screen.getByRole("table", { name: "Expenses table" }));
    for (const c of EXP) expect(exp.getByText(c)).toBeInTheDocument();
    const inc = within(screen.getByRole("table", { name: "Income table" }));
    for (const c of INC) expect(inc.getByText(c)).toBeInTheDocument();
    expect(screen.getByTestId("saved")).toHaveTextContent("2,000");
    expect(screen.getByTestId("start-balance")).toHaveTextContent("7,000");
    expect(screen.getByTestId("end-balance")).toHaveTextContent("9,000");
    expect(screen.getByText("Saved this month")).toBeInTheDocument();
    expect(screen.getByText("Increase in total savings")).toBeInTheDocument();
    expect(screen.getByLabelText("Starting balance")).toHaveValue(7000);
  });

  it("weekly, monthly and yearly each ask the API for their period; arrows move the date", async () => {
    renderPage();
    await screen.findByRole("heading", { name: /Budget November 2026/ });
    expect(budgetCalls().at(-1)![1].params.period).toBe("month");
    await userEvent.click(screen.getByText("Weekly"));
    expect(await screen.findByRole("heading", { name: "Budget 02 Nov - 08 Nov 2026" })).toBeInTheDocument();
    expect(screen.getByText("Saved this week")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Yearly"));
    expect(await screen.findByRole("heading", { name: "Budget 2026-27" })).toBeInTheDocument();
    expect(screen.getByText("Saved this year")).toBeInTheDocument();
    expect(budgetCalls().at(-1)![1].params.period).toBe("year");
    const before = budgetCalls().at(-1)![1].params.date;
    await userEvent.click(screen.getByRole("button", { name: "Next year" }));
    await waitFor(() => expect(budgetCalls().at(-1)![1].params.date).toBe(shiftDate("year", before, 1)));
    await userEvent.click(screen.getByRole("button", { name: "Previous year" }));
    await userEvent.click(screen.getByRole("button", { name: "Previous year" }));
    await waitFor(() => expect(budgetCalls().at(-1)![1].params.date).toBe(shiftDate("year", before, -1)));
  });

  it("saves a planned amount when the box loses focus, and only if it changed", async () => {
    renderPage();
    const box = await screen.findByLabelText("Planned Gifts");
    await userEvent.type(box, "750");
    await userEvent.tab();
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    expect(putMock).toHaveBeenCalledWith("/finance/budget/plan", { period: "month", date: expect.any(String), kind: "expense", category: "Gifts", planned: "750" });
    putMock.mockClear();
    await userEvent.click(screen.getByLabelText("Planned Grocery"));
    await userEvent.tab();
    expect(putMock).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("Planned Bonus"), "100");
    await userEvent.tab();
    await waitFor(() => expect(putMock).toHaveBeenCalledWith("/finance/budget/plan", expect.objectContaining({ kind: "income", category: "Bonus", planned: "100" })));
  });

  it("sets the starting balance by hand", async () => {
    renderPage();
    const box = await screen.findByLabelText("Starting balance");
    await userEvent.clear(box);
    await userEvent.type(box, "500");
    await userEvent.tab();
    await waitFor(() => expect(putMock).toHaveBeenCalledWith("/finance/budget/opening", { period: "month", date: expect.any(String), starting_balance: "500" }));
  });

  it("clearing a hand-set starting balance goes back to the ledger figure", async () => {
    wire({ starting_balance_manual: true, starting_balance: "500.00", end_balance: "2500.00" });
    renderPage();
    const box = await screen.findByLabelText("Starting balance");
    expect(box).toHaveValue(500);
    await userEvent.clear(box);
    await userEvent.tab();
    await waitFor(() => expect(putMock).toHaveBeenCalledWith("/finance/budget/opening", { period: "month", date: expect.any(String), starting_balance: null }));
  });

  it("leaves an untouched ledger-based starting balance alone", async () => {
    renderPage();
    const box = await screen.findByLabelText("Starting balance");
    await userEvent.click(box);
    await userEvent.tab();
    expect(putMock).not.toHaveBeenCalled();
  });

  it("is read-only without finance.manage", async () => {
    setPerms(["finance.view"]);
    renderPage();
    await screen.findByRole("heading", { name: /Budget November 2026/ });
    expect(screen.queryByLabelText("Planned Gifts")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Starting balance")).not.toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: "Expenses table" })).getByText("Grocery")).toBeInTheDocument();
    expect(screen.getAllByText(/2,000/).length).toBeGreaterThan(0);
  });

  it("shows an overspent category as a negative difference", async () => {
    wire({ expenses: sect(EXP, "expense", { Grocery: ["1000.00", "1200.00"] }) });
    renderPage();
    const row = (await screen.findByText("Grocery")).closest("tr")!;
    expect(row).toHaveTextContent("200");
    expect(within(row).getAllByRole("cell").at(-1)!).toHaveStyle({ color: "#c62828" });
  });
});
