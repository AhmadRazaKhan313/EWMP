/**
 * Banking page: statement lines, match / book / ignore, statement import, reconciliation, permission gating.
 *
 * Run:  cd frontend && npm test -- BankingPage
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { getMock, postMock, delMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn(), delMock: vi.fn() }));
vi.mock("@/services/api-client", () => ({ default: { get: getMock, post: postMock, delete: delMock } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { useAuthStore } from "@/store/auth.store";
import BankingPage from "../page";

const acc = (id: string, code: string, name: string, type: string) => ({ id, code, name, type, parent_id: null, is_system: false, is_active: true });
const ACCOUNTS = [
  acc("bank", "1020", "Bank", "asset"), acc("cash", "1010", "Cash", "asset"), acc("ar", "1100", "Accounts Receivable", "asset"),
  acc("inc", "4010", "Client Payments", "income"), acc("exp", "5100", "Grocery", "expense"),
];
const line = (over: Record<string, unknown>) => ({
  id: "l1", statement_id: "s1", account_id: "bank", date: "2026-11-05", description: "Grocery run", reference: null, amount: "-1200.00", balance: null,
  status: "unmatched", match: null, reconciled: false, ...over,
});
const OUT = line({ id: "out", description: "Grocery run" });
const IN = line({ id: "in", description: "Client retainer", amount: "5000.00", date: "2026-11-03", reference: "TID-1" });
const MATCHED = line({ id: "m", description: "Bank charges", amount: "-150.00", status: "matched", match: { entry_line_id: "x", entry_id: "e", number: "JE-000007", date: "2026-11-08", memo: "fee", voided: false } });
const VOIDED = line({ id: "v", description: "Voided one", amount: "-5.00", status: "matched", match: { entry_line_id: "y", entry_id: "e2", number: "JE-000009", date: "2026-11-08", memo: null, voided: true } });
const DONE = line({ id: "r", description: "Old line", status: "matched", reconciled: true, match: { entry_line_id: "z", entry_id: "e3", number: "JE-000001", date: "2026-10-01", memo: null, voided: false } });
const IGN = line({ id: "ig", description: "Dup", amount: "-80.00", status: "ignored" });

const check = (over: Record<string, unknown> = {}) => ({
  account_id: "bank", statement_date: "2026-11-30", beginning_balance: "10000.00", beginning_from_last: false, statement_balance: "15650.00", cleared_total: "5650.00",
  cleared_count: 4, unmatched_count: 0, difference: "0.00", ledger_balance: "5650.00", can_finish: true, reason: null, ...over,
});
let RECS: unknown[] = [];

function wire(items = [OUT, IN], counts = { unmatched: 2, matched: 3, ignored: 1 }) {
  getMock.mockImplementation(async (url: string) => {
    if (url === "/finance/summary") return { data: { currency: "PKR" } };
    if (url === "/finance/accounts") return { data: { items: ACCOUNTS } };
    if (url === "/finance/banking/lines") return { data: { items, total: items.length, counts } };
    if (url === "/finance/banking/reconciliations") return { data: { items: RECS } };
    if (url.endsWith("/suggestions")) return { data: { items: [{ entry_line_id: "el1", entry_id: "e9", number: "JE-000042", date: "2026-11-06", memo: "Groceries", reference: null, payment_tid: null, amount: "1200.00" }] } };
    throw new Error(`unexpected GET ${url}`);
  });
  postMock.mockImplementation(async (url: string) => {
    if (url.endsWith("/preview")) return { data: check() };
    if (url.endsWith("/auto-match")) return { data: { matched: 2 } };
    if (url.endsWith("/create-entry")) return { data: { number: "JE-000050", line: {} } };
    return { data: {} };
  });
  delMock.mockResolvedValue({ data: {} });
}
function setPerms(perms: string[]) { useAuthStore.setState({ hasPermission: (p: string) => perms.includes(p) } as never); }
function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><BankingPage /></QueryClientProvider>);
}
const lineCalls = () => getMock.mock.calls.filter((c) => c[0] === "/finance/banking/lines") as [string, { params: Record<string, unknown> }][];

beforeEach(() => { vi.clearAllMocks(); RECS = []; wire(); setPerms(["finance.view", "finance.post", "finance.manage"]); });

describe("Statement lines", () => {
  it("lists unmatched lines first, with counts, only money accounts in the picker", async () => {
    renderPage();
    expect(await screen.findByText("Grocery run")).toBeInTheDocument();
    expect(lineCalls().at(-1)![1].params).toMatchObject({ account_id: "bank", status: "unmatched" });
    expect(screen.getByRole("button", { name: /^Unmatched \(2\)/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^All \(6\)/ })).toBeInTheDocument();
    const opts = Array.from((screen.getByLabelText("Account") as HTMLSelectElement).options).map((o) => o.text);
    expect(opts).toEqual(["Bank", "Cash"]);
    expect(screen.getByText("TID-1")).toBeInTheDocument();
  });

  it("a filter chip, the search box and the account change what is requested", async () => {
    renderPage();
    await screen.findByText("Grocery run");
    await userEvent.click(screen.getByRole("button", { name: /^Matched/ }));
    await waitFor(() => expect(lineCalls().at(-1)![1].params.status).toBe("matched"));
    await userEvent.click(screen.getByRole("button", { name: /^All/ }));
    await waitFor(() => expect(lineCalls().at(-1)![1].params.status).toBeUndefined());
    await userEvent.type(screen.getByLabelText("Search lines"), "tid");
    await waitFor(() => expect(lineCalls().at(-1)![1].params.q).toBe("tid"));
    await userEvent.selectOptions(screen.getByLabelText("Account"), "cash");
    await waitFor(() => expect(lineCalls().at(-1)![1].params.account_id).toBe("cash"));
  });

  it("shows the right action for each state, and a voided entry warning", async () => {
    wire([OUT, MATCHED, IGN, DONE, VOIDED]);
    renderPage();
    const row = (t: string) => within((screen.getByText(t).closest("tr") as HTMLElement));
    await screen.findByText("Grocery run");
    expect(row("Grocery run").getByRole("button", { name: "Match" })).toBeInTheDocument();
    expect(row("Grocery run").getByRole("button", { name: "Book" })).toBeInTheDocument();
    expect(row("Grocery run").getByRole("button", { name: "Ignore" })).toBeInTheDocument();
    expect(row("Bank charges").getByRole("button", { name: "Unmatch" })).toBeInTheDocument();
    expect(row("Bank charges").getByText("JE-000007")).toBeInTheDocument();
    expect(row("Dup").getByRole("button", { name: "Restore" })).toBeInTheDocument();
    expect(row("Old line").getByText("Reconciled")).toBeInTheDocument();
    expect(row("Old line").queryByRole("button")).not.toBeInTheDocument();
    expect(row("Voided one").getByText("entry voided")).toBeInTheDocument();
  });

  it("unmatch, ignore and restore call the API", async () => {
    wire([OUT, MATCHED, IGN]);
    renderPage();
    await screen.findByText("Grocery run");
    await userEvent.click(screen.getByRole("button", { name: "Unmatch" }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/banking/lines/m/unmatch", {}));
    await userEvent.click(screen.getByRole("button", { name: "Ignore" }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/banking/lines/out/ignore", {}));
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/banking/lines/ig/restore", {}));
  });

  it("without finance.post it is read-only", async () => {
    setPerms(["finance.view"]);
    renderPage();
    await screen.findByText("Grocery run");
    expect(screen.queryByRole("button", { name: "Match" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Book" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /import statement/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /auto-match/i })).not.toBeInTheDocument();
  });

  it("auto-match posts for the selected account", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /auto-match/i }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/banking/accounts/bank/auto-match", {}));
  });

  it("an empty account explains what to do", async () => {
    wire([], { unmatched: 0, matched: 0, ignored: 0 });
    renderPage();
    expect(await screen.findByText("No statement imported yet")).toBeInTheDocument();
  });
});

describe("Match and book", () => {
  it("offers suggestions and matches the chosen one", async () => {
    renderPage();
    const row = (await screen.findByText("Grocery run")).closest("tr") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Match" }));
    const dlg = await screen.findByRole("dialog", { name: "Match to a ledger entry" });
    expect(await within(dlg).findByText(/JE-000042/)).toBeInTheDocument();
    await userEvent.click(within(dlg).getByRole("button", { name: "Match" }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/banking/lines/out/match", { entry_line_id: "el1" }));
  });

  it("books money out as an expense with a category", async () => {
    renderPage();
    const row = (await screen.findByText("Grocery run")).closest("tr") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Book" }));
    const dlg = await screen.findByRole("dialog", { name: "Book this line" });
    const book = within(dlg).getByRole("button", { name: "Book and match" });
    expect(book).toBeDisabled();
    const types = Array.from((within(dlg).getByLabelText("Book as") as HTMLSelectElement).options).map((o) => o.text);
    expect(types).toEqual(["Expense", "Transfer to another account"]);
    const cats = Array.from((within(dlg).getByLabelText("Category") as HTMLSelectElement).options).map((o) => o.text);
    expect(cats).toContain("Grocery");
    expect(cats).not.toContain("Client Payments");
    await userEvent.selectOptions(within(dlg).getByLabelText("Category"), "exp");
    await userEvent.click(book);
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/banking/lines/out/create-entry", { type: "expense", category_id: "exp", description: "Grocery run" }));
  });

  it("books money in as a transfer from another account", async () => {
    renderPage();
    const row = (await screen.findByText("Client retainer")).closest("tr") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Book" }));
    const dlg = await screen.findByRole("dialog", { name: "Book this line" });
    expect(Array.from((within(dlg).getByLabelText("Book as") as HTMLSelectElement).options).map((o) => o.text)).toEqual(["Income", "Transfer from another account"]);
    await userEvent.selectOptions(within(dlg).getByLabelText("Book as"), "transfer");
    const book = within(dlg).getByRole("button", { name: "Book and match" });
    expect(book).toBeDisabled();
    const others = Array.from((within(dlg).getByLabelText("Received from") as HTMLSelectElement).options).map((o) => o.text);
    expect(others).toContain("Cash");
    expect(others).not.toContain("Bank");                       // not the account itself
    expect(others).not.toContain("Accounts Receivable");
    await userEvent.selectOptions(within(dlg).getByLabelText("Received from"), "cash");
    await userEvent.click(book);
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/banking/lines/in/create-entry", { type: "transfer", other_account_id: "cash", description: "Client retainer" }));
  });
});

describe("Import statement", () => {
  const preview = (over: Record<string, unknown> = {}) => ({
    dry_run: true, total_rows: 4, to_import: 3, imported: 0, duplicates: 1, matched: 0, statement_id: null, date_order: "dmy", date_order_guessed: true,
    skipped: [{ row: 6, reason: "no date" }], preview: [{ date: "2026-11-03", description: "Client retainer", reference: null, amount: "5000.00", duplicate: false }], ...over,
  });

  it("checks the file first, then imports it", async () => {
    postMock.mockImplementation(async (url: string, body: FormData) => ({ data: url.endsWith("/import") ? (body.get("dry_run") === "true" ? preview() : preview({ dry_run: false, imported: 3, matched: 2 })) : {} }));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /import statement/i }));
    const dlg = await screen.findByRole("dialog", { name: "Import bank statement" });
    const file = new File(["Date,Amount\n"], "stmt.csv", { type: "text/csv" });
    await userEvent.upload(within(dlg).getByLabelText(/statement file/i), file);
    await userEvent.click(within(dlg).getByRole("button", { name: "Check file" }));
    expect(await within(dlg).findByText(/will be imported/)).toBeInTheDocument();
    expect(within(dlg).getByText(/1 already imported/)).toBeInTheDocument();
    expect(within(dlg).getByText(/Could not tell from the dates/)).toBeInTheDocument();
    expect(within(dlg).getByText("1 rows skipped")).toBeInTheDocument();
    const dry = postMock.mock.calls.at(-1)![1] as FormData;
    expect(dry.get("account_id")).toBe("bank");
    expect(dry.get("dry_run")).toBe("true");
    await userEvent.click(within(dlg).getByRole("button", { name: "Import 3 lines" }));
    await waitFor(() => expect((postMock.mock.calls.at(-1)![1] as FormData).get("dry_run")).toBe("false"));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Import bank statement" })).not.toBeInTheDocument());
  });

  it("changing the date order checks the file again", async () => {
    postMock.mockImplementation(async () => ({ data: preview() }));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /import statement/i }));
    const dlg = await screen.findByRole("dialog", { name: "Import bank statement" });
    await userEvent.upload(within(dlg).getByLabelText(/statement file/i), new File(["x"], "s.csv"));
    await userEvent.click(within(dlg).getByRole("button", { name: "Check file" }));
    await userEvent.selectOptions(await within(dlg).findByLabelText("Date order"), "mdy");
    await waitFor(() => expect((postMock.mock.calls.at(-1)![1] as FormData).get("date_order")).toBe("mdy"));
  });
});

describe("Reconcile", () => {
  async function open() {
    renderPage();
    await userEvent.click(await screen.findByText("Reconcile"));
  }
  const fill = async (bal = "15650") => {
    fireEvent.change(await screen.findByLabelText("Statement date"), { target: { value: "2026-11-30" } });
    fireEvent.change(screen.getByLabelText("Statement ending balance"), { target: { value: bal } });
  };

  it("checks the balance and finishes when the difference is 0", async () => {
    await open();
    const checkBtn = screen.getByRole("button", { name: "Check" });
    expect(checkBtn).toBeDisabled();
    await fill();
    fireEvent.change(screen.getByLabelText(/beginning balance/i), { target: { value: "10000" } });
    await userEvent.click(checkBtn);
    expect(await screen.findByTestId("difference")).toHaveTextContent("0");
    expect(screen.getByText("Everything adds up.")).toBeInTheDocument();
    expect(postMock).toHaveBeenCalledWith("/finance/banking/reconciliations/preview",
      { account_id: "bank", statement_date: "2026-11-30", statement_balance: "15650", beginning_balance: "10000" });
    await userEvent.click(screen.getByRole("button", { name: "Finish reconciliation" }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/banking/reconciliations", expect.objectContaining({ account_id: "bank", statement_balance: "15650" })));
  });

  it("explains why it cannot be finished", async () => {
    postMock.mockImplementation(async () => ({ data: check({ difference: "-650.00", can_finish: false, reason: "The difference is -650.00. It must be 0", unmatched_count: 2 }) }));
    await open();
    await fill("15000");
    await userEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The difference is -650.00");
    expect(screen.getByText(/2 line\(s\) up to this date still need matching/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finish reconciliation" })).toBeDisabled();
  });

  it("after the first reconciliation the beginning balance is no longer asked for; only the latest can be undone", async () => {
    RECS = [
      { id: "r2", account_id: "bank", statement_date: "2026-11-30", beginning_balance: "13650.00", statement_balance: "15650.00", cleared_total: "2000.00", line_count: 1, created_at: "x" },
      { id: "r1", account_id: "bank", statement_date: "2026-11-10", beginning_balance: "10000.00", statement_balance: "13650.00", cleared_total: "3650.00", line_count: 3, created_at: "x" },
    ];
    await open();
    await screen.findByText("2026-11-30");
    expect(screen.queryByLabelText(/beginning balance/i)).not.toBeInTheDocument();
    const undo = screen.getAllByRole("button", { name: "Undo" });
    expect(undo).toHaveLength(1);
    await userEvent.click(undo[0]!);
    await waitFor(() => expect(delMock).toHaveBeenCalledWith("/finance/banking/reconciliations/r2"));
  });

  it("without finance.manage you can check but not finish or undo", async () => {
    setPerms(["finance.view", "finance.post"]);
    RECS = [{ id: "r1", account_id: "bank", statement_date: "2026-11-10", beginning_balance: "0", statement_balance: "1", cleared_total: "1", line_count: 1, created_at: "x" }];
    await open();
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Check" }));
    await screen.findByText("Everything adds up.");
    expect(screen.queryByRole("button", { name: "Finish reconciliation" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });
});

describe("No account", () => {
  it("asks for a cash, bank or wallet account first", async () => {
    getMock.mockImplementation(async (url: string) => (url === "/finance/accounts" ? { data: { items: [ACCOUNTS[2], ACCOUNTS[3]] } } : { data: { currency: "PKR" } }));
    renderPage();
    expect(await screen.findByText("No cash, bank or wallet account yet")).toBeInTheDocument();
  });
});
