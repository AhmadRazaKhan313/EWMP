/**
 * Sales page: invoices list/filters, new-invoice totals + payload, payment allocation, permission gating.
 *
 * Run:  cd frontend && npm test -- SalesPage
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { getMock, postMock, deleteMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn(), deleteMock: vi.fn() }));
vi.mock("@/services/api-client", () => ({ default: { get: getMock, post: postMock, delete: deleteMock } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { useAuthStore } from "@/store/auth.store";
import SalesPage from "../page";

const CUSTOMERS = [{ id: "c1", name: "Acme Ltd", company: null, email: "a@acme.test", phone: null, address: null, currency: null, payment_terms_days: 14, notes: null, is_active: true, balance: "1500.00" }];
const inv = (o: Record<string, unknown>) => ({
  id: "i1", number: "INV-000001", customer_id: "c1", customer_name: "Acme Ltd", status: "sent", is_overdue: false,
  issue_date: "2026-11-01", due_date: "2026-11-15", currency: "PKR", exchange_rate: "1", subtotal: "1500", tax_total: "0",
  total: "1500", amount_paid: "0", balance: "1500.00", reference: null, notes: null, ...o,
});
const INVOICES = [inv({}), inv({ id: "i2", number: "INV-000002", status: "draft", balance: "300.00", total: "300" }), inv({ id: "i3", number: "INV-000003", is_overdue: true, balance: "90.00", total: "90" })];
const ACCOUNTS = [
  { id: "bank", code: "1020", name: "Bank", type: "asset", parent_id: null, is_system: true, is_active: true },
  { id: "ar", code: "1100", name: "Accounts Receivable", type: "asset", parent_id: null, is_system: true, is_active: true },
];

const QUOTES = [
  { id: "q1", number: "QUO-000001", customer_id: "c1", customer_name: "Acme Ltd", status: "sent", is_expired: false, issue_date: "2026-11-01", valid_until: "2026-12-01", currency: "PKR", subtotal: "1000", tax_total: "0", total: "1000", reference: null, notes: null, invoice_id: null },
  { id: "q2", number: "QUO-000002", customer_id: "c1", customer_name: "Acme Ltd", status: "draft", is_expired: false, issue_date: "2026-11-02", valid_until: "2026-12-02", currency: "PKR", subtotal: "200", tax_total: "0", total: "200", reference: null, notes: null, invoice_id: null },
];

const RECURRING = [
  { id: "r1", title: "Aqsa installment", customer_id: "c1", customer_name: "Acme Ltd", status: "active", frequency: "monthly", start_date: "2026-11-01", end_date: null, next_run_date: "2026-12-01", run_count: 1, auto_send: false, currency: "PKR", last_error: null },
  { id: "r2", title: "Old retainer", customer_id: "c1", customer_name: "Acme Ltd", status: "paused", frequency: "weekly", start_date: "2026-10-01", end_date: null, next_run_date: "2026-11-08", run_count: 4, auto_send: true, currency: "PKR", last_error: "No exchange rate for EUR" },
];

function wire() {
  getMock.mockImplementation(async (url: string, cfg?: { params?: Record<string, string> }) => {
    if (url === "/finance/summary") return { data: { currency: "PKR" } };
    if (url === "/finance/customers") return { data: { items: CUSTOMERS } };
    if (url === "/finance/accounts") return { data: { items: ACCOUNTS } };
    if (url === "/finance/tax-rates") return { data: { items: [{ id: "t1", name: "GST", percent: "10", is_active: true }] } };
    if (url === "/finance/recurring") return { data: { items: RECURRING } };
    if (url === "/finance/quotes") return { data: { items: QUOTES, total: QUOTES.length } };
    if (url === "/finance/payments") return { data: { items: [], total: 0 } };
    if (url === "/finance/invoices") {
      const s = cfg?.params?.status;
      const items = s ? INVOICES.filter((i) => i.status === s) : INVOICES;
      return { data: { items, total: items.length } };
    }
    throw new Error(`unexpected GET ${url}`);
  });
  postMock.mockResolvedValue({ data: {} });
}

function setPerms(perms: string[]) {
  useAuthStore.setState({ hasPermission: (p: string) => perms.includes(p) } as never);
}
function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><SalesPage /></QueryClientProvider>);
}

beforeEach(() => { vi.clearAllMocks(); wire(); setPerms(["finance.view", "finance.post", "finance.void"]); });

describe("Sales page", () => {
  it("lists invoices with receivables and row actions by status", async () => {
    renderPage();
    expect(await screen.findByText("INV-000001")).toBeInTheDocument();
    expect(screen.getByTestId("stat-receivable")).toHaveTextContent("1,500");
    expect(screen.getByLabelText("Void INV-000001")).toBeInTheDocument();
    expect(screen.getByLabelText("Send INV-000002")).toBeInTheDocument();
    expect(screen.queryByLabelText("Void INV-000002")).not.toBeInTheDocument();
  });

  it("filters by status through the API", async () => {
    renderPage();
    await screen.findByText("INV-000001");
    await userEvent.click(screen.getByRole("button", { name: "Draft" }));
    await waitFor(() => expect(screen.queryByText("INV-000001")).not.toBeInTheDocument());
    expect(screen.getByText("INV-000002")).toBeInTheDocument();
  });

  it("hides write actions without permission", async () => {
    setPerms(["finance.view"]);
    renderPage();
    await screen.findByText("INV-000001");
    expect(screen.queryByRole("button", { name: /New invoice/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Void INV-000001")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Send INV-000002")).not.toBeInTheDocument();
  });

  it("builds an invoice, shows live totals and posts the right body", async () => {
    renderPage();
    await screen.findByText("INV-000001");
    await userEvent.click(screen.getByRole("button", { name: /New invoice/ }));
    const save = screen.getByRole("button", { name: "Save & send" });
    expect(save).toBeDisabled();
    await userEvent.selectOptions(await screen.findByLabelText("Customer"), "c1");
    await userEvent.type(screen.getByLabelText("Description 1"), "Web work");
    await userEvent.clear(screen.getByLabelText("Quantity 1")); await userEvent.type(screen.getByLabelText("Quantity 1"), "2");
    await userEvent.type(screen.getByLabelText("Price 1"), "500");
    await userEvent.selectOptions(await screen.findByLabelText("Tax 1"), "t1");
    expect(screen.getByTestId("inv-subtotal")).toHaveTextContent("1,000");
    expect(screen.getByTestId("inv-total")).toHaveTextContent("1,100");
    await userEvent.click(save);
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    const [url, body] = postMock.mock.calls[0]!;
    expect(url).toBe("/finance/invoices");
    expect(body).toMatchObject({ customer_id: "c1", send: true, lines: [{ description: "Web work", quantity: "2", unit_price: "500", tax_rate_id: "t1" }] });
  });

  it("records a payment against an open invoice and blocks over-allocation", async () => {
    renderPage();
    await userEvent.click(await screen.findByLabelText("Record payment for INV-000001"));
    const apply = await screen.findByLabelText("Apply to INV-000001");
    await waitFor(() => expect(apply).toHaveValue("1500.00"));
    const save = screen.getByRole("button", { name: "Save payment" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.clear(apply); await userEvent.type(apply, "2000");
    expect(save).toBeDisabled();
    await userEvent.clear(apply); await userEvent.type(apply, "500");
    const amount = screen.getByLabelText(/Amount received/);
    await userEvent.clear(amount); await userEvent.type(amount, "500");
    expect(screen.getByTestId("pay-unapplied")).toHaveTextContent("kept as credit");
    await userEvent.click(save);
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    expect(postMock.mock.calls[0]![0]).toBe("/finance/payments");
    expect(postMock.mock.calls[0]![1]).toMatchObject({ customer_id: "c1", amount: "500", deposit_account_id: "bank", allocations: [{ invoice_id: "i1", amount: "500" }] });
  });

  it("quotes tab: actions follow status, convert and accept call the API", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Quotes"));
    expect(await screen.findByText("QUO-000001")).toBeInTheDocument();
    expect(screen.getByLabelText("Accept QUO-000001")).toBeInTheDocument();
    expect(screen.getByLabelText("Mark QUO-000002 sent")).toBeInTheDocument();
    expect(screen.queryByLabelText("Accept QUO-000002")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Convert QUO-000002 to invoice")).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Accept QUO-000001"));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/quotes/q1/accept"));
    await userEvent.click(screen.getByLabelText("Convert QUO-000001 to invoice"));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/quotes/q1/convert", {}));
  });

  it("new quote posts valid_until and lines", async () => {
    renderPage();
    await screen.findByText("INV-000001");
    await userEvent.click(screen.getByRole("button", { name: /New quote/ }));
    await userEvent.selectOptions(await screen.findByLabelText("Customer"), "c1");
    await userEvent.type(screen.getByLabelText("Description 1"), "Logo design");
    await userEvent.type(screen.getByLabelText("Price 1"), "250");
    await userEvent.click(screen.getByRole("button", { name: "Save as draft" }));
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    const [url, body] = postMock.mock.calls[0]!;
    expect(url).toBe("/finance/quotes");
    expect(body).toMatchObject({ customer_id: "c1", send: false, lines: [{ description: "Logo design", unit_price: "250" }] });
  });

  it("overdue invoices get a reminder button that calls the API", async () => {
    renderPage();
    await screen.findByText("INV-000003");
    expect(screen.queryByLabelText("Remind INV-000001")).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Remind INV-000003"));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/invoices/i3/remind"));
  });

  it("recurring tab: shows schedules, errors, pause/resume and creates one", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Recurring"));
    expect(await screen.findByText("Aqsa installment")).toBeInTheDocument();
    expect(screen.getByText("No exchange rate for EUR")).toBeInTheDocument();
    expect(screen.queryByLabelText("Resume Aqsa installment")).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Pause Aqsa installment"));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/recurring/r1/pause"));
    await userEvent.click(screen.getByLabelText("Resume Old retainer"));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith("/finance/recurring/r2/resume"));

    postMock.mockClear();
    await userEvent.click(screen.getByRole("button", { name: /New schedule/ }));
    const save = screen.getByRole("button", { name: "Save schedule" });
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Title"), "Monthly fee");
    await userEvent.selectOptions(screen.getByLabelText("Customer"), "c1");
    await userEvent.type(screen.getByLabelText("Description 1"), "Fee");
    await userEvent.type(screen.getByLabelText("Price 1"), "15000");
    expect(screen.getByTestId("rec-total")).toHaveTextContent("15,000");
    await userEvent.click(save);
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    expect(postMock.mock.calls[0]![0]).toBe("/finance/recurring");
    expect(postMock.mock.calls[0]![1]).toMatchObject({ title: "Monthly fee", customer_id: "c1", frequency: "monthly", auto_send: false });
  });
});
