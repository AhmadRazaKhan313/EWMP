/**
 * Finance page: totals, tabs, category chips, permission-gated actions, first-time setup.
 *
 * Run:  cd frontend && npm test -- FinancePage
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { getMock, postMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn() }));
vi.mock("@/services/api-client", () => ({ default: { get: getMock, post: postMock } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { useAuthStore } from "@/store/auth.store";
import FinancePage from "../page";

const acc = (id: string, code: string, name: string, type: string) => ({ id, code, name, type, parent_id: null, is_system: true, is_active: true });
const ACCOUNTS = [
  acc("cash", "1010", "Cash", "asset"), acc("bank", "1020", "Bank", "asset"), acc("fa", "1500", "Fixed Assets", "asset"),
  acc("gro", "5050", "Grocery", "expense"), acc("util", "5020", "Utilities", "expense"),
  acc("cl", "4010", "Client Payments", "income"), acc("fc", "3010", "Founders Capital", "equity"),
];
const SUMMARY = {
  currency: "PKR", income_total: "800000", income_operating: "300000", income_financing: "500000",
  expense_total: "5000", balance: "795000", profit: "295000",
  income_by_category: [{ category_id: "fc", category: "Founders Capital", type: "equity", total: "500000" }, { category_id: "cl", category: "Client Payments", type: "income", total: "300000" }],
  expense_by_category: [{ category_id: "gro", category: "Grocery", type: "expense", total: "650" }, { category_id: "util", category: "Utilities", type: "expense", total: "4350" }],
  money_accounts: [{ account_id: "cash", code: "1010", name: "Cash", balance: "100" }],
};
const txn = (id: string, desc: string, cat: string, amount: string, type = "expense") => ({
  id, number: `JE-${id}`, type, date: "2025-12-01", amount, currency: "PKR", description: desc,
  account_id: "cash", account: "Cash", category_id: cat, category: cat, category_type: "expense",
});

function wire(opts: { accounts?: unknown[]; byCategory?: Record<string, unknown[]> } = {}) {
  getMock.mockImplementation(async (url: string, cfg?: { params?: Record<string, string> }) => {
    if (url === "/finance/accounts") return { data: { items: opts.accounts ?? ACCOUNTS } };
    if (url === "/finance/summary") return { data: SUMMARY };
    if (url === "/finance/transactions") {
      const cat = cfg?.params?.category_id;
      if (cat && opts.byCategory?.[cat]) return { data: { items: opts.byCategory[cat], total: opts.byCategory[cat]!.length } };
      const items = cfg?.params?.type === "income"
        ? [txn("3", "Founder money", "Founders Capital", "500000", "income")]
        : [txn("1", "Milk purchased", "Grocery", "650"), txn("2", "Water bill", "Utilities", "4350")];
      return { data: { items, total: items.length } };
    }
    if (url === "/finance/providers") {
      return { data: { items: cfg?.params?.kind === "wallet" ? ["JazzCash", "Easypaisa"] : ["HBL (Habib Bank)", "Meezan Bank"] } };
    }
    throw new Error(`unexpected GET ${url}`);
  });
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><FinancePage /></QueryClientProvider>);
}
function signIn(perms: string[]) {
  useAuthStore.setState({ isAuthenticated: true, user: { id: "u", is_platform_admin: false, permissions: perms } as never, permissions: perms } as never);
}

describe("FinancePage", () => {
  beforeEach(() => { getMock.mockReset(); postMock.mockReset(); signIn(["finance.view", "finance.post", "finance.void", "finance.export", "finance.manage"]); });

  it("shows income, expenses and balance and lists expense rows with a total", async () => {
    wire();
    renderPage();
    expect(await screen.findByText("Milk purchased")).toBeInTheDocument();
    expect(screen.getByTestId("stat-income")).toHaveTextContent("800,000");
    expect(screen.getByTestId("stat-balance")).toHaveTextContent("795,000");
    expect(screen.getByTestId("shown-total")).toHaveTextContent("5,000");
  });

  it("narrows the table with a category chip", async () => {
    wire({ byCategory: { gro: [txn("1", "Milk purchased", "Grocery", "650")] } });
    renderPage();
    await screen.findByText("Water bill");
    await userEvent.click(screen.getByRole("button", { name: "Grocery" }));
    await waitFor(() => expect(screen.queryByText("Water bill")).not.toBeInTheDocument());
    expect(screen.getByTestId("shown-total")).toHaveTextContent("650");
  });

  it("income tab lists income and the Balance tab shows the breakdown", async () => {
    wire();
    renderPage();
    await screen.findByText("Milk purchased");
    await userEvent.click(screen.getByRole("tab", { name: "Income" }));
    expect(await screen.findByText("Founder money")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Balance" }));
    expect(await screen.findByText("Balance (income minus expenses)")).toBeInTheDocument();
    expect(screen.getByText("Accounts")).toBeInTheDocument();
  });

  it("hides write actions without the permissions", async () => {
    signIn(["finance.view"]);
    wire();
    renderPage();
    await screen.findByText("Milk purchased");
    expect(screen.queryByRole("button", { name: /add entry/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /import/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download excel/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /void/i })).not.toBeInTheDocument();
  });

  it("offers one-click setup when the org has no accounts yet", async () => {
    wire({ accounts: [] });
    postMock.mockResolvedValue({ data: { created: 25 } });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Set up finance" }));
    expect(postMock).toHaveBeenCalledWith("/finance/setup");
  });

  it("Add entry posts an expense with the picked category and account", async () => {
    wire();
    postMock.mockResolvedValue({ data: txn("9", "Tea", "Grocery", "120") });
    renderPage();
    await screen.findByText("Milk purchased");
    await userEvent.click(screen.getByRole("button", { name: /add entry/i }));
    const dialog = screen.getByRole("dialog", { name: "Add entry" });
    await userEvent.type(within(dialog).getByLabelText("Amount"), "120");
    await userEvent.selectOptions(within(dialog).getByLabelText("Category"), "gro");
    await userEvent.type(within(dialog).getByLabelText("Description"), "Tea");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save entry" }));
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    expect(postMock.mock.calls[0]![0]).toBe("/finance/transactions");
    expect(postMock.mock.calls[0]![1]).toMatchObject({ type: "expense", amount: "120", account_id: "cash", category_id: "gro", description: "Tea" });
  });

  it("the expense form never offers income or equity categories, nor cash accounts as a category", async () => {
    wire();
    renderPage();
    await screen.findByText("Milk purchased");
    await userEvent.click(screen.getByRole("button", { name: /add entry/i }));
    const cat = within(screen.getByRole("dialog")).getByLabelText("Category");
    const labels = within(cat).getAllByRole("option").map((o) => o.textContent);
    expect(labels).toEqual(expect.arrayContaining(["Grocery", "Utilities", "Fixed Assets"]));
    expect(labels).not.toContain("Client Payments");
    expect(labels).not.toContain("Founders Capital");
    expect(labels).not.toContain("Cash");
  });

  describe("bank and wallet details", () => {
    const KINDED = ACCOUNTS.map((a) => (a.id === "cash" ? { ...a, money_kind: "cash" } : a.id === "bank" ? { ...a, money_kind: "bank" } : a))
      .concat([{ ...acc("wal", "1030", "Mobile Wallet", "asset"), money_kind: "wallet" } as never]);

    async function openForm(accounts = KINDED) {
      wire({ accounts });
      postMock.mockResolvedValue({ data: {} });
      renderPage();
      await screen.findByText("Milk purchased");
      await userEvent.click(screen.getByRole("button", { name: /add entry/i }));
      return within(screen.getByRole("dialog", { name: "Add entry" }));
    }

    it("cash shows no bank fields; picking Bank shows name, account no and TID", async () => {
      const d = await openForm();
      expect(d.queryByLabelText("TID (transaction ID)")).not.toBeInTheDocument();
      await userEvent.selectOptions(d.getByLabelText("Paid from"), "bank");
      expect(await d.findByLabelText("Bank name")).toBeInTheDocument();
      expect(d.getByLabelText("Account no")).toBeInTheDocument();
      expect(d.getByLabelText("TID (transaction ID)")).toBeInTheDocument();
      const names = within(d.getByLabelText("Bank name")).getAllByRole("option").map((o) => o.textContent);
      expect(names).toEqual(expect.arrayContaining(["HBL (Habib Bank)", "Meezan Bank", "+ Add new bank…"]));
    });

    it("mobile wallet uses wallet names and a wallet number", async () => {
      const d = await openForm();
      await userEvent.selectOptions(d.getByLabelText("Paid from"), "wal");
      const sel = await d.findByLabelText("Wallet name");
      await waitFor(() => expect(within(sel).getAllByRole("option").map((o) => o.textContent)).toContain("JazzCash"));
      expect(within(sel).getAllByRole("option").map((o) => o.textContent)).toContain("+ Add new wallet…");
      expect(d.getByLabelText("Wallet number")).toBeInTheDocument();
    });

    it("a bank must be chosen before saving, then the details are sent", async () => {
      const d = await openForm();
      await userEvent.selectOptions(d.getByLabelText("Paid from"), "bank");
      await userEvent.type(d.getByLabelText("Amount"), "900");
      await userEvent.selectOptions(d.getByLabelText("Category"), "gro");
      const save = d.getByRole("button", { name: "Save entry" });
      expect(save).toBeDisabled();
      await userEvent.selectOptions(await d.findByLabelText("Bank name"), "Meezan Bank");
      await userEvent.type(d.getByLabelText("Account no"), "0101-123");
      await userEvent.type(d.getByLabelText("TID (transaction ID)"), "T777");
      expect(save).toBeEnabled();
      await userEvent.click(save);
      await waitFor(() => expect(postMock).toHaveBeenCalled());
      expect(postMock.mock.calls[0]![0]).toBe("/finance/transactions");
      expect(postMock.mock.calls[0]![1]).toMatchObject({
        account_id: "bank", payment_provider: "Meezan Bank", payment_account_no: "0101-123", payment_tid: "T777",
      });
    });

    it("'+ Add new bank…' shows an input, saves the name to the list, then the entry", async () => {
      const d = await openForm();
      await userEvent.selectOptions(d.getByLabelText("Paid from"), "bank");
      await userEvent.type(d.getByLabelText("Amount"), "50");
      await userEvent.selectOptions(d.getByLabelText("Category"), "gro");
      await userEvent.selectOptions(await d.findByLabelText("Bank name"), "__new__");
      const save = d.getByRole("button", { name: "Save entry" });
      expect(save).toBeDisabled();
      await userEvent.type(d.getByLabelText("New bank name"), "Khushhali Bank");
      await userEvent.click(save);
      await waitFor(() => expect(postMock).toHaveBeenCalledTimes(2));
      expect(postMock.mock.calls[0]).toEqual(["/finance/providers", { kind: "bank", name: "Khushhali Bank" }]);
      expect(postMock.mock.calls[1]![1]).toMatchObject({ payment_provider: "Khushhali Bank" });
    });

    it("income shows the details too, transfers do not", async () => {
      const d = await openForm();
      await userEvent.selectOptions(d.getByLabelText("Paid from"), "bank");
      expect(await d.findByLabelText("Bank name")).toBeInTheDocument();
      await userEvent.click(d.getByRole("button", { name: /^income$/i }));
      expect(d.getByLabelText("Bank name")).toBeInTheDocument();
      await userEvent.click(d.getByRole("button", { name: /^transfer$/i }));
      expect(d.queryByLabelText("Bank name")).not.toBeInTheDocument();
    });
  });
});
