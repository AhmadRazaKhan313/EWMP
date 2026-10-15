import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PayslipsScreen from "../PayslipsScreen";
import * as payslipsService from "../../services/payslipsService";
import type { MyPayslipItem } from "../../types/hrms";

vi.mock("../../services/payslipsService");

const PAYSLIPS: MyPayslipItem[] = [
  {
    id: "ps-1",
    status: "paid",
    gross_salary: "60000",
    total_deductions: "10000",
    net_salary: "50000",
    run: {
      id: "run-1",
      name: "September 2026",
      period_start: "2026-09-01",
      period_end: "2026-09-30",
      pay_date: "2026-10-01",
      currency: "USD",
    },
  },
];

function renderWithClient(ui: React.ReactElement): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("PayslipsScreen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders each payslip with its run name, gross, and net pay", async () => {
    vi.mocked(payslipsService.getMyPayslips).mockResolvedValue(PAYSLIPS);
    renderWithClient(<PayslipsScreen />);

    await waitFor(() => expect(screen.getByTestId("payslips-list")).toBeInTheDocument());
    expect(screen.getByText("September 2026")).toBeInTheDocument();
    expect(screen.getByText("$60,000.00")).toBeInTheDocument();
    expect(screen.getByText("$50,000.00")).toBeInTheDocument();
    expect(screen.getByText("paid")).toBeInTheDocument();
  });

  it("shows an empty state when there are no payslips yet", async () => {
    vi.mocked(payslipsService.getMyPayslips).mockResolvedValue([]);
    renderWithClient(<PayslipsScreen />);

    expect(await screen.findByText("No payslips yet")).toBeInTheDocument();
  });

  it("downloads the PDF and triggers a browser download when the button is clicked", async () => {
    vi.mocked(payslipsService.getMyPayslips).mockResolvedValue(PAYSLIPS);
    vi.mocked(payslipsService.downloadPayslipPdf).mockResolvedValue(new Blob(["%PDF-1.4"], { type: "application/pdf" }));

    const createObjectURL = vi.fn().mockReturnValue("blob:mock-url");
    const revokeObjectURL = vi.fn();
    // jsdom doesn't implement these — the download flow uses them to turn
    // the fetched Blob into a clickable, named download.
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    renderWithClient(<PayslipsScreen />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByTestId("payslip-download-button")).toBeInTheDocument());

    await user.click(screen.getByTestId("payslip-download-button"));

    await waitFor(() => expect(payslipsService.downloadPayslipPdf).toHaveBeenCalledWith("ps-1"));
    expect(createObjectURL).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
  });

  it("shows an error message if the PDF download fails", async () => {
    vi.mocked(payslipsService.getMyPayslips).mockResolvedValue(PAYSLIPS);
    vi.mocked(payslipsService.downloadPayslipPdf).mockRejectedValue(new Error("network error"));
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(), revokeObjectURL: vi.fn() });

    renderWithClient(<PayslipsScreen />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByTestId("payslip-download-button")).toBeInTheDocument());
    await user.click(screen.getByTestId("payslip-download-button"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not download this payslip");
  });
});
