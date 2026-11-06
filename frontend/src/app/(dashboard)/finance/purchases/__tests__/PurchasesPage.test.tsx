/**
 * Purchases page: bills list/filters, new-bill totals + payload, vendor payment allocation, permission gating.
 *
 * Run:  cd frontend && npm test -- PurchasesPage
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { getMock, postMock, putMock, deleteMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn(), putMock: vi.fn(), deleteMock: vi.fn() }));
vi.mock("@/services/api-client", () => ({ default: { get: getMock, post: postMock, put: putMock, delete: deleteMock } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { useAuthStore } from "@/store/auth.store";
import PurchasesPage from "../page";

const VENDORS = [{ id: "v1", name: "Zed Supplies", company: null, email: "z@zed.test", phone: null, address: null, currency: null, payment_terms_days: 30, notes: null, is_active: true, balance: "700.00" }];
const bill = (o: Record<string, unknown>) => ({
  id: "b1", number: "BILL-000001", vendor_id: "v1", vendor_name: "Zed Supplies", vendor_ref: "ZS-77", status: "open", is_overdue: false,
  issue_date: "2026-11-01", due_date: "2026-12-01", currency: "PKR", exchange_rate: "1", subtotal: "700", tax_total: "0",
  total: "700", amount_paid: "0", balance: "700.00", notes: null, approval_status: "none", rejection_reason: null, recurring_id: null, ...o,
});
let BILLS = [bill({}), bill({ id: "b2", number: "BILL-000002", status: "draft", vendor_ref: null }), bill({ id: "b3", number: "BILL-000003", is_overdue: true, balance: "90.00", total: "90" })];
const ACCOUNTS = [
  { id: "bank", code: "1020", name: "Bank", type: "asset", parent_id: null, is_system: true, is_active: true, money_kind: "bank" },
  { id: "ap", code: "2010", name: "Accounts Payable", type: "liability", parent_id: null, is_system: true, is_active: true },
  { id: "rent", code: "5100", name: "Rent", type: "expense", parent_id: null, is_system: false, is_active: true },
  { id: "oth", code: "5900", name: "Other Expenses", type: "expense", parent_id: null, is_system: true, is_active: true },
  { id: "fa", code: "1500", name: "Fixed Assets", type: "asset", parent_id: null, is_system: true, is_active: true },
];

let LIMIT: string | null = null;
const ORDERS = [
  { id: "o1", number: "PO-000001", vendor_id: "v1", vendor_name: "Zed Supplies", status: "draft", issue_date: "2026-11-01", expected_date: null, currency: "PKR", subtotal: "500", tax_total: "0", total: "500", reference: null, notes: null, bill_id: null },
  { id: "o2", number: "PO-000002", vendor_id: "v1", vendor_name: "Zed Supplies", status: "sent", issue_date: "2026-11-02", expected_date: "2026-11-09", currency: "PKR", subtotal: "800", tax_total: "0", total: "800", reference: null, notes: null, bill_id: null },
];
const RECURRING = [
  { id: "r1", title: "Office rent", vendor_id: "v1", vendor_name: "Zed Supplies", status: "active", frequency: "monthly", start_date: "2026-11-01", end_date: null, next_run_date: "2026-12-01", run_count: 1, auto_post: false, currency: "PKR", last_error: null },
  { id: "r2", title: "Old lease", vendor_id: "v1", vendor_name: "Zed Supplies", status: "paused", frequency: "weekly", start_date: "2026-10-01", end_date: null, next_run_date: "2026-11-08", run_count: 4, auto_post: true, currency: "PKR", last_error: "No exchange rate for EUR" },
];
const FILES = [{ id: "f1", file_name: "invoice.pdf", mime_type: "application/pdf", size_bytes: 2048, uploaded_at: null }];

function wire() {
  getMock.mockImplementation(async (url: string, cfg?: { params?: Record<string, string> }) => {
    if (url === "/finance/summary") return { data: { currency: "PKR" } };
    if (url === "/finance/vendors") return { data: { items: VENDORS } };
    if (url === "/finance/accounts") return { data: { items: ACCOUNTS } };
    if (url === "/finance/tax-rates") return { data: { items: [{ id: "t1", name: "GST", percent: "10", is_active: true }] } };
    if (url === "/finance/purchase-settings") return { data: { approval_threshold: LIMIT } };
    if (url === "/finance/purchase-orders") return { data: { items: ORDERS, total: ORDERS.length } };
    if (url === "/finance/recurring-bills") return { data: { items: RECURRING } };
    if (/^\/finance\/bills\/[^/]+\/attachments$/.test(url)) return { data: { items: FILES } };
    if (url === "/finance/bill-payments") return { data: { items: [], total: 0 } };
    if (url === "/finance/bills") {
      const s = cfg?.params?.status;
      const items = s === "overdue" ? BILLS.filter((b) => b.is_overdue) : s ? BILLS.filter((b) => b.status === s) : BILLS;
      return { data: { items, total: items.length } };
    }
    throw new Error(`unexpected GET ${url}`);
  });
  postMock.mockResolvedValue({ data: {} });
  putMock.mockResolvedValue({ data: {} });
}
function setPerms(perms: string[]) {
  useAuthStore.setState({ hasPermission: (p: string) => perms.includes(p) } as never);
}
function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><PurchasesPage /></QueryClientProvider>);
}

beforeEach(() => { vi.clearAllMocks(); LIMIT = null; wire(); setPerms(["finance.view", "finance.post", "finance.void"]); });

describe("Purchases page", () => {
  it("lists bills, shows payables and status-specific actions", async () => {
    renderPage();
    expect(await screen.findByText("BILL-000001")).toBeInTheDocument();
    expect(screen.getAllByText("ZS-77").length).toBeGreaterThan(0);
    expect(screen.getByTestId("stat-payable")).toHaveTextContent("700");
    expect(screen.getByLabelText("Post BILL-000002")).toBeInTheDocument();
    expect(screen.getByLabelText("Pay BILL-000001")).toBeInTheDocument();
    expect(screen.queryByLabelText("Pay BILL-000002")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Void BILL-000001")).toBeInTheDocument();
  });

  it("posts a draft bill", async () => {
    renderPage();
    await userEvent.click(await screen.findByLabelText("Post BILL-000002"));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/bills/b2/post"));
  });

  it("filters overdue bills", async () => {
    renderPage();
    await screen.findByText("BILL-000001");
    await userEvent.click(screen.getByRole("button", { name: "Overdue" }));
    await waitFor(() => expect(screen.queryByText("BILL-000001")).not.toBeInTheDocument());
    expect(screen.getByText("BILL-000003")).toBeInTheDocument();
  });

  it("new bill: computes totals, offers only expense/fixed-asset accounts, sends payload", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /new bill/i }));
    await userEvent.selectOptions(await screen.findByLabelText("Vendor"), "v1");
    await userEvent.type(screen.getByLabelText("Description 1"), "Office rent");
    await userEvent.clear(screen.getByLabelText("Quantity 1"));
    await userEvent.type(screen.getByLabelText("Quantity 1"), "2");
    await userEvent.type(screen.getByLabelText("Price 1"), "100");
    await userEvent.selectOptions(screen.getByLabelText("Tax 1"), "t1");
    await userEvent.selectOptions(screen.getByLabelText("Expense account 1"), "rent");
    expect(screen.getByTestId("bill-subtotal")).toHaveTextContent("200");
    expect(screen.getByTestId("bill-total")).toHaveTextContent("220");
    const opts = Array.from((screen.getByLabelText("Expense account 1") as HTMLSelectElement).options).map((o) => o.text);
    expect(opts).toEqual(expect.arrayContaining(["Rent", "Fixed Assets"]));
    expect(opts).not.toContain("Bank");
    expect(opts).not.toContain("Accounts Payable");
    await userEvent.click(screen.getByRole("button", { name: /save & post/i }));
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    const [url, body] = postMock.mock.calls[0] as [string, any];
    expect(url).toBe("/finance/bills");
    expect(body).toMatchObject({ vendor_id: "v1", post: true });
    expect(body.lines[0]).toMatchObject({ description: "Office rent", quantity: "2", unit_price: "100", tax_rate_id: "t1", expense_account_id: "rent" });
  });

  it("pay vendor: preset bill is pre-allocated and posted", async () => {
    renderPage();
    await userEvent.click(await screen.findByLabelText("Pay BILL-000001"));
    expect(await screen.findByLabelText("Apply to BILL-000001")).toHaveValue("700.00");
    await userEvent.click(screen.getByRole("button", { name: /save payment/i }));
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    const [url, body] = postMock.mock.calls[0] as [string, any];
    expect(url).toBe("/finance/bill-payments");
    expect(body).toMatchObject({ vendor_id: "v1", amount: "700.00", paid_from_account_id: "bank" });
    expect(body.allocations).toEqual([{ bill_id: "b1", amount: "700.00" }]);
  });

  it("blocks a payment whose allocations exceed the amount", async () => {
    renderPage();
    await userEvent.click(await screen.findByLabelText("Pay BILL-000001"));
    const amt = await screen.findByLabelText(/amount paid/i);
    await userEvent.clear(amt);
    await userEvent.type(amt, "100");
    expect(screen.getByTestId("bpay-unapplied")).toHaveTextContent(/exceed/i);
    expect(screen.getByRole("button", { name: /save payment/i })).toBeDisabled();
  });

  it("hides write actions without finance.post", async () => {
    setPerms(["finance.view"]);
    renderPage();
    await screen.findByText("BILL-000001");
    expect(screen.queryByRole("button", { name: /new bill/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Post BILL-000002")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Void BILL-000001")).not.toBeInTheDocument();
  });

  it("above the approval limit: request approval replaces Post; a manager can approve or reject", async () => {
    LIMIT = "500";
    const { unmount } = renderPage();
    await screen.findByText("BILL-000001");
    expect(screen.queryByLabelText("Post BILL-000002")).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Request approval BILL-000002"));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/bills/b2/request-approval"));
    expect(screen.queryByLabelText("Approve BILL-000002")).not.toBeInTheDocument();      // not a manager
    unmount();

    BILLS[1] = bill({ id: "b2", number: "BILL-000002", status: "draft", approval_status: "pending", vendor_ref: null });
    setPerms(["finance.view", "finance.post", "finance.manage"]);
    renderPage();
    expect(await screen.findByText("Awaiting approval")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Approve BILL-000002"));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/bills/b2/approve"));
    await userEvent.click(screen.getByLabelText("Reject BILL-000002"));
    await userEvent.type(await screen.findByLabelText("Reason"), "wrong vendor");
    await userEvent.click(screen.getByRole("button", { name: "Reject bill" }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/bills/b2/reject", { reason: "wrong vendor" }));
    BILLS[1] = bill({ id: "b2", number: "BILL-000002", status: "draft", vendor_ref: null });
  });

  it("a new bill above the limit cannot be posted straight away", async () => {
    LIMIT = "100";
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /new bill/i }));
    await userEvent.selectOptions(await screen.findByLabelText("Vendor"), "v1");
    await userEvent.type(screen.getByLabelText("Description 1"), "Big job");
    await userEvent.type(screen.getByLabelText("Price 1"), "500");
    expect(await screen.findByText(/above the approval limit/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save & post/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /save as draft/i })).toBeEnabled();
  });

  it("managers set the approval limit; others do not see it", async () => {
    setPerms(["finance.view", "finance.post", "finance.manage"]);
    const { unmount } = renderPage();
    const box = await screen.findByLabelText("Approval limit");
    await userEvent.type(box, "25000");
    await userEvent.click(screen.getByRole("button", { name: /save limit/i }));
    await waitFor(() => expect(putMock).toHaveBeenCalledWith("/finance/purchase-settings", { approval_threshold: "25000" }));
    unmount();
    setPerms(["finance.view", "finance.post"]);
    renderPage();
    await screen.findByText("BILL-000001");
    expect(screen.queryByLabelText("Approval limit")).not.toBeInTheDocument();
  });

  it("orders tab: status-specific actions and convert to bill", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Orders"));
    expect(await screen.findByText("PO-000001")).toBeInTheDocument();
    expect(screen.getByLabelText("Send PO-000001")).toBeInTheDocument();
    expect(screen.queryByLabelText("Bill PO-000001")).not.toBeInTheDocument();           // draft: not billable yet
    expect(screen.getByLabelText("Receive PO-000002")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Bill PO-000002"));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/purchase-orders/o2/convert", {}));
    await userEvent.click(screen.getByLabelText("Send PO-000001"));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/purchase-orders/o1/sent"));
  });

  it("new purchase order posts vendor, dates and lines", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /new order/i }));
    await userEvent.selectOptions(await screen.findByLabelText("Vendor"), "v1");
    await userEvent.type(screen.getByLabelText("Description 1"), "Chairs");
    await userEvent.clear(screen.getByLabelText("Quantity 1"));
    await userEvent.type(screen.getByLabelText("Quantity 1"), "4");
    await userEvent.type(screen.getByLabelText("Price 1"), "250");
    expect(screen.getByTestId("lines-total")).toHaveTextContent("1,000");
    await userEvent.click(screen.getByRole("button", { name: /save & mark sent/i }));
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    const [url, body] = postMock.mock.calls[0] as [string, any];
    expect(url).toBe("/finance/purchase-orders");
    expect(body).toMatchObject({ vendor_id: "v1", send: true });
    expect(body.lines[0]).toMatchObject({ description: "Chairs", quantity: "4", unit_price: "250" });
  });

  it("recurring tab: shows schedules and errors, pause/resume, creates one", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Recurring"));
    expect(await screen.findByText("Office rent")).toBeInTheDocument();
    expect(screen.getByText("No exchange rate for EUR")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Pause Office rent"));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/recurring-bills/r1/pause"));
    await userEvent.click(screen.getByLabelText("Resume Old lease"));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/recurring-bills/r2/resume"));

    await userEvent.click(screen.getByRole("button", { name: /new schedule/i }));
    await userEvent.type(await screen.findByLabelText("Title"), "Internet");
    await userEvent.selectOptions(screen.getByLabelText("Vendor"), "v1");
    await userEvent.type(screen.getByLabelText("Description 1"), "Monthly internet");
    await userEvent.type(screen.getByLabelText("Price 1"), "3000");
    await userEvent.click(screen.getByRole("button", { name: /save schedule/i }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/recurring-bills", expect.objectContaining({ title: "Internet", vendor_id: "v1", frequency: "monthly", auto_post: false })));
  });

  it("files dialog lists attachments and removes one", async () => {
    renderPage();
    await userEvent.click(await screen.findByLabelText("Files BILL-000001"));
    expect(await screen.findByText("invoice.pdf")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Remove invoice.pdf"));
    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith("/finance/bills/b1/attachments/f1"));
  });

  it("files dialog hides upload and remove without finance.post", async () => {
    setPerms(["finance.view"]);
    renderPage();
    await userEvent.click(await screen.findByLabelText("Files BILL-000001"));
    expect(await screen.findByText("invoice.pdf")).toBeInTheDocument();
    expect(screen.queryByLabelText("Remove invoice.pdf")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /attach a file/i })).not.toBeInTheDocument();
  });
});
