/**
 * Close books page: lock status, preview with warnings, close / reopen with confirmation, opening balances, permission gating.
 *
 * Run:  cd frontend && npm test -- ClosePage
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { getMock, postMock, putMock, delMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn(), putMock: vi.fn(), delMock: vi.fn() }));
vi.mock("@/services/api-client", () => ({ default: { get: getMock, post: postMock, put: putMock, delete: delMock } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { useAuthStore } from "@/store/auth.store";
import ClosePage from "../page";

const acc = (id: string, code: string, name: string, type: string, parent_id: string | null = null) => ({ id, code, name, type, parent_id, is_system: false, is_active: true });
const ACCOUNTS = [
  acc("assets", "1000", "Assets", "asset"), acc("cash", "1010", "Cash", "asset", "assets"), acc("bank", "1020", "Bank", "asset", "assets"),
  acc("liab", "2000", "Liabilities", "liability"), acc("loans", "2100", "Loans", "liability", "liab"),
  acc("eq", "3000", "Equity", "equity"), acc("cap", "3010", "Founders Capital", "equity", "eq"), acc("obe", "3020", "Opening Balance Equity", "equity", "eq"),
  acc("inc", "4010", "Client Payments", "income"),
];
const PREVIEW = {
  period_type: "month", period_start: "2026-10-01", period_end: "2026-10-31", label: "October 2026", income: "5000.00", expenses: "1200.00", net_profit: "3800.00",
  draft_invoices: 1, draft_bills: 0, pending_approval: 0, unmatched_bank_lines: 2, blockers: [],
  warnings: ["1 draft invoice(s) dated up to 2026-10-31 are not in the books yet.", "2 bank statement line(s) are not matched yet."], can_close: true,
};
const CLOSED = { id: "c1", period_type: "month", period_start: "2026-09-01", period_end: "2026-09-30", net_profit: "900.00", note: "Sept done", closed_at: "2026-10-02T00:00:00Z" };
let STATUS: unknown, P: unknown, OPENING: unknown;

function wire() {
  getMock.mockImplementation(async (url: string, cfg?: { params?: Record<string, string> }) => {
    if (url === "/finance/summary") return { data: { currency: "PKR" } };
    if (url === "/finance/accounts") return { data: { items: ACCOUNTS } };
    if (url === "/finance/close") return { data: STATUS };
    if (url === "/finance/close/preview") return { data: { ...(P as object), period_type: cfg?.params?.period_type } };
    if (url === "/finance/opening-balances") return { data: OPENING };
    throw new Error(`unexpected GET ${url}`);
  });
  postMock.mockResolvedValue({ data: {} });
  putMock.mockResolvedValue({ data: {} });
  delMock.mockResolvedValue({ data: {} });
}
function setPerms(perms: string[]) { useAuthStore.setState({ hasPermission: (p: string) => perms.includes(p) } as never); }
function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ClosePage /></QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  STATUS = { locked_through: "2026-09-30", closes: [CLOSED], suggested: { period_type: "month", period_start: "2026-10-01", period_end: "2026-10-31", label: "October 2026" } };
  P = PREVIEW;
  OPENING = { as_of: null, entry_number: null, items: [], balancing: "0.00" };
  wire();
  setPerms(["finance.view", "finance.manage"]);
});

describe("Month / year close", () => {
  it("shows the lock state, the suggested period's preview with warnings, and the history", async () => {
    renderPage();
    expect(await screen.findByTestId("lock-state")).toHaveTextContent("Closed through 2026-09-30");
    expect(await screen.findByText(/October 2026/)).toBeInTheDocument();
    expect(screen.getByText(/draft invoice/)).toBeInTheDocument();
    expect(screen.getByText(/not matched yet/)).toBeInTheDocument();
    expect(screen.getByText(/Sept done/)).toBeInTheDocument();
    const prev = getMock.mock.calls.filter((c) => c[0] === "/finance/close/preview").at(-1)!;
    expect(prev[1].params).toEqual({ period_type: "month", date: "2026-10-31" });
  });

  it("closing asks for confirmation first, then posts the period and note", async () => {
    renderPage();
    await screen.findByText(/October 2026/);
    await userEvent.type(screen.getByLabelText("Note (optional)"), "Oct done");
    await userEvent.click(screen.getByRole("button", { name: "Close period" }));
    expect(postMock).not.toHaveBeenCalled();
    const dlg = await screen.findByRole("dialog", { name: "Close this period?" });
    expect(within(dlg).getByText("2026-10-31")).toBeInTheDocument();
    await userEvent.click(within(dlg).getByRole("button", { name: "Close period" }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/close", { period_type: "month", date: "2026-10-31", note: "Oct done" }));
  });

  it("a period that cannot be closed shows why and the button stays off", async () => {
    P = { ...PREVIEW, can_close: false, blockers: ["October 2026 has not ended yet."], warnings: [] };
    wire();
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("has not ended yet");
    expect(screen.getByRole("button", { name: "Close period" })).toBeDisabled();
  });

  it("switching to financial year asks the server for a year", async () => {
    renderPage();
    await screen.findByText(/October 2026/);
    await userEvent.selectOptions(screen.getByLabelText("Close a"), "year");
    await waitFor(() => expect(getMock.mock.calls.filter((c) => c[0] === "/finance/close/preview").at(-1)![1].params.period_type).toBe("year"));
  });

  it("only the latest closed period can be reopened, after confirming", async () => {
    STATUS = { ...(STATUS as object), closes: [CLOSED, { ...CLOSED, id: "c0", period_start: "2026-08-01", period_end: "2026-08-31", note: null }] };
    wire();
    renderPage();
    await screen.findByText(/Sept done/);
    const buttons = screen.getAllByRole("button", { name: "Reopen" });
    expect(buttons).toHaveLength(1);
    await userEvent.click(buttons[0]!);
    const dlg = await screen.findByRole("dialog", { name: "Reopen this period?" });
    await userEvent.click(within(dlg).getByRole("button", { name: "Reopen" }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/close/reopen", {}));
  });

  it("without finance.manage nothing can be changed", async () => {
    setPerms(["finance.view"]);
    renderPage();
    await screen.findByText(/October 2026/);
    expect(screen.queryByRole("button", { name: "Close period" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reopen" })).not.toBeInTheDocument();
  });

  it("an open book says nothing is closed", async () => {
    STATUS = { locked_through: null, closes: [], suggested: null };
    wire();
    renderPage();
    expect(await screen.findByTestId("lock-state")).toHaveTextContent(/nothing is closed yet/i);
    expect(screen.getByText("None yet.")).toBeInTheDocument();
  });
});

describe("Opening balances", () => {
  async function openTab() {
    renderPage();
    await userEvent.click(await screen.findByRole("tab", { name: "Opening balances" }).catch(() => screen.findByText("Opening balances")));
  }

  it("lists only leaf balance-sheet accounts and calculates the equity plug live", async () => {
    await openTab();
    expect(await screen.findByLabelText("Cash")).toBeInTheDocument();
    for (const n of ["Bank", "Loans", "Founders Capital"]) expect(screen.getByLabelText(n)).toBeInTheDocument();
    for (const n of ["Assets", "Liabilities", "Equity", "Client Payments", "Opening Balance Equity"]) expect(screen.queryByRole("spinbutton", { name: n })).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Cash"), "10000");
    await userEvent.type(screen.getByLabelText("Bank"), "40000");
    await userEvent.type(screen.getByLabelText("Loans"), "15000");
    expect(screen.getByTestId("plug")).toHaveTextContent("Rs 35,000");
  });

  it("saves only the filled accounts with the date", async () => {
    await openTab();
    await userEvent.type(await screen.findByLabelText("Cash"), "2500.50");
    await userEvent.type(screen.getByLabelText("Loans"), "0");
    const save = screen.getByRole("button", { name: "Save opening balances" });
    expect(save).toBeDisabled(); // no date yet
    await userEvent.type(screen.getByLabelText("Balances as of"), "2026-07-01");
    await userEvent.click(save);
    await waitFor(() => expect(putMock).toHaveBeenCalledWith("/finance/opening-balances", { as_of: "2026-07-01", items: [{ account_id: "cash", amount: "2500.5" }] }));
  });

  it("shows what is saved, and remove asks first", async () => {
    OPENING = { as_of: "2026-07-01", entry_number: "JE-000003", balancing: "35000.00",
      items: [{ account_id: "cash", code: "1010", name: "Cash", type: "asset", amount: "10000.00" }, { account_id: "loans", code: "2100", name: "Loans", type: "liability", amount: "15000.00" }] };
    wire();
    await openTab();
    expect((await screen.findByLabelText("Cash") as HTMLInputElement).value).toBe("10000.00");
    expect(screen.getByText(/Saved as JE-000003/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(delMock).not.toHaveBeenCalled();
    const dlg = await screen.findByRole("dialog", { name: "Remove opening balances?" });
    await userEvent.click(within(dlg).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(delMock).toHaveBeenCalledWith("/finance/opening-balances"));
  });

  it("read-only without finance.manage", async () => {
    setPerms(["finance.view"]);
    await openTab();
    expect(await screen.findByLabelText("Cash")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save opening balances" })).not.toBeInTheDocument();
  });
});
